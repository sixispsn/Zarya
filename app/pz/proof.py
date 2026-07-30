"""Zarya Proof: доказательный граф уже принятых проектных решений.

Модуль не меняет расчётное ядро и не вводит новых инженерных допущений.
Он повторно читает результаты Project, раскрывает промежуточные значения
штатных расчётчиков и связывает их с исходными данными, нормативами и
документами комплекта.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.data.sp30_tables import get_consumer_norm
from app.pz.commission import CommissionReport
from app.pz.project import Project
from app.pz.rules import calc_required_head, decide_fire_network


STATUS_LABELS = {
    "verified": "подтверждено",
    "specified": "предусмотрено",
    "stage_r": "стадия Р",
    "missing": "нужны данные",
    "not_applicable": "не требуется",
    "fail": "не соответствует",
}

KIND_LABELS = {
    "source": "Исходные данные",
    "norm": "Норматив",
    "calculation": "Расчёт",
    "decision": "Решение",
    "artifact": "Комплект",
}


@dataclass(frozen=True)
class ProofStep:
    kind: str
    label: str
    value: str
    detail: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


@dataclass(frozen=True)
class ProofDecision:
    id: str
    system: str
    title: str
    value: str
    unit: str
    status: str
    summary: str
    steps: list[ProofStep] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    impact: list[str] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


@dataclass
class ProofGraph:
    project_fingerprint: str
    legacy_fingerprint: str
    build_commit: str
    generated_at: str
    decisions: list[ProofDecision] = field(default_factory=list)
    version: str = "1.0"

    @property
    def proven_count(self) -> int:
        return sum(
            item.status in {"verified", "specified", "not_applicable"}
            for item in self.decisions
        )

    @property
    def missing_count(self) -> int:
        return sum(item.status in {"missing", "fail"} for item in self.decisions)

    @property
    def stage_r_count(self) -> int:
        return sum(item.status == "stage_r" for item in self.decisions)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["summary"] = {
            "total": len(self.decisions),
            "proven": self.proven_count,
            "missing": self.missing_count,
            "stage_r": self.stage_r_count,
        }
        for decision, encoded in zip(self.decisions, data["decisions"]):
            encoded["status_label"] = decision.status_label
            for step, encoded_step in zip(decision.steps, encoded["steps"]):
                encoded_step["kind_label"] = step.kind_label
        return data


def _ru(value: Optional[float], precision: int = 2) -> str:
    if value is None:
        return "не задано"
    return f"{value:.{precision}f}".replace(".", ",")


def _cold_meter(project: Project):
    rows = project.meters.rows or []
    for row in rows:
        if "ввод" in row.label.lower():
            return row
    for row in rows:
        if "хвс" in row.label.lower() or "холодн" in row.label.lower():
            return row
    return rows[0] if rows else None


def _consumer_source_steps(project: Project) -> tuple[list[ProofStep], object | None]:
    if not project.consumer_groups:
        return [
            ProofStep(
                "source",
                "Группы потребителей",
                "не заданы",
                "Расходы нельзя подтвердить без состава и количества потребителей.",
            ),
        ], None

    lines = []
    formula_parts = []
    for code, count in project.consumer_groups:
        norm = get_consumer_norm(code)
        if norm is None:
            lines.append(f"{code}: {count}; нормативная строка не найдена")
            continue
        contribution = norm.qu_tot * count / 1000.0
        lines.append(
            f"{norm.label}: {count} {norm.unit}; "
            f"qᵤ={norm.qu_tot:g} л/(ед·сут)"
        )
        formula_parts.append(f"{count}×{norm.qu_tot:g}/1000={_ru(contribution, 3)}")

    result = calculate_water_demand(
        [ConsumerGroup(code=code, count=count)
         for code, count in project.consumer_groups if count > 0],
        sewage_max_fixture_lps=project.sewage_max_fixture_lps,
    )
    steps = [
        ProofStep(
            "source",
            "Состав потребителей",
            "; ".join(lines),
            "Количество принято из блока 02 исходных данных проекта.",
        ),
        ProofStep(
            "norm",
            "Нормы водопотребления",
            "СП 30.13330.2020, таблица А.2",
            "Таблица и ветвления перенесены из legacy/sp30_calculator.html.",
        ),
        ProofStep(
            "calculation",
            "Суточная сумма",
            " + ".join(formula_parts),
            f"Итог штатного расчётчика: {_ru(result.total.q_day, 3)} м³/сут.",
        ),
    ]
    return steps, result


def _daily_flow_decision(
    project: Project,
    source_steps: list[ProofStep],
    demand_result,
) -> ProofDecision:
    has_result = demand_result is not None
    parity = (
        has_result
        and abs(demand_result.total.q_day - project.flows.q_day_tot) <= 0.001
    )
    status = "verified" if parity else "missing"
    summary = (
        "Суточный расход совпадает со штатным legacy-алгоритмом."
        if parity else
        "Расход не подтверждён либо отличается от результата расчётного ядра."
    )
    steps = list(source_steps)
    steps.extend((
        ProofStep(
            "decision",
            "Принятый суточный расход",
            f"{_ru(project.flows.q_day_tot, 3)} м³/сут",
            summary,
        ),
        ProofStep(
            "artifact",
            "Где использовано",
            "ПЗ · расчёты В1 · баланс ВиВ",
            "Одно значение передаётся во все документы из модели Project.",
        ),
    ))
    return ProofDecision(
        "v1-q-day", "В1", "Суточный расход",
        _ru(project.flows.q_day_tot, 1), "м³/сут", status, summary,
        steps=steps,
        artifacts=["Пояснительная записка", "Расчёты В1", "Баланс ВиВ"],
        impact=[
            "баланс водопотребления и водоотведения",
            "эксплуатационные расходы водомеров",
            "годовой расход воды",
        ],
    )


def _second_flow_decision(project: Project, demand_result) -> ProofDecision:
    if demand_result is None:
        return ProofDecision(
            "v1-q-sec", "В1", "Секундный расход ХВС", "—", "л/с", "missing",
            "Группы потребителей не заданы.",
            steps=[
                ProofStep("source", "Группы потребителей", "не заданы"),
                ProofStep("artifact", "Результат", "не сформирован"),
            ],
            artifacts=["Расчёты В1"],
            impact=["водомерный узел", "диаметр ввода", "рабочая точка насоса"],
        )

    cold = demand_result.cold
    direct_hydraulic = getattr(
        getattr(project, "v1_hydraulic_result", None), "source_flow_lps", None,
    )
    parity = abs(cold.q_sec - project.flows.q_sec_c) <= 0.001
    explained_by_topology = (
        direct_hydraulic is not None
        and abs(float(direct_hydraulic) - project.flows.q_sec_c) <= 0.001
    )
    status = "verified" if parity or explained_by_topology else "missing"
    if parity:
        calculation_detail = (
            f"NP={_ru(cold.np_sec, 4)}; q₀,ср={_ru(cold.q0_avg, 4)} л/с; "
            f"α={_ru(cold.alpha, 3)}; "
            f"q=5×q₀,ср×α={_ru(cold.q_sec, 3)} л/с."
        )
        summary = "Секундный расход совпадает со штатным вероятностным расчётом."
    elif explained_by_topology:
        calculation_detail = (
            f"Расчёт групп дал {_ru(cold.q_sec, 3)} л/с; "
            f"расчётная топология В1 — {_ru(direct_hydraulic, 3)} л/с."
        )
        summary = "Итоговый расход подтверждён расчётной топологией В1."
    else:
        calculation_detail = (
            f"Расчёт групп дал {_ru(cold.q_sec, 3)} л/с; "
            f"в Project записано {_ru(project.flows.q_sec_c, 3)} л/с."
        )
        summary = "Обнаружено расхождение результата и расчётного ядра."

    return ProofDecision(
        "v1-q-sec", "В1", "Секундный расход ХВС",
        _ru(project.flows.q_sec_c, 3), "л/с", status, summary,
        steps=[
            ProofStep(
                "source", "Группы потребителей",
                f"{len(project.consumer_groups)} расчётных групп",
                "Состав и количество взяты из блока 02.",
            ),
            ProofStep(
                "norm", "Вероятностный метод",
                "СП 30.13330.2020, приложения А и Б",
                "Коэффициент α определяется по таблице Б.2.",
            ),
            ProofStep(
                "calculation", "Алгоритм calcBlock",
                "q = 5 × q₀,ср × α",
                calculation_detail,
            ),
            ProofStep(
                "decision", "Расчётный расход ХВС",
                f"{_ru(project.flows.q_sec_c, 3)} л/с",
                summary,
            ),
            ProofStep(
                "artifact", "Где использовано",
                "водомер · ввод В1 · насос · расчётный лист",
            ),
        ],
        artifacts=["Расчёты В1", "Подбор насосов", "Спецификация"],
        impact=["подбор водомера", "диаметр и скорость на вводе", "расход насоса В1"],
    )


def _meter_decision(project: Project) -> ProofDecision:
    meter = _cold_meter(project)
    if meter is None:
        return ProofDecision(
            "v1-meter", "В1", "Водомерный узел", "—", "", "missing",
            "Водомерный узел не подобран.",
            steps=[
                ProofStep(
                    "source", "Расчётные расходы",
                    f"qсек={_ru(project.flows.q_sec_c, 3)} л/с",
                ),
                ProofStep("norm", "Проверки водомера", "СП 30.13330.2020, раздел 12"),
                ProofStep("decision", "Подбор", "результат отсутствует"),
            ],
            artifacts=["Расчёты В1", "Спецификация"],
            impact=["потери напора", "требуемый напор", "обводная линия"],
        )
    checks_ok = meter.ok_a and meter.ok_b and meter.ok_v
    status = "verified" if checks_ok else "missing"
    summary = (
        "Проверки потерь, пожарного режима и малых расходов пройдены."
        if checks_ok else
        "Одна или несколько проверок водомера требуют решения."
    )
    return ProofDecision(
        "v1-meter", "В1", "Водомерный узел",
        f"DN{meter.dn}", meter.type_label, status, summary,
        steps=[
            ProofStep(
                "source", "Расчётные расходы",
                (
                    f"qсек ХВС={_ru(project.flows.q_sec_c, 3)} л/с; "
                    f"qч ХВС={_ru(project.flows.q_hr_c, 3)} м³/ч"
                ),
            ),
            ProofStep(
                "norm", "Условия подбора",
                "СП 30.13330.2020, раздел 12",
                "Проверяются потери при нормальном и пожарном режимах и малые расходы.",
            ),
            ProofStep(
                "calculation", "Потери напора",
                f"h=S·q²={_ru(meter.h_a, 3)} м",
                (
                    f"Допустимо {_ru(meter.lim_a, 1)} м; "
                    f"пожарный режим "
                    f"{_ru(meter.h_b, 3) + ' м' if meter.h_b is not None else 'не применяется'}."
                ),
            ),
            ProofStep(
                "decision", "Принятый узел",
                f"{meter.label}, DN{meter.dn}",
                summary,
            ),
            ProofStep(
                "artifact", "Где использовано",
                "ПЗ · расчёт В1 · спецификация · Hтр",
            ),
        ],
        artifacts=["Пояснительная записка", "Расчёты В1", "Спецификация"],
        impact=["потери ∑Hвод", "требуемый напор", "обводная линия"],
    )


def _head_decision(project: Project) -> ProofDecision:
    meter = _cold_meter(project)
    head = calc_required_head(
        project.source,
        h_vod_m=(meter.h_a if meter is not None else project.source.h_vod_m),
    )
    complete = head.h_required_m is not None
    comparable = complete and head.h_guaranteed_m is not None
    status = "verified" if comparable else "missing"
    formula = " + ".join(
        f"{name.split('—', 1)[0].strip()} {_ru(value, 2)}"
        for name, value in head.components
    )
    if comparable:
        decision = (
            f"Hтр={_ru(head.h_required_m, 2)} м; "
            f"Hгар={_ru(head.h_guaranteed_m, 2)} м; "
            f"насос {'требуется' if head.pump_needed else 'не требуется'}."
        )
        summary = "Все составляющие напора и значение по ТУ сопоставлены."
    else:
        decision = (
            f"Hтр={_ru(head.h_required_m, 2)} м; "
            f"Hгар={_ru(head.h_guaranteed_m, 2)} м."
        )
        summary = "Не хватает составляющих Hтр или гарантированного напора по ТУ."
    return ProofDecision(
        "v1-head", "В1", "Требуемый напор",
        _ru(head.h_required_m, 2), "м вод. ст.", status, summary,
        steps=[
            ProofStep(
                "source", "Составляющие напора",
                formula or "неполный набор",
                (
                    f"Свободный напор диктующего прибора Hпр="
                    f"{_ru(head.h_pr_m, 1)} м."
                ),
            ),
            ProofStep(
                "norm", "Формула требуемого напора",
                "СП 30.13330.2020, п. 8.27, формула (14)",
            ),
            ProofStep(
                "calculation", "Суммирование",
                f"Hтр={_ru(head.h_required_m, 2)} м",
                formula,
            ),
            ProofStep(
                "decision", "Сопоставление с ТУ",
                decision,
                summary,
            ),
            ProofStep(
                "artifact", "Где использовано",
                "ПЗ · расчёт В1 · подбор насосов",
            ),
        ],
        artifacts=["Пояснительная записка", "Расчёты В1", "Подбор насосов"],
        impact=["необходимость повысительной установки", "рабочая точка насоса"],
    )


def _pump_decision(project: Project) -> ProofDecision:
    pump = project.pumps
    meter = _cold_meter(project)
    head = calc_required_head(
        project.source,
        h_vod_m=(meter.h_a if meter is not None else project.source.h_vod_m),
    )
    if head.pump_needed is False:
        return ProofDecision(
            "v1-pump", "В1", "Повысительная установка",
            "не требуется", "", "not_applicable",
            "Гарантированный напор покрывает требуемый.",
            steps=[
                ProofStep(
                    "source", "Напоры",
                    (
                        f"Hтр={_ru(head.h_required_m, 2)} м; "
                        f"Hгар={_ru(head.h_guaranteed_m, 2)} м"
                    ),
                ),
                ProofStep("norm", "Насосные установки", "СП 30.13330.2020, раздел 13"),
                ProofStep(
                    "decision", "Повышение давления",
                    "не требуется",
                    "Hтр не превышает Hгар.",
                ),
                ProofStep("artifact", "Где отражено", "ПЗ · подбор насосов · схема"),
            ],
            artifacts=["Пояснительная записка", "Подбор насосов", "Схема"],
            impact=["состав оборудования", "спецификация", "принципиальная схема"],
        )

    if head.pump_needed is None:
        status = "missing"
        value = "не определено"
        summary = "Нельзя определить насос без полного Hтр и Hгар."
    elif not pump.model:
        status = "missing"
        value = "требуется подбор"
        summary = "Насос требуется, но каталог не дал подтверждённого кандидата."
    else:
        status = "verified"
        value = pump.model
        summary = "Модель выбрана по пересечению кривой насоса и кривой системы."

    return ProofDecision(
        "v1-pump", "В1", "Повысительная установка",
        value, "", status, summary,
        steps=[
            ProofStep(
                "source", "Расчётная точка системы",
                (
                    f"Q={_ru(pump.q_design_m3h or pump.wp_q, 2)} м³/ч; "
                    f"Hнас={_ru(head.h_pump_m, 2)} м"
                ),
                "Напор насоса равен дефициту Hтр − Hгар.",
            ),
            ProofStep(
                "norm", "Насосные установки",
                "СП 30.13330.2020, раздел 13",
            ),
            ProofStep(
                "calculation", "Рабочая точка",
                (
                    f"Q={_ru(pump.wp_q, 2)} м³/ч; "
                    f"H={_ru(pump.wp_h, 1)} м"
                    if pump.model else "каталожный кандидат отсутствует"
                ),
                pump.selection_note,
            ),
            ProofStep(
                "decision", "Принятая установка",
                value,
                summary,
            ),
            ProofStep(
                "artifact", "Где использовано",
                "подбор насосов · ПЗ · схема · спецификация",
            ),
        ],
        artifacts=["Подбор насосов", "Пояснительная записка", "Схема", "Спецификация"],
        impact=["график Q–H", "электрическая мощность", "состав насосной группы"],
    )


def _diameter_decision(project: Project) -> ProofDecision:
    stage_p = getattr(project, "v1_stage_p_result", None)
    if stage_p and getattr(stage_p, "rows", None):
        row = stage_p.rows[0]
        status = "verified" if row.velocity_ok else "missing"
        summary = (
            "Сечение ввода прошло проверку скорости."
            if row.velocity_ok else
            "Скорость на вводе превышает допустимую."
        )
        return ProofDecision(
            "v1-diameter", "В1", "Сечение ввода",
            f"DN{row.dn}", f"{row.outer_mm:g}×{row.wall_mm:g} мм", status, summary,
            steps=[
                ProofStep(
                    "source", "Расход и число вводов",
                    (
                        f"Q={_ru(row.flow_lps, 3)} л/с; "
                        f"вводов={project.source.inputs_count}"
                    ),
                ),
                ProofStep(
                    "norm", "Подбор трубопровода",
                    "СП 30.13330.2020; каталог точных размеров Zarya",
                ),
                ProofStep(
                    "calculation", "Фактическое внутреннее сечение",
                    (
                        f"Dнар={row.outer_mm:g} мм; стенка={row.wall_mm:g} мм; "
                        f"Dвн={row.inner_mm:g} мм"
                    ),
                ),
                ProofStep(
                    "decision", "Скорость",
                    f"v={_ru(row.velocity_mps, 3)} м/с",
                    summary,
                ),
                ProofStep("artifact", "Где использовано", "расчёт В1 · спецификация"),
            ],
            artifacts=["Расчёты В1", "Спецификация"],
            impact=["скорость на вводе", "позиция трубы в спецификации"],
        )
    return ProofDecision(
        "v1-diameter", "В1", "Сечение ввода", "стадия Р", "", "stage_r",
        "Точное сечение определяется расчётной топологией или на стадии Р.",
        steps=[
            ProofStep(
                "source", "Расчётная схема В1",
                "точная топология не задана",
            ),
            ProofStep(
                "decision", "Граница стадии",
                "не выдавать фиктивно точное сечение",
            ),
            ProofStep("artifact", "Фиксация", "ПЗ · паспорт проекта"),
        ],
        artifacts=["Пояснительная записка", "Паспорт проекта"],
        impact=["гидравлика участков", "спецификация труб"],
    )


def _fire_decision(project: Project) -> ProofDecision:
    fire = project.fire
    auto_ready = (
        fire.determination_mode != "auto"
        or project.building.fire_height_m is not None
    )
    status = "verified" if auto_ready else "missing"
    if fire.required:
        value = f"{_ru(fire.q_total, 1)} л/с"
        summary = "Необходимость В2 и пожарный расход определены по СП 10."
        result = (
            f"В2 требуется; {fire.streams} струй × "
            f"{_ru(fire.q_per_stream, 1)} л/с = {_ru(fire.q_total, 1)} л/с."
        )
    else:
        value = "не требуется"
        summary = (
            "ВПВ не требуется для введённых параметров здания."
            if auto_ready else
            "Для автоматической проверки не задана пожарно-техническая высота."
        )
        result = fire.normative_note or summary
    return ProofDecision(
        "v2-requirement", "В2", "Необходимость ВПВ",
        value, "", status, summary,
        steps=[
            ProofStep(
                "source", "Параметры здания",
                (
                    f"назначение={project.building.purpose.value}; "
                    f"этажей={project.building.floors_above}; "
                    f"hпт={_ru(project.building.fire_height_m, 1)} м"
                ),
                f"Режим определения: {fire.determination_mode}.",
            ),
            ProofStep(
                "norm", "Область применения и расход",
                "СП 10.13130.2020, таблица 7.1",
                "Интерполяции и значения «по практике» не применяются.",
            ),
            ProofStep(
                "decision", "Решение по В2",
                result,
                fire.normative_note,
            ),
            ProofStep(
                "artifact", "Где использовано",
                "ПЗ · схема · гидравлика В2 · спецификация",
            ),
        ],
        artifacts=["Пояснительная записка", "Схема", "Гидравлический расчёт", "Спецификация"],
        impact=["схема В1/В2", "пожарный расход", "пожарная насосная", "спецификация"],
    )


def _fire_hydraulic_decision(project: Project) -> Optional[ProofDecision]:
    if not project.fire.required:
        return None
    fire = project.fire
    complete = fire.required_head_m is not None
    if not complete:
        status = "missing"
        value = "нужна схема"
        summary = "Без расчётной сети В2 требуемый напор не подтверждён."
    else:
        status = "verified"
        value = f"{_ru(fire.required_head_m, 1)} м"
        summary = "Требуемый напор получен по диктующему сценарию В2."
    return ProofDecision(
        "v2-hydraulics", "В2", "Напор и насос В2",
        value, "", status, summary,
        steps=[
            ProofStep(
                "source", "Расчётная сеть",
                (
                    f"ПК={fire.pk_total}; диктующий="
                    f"{fire.dictating_cabinet_id or 'не определён'}"
                ),
            ),
            ProofStep(
                "norm", "Гидравлика ВПВ",
                "СП 10.13130.2020, разделы 6 и 12",
            ),
            ProofStep(
                "calculation", "Сопоставление напоров",
                (
                    f"Hтр={_ru(fire.required_head_m, 1)} м; "
                    f"Hдост={_ru(fire.available_head_m, 1)} м"
                ),
            ),
            ProofStep(
                "decision", "Пожарная насосная",
                (
                    project.fire_pumps.model
                    if project.fire_pumps.model else
                    "требуется подбор" if fire.needs_pump else
                    "не требуется" if fire.needs_pump is False else
                    "не определено"
                ),
                summary,
            ),
            ProofStep(
                "artifact", "Где использовано",
                "гидравлический расчёт · подбор насосов · ПЗ",
            ),
        ],
        artifacts=["Гидравлический расчёт", "Подбор насосов", "Пояснительная записка"],
        impact=["рабочая точка насоса В2", "график Q–H", "схема В2"],
    )


def _stage_boundary_decision(project: Project) -> ProofDecision:
    return ProofDecision(
        "t3-t4-stage", "Т3/Т4", "Граница расчётов стадии П",
        "зафиксирована", "", "stage_r",
        "Точные параметры циркуляционных ветвей не выдаются без аксонометрии.",
        steps=[
            ProofStep(
                "source", "Стадия и геометрия",
                (
                    f"стадия {project.document.stage_label}; "
                    f"точная аксонометрия "
                    f"{'задана' if project.v1_network else 'не задана'}"
                ),
            ),
            ProofStep(
                "norm", "Граница детализации",
                "СП 30.13330.2020; правила расчётного ядра Zarya",
            ),
            ProofStep(
                "decision", "На стадии П",
                (
                    "общие принципы балансировки и предварительные решения; "
                    "без фиктивных Kv, настроек клапанов и окончательной "
                    "рабочей точки циркуляционного насоса"
                ),
            ),
            ProofStep(
                "artifact", "Где зафиксировано",
                "ПЗ · паспорт проекта · спецификация",
            ),
        ],
        artifacts=["Пояснительная записка", "Паспорт проекта", "Спецификация"],
        impact=["циркуляционные клапаны", "гидравлика колец Т4", "насос Т4"],
    )


def _optional_normative_decisions(project: Project) -> list[ProofDecision]:
    decisions: list[ProofDecision] = []
    normative = project.normative
    if normative.sp253_applicable:
        network = decide_fire_network(project.fire, project.materials, normative)
        decisions.append(ProofDecision(
            "high-rise-systems", "В1/В2", "Высотные требования",
            "учтены", "", "specified",
            "Раздельные системы и требования к оборудованию прослежены в комплекте.",
            steps=[
                ProofStep(
                    "source", "Высота здания",
                    f"{_ru(project.building.height_m, 1)} м",
                ),
                ProofStep(
                    "norm", "Высотные инженерные системы",
                    (
                        "СП 253.1325800.2016, пп. 10.3, 10.15, "
                        "10.23, 10.25, 10.27"
                    ),
                ),
                ProofStep(
                    "decision", "Принятые меры",
                    (
                        (network.summary if network else "В2 не требуется")
                        + "; изоляция 10/25 мм; 100% резерв; "
                        "регулируемый привод; диспетчеризация."
                    ),
                ),
                ProofStep("artifact", "Где использовано", "ПЗ · схема · спецификация"),
            ],
            artifacts=["Пояснительная записка", "Схема", "Спецификация"],
            impact=["схема В1/В2", "изоляция", "насосные группы", "диспетчеризация"],
        ))
    if normative.apartment_hose_tap_required:
        count = project.building.apartments
        decisions.append(ProofDecision(
            "apartment-hose-tap", "В1", "Квартирные краны DN15",
            str(count) if count else "нужно число квартир", "компл.",
            "specified" if count else "missing",
            (
                "Количество равно числу квартир."
                if count else "Для количества комплектов нужна экспликация квартир."
            ),
            steps=[
                ProofStep("source", "Количество квартир", str(count) if count else "не задано"),
                ProofStep(
                    "norm", "Первичное пожаротушение",
                    "СП 54.13330.2022, п. 6.2.4.3",
                ),
                ProofStep(
                    "decision", "Кран DN15, шланг и распылитель",
                    f"{count} комплектов" if count else "количество не определено",
                ),
                ProofStep("artifact", "Где использовано", "ПЗ · спецификация В1"),
            ],
            artifacts=["Пояснительная записка", "Спецификация"],
            impact=["количество комплектов", "спецификация В1"],
        ))
    sewage = project.sewage
    sewage_result = sewage.result
    decisions.append(ProofDecision(
        "k1-flow", "К1", "Расчётный расход стоков",
        (
            _ru(sewage_result.total.q_sewage_lps, 3)
            if sewage_result is not None else "нужны данные"
        ),
        "л/с",
        "verified" if sewage_result is not None else "missing",
        (
            "Расход К1 получен тем же принятым алгоритмом, что и legacy."
            if sewage_result is not None else
            "Группы потребителей не заданы; условный расход не подставлен."
        ),
        steps=[
            ProofStep(
                "source", "Расход воды и диктующий прибор",
                (
                    f"qtot={_ru(sewage_result.total.q_water_total_lps, 3)} л/с; "
                    f"q0s={_ru(sewage_result.total.q_fixture_max_lps, 3)} л/с"
                    if sewage_result is not None else "не определены"
                ),
            ),
            ProofStep(
                "norm", "Расчёт водоотведения",
                "СП 30.13330.2020, п. 5.5, формула (5)",
            ),
            ProofStep(
                "calculation", "qₛ = qtot + q0s",
                (
                    f"{_ru(sewage_result.total.q_sewage_lps, 3)} л/с"
                    if sewage_result is not None else "не рассчитан"
                ),
            ),
            ProofStep(
                "artifact", "Где использовано",
                "ПЗ К1/К2 · расчёты К1/К2 · схема К1/К2 · спецификация К1/К2",
            ),
        ],
        artifacts=[
            "Пояснительная записка К1/К2",
            "Расчёты К1/К2",
            "Схема К1/К2",
            "Спецификация К1/К2",
        ],
        impact=["стояки К1", "выпуски К1", "спецификация"],
    ))
    for row in (sewage_result.risers if sewage_result else []):
        decisions.append(ProofDecision(
            f"k1-riser-{row.riser_id}", "К1",
            f"Стояк {row.riser_id}",
            (
                _ru(row.capacity_lps, 3)
                if row.capacity_lps is not None else "требует данных"
            ),
            "л/с",
            (
                "verified" if row.status == "verified"
                else "missing" if row.status == "missing"
                else "stage_r" if row.status == "stage_r"
                else "fail"
            ),
            row.note,
            steps=[
                ProofStep(
                    "source", "Назначенная нагрузка",
                    f"{_ru(row.design_flow_lps, 3)} л/с",
                ),
                ProofStep(
                    "source", "Конфигурация",
                    (
                        f"{row.material_label}; {row.ventilation_label}; "
                        f"DN {row.riser_dn_mm}/{row.branch_dn_mm}; "
                        f"{_ru(row.branch_angle_deg, 1)}°"
                    ),
                ),
                ProofStep(
                    "norm", "Точный табличный узел",
                    f"СП 30.13330.2020, приложение К, таблица {row.table}",
                ),
                ProofStep(
                    "decision", "Проверка",
                    row.note,
                ),
            ],
            artifacts=["Расчёты К1/К2"],
            impact=["диаметр стояка", "аксонометрия", "спецификация"],
        ))

    if project.storm.roof_type != "not_set":
        storm = project.storm
        result = storm.result
        decisions.append(ProofDecision(
            "k2-flow", "К2", "Дождевой расход",
            (
                _ru(result.q_total_l_per_s, 3)
                if result is not None else "нужны данные"
            ),
            "л/с",
            "verified" if result is not None else "missing",
            (
                "Расход рассчитан штатным алгоритмом К2."
                if result is not None else
                "Не заданы город и/или площадь кровли."
            ),
            steps=[
                ProofStep(
                    "source", "Кровля и интенсивность дождя",
                    (
                        f"тип={storm.roof_type}; город={storm.city_code or 'не задан'}; "
                        f"F={_ru(storm.roof_area_m2, 1)} м²"
                    ),
                ),
                ProofStep(
                    "norm", "Внутренние водостоки",
                    "СП 30.13330.2020, пп. 21.10–21.12",
                ),
                ProofStep(
                    "calculation", "Расход К2",
                    (
                        f"{_ru(result.q_total_l_per_s, 3)} л/с"
                        if result is not None else "не рассчитан"
                    ),
                ),
                ProofStep(
                    "artifact", "Где использовано",
                    "ПЗ К1/К2 · расчёты К1/К2 · схема К1/К2 · спецификация К1/К2",
                ),
            ],
            artifacts=[
                "Пояснительная записка К1/К2",
                "Расчёты К1/К2",
                "Схема К1/К2",
                "Спецификация К1/К2",
            ],
            impact=["воронки и стояки К2", "выпуски", "спецификация"],
        ))
        assessment = storm.network_assessment
        decisions.append(ProofDecision(
            "k2-network", "К2", "Воронки и стояки",
            (
                "проверено" if assessment and assessment.status == "verified"
                else "ошибка" if assessment and assessment.status == "fail"
                else "стадия Р"
            ),
            "",
            (
                assessment.status
                if assessment and assessment.status in (
                    "verified", "stage_r", "missing", "fail"
                )
                else "missing"
            ),
            (
                "; ".join(assessment.notes)
                if assessment else
                "Нагрузки элементов и геометрия по плану кровли не заданы."
            ),
            steps=[
                ProofStep(
                    "source", "Явные данные",
                    (
                        f"воронок={storm.funnels_count}; "
                        f"стояков={storm.risers_count}; "
                        f"DN={storm.selected_riser_dn_mm or '—'}"
                    ),
                ),
                ProofStep(
                    "norm", "Проверяемые требования",
                    "СП 30.13330.2020, пп. 21.5, 21.6, таблица 21.1",
                ),
                ProofStep(
                    "decision", "Автораспределение",
                    "общий расход между элементами не распределялся",
                ),
            ],
            artifacts=["Расчёты К1/К2", "Схема К1/К2"],
            impact=["число воронок", "DN стояка", "план кровли"],
        ))
    if project.grease_trap.required:
        decisions.append(ProofDecision(
            "k1-grease", "К1", "Жироуловители",
            "требуются", "", "stage_r",
            "Необходимость определена; число и производительность требуют задания ТХ.",
            steps=[
                ProofStep(
                    "source", "Предприятие питания",
                    (
                        f"тип={project.grease_trap.preparation_type}; "
                        f"мест={project.grease_trap.seats}; "
                        f"блюд={project.grease_trap.conditional_dishes}"
                    ),
                ),
                ProofStep("norm", "Производственные стоки", "СП 118.13330.2022, п. 8.7"),
                ProofStep(
                    "decision", "Стадия П",
                    project.grease_trap.decision_note,
                ),
                ProofStep(
                    "artifact",
                    "Где использовано",
                    "ПЗ К1/К2 · спецификация К1/К2",
                ),
            ],
            artifacts=[
                "Пояснительная записка К1/К2",
                "Спецификация К1/К2",
            ],
            impact=["выпуски К1", "задание ТХ", "спецификация"],
        ))
    return decisions


def build_proof_graph(
    project: Project,
    commission: CommissionReport,
) -> ProofGraph:
    """Собрать доказательную модель без изменения Project."""
    source_steps, demand_result = _consumer_source_steps(project)
    decisions = [
        _daily_flow_decision(project, source_steps, demand_result),
        _second_flow_decision(project, demand_result),
        _meter_decision(project),
        _diameter_decision(project),
        _head_decision(project),
        _pump_decision(project),
        _fire_decision(project),
    ]
    fire_hydraulic = _fire_hydraulic_decision(project)
    if fire_hydraulic is not None:
        decisions.append(fire_hydraulic)
    decisions.append(_stage_boundary_decision(project))
    decisions.extend(_optional_normative_decisions(project))
    return ProofGraph(
        project_fingerprint=commission.project_fingerprint,
        legacy_fingerprint=commission.legacy_fingerprint,
        build_commit=commission.build_commit,
        generated_at=commission.generated_at,
        decisions=decisions,
    )

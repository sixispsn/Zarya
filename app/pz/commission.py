"""Комиссионный паспорт: воспроизводимость, трассировка и контроль выпуска.

Модуль не выполняет новых инженерных расчётов. Он читает уже полученные
результаты Project и объясняет, из каких данных и нормативных решений собран
комплект, а также честно показывает незакрытые вопросы стадии П/Р.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.pz.project import BuildingPurpose, Project
from app.pz.rules import decide_fire_network, project_governing_head
from app.normative.baseline import get_active_baseline


APP_VERSION = "0.6.1"
@dataclass(frozen=True)
class PassportItem:
    label: str
    value: str


@dataclass(frozen=True)
class TraceRow:
    requirement: str
    reference: str
    source_data: str
    decision: str
    deliverable: str
    status: str = "specified"


@dataclass(frozen=True)
class ControlCheck:
    code: str
    check: str
    status: str
    result: str
    action: str
    reference: str
    blocking: bool = False


@dataclass
class CommissionReport:
    passport: list[PassportItem] = field(default_factory=list)
    trace_rows: list[TraceRow] = field(default_factory=list)
    checks: list[ControlCheck] = field(default_factory=list)
    project_fingerprint: str = ""
    legacy_fingerprint: str = ""
    build_commit: str = ""
    generated_at: str = ""

    @property
    def blocking_count(self) -> int:
        return sum(1 for row in self.checks if row.blocking)

    @property
    def pending_r_count(self) -> int:
        return sum(1 for row in self.checks if row.status == "stage_r")

    @property
    def release_status(self) -> str:
        if self.blocking_count:
            return "Есть блокирующие замечания к исходным данным или расчётам"
        return "Комплект пригоден для рассмотрения на стадии П"


def _ru(value: Optional[float], precision: int = 2, suffix: str = "") -> str:
    if value is None:
        return "не задано"
    return f"{value:.{precision}f}".replace(".", ",") + suffix


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "недоступен"
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _git_commit(repo_root: Path) -> str:
    configured = os.environ.get("ZARYA_BUILD_COMMIT", "").strip()
    if configured:
        return configured[:16]
    git_dir = repo_root / ".git"
    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return "не задан в сборке"
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head[:16]
    ref = head.removeprefix("ref: ").strip()
    ref_path = git_dir / ref
    if ref_path.exists():
        return ref_path.read_text(encoding="utf-8").strip()[:16]
    packed = git_dir / "packed-refs"
    if packed.exists():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith(("#", "^")):
                commit, name = line.split(" ", 1)
                if name == ref:
                    return commit[:16]
    return "не задан в сборке"


def _project_fingerprint(project: Project) -> str:
    """Стабильный отпечаток исходных данных, а не результатов/времени выпуска."""
    source = project.source
    payload = {
        "document": {
            "cipher": project.document.cipher,
            "name": project.document.object_name,
            "stage": project.document.stage_label,
        },
        "building": {
            "purpose": project.building.purpose.value,
            "floors": project.building.floors_above,
            "height_m": project.building.height_m,
            "fire_height_m": project.building.fire_height_m,
            "area_m2": project.building.total_area_m2,
            "apartments": project.building.apartments,
            "zones": project.building.zones,
        },
        "consumers": list(project.consumer_groups),
        "source": {
            "guaranteed_head_m": source.guaranteed_head_m,
            "maximum_head_m": source.maximum_head_m,
            "h_geom_m": source.h_geom_m,
            "h_il_m": source.h_il_m,
            "h_pr_m": source.h_pr_m,
            "h_vod_m": source.h_vod_m,
            "h_tepl_m": source.h_tepl_m,
            "h_vvod_m": source.h_vvod_m,
            "inputs_count": source.inputs_count,
        },
        "fire": {
            "mode": project.fire.determination_mode,
            "required": project.fire.required,
            "streams": project.fire.streams,
            "q_per_stream": project.fire.q_per_stream,
        },
        "storm": {
            "roof_type": project.storm.roof_type,
            "city": project.storm.city_code,
            "roof_area_m2": project.storm.roof_area_m2,
            "walls_area_m2": project.storm.walls_area_m2,
            "period_years": project.storm.period_years,
            "roof_sections": project.storm.roof_sections,
            "funnels_count": project.storm.funnels_count,
            "max_funnel_spacing_m": project.storm.max_funnel_spacing_m,
            "funnel_capacity_lps":
                project.storm.selected_funnel_capacity_lps,
            "max_funnel_flow_lps": project.storm.max_funnel_flow_lps,
            "risers_count": project.storm.risers_count,
            "riser_dn_mm": project.storm.selected_riser_dn_mm,
            "max_riser_flow_lps": project.storm.max_riser_flow_lps,
            "design_m3_day": project.storm.design_m3_day,
            "annual_m3": project.storm.annual_m3,
            "melt_m3h": project.storm.melt_m3h,
            "melt_m3_day": project.storm.melt_m3_day,
            "melt_m3_year": project.storm.melt_m3_year,
            "treatment_volume_m3": project.storm.treatment_volume_m3,
            "storage_volume_m3": project.storm.storage_volume_m3,
        },
        "sewage": {
            "q0s_lps": project.sewage_max_fixture_lps,
            "outlets_count": project.sewage.outlets_count,
            "risers": [vars(row) for row in project.sewage.risers],
            "pipes": [vars(row) for row in project.sewage.pipes],
            "elements": [vars(row) for row in project.sewage.elements],
            "discharge_events": [
                vars(row) for row in project.sewage.discharge_events
            ],
            "fixture_safety_inputs": [
                vars(row) for row in project.sewage.fixture_safety_inputs
            ],
            "first_manholes": [{
                **{
                    key: value for key, value in vars(row).items()
                    if key != "levels"
                },
                "levels": [vars(point) for point in row.levels],
            } for row in project.sewage.first_manholes],
            "internal_nodes": [
                vars(row) for row in project.sewage.internal_nodes
            ],
            "gost_inputs": {
                key: value for key, value in vars(project.sewage).items()
                if key not in {
                    "result", "hydraulic_assessment", "transient_assessment",
                    "risers", "pipes", "elements", "discharge_events",
                    "fixture_safety_inputs", "first_manholes",
                    "internal_nodes",
                }
            },
        },
        "catering": {
            "type": project.grease_trap.preparation_type,
            "seats": project.grease_trap.seats,
            "dishes": project.grease_trap.conditional_dishes,
            "school_assignment": project.grease_trap.school_by_assignment,
        },
        "owner_groups": project.meters.owner_groups_count,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _cold_meter_loss(project: Project) -> Optional[float]:
    for row in project.meters.rows or []:
        if "ввод" in row.label.lower():
            return row.h_a
    for row in project.meters.rows or []:
        if "хвс" in row.label.lower() or "холодн" in row.label.lower():
            return row.h_a
    return project.source.h_vod_m


def _consumer_source(project: Project) -> str:
    if not project.consumer_groups:
        return "группы потребителей не заданы"
    details = []
    names = {
        code: name for name, code, _ in (project.consumer_details or [])
    }
    for code, count in project.consumer_groups:
        details.append(f"{names.get(code) or code}: {count}")
    return "; ".join(details)


def _systems(project: Project) -> str:
    systems = ["В1"]
    if project.building.hws_type.value != "none":
        systems.extend(("Т3", "Т4"))
    if project.fire.required:
        systems.append("В2")
    systems.append("К1")
    if project.storm.roof_type != "not_set":
        systems.append("К2")
    return ", ".join(systems)


def _purpose_label(purpose: BuildingPurpose) -> str:
    return {
        BuildingPurpose.RESIDENTIAL: "жилое",
        BuildingPurpose.PUBLIC: "общественное",
        BuildingPurpose.INDUSTRIAL: "производственное",
    }[purpose]


def build_commission_report(
    project: Project,
    artifacts: Optional[dict[str, bool]] = None,
) -> CommissionReport:
    repo_root = Path(__file__).resolve().parents[2]
    legacy_hash = _file_sha256(repo_root / "legacy" / "sp30_calculator.html")
    commit = _git_commit(repo_root)
    project_hash = _project_fingerprint(project)
    normative_baseline = get_active_baseline()
    generated_at = datetime.now().astimezone().strftime("%d.%m.%Y %H:%M %Z")
    head = project_governing_head(
        project, fallback_h_vod_m=_cold_meter_loss(project),
    )
    fire_net = decide_fire_network(
        project.fire, project.materials, project.normative,
    )
    head_paths_complete = (
        project.head_paths is None or project.head_paths.complete
    )

    passport = [
        PassportItem("Объект", project.document.object_name or "не задан"),
        PassportItem("Шифр / стадия", f"{project.document.cipher or 'без шифра'} / {project.document.stage_label}"),
        PassportItem(
            "Назначение и геометрия",
            f"{_purpose_label(project.building.purpose)}; "
            f"{project.building.floors_above} эт.; "
            f"{_ru(project.building.height_m, 1, ' м')}",
        ),
        PassportItem("Системы комплекта", _systems(project)),
        PassportItem("Расчётное ядро", f"legacy/sp30_calculator.html, SHA-256 {legacy_hash}"),
        PassportItem("Версия приложения / commit", f"Zarya {APP_VERSION} / {commit}"),
        PassportItem("Fingerprint исходных данных", project_hash),
        PassportItem(
            "Нормативная база",
            normative_baseline.commission_summary(),
        ),
        PassportItem(
            "Граница стадии",
            "Точные расходы и напоры — по введённым данным; количества и настройки, "
            "требующие планов/аксонометрии, маркируются для стадии Р.",
        ),
    ]

    flow_ok = bool(project.consumer_groups) and project.flows.q_day_tot > 0
    transient = project.sewage.transient_assessment
    fixture_checks = list(
        getattr(transient, "fixture_checks", ()) if transient else ()
    )
    fixture_safety_ok = bool(fixture_checks) and all(
        row.status.value == "Норма" for row in fixture_checks
    )
    fixture_safety_critical = any(
        row.status.value in {"Критическое состояние", "Подпор", "Подтопление"}
        for row in fixture_checks
    )
    internal_node_checks = list(
        getattr(transient, "internal_node_summaries", ()) if transient else ()
    )
    internal_node_overflow = any(
        row.status.value == "overflow" for row in internal_node_checks
    )
    internal_nodes_ok = bool(internal_node_checks) and not internal_node_overflow
    trace_rows = [
        TraceRow(
            "Расчётные расходы В1/Т3",
            "СП 30.13330.2020, приложение А",
            _consumer_source(project),
            (
                f"Qсут={_ru(project.flows.q_day_tot, 2, ' м³/сут')}; "
                f"qсек={_ru(project.flows.q_sec_tot, 3, ' л/с')}"
                if flow_ok else "расчёт не подтверждён"
            ),
            "ПЗ, подп. г; Расчёты В1; Баланс ВиВ",
            "verified" if flow_ok else "missing",
        ),
        TraceRow(
            "Расчётный расход К1",
            "СП 30.13330.2020, п. 5.5, формула (5)",
            (
                f"qtot={_ru(project.flows.q_sec_tot, 3, ' л/с')}; "
                f"q0s={_ru(project.sewage_max_fixture_lps, 3, ' л/с')}"
            ),
            (
                f"qs={_ru(project.sewage.result.total.q_sewage_lps, 3, ' л/с')}"
                if project.sewage.result else "расчёт не подтверждён"
            ),
            "ПЗ К1/К2; Расчёты К1/К2; схема К1/К2",
            "verified" if project.sewage.result else "missing",
        ),
        TraceRow(
            "Гидрозатворы и подпор от первого колодца",
            "СП 30.13330.2020, раздел 19",
            (
                f"точных привязок приборов: {len(fixture_checks)}; "
                f"первых колодцев: {len(project.sewage.first_manholes)}"
                if fixture_checks else
                "абсолютные отметки приборов/уровни первых колодцев не заданы"
            ),
            (
                "гидрозатворы сохранены, подпор к приборам отсутствует"
                if fixture_safety_ok else
                "обнаружено критическое состояние/подпор"
                if fixture_safety_critical else
                "требуются точные высотные и граничные данные"
            ),
            "Расчёты К1/К2 — временной сценарий",
            (
                "verified" if fixture_safety_ok else
                "fail" if fixture_safety_critical else "stage_r"
            ),
        ),
        TraceRow(
            "Локализация накопления и аварийного перелива К1",
            "СП 30.13330.2020, раздел 19; профиль и аксонометрия К1",
            (
                f"внутренних узлов с точной геометрией: "
                f"{len(project.sewage.internal_nodes)}"
                if project.sewage.internal_nodes else
                "отметки перелива и объёмы внутренних узлов не заданы"
            ),
            (
                "перелив в расчётном сценарии отсутствует"
                if internal_nodes_ok else
                "обнаружен аварийный перелив в зарегистрированном узле"
                if internal_node_overflow else
                "место выхода воды нельзя подтвердить"
            ),
            "Расчёты К1/К2 — временной сценарий",
            (
                "verified" if internal_nodes_ok else
                "fail" if internal_node_overflow else "stage_r"
            ),
        ),
        TraceRow(
            "Требуемый напор В1",
            "СП 30.13330.2020, п. 8.27, формула (14)",
            (
                f"Hгеом={_ru(head.h_geom_m, 2, ' м')}; "
                f"ΣHпот={_ru(head.h_losses_dynamic_m, 2, ' м')}; "
                f"Hпр={_ru(head.h_pr_m, 2, ' м')}; "
                f"Hгар={_ru(head.h_guaranteed_m, 2, ' м')}"
            ),
            (
                f"Hтр={_ru(head.h_required_m, 2, ' м')}; "
                f"насос {'требуется' if head.pump_needed else 'не требуется'}"
                if head.h_required_m is not None and head.pump_needed is not None
                else "исходные данные недостаточны"
            ),
            "ПЗ, подп. е; Расчёты В1; Подбор насосов",
            "verified" if head.h_required_m is not None and head_paths_complete else "missing",
        ),
        TraceRow(
            "Внутренний противопожарный водопровод",
            "СП 10.13130.2020, таблица 7.1 и разделы 6, 12",
            (
                f"режим={project.fire.determination_mode}; "
                f"hпт={_ru(project.building.fire_height_m, 1, ' м')}; "
                f"струй={project.fire.streams}"
            ),
            (
                f"В2 требуется; q={_ru(project.fire.q_total, 1, ' л/с')}; "
                f"Hтр={_ru(project.fire.required_head_m, 1, ' м')}"
                if project.fire.required else
                f"В2 не требуется: {project.fire.normative_note}"
            ),
            "ПЗ; схема; гидравлический расчёт; подбор насосов",
            (
                "verified" if not project.fire.required or project.fire.required_head_m is not None
                else "missing"
            ),
        ),
    ]

    if project.normative.separate_v1_v2_required:
        trace_rows.append(TraceRow(
            "Раздельные системы В1 и В2 высотного здания",
            "СП 253.1325800.2016, п. 10.3",
            f"высота здания {_ru(project.building.height_m, 1, ' м')}",
            fire_net.summary if fire_net else "В2 не определён",
            "ПЗ, подп. в; схема; спецификация",
            "specified" if fire_net and not fire_net.combined else "missing",
        ))
    if project.normative.apartment_hose_tap_required:
        trace_rows.append(TraceRow(
            "Квартирный кран Ду15 со шлангом и распылителем",
            "СП 54.13330.2022, п. 6.2.4.3",
            f"квартир: {project.building.apartments or 'не задано'}",
            (
                f"{project.building.apartments} комплектов"
                if project.building.apartments else "количество не определено"
            ),
            "ПЗ, подп. в; спецификация В1",
            "specified" if project.building.apartments else "missing",
        ))
    if project.normative.sp253_applicable:
        trace_rows.extend((
            TraceRow(
                "Теплоизоляция трубопроводов высотного здания",
                "СП 253.1325800.2016, п. 10.15",
                "расчёт толщины legacy + нормативный минимум",
                "ХВС ≥10 мм; ГВС и циркуляция ≥25 мм",
                "ПЗ, подп. в; спецификация В1/Т3-Т4",
                "specified",
            ),
            TraceRow(
                "Резервирование, привод и управление насосами",
                "СП 253.1325800.2016, пп. 10.23, 10.25, 10.27",
                "рабочие точки В1/В2 по расчёту напора",
                "100% резерв; регулируемый привод; диспетчеризация",
                "ПЗ; подбор насосов; спецификация",
                "specified",
            ),
        ))
    if project.normative.separate_owner_metering_required:
        trace_rows.append(TraceRow(
            "Автономный учёт групп разных собственников",
            "СП 118.13330.2022, п. 8.24",
            f"групп собственников: {project.meters.owner_groups_count}",
            "самостоятельные узлы учёта ХВС и ГВС",
            "ПЗ, подп. л; спецификация В1/Т3-Т4",
            "specified",
        ))
    if project.normative.separate_k1_required:
        trace_rows.append(TraceRow(
            "Раздельные выпуски канализации функциональных частей",
            "СП 253.1325800.2016, п. 11.2",
            "смешанный функциональный состав высотного здания",
            "самостоятельные системы и выпуски К1",
            "ПЗ; графические решения стадии Р",
            "stage_r",
        ))
    if project.storm.roof_type != "not_set":
        storm_result = project.storm.result
        trace_rows.append(TraceRow(
            "Система К2 и расход дождевых вод",
            "СП 30.13330.2020, пп. 21.5–21.12",
            (
                f"кровля={project.storm.roof_type}; город={project.storm.city_code or 'не задан'}; "
                f"Fкр={_ru(project.storm.roof_area_m2, 1, ' м²')}"
            ),
            (
                f"{project.storm.system_note} Q={_ru(storm_result.q_total_l_per_s, 3, ' л/с')}"
                if storm_result else project.storm.system_note
            ),
            "ПЗ К1/К2; Расчёты К1/К2; схема К1/К2; спецификация К1/К2",
            "verified" if storm_result else "missing",
        ))
    if project.grease_trap.preparation_type != "none":
        trace_rows.append(TraceRow(
            "Жироуловители производственных стоков",
            "СП 118.13330.2022, п. 8.7",
            (
                f"тип={project.grease_trap.preparation_type}; "
                f"мест={project.grease_trap.seats}; "
                f"блюд={project.grease_trap.conditional_dishes}"
            ),
            project.grease_trap.decision_note,
            "ПЗ; спецификация К1",
            "stage_r" if project.grease_trap.required else "verified",
        ))

    checks: list[ControlCheck] = []

    def add(
        code: str,
        check: str,
        status: str,
        result: str,
        action: str,
        reference: str,
        blocking: bool = False,
    ) -> None:
        checks.append(ControlCheck(
            code, check, status, result, action, reference, blocking,
        ))

    add(
        "SRC-01", "Группы потребителей заданы",
        "verified" if project.consumer_groups else "missing",
        _consumer_source(project),
        "Нет действий" if project.consumer_groups else "Заполнить блок 02 Wizard",
        "СП 30.13330.2020, приложение А",
        blocking=not bool(project.consumer_groups),
    )
    add(
        "CALC-01", "Расходы В1/Т3/К1 рассчитаны",
        "verified" if flow_ok else "missing",
        (
            f"Qсут={_ru(project.flows.q_day_tot, 2, ' м³/сут')}; "
            f"qсек={_ru(project.flows.q_sec_tot, 3, ' л/с')}"
            if flow_ok else "расчётного результата нет"
        ),
        "Нет действий" if flow_ok else "Проверить группы потребителей",
        "СП 30.13330.2020, приложение А",
        blocking=not flow_ok,
    )
    head_ok = head.h_required_m is not None and head.h_guaranteed_m is not None
    add(
        "CALC-02", "Требуемый и гарантированный напоры сопоставлены",
        "verified" if head_ok else "missing",
        (
            f"Hтр={_ru(head.h_required_m, 2, ' м')}; "
            f"Hгар={_ru(head.h_guaranteed_m, 2, ' м')}"
        ),
        "Нет действий" if head_ok else "Получить ТУ и заполнить составляющие Hтр",
        "СП 30.13330.2020, п. 8.27",
        blocking=not head_ok,
    )
    meters_ok = bool(project.meters.rows)
    add(
        "CALC-03", "Водомерные узлы подобраны по расчётным расходам",
        "verified" if meters_ok else "missing",
        f"расчётных узлов: {len(project.meters.rows or [])}",
        "Нет действий" if meters_ok else "Выполнить расчёт расходов и подбор водомеров",
        "СП 30.13330.2020, раздел 12",
        blocking=not meters_ok,
    )
    pump_blocking = bool(head.pump_needed and not project.pumps.model)
    add(
        "CALC-04", "Насос В1 подобран по рабочей точке",
        (
            "verified" if project.pumps.model
            else "missing" if head.pump_needed
            else "not_applicable"
        ),
        (
            f"{project.pumps.model}; Q={_ru(project.pumps.wp_q, 2, ' м³/ч')}; "
            f"H={_ru(project.pumps.wp_h, 1, ' м')}"
            if project.pumps.model else
            "насос требуется, модель не подобрана" if head.pump_needed else
            "гарантированный напор достаточен"
        ),
        "Подтвердить актуальную каталоговую кривую" if project.pumps.model
        else "Расширить/уточнить каталог насосов" if head.pump_needed
        else "Нет действий",
        "СП 30.13330.2020, раздел 13",
        blocking=pump_blocking,
    )
    fire_ok = not project.fire.required or project.fire.required_head_m is not None
    add(
        "FIRE-01", "Необходимость и параметры В2 подтверждены",
        "verified" if fire_ok else "missing",
        (
            project.fire.normative_note if not project.fire.required else
            f"q={_ru(project.fire.q_total, 1, ' л/с')}; "
            f"Hтр={_ru(project.fire.required_head_m, 1, ' м')}"
        ),
        "Нет действий" if fire_ok else "Задать расчётную схему В2 и выполнить гидравлику",
        "СП 10.13130.2020",
        blocking=not fire_ok,
    )
    if project.normative.apartment_hose_tap_required:
        apartment_ok = project.building.apartments > 0
        add(
            "SP54-01", "Количество квартирных кранов Ду15 определено",
            "specified" if apartment_ok else "missing",
            (
                f"{project.building.apartments} комплектов"
                if apartment_ok else "число квартир не задано"
            ),
            "Нет действий" if apartment_ok else "Получить экспликацию квартир АР",
            "СП 54.13330.2022, п. 6.2.4.3",
            blocking=not apartment_ok,
        )
    if project.normative.sp253_applicable:
        add(
            "SP253-01", "Раздельные В1/В2 и требования к оборудованию учтены",
            "specified",
            "В1/В2 раздельные; изоляция 10/25 мм; резерв и регулируемый привод",
            "Подтвердить марки и сигналы диспетчеризации на стадии Р",
            "СП 253.1325800.2016, пп. 10.3, 10.15, 10.23, 10.25, 10.27",
        )
    sewage_ok = project.sewage.result is not None
    add(
        "K1-00", "Расчётный расход К1 подтверждён",
        "verified" if sewage_ok else "missing",
        (
            f"Q={_ru(project.sewage.result.total.q_sewage_lps, 3, ' л/с')}"
            if sewage_ok else "нет групп потребителей"
        ),
        "Нет действий" if sewage_ok else "Заполнить группы потребителей",
        "СП 30.13330.2020, п. 5.5, формула (5)",
        blocking=not sewage_ok,
    )
    if project.sewage.risers:
        failed_risers = [
            row.riser_id for row in project.sewage.result.risers
            if row.status == "fail"
        ] if sewage_ok else []
        pending_risers = [
            row.riser_id for row in project.sewage.result.risers
            if row.status in ("missing", "stage_r")
        ] if sewage_ok else []
        riser_status = (
            "missing" if not sewage_ok or failed_risers
            else "stage_r" if pending_risers
            else "verified"
        )
        add(
            "K1-02", "Характерные стояки К1 проверены по приложению К",
            riser_status,
            (
                "общий расход К1 не рассчитан"
                if not sewage_ok else
                "не соответствуют: " + ", ".join(failed_risers)
                if failed_risers else
                "требуют точной аксонометрии: " + ", ".join(pending_risers)
                if pending_risers else
                f"проверено {len(project.sewage.result.risers)} стояков"
            ),
            (
                "Проверить диаметр и назначенную нагрузку"
                if failed_risers else
                "Завершить по аксонометрии стадии Р"
                if pending_risers else "Нет действий"
            ),
            "СП 30.13330.2020, пп. 19.7–19.8, приложение К",
            blocking=bool(failed_risers),
        )
    add(
        "K1-03", "Конкретные гидрозатворы проверены по давлению стояков и уровню первого колодца",
        (
            "verified" if fixture_safety_ok else
            "missing" if fixture_safety_critical else "stage_r"
        ),
        (
            f"проверено {len(fixture_checks)} приборов; срыв и подпор отсутствуют"
            if fixture_safety_ok else
            "обнаружено критическое состояние, подпор или подтопление"
            if fixture_safety_critical else
            "нет полной абсолютной привязки приборов и первых колодцев"
        ),
        (
            "Нет действий" if fixture_safety_ok else
            "Устранить причину подпора/срыва и пересчитать"
            if fixture_safety_critical else
            "Задать абсолютные отметки, гидрозатворы и уровни первых колодцев"
        ),
        "СП 30.13330.2020, раздел 19; профиль выпуска",
        blocking=fixture_safety_critical,
    )
    add(
        "K1-04", "Накопление и аварийный перелив локализованы внутренними узлами",
        (
            "verified" if internal_nodes_ok else
            "missing" if internal_node_overflow else "stage_r"
        ),
        (
            f"проверено узлов: {len(internal_node_checks)}; перелив отсутствует"
            if internal_nodes_ok else
            "в расчётном сценарии зафиксирован аварийный перелив"
            if internal_node_overflow else
            "нет полного реестра отметок перелива и доступных объёмов"
        ),
        (
            "Нет действий" if internal_nodes_ok else
            "Устранить перегрузку и пересчитать сценарий"
            if internal_node_overflow else
            "Задать внутренние узлы по аксонометрии и планам АР"
        ),
        "СП 30.13330.2020, раздел 19; профиль и аксонометрия К1",
        blocking=internal_node_overflow,
    )
    if project.storm.system_kind == "internal":
        storm_ok = project.storm.result is not None
        add(
            "K2-01", "Расход внутреннего водостока рассчитан",
            "verified" if storm_ok else "missing",
            (
                f"Q={_ru(project.storm.result.q_total_l_per_s, 3, ' л/с')}"
                if storm_ok else "нет города и/или площади кровли"
            ),
            "Нет действий" if storm_ok else "Заполнить исходные данные К2",
            "СП 30.13330.2020, раздел 21",
            blocking=not storm_ok,
        )
        assessment = project.storm.network_assessment
        assessment_status = (
            "missing" if assessment and assessment.status == "fail"
            else assessment.status if assessment else "stage_r"
        )
        add(
            "K2-02", "Воронки и стояки К2 проверены по плану кровли",
            assessment_status,
            (
                "; ".join(assessment.notes)
                if assessment else
                "точная геометрия и нагрузки элементов не заданы"
            ),
            (
                "Исправить несоответствие исходных данных"
                if assessment and assessment.status == "fail"
                else "Разработать планы и аксонометрию на стадии Р"
                if assessment_status == "stage_r"
                else "Нет действий"
            ),
            "СП 30.13330.2020, пп. 21.5, 21.6, таблица 21.1",
            blocking=bool(assessment and assessment.status == "fail"),
        )
    if project.grease_trap.required:
        add(
            "K1-01", "Жироуловители предусмотрены",
            "stage_r",
            "необходимость подтверждена; число и производительность не назначены",
            "Получить задание ТХ и схему производственных выпусков",
            "СП 118.13330.2022, п. 8.7",
        )
    if project.normative.separate_owner_metering_required:
        add(
            "METER-01", "Раздельный учёт собственников предусмотрен",
            "specified",
            f"групп собственников: {project.meters.owner_groups_count}",
            "Уточнить границы балансовой принадлежности и Ду на стадии Р",
            "СП 118.13330.2022, п. 8.24",
        )
    add(
        "STAGE-01", "Граница стадии П/Р соблюдена",
        "stage_r",
        "циркуляционные расходы ветвей Т4, Kv балансиров и окончательные "
        "рабочие точки без аксонометрии не выдаются",
        "Закрыть после разработки точной аксонометрии стадии Р",
        "Правила расчётного ядра Zarya; СП 30.13330.2020",
    )
    if artifacts is not None:
        core_names = (
            "Пояснительная записка",
            "Расчёты В1",
            "Баланс ВиВ",
            "Подбор насосов",
            "Спецификация",
            "Принципиальная схема",
        )
        missing_documents = [name for name in core_names if not artifacts.get(name)]
        add(
            "DOC-01", "Основные документы комплекта сформированы",
            "verified" if not missing_documents else "missing",
            (
                "ПЗ, расчёты, баланс, подбор насосов, спецификация и схема сформированы"
                if not missing_documents else
                "не сформированы: " + ", ".join(missing_documents)
            ),
            "Нет действий" if not missing_documents else "Устранить ошибку сборки документа",
            "ПП РФ № 87; ГОСТ Р 21.619-2023",
            blocking=bool(missing_documents),
        )
        wastewater_names = (
            "Пояснительная записка К1/К2",
            "Расчёты К1/К2",
            "Баланс ИОС3 по ГОСТ Р 21.620",
            "Принципиальная схема К1/К2",
            "Спецификация К1/К2",
            "Комплект К1/К2",
        )
        missing_wastewater = [
            name for name in wastewater_names if not artifacts.get(name)
        ]
        add(
            "DOC-03", "Самостоятельный комплект К1/К2 сформирован",
            "verified" if not missing_wastewater else "missing",
            (
                "ПЗ К1/К2 с расчётным приложением и балансом приложения А, "
                "схема, спецификация и единый PDF сформированы"
                if not missing_wastewater else
                "не сформированы: " + ", ".join(missing_wastewater)
            ),
            (
                "Нет действий" if not missing_wastewater
                else "Устранить ошибку сборки комплекта К1/К2"
            ),
            "ПП РФ № 87, пункт 18; ГОСТ Р 21.620-2023; СП 30.13330.2020",
            blocking=bool(missing_wastewater),
        )
        from app.pz.wastewater_gost import audit_wastewater_gost
        wastewater_audit = audit_wastewater_gost(project)
        add(
            "DOC-04", "Состав ИОС3 проверен по ГОСТ Р 21.620-2023",
            "verified" if wastewater_audit.complete else "missing",
            (
                "обязательные сведения текстовой и графической частей заполнены"
                if wastewater_audit.complete else
                "не закрыты: " + "; ".join(
                    f"{row.code} {row.requirement}"
                    for row in wastewater_audit.missing
                )
            ),
            (
                "Нет действий" if wastewater_audit.complete else
                "Заполнить обязательные исходные данные ИОС3"
            ),
            "ГОСТ Р 21.620-2023, разделы 5-6",
            blocking=not wastewater_audit.complete,
        )
        hydraulic_exists = bool(artifacts.get("Гидравлический расчёт В2"))
        add(
            "DOC-02", "Расчётное обоснование В2 приложено",
            (
                "verified" if hydraulic_exists
                else "missing" if project.fire.required
                else "not_applicable"
            ),
            (
                "гидравлический расчёт В2 сформирован"
                if hydraulic_exists else
                "В2 требуется, расчётный лист отсутствует"
                if project.fire.required else
                "В2 не требуется"
            ),
            (
                "Нет действий" if hydraulic_exists or not project.fire.required
                else "Задать расчётную схему В2 и сформировать гидравлический лист"
            ),
            "СП 10.13130.2020",
            blocking=project.fire.required and not hydraulic_exists,
        )

    return CommissionReport(
        passport=passport,
        trace_rows=trace_rows,
        checks=checks,
        project_fingerprint=project_hash,
        legacy_fingerprint=legacy_hash,
        build_commit=commit,
        generated_at=generated_at,
    )

"""
Нормативные решения для пояснительной записки (ВК).

Чистые функции: на вход — части модели Project, на выходе — структурированное
решение с текстом обоснования и ссылкой на пункт норматива. Логика держится
здесь (не в шаблоне и не в сборщике PDF), чтобы её можно было покрыть тестами
и переиспользовать в API.

Источники:
  СП 30.13330.2020 (ред. Изм. №3 от 18.12.2023)
  СП 10.13130.2020
  ГОСТ Р 21.619-2023 (оформление)
"""
from dataclasses import dataclass, field
from typing import List, Optional

from app.pz.project import (
    BuildingFlags, BuildingPurpose, FireSystem, FlowsData, NormativeRequirements,
    PipeMaterials, WaterSource,
)

# Порог рабочего давления, выше которого хоз-питьевую и пожарную сети разделяют
# (СП 10.13130.2020, пп. 6.1.1–6.1.2; СП 30.13330.2020, 5.4.1)
PRESSURE_LIMIT_MPA = 0.45

# Коэффициент kм местных сопротивлений (∑Hil = i·l·(1+kм)), раздел 8 СП 30.13330.2020
KM_BY_NETWORK = {
    "domestic": 0.3,   # хоз-питьевые сети жилых и общественных зданий
    "combined": 0.2,   # объединённые хоз-противопожарные / производственные
    "fire": 0.1,       # противопожарные
}


@dataclass
class FireNetworkDecision:
    """Решение по схеме внутреннего противопожарного водопровода (В2)."""
    combined: bool                 # True — объединён с В1, False — раздельная сеть
    reasons: List[str]             # основания для раздельной схемы (пустой при combined)
    topology: str = "combined"
    basis: str = ""
    electric_valves: bool = False

    @property
    def summary(self) -> str:
        """Готовая фраза для подпункта в)."""
        if self.combined:
            return (
                "Система внутреннего противопожарного водопровода (В2) принята "
                "объединённой с хозяйственно-питьевым водопроводом (В1) — допускается "
                "при совпадении требований к качеству воды и рабочему давлению "
                "(СП 30.13330.2020, п. 6.1; СП 10.13130.2020, пп. 4.1, 6.1.8)."
            )
        if self.topology == "pre_meter_branch":
            basis = self.basis or "решение проектировщика по техническим условиям"
            valves = (
                " На ответвлениях В2 предусматриваются задвижки с электроприводом."
                if self.electric_valves else ""
            )
            return (
                "Ответвления внутреннего противопожарного водопровода (В2) "
                "предусматриваются от каждого ввода до узлов учёта В1; пожарный "
                f"расход через счётчики В1 не проходит. Основание: {basis}.{valves}"
            )
        reasons_txt = "; ".join(self.reasons)
        return (
            "Система внутреннего противопожарного водопровода (В2) принята "
            f"самостоятельной (раздельной) из стальных труб. Основание: {reasons_txt}."
        )


def decide_fire_network(
    fire: FireSystem,
    materials: PipeMaterials,
    normative: Optional[NormativeRequirements] = None,
) -> Optional[FireNetworkDecision]:
    """Объединённая или раздельная сеть В2. None — если ВПВ не требуется."""
    if not fire.required:
        return None

    reasons: List[str] = []

    if normative and normative.separate_v1_v2_required:
        reasons.append(
            "для высотного здания системы водоснабжения и водяного "
            "пожаротушения должны быть раздельными "
            "(СП 253.1325800.2016, п. 10.3)"
        )

    if (
        fire.pressure_at_lowest_pk_mpa is not None
        and fire.pressure_at_lowest_pk_mpa > PRESSURE_LIMIT_MPA
    ):
        reasons.append(
            f"гидростатическое давление у наиболее низко расположенного "
            f"пожарного крана ({fire.pressure_at_lowest_pk_mpa:.2f} МПа) превышает "
            f"{PRESSURE_LIMIT_MPA} МПа (СП 10.13130.2020, 6.1.1–6.1.2)"
        )

    if materials.cold_is_plastic_uncertified:
        reasons.append(
            "хозяйственно-питьевая сеть выполнена из пластиковых труб без "
            "пожарного сертификата (СП 30.13330.2020, 7.1.3)"
        )

    if fire.has_aupt:
        reasons.append(
            "пожарные краны запитываются от трубопроводов установки "
            "автоматического пожаротушения (СП 10.13130.2020, 12.1)"
        )

    requested = fire.network_topology or "auto"
    basis = fire.topology_basis.strip()

    if requested == "pre_meter_branch":
        return FireNetworkDecision(
            combined=False,
            reasons=[basis or "решение проектировщика по техническим условиям"],
            topology="pre_meter_branch",
            basis=basis,
            electric_valves=fire.branch_electric_valves,
        )

    if requested == "separate" and not reasons:
        reasons.append(basis or "раздельная схема задана проектировщиком")

    # Явное объединение не отменяет обязательные основания для разделения.
    combined = requested in ("auto", "combined") and not reasons
    topology = "combined" if combined else "separate"
    return FireNetworkDecision(
        combined=combined,
        reasons=reasons,
        topology=topology,
        basis=basis,
        electric_valves=fire.branch_electric_valves,
    )


@dataclass
class WaterInletDecision:
    """Минимальное и принятое число вводов по проверяемым условиям п. 8.4."""
    minimum_count: int
    adopted_count: int
    reasons: List[str]
    compliant: bool
    assessment_complete: bool


def decide_water_inlets(
    building: BuildingFlags,
    fire: FireSystem,
    adopted_count: int,
) -> WaterInletDecision:
    """Проверить условия, которые однозначно следуют из данных модели.

    Не подставляет категории общественных зданий и число узлов АУПТ, которых
    нет во входных данных. Для ВПВ с неизвестным числом ПК проверка помечается
    незавершённой.
    """
    reasons: List[str] = []
    if fire.required and fire.pk_total >= 12:
        reasons.append(
            f"предусмотрено {fire.pk_total} пожарных кранов (12 и более; "
            "СП 30.13330.2020, п. 8.4)"
        )
    if (building.purpose == BuildingPurpose.RESIDENTIAL
            and building.apartments > 400):
        reasons.append(
            f"жилое здание содержит {building.apartments} квартир (более 400; "
            "СП 30.13330.2020, п. 8.4)"
        )
    if fire.required and fire.network_topology == "pre_meter_branch":
        reasons.append(
            "проектировщиком задана двухвводная схема с ответвлением В2 до ВУ В1"
        )
    minimum = 2 if reasons else 1
    return WaterInletDecision(
        minimum_count=minimum,
        adopted_count=max(int(adopted_count or 1), 1),
        reasons=reasons,
        compliant=int(adopted_count or 1) >= minimum,
        assessment_complete=not (fire.required and fire.pk_total <= 0),
    )


@dataclass
class FirePumpDecision:
    """Решение о повысительной насосной установке В2 (по гидравлике)."""
    needs_pump: Optional[bool]         # None — гидравлика не рассчитана
    required_head_m: Optional[float]
    available_head_m: Optional[float]
    text: str                          # формулировка для пояснительной записки


def describe_fire_pump_requirement(fire: FireSystem) -> FirePumpDecision:
    """Формирует вывод о необходимости насосной В2 для пояснительной записки
    из результатов гидравлического расчёта (СП 10.13130.2020, 4.4, п. 6.1.9 прим.1).

    Если гидравлика не рассчитана (нет required_head_m) — текст-заглушка, чтобы
    ПЗ не молчала о напоре.
    """
    if not fire.required:
        return FirePumpDecision(None, None, None,
                                "Внутренний противопожарный водопровод не требуется.")
    req = fire.required_head_m
    avail = fire.available_head_m
    needs = fire.needs_pump

    if req is None:
        return FirePumpDecision(
            needs, req, avail,
            "Требуемый напор В2 уточняется гидравлическим расчётом сети.")

    if needs is None:
        return FirePumpDecision(
            None, req, avail,
            f"Требуемый напор на вводе В2 составляет {req:.1f} м. "
            "Достаточность напора источника уточняется по данным водоканала.")

    if needs:
        gap = (req - avail) if avail is not None else None
        gap_txt = f" (дефицит {gap:.1f} м)" if gap is not None else ""
        return FirePumpDecision(
            True, req, avail,
            f"Требуемый напор на вводе В2 — {req:.1f} м, доступный напор источника "
            f"{('— ' + format(avail, '.1f') + ' м') if avail is not None else 'недостаточен'}"
            f"{gap_txt}. Предусматривается повысительная насосная установка В2 "
            "(СП 10.13130.2020, 4.4).")
    return FirePumpDecision(
        False, req, avail,
        f"Требуемый напор на вводе В2 — {req:.1f} м, обеспечивается напором "
        f"источника ({avail:.1f} м). Повысительная насосная установка В2 не требуется "
        "(СП 10.13130.2020, 6.1.9, примечание 1).")


@dataclass
class HeadCalc:
    """Расчёт требуемого напора Hтр по формуле (14) п.8.27 СП 30.13330.2020
    и решение о необходимости повысительной установки."""
    h_required_m: Optional[float]   # Hтр, м (None — неполные данные)
    h_guaranteed_m: Optional[float] # Hгар, м (из ТУ заказчика)
    components: List[tuple]         # [(название, значение_м), ...] для таблицы
    pump_needed: Optional[bool]     # True/False/None
    # разложение для подбора насоса (чтобы насос и таблица не расходились)
    h_geom_m: Optional[float] = None        # Hgeom
    h_losses_dynamic_m: Optional[float] = None  # ∑Hil+∑Hвод+Hтепл+Hlввод (динамика без Hпр)
    h_pr_m: float = 20.0
    km: float = 0.3

    @property
    def deficit_m(self) -> Optional[float]:
        if self.h_required_m is None or self.h_guaranteed_m is None:
            return None
        return round(self.h_required_m - self.h_guaranteed_m, 2)

    @property
    def h_pump_m(self) -> Optional[float]:
        """Hнас = Hтр − Hгар (вход из сети). None — если данных нет."""
        if self.h_required_m is None:
            return None
        if self.h_guaranteed_m is None:
            return self.h_required_m
        return round(max(self.h_required_m - self.h_guaranteed_m, 0.0), 2)


def calc_required_head(
    source: WaterSource,
    *,
    h_vod_m: Optional[float] = None,
    h_tepl_m: Optional[float] = None,
) -> HeadCalc:
    """
    Hтр = Hgeom + ∑Hil + Hпр + ∑Hвод + Hтепл + Hlввод (формула 14, п.8.27).

    Слагаемые:
      Hgeom  — из отметок (elev_fixture − elev_header), иначе source.h_geom_m;
      ∑Hil   — il_dict·(1+kм), kм по network_kind; иначе source.h_il_m готовой суммой;
      Hпр    — source.h_pr_m (20 м, п.8.21);
      ∑Hвод  — h_vod_m из расчёта счётчика (приоритет), иначе source.h_vod_m;
      Hтепл  — source.h_tepl_m (3 м если ТО наш; 0 если ГВС готовое/внешнее);
      Hlввод — il_vvod·1,1, иначе source.h_vvod_m готовой суммой.
    Hтр считается, если заданы Hgeom, ∑Hil, ∑Hвод, Hlввод (Hпр всегда есть).
    """
    km = KM_BY_NETWORK.get(source.network_kind, 0.3)

    # Hgeom — отметки в приоритете
    if source.elev_header_m is not None and source.elev_fixture_m is not None:
        h_geom = round(source.elev_fixture_m - source.elev_header_m, 2)
    else:
        h_geom = source.h_geom_m

    # ∑Hil = i·l·(1+kм)
    if source.il_dict_m is not None:
        h_il = round(source.il_dict_m * (1 + km), 2)
    else:
        h_il = source.h_il_m

    h_pr = source.h_pr_m
    h_vod = h_vod_m if h_vod_m is not None else source.h_vod_m
    h_tepl = source.h_tepl_m if h_tepl_m is None else h_tepl_m

    # Hlввод = i·Lввод·1,1
    if source.il_vvod_m is not None:
        h_vvod = round(source.il_vvod_m * 1.1, 2)
    else:
        h_vvod = source.h_vvod_m

    h_il_label = (f"∑Hil — потери по диктующему направлению, i·l·(1+{km:.1f})"
                  if source.il_dict_m is not None
                  else "∑Hil — расчетная сумма потерь по участкам диктующего направления")
    h_vvod_label = ("Hlввод — потери на вводе, i·L·1,1"
                    if source.il_vvod_m is not None
                    else "Hlввод — расчетные потери на участках ввода")
    parts = [
        ("Hgeom — геом. высота диктующего прибора над точкой подключения", h_geom),
        (h_il_label, h_il),
        ("Hпр — свободный напор перед прибором (п.8.21)", h_pr),
        ("∑Hвод — потери в узле учёта, h=S·q² (п.12.15)", h_vod),
        ("Hтепл — потери в теплообменнике/ИТП", h_tepl if h_tepl else None),
        (h_vvod_label, h_vvod),
    ]
    components = [(name, val) for name, val in parts if val is not None]

    required = [h_geom, h_il, h_pr, h_vod, h_vvod]
    has_core = all(x is not None for x in required)
    h_req = round(sum(val for _, val in components), 2) if has_core else None

    # динамика (для подбора насоса): всё кроме Hgeom и Hпр
    dyn_parts = [h_il, h_vod, (h_tepl or 0.0), h_vvod]
    h_losses_dyn = round(sum(x for x in dyn_parts if x is not None), 2) if has_core else None

    pump_needed: Optional[bool] = None
    if h_req is not None and source.guaranteed_head_m is not None:
        pump_needed = h_req > source.guaranteed_head_m

    return HeadCalc(
        h_required_m=h_req,
        h_guaranteed_m=source.guaranteed_head_m,
        components=components,
        pump_needed=pump_needed,
        h_geom_m=h_geom,
        h_losses_dynamic_m=h_losses_dyn,
        h_pr_m=h_pr,
        km=km,
    )


@dataclass
class HeadPathResult:
    """Одна расчётная трасса; все потери сведены в legacy-вход ΣHl."""
    code: str
    label: str
    meter_loss_m: float
    heater_loss_m: float
    head: HeadCalc
    missing: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing and self.head.h_required_m is not None


@dataclass
class HeadPathSet:
    cold: HeadPathResult
    hot: Optional[HeadPathResult] = None

    @property
    def paths(self) -> List[HeadPathResult]:
        return [self.cold] + ([self.hot] if self.hot is not None else [])

    @property
    def complete(self) -> bool:
        return all(path.complete for path in self.paths)

    @property
    def governing(self) -> HeadPathResult:
        available = [p for p in self.paths if p.head.h_required_m is not None]
        return max(available, key=lambda p: p.head.h_required_m) if available else self.cold


def calc_head_paths(
    source: WaterSource,
    meters,
    *,
    hws_type: str = "central",
    apartment_meter_required: bool = False,
) -> HeadPathSet:
    """Собрать холодную и горячую диктующие трассы без новой гидравлики.

    Потери каждого реально присутствующего водомера суммируются и вместе с
    Hтепл входят в тот же агрегат ΣHl, который принимает legacy-калькулятор.
    Неизвестные потери квартирных узлов не заменяются нулём: путь получает
    явный список недостающих данных.
    """
    rows = list(getattr(meters, "rows", []) or [])
    common = [r for r in rows if "ввод" in r.label.lower()]
    cold_rows = [
        r for r in rows
        if ("хвс" in r.label.lower() or "холодн" in r.label.lower())
        and r not in common
    ]
    hot_rows = [
        r for r in rows
        if "гвс" in r.label.lower() or "нагревател" in r.label.lower()
    ]

    def losses(items) -> float:
        return round(sum(float(r.h_a or 0.0) for r in items), 3)

    cold_missing: List[str] = []
    cold_meter = losses(common + cold_rows)
    if apartment_meter_required:
        if source.h_apartment_c_meter_m is None:
            cold_missing.append("потери в квартирном узле учёта ХВС")
        else:
            cold_meter = round(cold_meter + source.h_apartment_c_meter_m, 3)
    cold = HeadPathResult(
        code="V1",
        label="В1 — холодный диктующий прибор",
        meter_loss_m=cold_meter,
        heater_loss_m=0.0,
        head=calc_required_head(source, h_vod_m=cold_meter, h_tepl_m=0.0),
        missing=cold_missing,
    )

    hot = None
    if hws_type != "none":
        hot_missing: List[str] = []
        hot_meter = losses(common + hot_rows)
        if apartment_meter_required:
            if source.h_apartment_h_meter_m is None:
                hot_missing.append("потери в квартирном узле учёта ГВС")
            else:
                hot_meter = round(hot_meter + source.h_apartment_h_meter_m, 3)
        heater = source.h_tepl_m if source.hws_heater_in_scope else 0.0
        if source.hws_heater_in_scope and heater <= 0:
            hot_missing.append("потери в водонагревателе/теплообменнике")
        hot = HeadPathResult(
            code="T3",
            label="Т3 — через водонагреватель к горячему диктующему прибору",
            meter_loss_m=hot_meter,
            heater_loss_m=heater,
            head=calc_required_head(source, h_vod_m=hot_meter, h_tepl_m=heater),
            missing=hot_missing,
        )
    return HeadPathSet(cold=cold, hot=hot)


def project_governing_head(project, *, fallback_h_vod_m: Optional[float] = None) -> HeadCalc:
    """Единый результат Hтр для документов, API и подбора оборудования."""
    paths = getattr(project, "head_paths", None)
    if paths is not None:
        return paths.governing.head
    return calc_required_head(project.source, h_vod_m=fallback_h_vod_m)


@dataclass
class TuCheck:
    """Результат одной проверки соответствия расчёта лимиту ТУ."""
    label: str
    calc: float
    limit: float
    unit: str
    ok: bool

    @property
    def margin(self) -> float:
        return round(self.limit - self.calc, 3)


@dataclass
class TuComplianceResult:
    """Сводка проверки соответствия расчётных расходов лимитам ТУ."""
    checks: list
    all_ok: bool

    @property
    def summary(self) -> str:
        if not self.checks:
            return ("Лимиты присоединения в техн. условиях не заданы — "
                    "проверку соответствия выполнить после получения ТУ.")
        lines = []
        for c in self.checks:
            verb = "не превышает" if c.ok else "ПРЕВЫШАЕТ"
            lines.append(
                f"{c.label}: расчётное {c.calc:.2f} {c.unit} {verb} "
                f"лимит присоединения по ТУ {c.limit:.2f} {c.unit}"
                + (f" (запас {c.margin:.2f} {c.unit})" if c.ok
                   else f" (превышение {-c.margin:.2f} {c.unit} — требуется корректировка)")
            )
        return ". ".join(lines) + "."


def check_tu_limits(flows: FlowsData, source: WaterSource) -> TuComplianceResult:
    """Проверка: расчётные расходы (наш расчёт по СП 30) ≤ лимиты ТУ (дебит)."""
    checks: list = []

    if source.tu_limit_q_day is not None:
        ok = flows.q_day_tot <= source.tu_limit_q_day
        checks.append(TuCheck(
            "Суточный расход ХВС", flows.q_day_tot, source.tu_limit_q_day, "м³/сут", ok))

    if source.tu_limit_q_sec is not None:
        ok = flows.q_sec_tot <= source.tu_limit_q_sec
        checks.append(TuCheck(
            "Секундный расход ХВС", flows.q_sec_tot, source.tu_limit_q_sec, "л/с", ok))

    all_ok = all(c.ok for c in checks) if checks else True
    return TuComplianceResult(checks=checks, all_ok=all_ok)

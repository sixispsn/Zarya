"""Bind a final K1 segment to the EXISTING solver, without sizing a network.

Assigned DN/i are not an automatic selection. No flow split, paper lengths,
fallback 1/d or K1 self-cleaning criteria for K2 are introduced here.
"""
from dataclasses import dataclass
from math import isfinite

from app.calc.sewer_hydraulics import SewerHydraulicInput, SewerHydraulicResult, calculate_sewer_hydraulics
from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.pz.wastewater_presentation import SectionMainInput
from app.calc.sewage_horizontal import HorizontalSewageResult, resolve_horizontal_flow


def current_k1_total(groups, fixture_flow):
    """Formula 5.5 reference only. NEVER the flow of a horizontal pipe."""
    if not groups or fixture_flow is None:
        return None
    try:
        return calculate_water_demand([ConsumerGroup(code, count) for code, count in groups],
                                      sewage_max_fixture_lps=fixture_flow).sewage_flow
    except ValueError:
        # Demand validation owns the error; no surrogate flow for the drawing.
        return None


def current_k1_hourly(groups):
    """Canonical maximum hourly flow (published precision), NOT daily / 24."""
    if not groups:
        return None
    try:
        return calculate_water_demand([ConsumerGroup(code, count) for code, count in groups]).total.q_hr
    except ValueError:
        return None


@dataclass(frozen=True)
class SectionMainCheck:
    system: str
    status: str
    note: str
    result: SewerHydraulicResult | None = None
    flow_result: HorizontalSewageResult | None = None

    @property
    def short(self):
        if self.system == "К2" and self.status == "pending":
            return "К2: показана характерная магистраль"
        status = {"pending":"нужны данные", "verified":"режим проверен",
                  "review":"режим требует решения", "fail":"пропускной способности недостаточно"}[self.status]
        return f"{self.system}: {status}"


def assess_section_main(system: str, data: SectionMainInput, total_flow_lps=None, *,
                        q_hour_max_m3h=None, fixture_max_lps=None) -> SectionMainCheck:
    # total_flow_lps is retained for old callers but never used for hydraulics.
    if system == "К2":
        return SectionMainCheck(system, "pending", "Горизонтальная К2 показана принципиально: DN и уклон берутся "
            "из заданных проектных решений, а не рассчитываются по условным длинам рисунка. "
            "Гидравлика магистрали этим изображением не подтверждается. "
            "Таблица 21.1 проверяет стояки, а не эту магистраль; критерии самоочищения К1 не переносятся.")
    if system != "К1":
        raise ValueError("Поддерживается только К1/К2")
    if data.flow_basis == "whole_building" and (data.q_hour_max_m3h is not None or data.fixture_max_lps is not None):
        return SectionMainCheck(system, "pending", "Для всего здания часовой расход и q0s берутся из текущих "
            "исходных; удалите ручные значения либо выберите часовой расход отдельного участка.")
    automatic = data.flow_basis != "manual"
    if automatic and data.design_flow_lps is not None:
        return SectionMainCheck(system, "pending", "Выбран расчёт по формуле (7), но сохранён ручной расход; удалите его.")
    if not automatic and any(v is not None for v in (data.q_hour_max_m3h, data.fixtures_count,
                                                     data.receiving_length_m, data.fixture_max_lps)):
        return SectionMainCheck(system, "pending", "Для ручного расхода удалите исходные формулы (7) либо выберите расчёт по часовому расходу.")
    flow, evidence, flow_note = resolve_horizontal_flow(
        design_flow_lps=data.design_flow_lps, flow_source=data.flow_source,
        q_hour_max_m3h=(q_hour_max_m3h if data.flow_basis == "whole_building" else data.q_hour_max_m3h) if automatic else None,
        fixtures_count=data.fixtures_count, receiving_length_m=data.receiving_length_m,
        fixture_max_lps=(fixture_max_lps if data.flow_basis == "whole_building" else data.fixture_max_lps) if automatic else None)
    if automatic and data.flow_source.strip():
        flow_note += " Основание исходных N/L: " + data.flow_source.strip()
    if flow is None:
        return SectionMainCheck(system, "pending", flow_note)
    values = ((data.dn_mm, "DN"), (data.slope, "уклон"), (flow, "расход конечного участка"),
              (data.outer_diameter_mm, "наружный диаметр"), (data.wall_thickness_mm, "толщина стенки"),
              (data.material, "материал"), (data.manning_n, "n"),
              (data.roughness_source.strip(), "источник n"), (data.source_ref.strip(), "основание выбора трубы"))
    missing = [label for value, label in values if value is None or value == ""]
    if missing:
        return SectionMainCheck(system, "pending", flow_note + " Проверка конечного участка К1: уточните " + ", ".join(missing) + ".", flow_result=evidence)
    try:
        result = calculate_sewer_hydraulics(SewerHydraulicInput(
            section_id="К1-конечный участок", design_flow_lps=flow, inner_diameter_mm=data.inner_diameter_mm,
            slope_per_mille=data.slope * 1000, material=data.material, manning_n=data.manning_n,
            roughness_source=data.roughness_source))
    except (ArithmeticError, ValueError):
        return SectionMainCheck(system, "pending", "Численные исходные участка не позволяют выполнить проверку. "
            "Проверьте размеры, расход и коэффициент n; заменяющие значения не подставлены.")
    if any(type(value) is float and not isfinite(value) for value in vars(result).values()):
        return SectionMainCheck(system, "pending", "Получен неконечный результат расчёта; проверьте исходные данные участка.")
    status = "fail" if result.fill_ratio is None else "verified" if result.status == "verified" else "review"
    source = "по текущему расчёту всего здания, только после сбора всех стоков" if data.flow_basis == "whole_building" else "явно заданный расход участка"
    note = (f"{flow_note} Конечный участок К1: {source}. Проверка выбранных трубы и уклона существующим модулем Шези-Маннинга; "
            f"{result.note}. Это не автоподбор DN/i и не проверка всей сети. "
            "Условие применения нерасчётного уклона 1/d автоматически не принимается.")
    return SectionMainCheck(system, status, note, result, evidence)

"""L03: повторная проверка сохранённого насоса перед выпуском, не доверяя имени."""
import math

from app.calc.pumps import check_pump_duty
from app.calc.pump_curve import find_intersections
from app.data.pumps import PumpCurvePoint
from app.pz.pump_bridge import project_booster_flow_m3h


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def check_saved_pump_intersection(p) -> tuple[bool, str]:
    """Do not display/release a rounded legacy nearest point as an intersection."""
    if p.curve_kind != "quadratic_estimate":
        return False, "Кривая системы не задана; пересечение не определено"
    values = [p.h_stat, p.k_sys, p.wp_q, p.wp_h, p.q_design_m3h, p.h_design_m]
    if not all(_finite(v) for v in values) or p.q_design_m3h <= 0 or p.wp_q <= 0:
        return False, "Нет данных для проверки сохранённого пересечения; требуется пересчёт"
    result = find_intersections(p.curve, p.h_stat, p.k_sys)
    wp = result.working_point
    if wp is None:
        return False, result.reason + "; требуется пересчёт подбора"
    if (not math.isclose(p.wp_q, wp.q, rel_tol=1e-12, abs_tol=1e-8)
            or not math.isclose(p.wp_h, wp.h, rel_tol=1e-12, abs_tol=1e-8)
            or not math.isclose(max(0, p.h_stat + p.k_sys*p.q_design_m3h**2),
                                p.h_design_m, rel_tol=1e-12, abs_tol=1e-8)):
        return False, "Сохранённая точка не подтверждена пересечением текущих кривых; требуется пересчёт"
    return True, result.reason


def check_project_booster(project, head) -> tuple[str, str]:
    """(Статус, пояснение). verified означает только покрытие расчётной Q/H."""
    if head.pump_needed is None or (
        project.head_paths is not None and not project.head_paths.complete
    ):
        return "missing", "Недостаточно данных для проверки необходимости и напора насоса"
    if head.pump_needed is False:
        return "not_applicable", "Гарантированный напор достаточен при расчётном расходе"
    p = project.pumps
    if not p.required or not p.model:
        return "missing", "Насос требуется, подтверждённая модель не выбрана"
    q = project_booster_flow_m3h(project)
    h = head.h_pump_m
    if (not _finite(q) or q <= 0 or not _finite(h)
            or h <= 0):
        return "missing", "Текущая расчётная пара Q/H не определена"
    if (not _finite(p.q_design_m3h) or not _finite(p.h_design_m)
            or not math.isclose(p.q_design_m3h, q, rel_tol=1e-12, abs_tol=1e-9)
            # HeadCalc округляет отображаемую сумму до 0,01 м.
            or not math.isclose(p.h_design_m, h, rel_tol=0, abs_tol=.011)):
        return "missing", "Сохранённый подбор не соответствует текущим Q/H: требуется пересчёт"
    try:
        curve = [PumpCurvePoint(*row) for row in p.curve]
        duty = check_pump_duty(curve, q, h)
    except (ValueError, TypeError, AttributeError):
        return "missing", "Нет корректной сохранённой каталожной характеристики насоса"
    if not duty.ok:
        return "fail", f"{p.model}: {duty.reason}"
    if p.curve_kind == "quadratic_estimate":
        valid, reason = check_saved_pump_intersection(p)
        if not valid:
            return "fail", f"{p.model}: {reason}"
    return "verified", (
        f"{p.model}: {duty.reason}. Проверено только обеспечение расчётной пары; "
        "регулирование, кавитация и ограничения давления — отдельно."
    )

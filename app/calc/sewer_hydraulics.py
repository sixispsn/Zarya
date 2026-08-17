"""Гидравлика самотечных горизонтальных участков К1 по уравнению Шези.

Legacy-калькулятор содержит канонический расчёт общего расхода К1, но не
содержит гидравлику отдельных горизонтальных участков. Поэтому этот модуль не
распределяет расход между трубами и не подставляет скрытые коэффициенты.

Для участка должны быть явно заданы расчётный расход, фактический внутренний
диаметр, уклон и коэффициент шероховатости Маннинга ``n`` с источником. Расчёт
использует форму уравнения Шези

    V = C * sqrt(R * i),   Q = A * V,

где ``C = R**(1/6) / n``. Геометрия ``A`` и ``R`` определяется для реально
наполненного круглого сечения. Нормативная проверка режима самоочищения
выполняется отдельно по СП 30.13330.2020, п. 19.1, формула (33):

    V * sqrt(h/d) >= K,

``K = 0.5`` для полимерных труб и ``0.6`` для остальных материалов; кроме
того, ``V >= 0.7 м/с`` и ``h/d >= 0.3``.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import acos, pi, sin, sqrt
from typing import Optional


POLYMER_ALIASES = {
    "pp", "pvc", "pe", "pex", "pe_x", "hdpe", "ldpe",
    "пп", "пвх", "пэ", "полимер",
}
POLYMER_PREFIXES = (
    "polyprop", "polyvinyl", "polyeth",
    "полипроп", "поливинил", "полиэтил",
)


@dataclass(frozen=True)
class CircularFlowGeometry:
    fill_ratio: float
    area_m2: float
    wetted_perimeter_m: float
    hydraulic_radius_m: float


@dataclass(frozen=True)
class SewerHydraulicInput:
    section_id: str
    design_flow_lps: float
    inner_diameter_mm: float
    slope_per_mille: float
    material: str
    manning_n: float
    roughness_source: str
    declared_fill_ratio: Optional[float] = None


@dataclass(frozen=True)
class SewerHydraulicResult:
    section_id: str
    design_flow_lps: float
    inner_diameter_mm: float
    slope_per_mille: float
    manning_n: float
    roughness_source: str
    fill_ratio: Optional[float]
    wetted_area_m2: Optional[float]
    hydraulic_radius_m: Optional[float]
    chezy_c: Optional[float]
    velocity_mps: Optional[float]
    self_cleaning_value: Optional[float]
    self_cleaning_k: float
    self_cleaning_ok: Optional[bool]
    velocity_ok: Optional[bool]
    minimum_fill_ok: Optional[bool]
    target_fill_05_06: Optional[bool]
    declared_fill_matches: Optional[bool]
    maximum_capacity_lps: float
    status: str
    note: str


def is_polymer(material: str) -> bool:
    normalized = (material or "").strip().lower()
    token = normalized.replace("-", "_").split()[0] if normalized else ""
    return token in POLYMER_ALIASES or normalized.startswith(POLYMER_PREFIXES)


def circular_partial_geometry(
    inner_diameter_mm: float,
    fill_ratio: float,
) -> CircularFlowGeometry:
    """Вернуть смоченную геометрию круглой трубы при ``0 < h/d <= 1``."""
    if inner_diameter_mm <= 0:
        raise ValueError("внутренний диаметр должен быть больше 0")
    if not 0 < fill_ratio <= 1:
        raise ValueError("наполнение h/d должно быть в интервале (0; 1]")
    diameter = inner_diameter_mm / 1000.0
    radius = diameter / 2.0
    if fill_ratio == 1:
        area = pi * radius**2
        perimeter = 2.0 * pi * radius
    else:
        wet_angle = 2.0 * acos(1.0 - 2.0 * fill_ratio)
        area = radius**2 * (wet_angle - sin(wet_angle)) / 2.0
        perimeter = radius * wet_angle
    hydraulic_radius = area / perimeter
    return CircularFlowGeometry(
        fill_ratio=fill_ratio,
        area_m2=area,
        wetted_perimeter_m=perimeter,
        hydraulic_radius_m=hydraulic_radius,
    )


def chezy_manning_capacity_lps(
    *,
    inner_diameter_mm: float,
    fill_ratio: float,
    slope_per_mille: float,
    manning_n: float,
) -> tuple[float, float, float, CircularFlowGeometry]:
    """Вернуть ``Q, V, C, geometry`` для заданного частичного наполнения."""
    if slope_per_mille <= 0:
        raise ValueError("уклон самотечного участка должен быть больше 0")
    if manning_n <= 0:
        raise ValueError("коэффициент Маннинга n должен быть больше 0")
    geometry = circular_partial_geometry(inner_diameter_mm, fill_ratio)
    slope = slope_per_mille / 1000.0
    chezy_c = geometry.hydraulic_radius_m ** (1.0 / 6.0) / manning_n
    velocity = chezy_c * sqrt(geometry.hydraulic_radius_m * slope)
    flow_lps = geometry.area_m2 * velocity * 1000.0
    return flow_lps, velocity, chezy_c, geometry


def _solve_fill_ratio(data: SewerHydraulicInput) -> tuple[
    Optional[float], float,
]:
    """Найти первое физическое наполнение, пропускающее заданный расход."""
    target = data.design_flow_lps
    def capacity(ratio: float) -> float:
        return chezy_manning_capacity_lps(
            inner_diameter_mm=data.inner_diameter_mm,
            fill_ratio=ratio,
            slope_per_mille=data.slope_per_mille,
            manning_n=data.manning_n,
        )[0]

    # Q круглого сечения достигает максимума до полного наполнения. Троичный
    # поиск на безразмерном интервале заменяет дорогое сканирование 2000 точек;
    # после максимума корень не ищется, поэтому всегда выбирается первый
    # физический безнапорный режим по мере роста h/d.
    maximum_left, maximum_right = 0.5, 1.0
    for _ in range(56):
        third = (maximum_right - maximum_left) / 3.0
        first = maximum_left + third
        second = maximum_right - third
        if capacity(first) < capacity(second):
            maximum_left = first
        else:
            maximum_right = second
    maximum_ratio = (maximum_left + maximum_right) / 2.0
    maximum_capacity = capacity(maximum_ratio)
    if target > maximum_capacity + 1e-12:
        return None, maximum_capacity

    lower, upper = 1e-9, maximum_ratio
    for _ in range(80):
        middle = (lower + upper) / 2.0
        if capacity(middle) < target:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0, maximum_capacity


@lru_cache(maxsize=512)
def calculate_sewer_hydraulics(
    data: SewerHydraulicInput,
) -> SewerHydraulicResult:
    """Рассчитать участок и проверить режим самоочищения по СП 30, п. 19.1."""
    if not data.section_id.strip():
        raise ValueError("обозначение расчётного участка не задано")
    if data.design_flow_lps <= 0:
        raise ValueError("расчётный расход должен быть больше 0")
    if data.inner_diameter_mm <= 0:
        raise ValueError("внутренний диаметр должен быть больше 0")
    if data.slope_per_mille <= 0:
        raise ValueError("уклон должен быть больше 0")
    if data.manning_n <= 0:
        raise ValueError("коэффициент Маннинга n должен быть больше 0")
    if not data.roughness_source.strip():
        raise ValueError("для коэффициента шероховатости нужен источник")
    if (
        data.declared_fill_ratio is not None
        and not 0 < data.declared_fill_ratio <= 1
    ):
        raise ValueError("заявленное наполнение должно быть в интервале (0; 1]")

    fill_ratio, maximum_capacity = _solve_fill_ratio(data)
    required_k = 0.5 if is_polymer(data.material) else 0.6
    if fill_ratio is None:
        return SewerHydraulicResult(
            section_id=data.section_id,
            design_flow_lps=round(data.design_flow_lps, 3),
            inner_diameter_mm=round(data.inner_diameter_mm, 3),
            slope_per_mille=round(data.slope_per_mille, 3),
            manning_n=data.manning_n,
            roughness_source=data.roughness_source,
            fill_ratio=None,
            wetted_area_m2=None,
            hydraulic_radius_m=None,
            chezy_c=None,
            velocity_mps=None,
            self_cleaning_value=None,
            self_cleaning_k=required_k,
            self_cleaning_ok=False,
            velocity_ok=None,
            minimum_fill_ok=None,
            target_fill_05_06=None,
            declared_fill_matches=None,
            maximum_capacity_lps=round(maximum_capacity, 3),
            status="fail",
            note=(
                "расчётный расход превышает максимальную пропускную "
                "способность безнапорного круглого сечения"
            ),
        )

    _, velocity, chezy_c, geometry = chezy_manning_capacity_lps(
        inner_diameter_mm=data.inner_diameter_mm,
        fill_ratio=fill_ratio,
        slope_per_mille=data.slope_per_mille,
        manning_n=data.manning_n,
    )
    self_cleaning_value = velocity * sqrt(fill_ratio)
    self_cleaning_ok = self_cleaning_value + 1e-12 >= required_k
    velocity_ok = velocity + 1e-12 >= 0.7
    minimum_fill_ok = fill_ratio + 1e-12 >= 0.3
    target_fill = 0.5 <= fill_ratio <= 0.6
    declared_matches = (
        None
        if data.declared_fill_ratio is None
        else abs(data.declared_fill_ratio - fill_ratio) <= 0.03
    )
    mandatory_ok = self_cleaning_ok and velocity_ok and minimum_fill_ok
    notes = []
    if not self_cleaning_ok:
        notes.append("не выполнена формула (33) режима самоочищения")
    if not velocity_ok:
        notes.append("скорость меньше 0,7 м/с")
    if not minimum_fill_ok:
        notes.append("наполнение меньше 0,3")
    if declared_matches is False:
        notes.append("заявленное h/d не совпадает с расчётом Шези")
    if not target_fill:
        notes.append("вне целевого проектного диапазона h/d=0,5–0,6")
    if not notes:
        notes.append("пропускная способность и режим самоочищения подтверждены")
    return SewerHydraulicResult(
        section_id=data.section_id,
        design_flow_lps=round(data.design_flow_lps, 3),
        inner_diameter_mm=round(data.inner_diameter_mm, 3),
        slope_per_mille=round(data.slope_per_mille, 3),
        manning_n=data.manning_n,
        roughness_source=data.roughness_source,
        fill_ratio=round(fill_ratio, 4),
        wetted_area_m2=round(geometry.area_m2, 8),
        hydraulic_radius_m=round(geometry.hydraulic_radius_m, 6),
        chezy_c=round(chezy_c, 3),
        velocity_mps=round(velocity, 3),
        self_cleaning_value=round(self_cleaning_value, 3),
        self_cleaning_k=required_k,
        self_cleaning_ok=self_cleaning_ok,
        velocity_ok=velocity_ok,
        minimum_fill_ok=minimum_fill_ok,
        target_fill_05_06=target_fill,
        declared_fill_matches=declared_matches,
        maximum_capacity_lps=round(maximum_capacity, 3),
        status="verified" if mandatory_ok else "fail",
        note="; ".join(notes),
    )

"""
Расчёт расхода дождевых вод с кровли по СП 30.13330.2020 + СП 32.13330.2018.

Алгоритм 1-в-1 из legacy/sp30_calculator.html, функция calcStorm().

Формулы:
  F = F_roof + 0.3 × F_walls           м² (приведённая площадь)
  q20_P = q20 × γ(P)                    л/(с·га) (при периоде > 1 раз/год)
  q5 = 4^n × q20_P                      л/(с·га) (интенсивность за 5 мин)
  Q = F × q5 / 10000                    л/с
"""
import math
from dataclasses import dataclass
from typing import Optional

from app.data.storm_cities import StormCity, get_city, get_gamma


@dataclass
class StormInput:
    """Входные данные расчёта водостоков."""
    city_code: str               # код города из STORM_CITIES
    roof_area_m2: float          # площадь кровли, м²
    walls_area_m2: float = 0.0   # площадь примыкающих вертикальных стен, м²
    period_years: int = 1        # период P (лет): 1, 2, 3, 5, 10


@dataclass
class StormResult:
    """Результат расчёта водостоков."""
    city: StormCity              # данные города
    period_years: int            # период P
    f_calculated_m2: float       # приведённая площадь F = F_кр + 0.3 × F_ст
    q20_base: float              # q20 базовое из таблицы, л/(с·га)
    gamma: float                 # коэф. γ
    q20_adjusted: float          # q20 × γ, л/(с·га)
    n: float                     # показатель степени
    q5: float                    # 4^n × q20_adj, л/(с·га)
    q_total_l_per_s: float       # итоговый расход Q, л/с


STORM_RISER_CAPACITY_LPS = {
    85: 10.0,
    100: 20.0,
    150: 50.0,
    200: 80.0,
}


@dataclass(frozen=True)
class StormNetworkInput:
    """Явные данные для проверки решений К2 на стадии П/Р.

    Расход между воронками и стояками автоматически не распределяется.
    max_*_flow_lps задаются по плану кровли/аксонометрии.
    """
    roof_type: str
    roof_sections: int = 0
    funnels_count: int = 0
    sectional_residential_single_funnel: bool = False
    max_funnel_spacing_m: Optional[float] = None
    selected_funnel_capacity_lps: Optional[float] = None
    max_funnel_flow_lps: Optional[float] = None
    risers_count: int = 0
    selected_riser_dn_mm: int = 0
    max_riser_flow_lps: Optional[float] = None
    funnels_on_different_levels: bool = False


@dataclass(frozen=True)
class StormNetworkAssessment:
    roof_sections: int
    funnels_count: int
    minimum_funnels: Optional[int]
    funnels_count_ok: Optional[bool]
    max_funnel_spacing_m: Optional[float]
    spacing_ok: Optional[bool]
    selected_funnel_capacity_lps: Optional[float]
    max_funnel_flow_lps: Optional[float]
    funnel_capacity_ok: Optional[bool]
    aggregate_funnel_capacity_lps: Optional[float]
    aggregate_funnel_capacity_ok: Optional[bool]
    risers_count: int
    selected_riser_dn_mm: int
    base_riser_capacity_lps: Optional[float]
    effective_riser_capacity_lps: Optional[float]
    max_riser_flow_lps: Optional[float]
    riser_capacity_ok: Optional[bool]
    aggregate_riser_capacity_lps: Optional[float]
    aggregate_riser_capacity_ok: Optional[bool]
    status: str
    notes: tuple[str, ...]


def calculate_storm(data: StormInput) -> StormResult:
    """
    Рассчитать расход дождевых вод с кровли.

    Args:
        data: входные параметры (город, площадь кровли, стен, период)

    Returns:
        StormResult с пошаговым расчётом.

    Raises:
        ValueError: если город не найден или некорректный период.
    """
    if data.roof_area_m2 <= 0:
        raise ValueError("Площадь кровли должна быть больше 0")
    if data.walls_area_m2 < 0:
        raise ValueError("Площадь стен не может быть отрицательной")

    city = get_city(data.city_code)
    if city is None:
        raise ValueError(f"Неизвестный код города: {data.city_code}")

    gamma = get_gamma(data.period_years)

    # Приведённая площадь
    f_calc = data.roof_area_m2 + 0.3 * data.walls_area_m2

    # q20 с учётом периода
    q20_adj = city.q20 * gamma

    # Интенсивность за 5 минут
    q5 = math.pow(4, city.n) * q20_adj

    # Расход
    q_total = f_calc * q5 / 10000.0

    return StormResult(
        city=city,
        period_years=data.period_years,
        f_calculated_m2=round(f_calc, 1),
        q20_base=city.q20,
        gamma=gamma,
        q20_adjusted=round(q20_adj, 1),
        n=city.n,
        q5=round(q5, 2),
        q_total_l_per_s=round(q_total, 3),
    )


def assess_storm_network(
    result: StormResult,
    data: StormNetworkInput,
) -> StormNetworkAssessment:
    """Проверить только явно заданные решения К2 по пп. 21.5–21.12 СП 30."""
    if data.roof_type not in ("not_set", "flat", "sloped"):
        raise ValueError("roof_type должен быть not_set, flat или sloped")
    if min(data.roof_sections, data.funnels_count, data.risers_count) < 0:
        raise ValueError("Число секций, воронок и стояков не может быть отрицательным")
    for name, value in (
        ("max_funnel_spacing_m", data.max_funnel_spacing_m),
        ("selected_funnel_capacity_lps", data.selected_funnel_capacity_lps),
        ("max_funnel_flow_lps", data.max_funnel_flow_lps),
        ("max_riser_flow_lps", data.max_riser_flow_lps),
    ):
        if value is not None and value <= 0:
            raise ValueError(f"{name} должен быть больше 0")

    notes: list[str] = []
    minimum_funnels: Optional[int] = None
    funnels_ok: Optional[bool] = None
    if data.roof_type == "flat" and data.roof_sections > 0:
        minimum_funnels = (
            data.roof_sections
            if data.sectional_residential_single_funnel
            else 2 * data.roof_sections
        )
        if data.funnels_count > 0:
            funnels_ok = data.funnels_count >= minimum_funnels
            if not funnels_ok:
                notes.append(
                    f"воронок {data.funnels_count}, требуется не менее "
                    f"{minimum_funnels}"
                )
        else:
            notes.append("число водосточных воронок не задано")
    elif data.roof_type == "sloped":
        notes.append(
            "число воронок скатной кровли определяется по ендовам и плану кровли"
        )

    spacing_ok: Optional[bool] = None
    if data.max_funnel_spacing_m is not None:
        spacing_ok = data.max_funnel_spacing_m <= 48.0
        if not spacing_ok:
            notes.append("расстояние между воронками превышает 48 м")
    elif data.funnels_count:
        notes.append("максимальное расстояние между воронками не задано")

    funnel_capacity_ok: Optional[bool] = None
    aggregate_funnel_capacity: Optional[float] = None
    aggregate_funnel_capacity_ok: Optional[bool] = None
    if (
        data.selected_funnel_capacity_lps is not None
        and data.max_funnel_flow_lps is not None
    ):
        funnel_capacity_ok = (
            data.max_funnel_flow_lps <= data.selected_funnel_capacity_lps
        )
        if not funnel_capacity_ok:
            notes.append(
                "нагрузка на воронку превышает паспортную пропускную способность"
            )
        if data.max_funnel_flow_lps > result.q_total_l_per_s:
            funnel_capacity_ok = False
            notes.append(
                "нагрузка отдельной воронки превышает общий расчётный расход К2"
            )
    elif data.funnels_count:
        notes.append(
            "паспортная пропускная способность и максимальная нагрузка "
            "на диктующую воронку требуют плана кровли"
        )
    if (
        data.funnels_count > 0
        and data.selected_funnel_capacity_lps is not None
    ):
        aggregate_funnel_capacity = round(
            data.funnels_count * data.selected_funnel_capacity_lps,
            3,
        )
        aggregate_funnel_capacity_ok = (
            aggregate_funnel_capacity >= result.q_total_l_per_s
        )
        if not aggregate_funnel_capacity_ok:
            notes.append(
                "суммарная паспортная способность заданных воронок меньше "
                "общего расчётного расхода К2"
            )

    base_capacity = STORM_RISER_CAPACITY_LPS.get(data.selected_riser_dn_mm)
    effective_capacity: Optional[float] = None
    riser_capacity_ok: Optional[bool] = None
    aggregate_riser_capacity: Optional[float] = None
    aggregate_riser_capacity_ok: Optional[bool] = None
    if base_capacity is not None:
        effective_capacity = round(
            base_capacity * (0.7 if data.funnels_on_different_levels else 1.0),
            3,
        )
        if data.max_riser_flow_lps is not None:
            riser_capacity_ok = data.max_riser_flow_lps <= effective_capacity
            if not riser_capacity_ok:
                notes.append(
                    "нагрузка на диктующий стояк превышает таблицу 21.1"
                )
            if data.max_riser_flow_lps > result.q_total_l_per_s:
                riser_capacity_ok = False
                notes.append(
                    "нагрузка отдельного стояка превышает общий "
                    "расчётный расход К2"
                )
        else:
            notes.append(
                "максимальная нагрузка на диктующий стояк не задана; "
                "общий расход автоматически не делится"
            )
        if data.risers_count > 0:
            aggregate_riser_capacity = round(
                data.risers_count * effective_capacity,
                3,
            )
            aggregate_riser_capacity_ok = (
                aggregate_riser_capacity >= result.q_total_l_per_s
            )
            if not aggregate_riser_capacity_ok:
                notes.append(
                    "суммарная табличная способность заданных стояков меньше "
                    "общего расчётного расхода К2"
                )
    elif data.selected_riser_dn_mm:
        notes.append(
            "для выбранного DN нет точного значения в таблице 21.1; "
            "интерполяция не выполняется"
        )

    explicit_checks = [
        funnels_ok,
        spacing_ok,
        funnel_capacity_ok,
        aggregate_funnel_capacity_ok,
        riser_capacity_ok,
        aggregate_riser_capacity_ok,
    ]
    failed = any(value is False for value in explicit_checks)
    required_checks: list[Optional[bool]] = []
    if data.roof_type == "flat":
        required_checks.append(funnels_ok)
    if data.funnels_count > 0:
        required_checks.extend((
            spacing_ok,
            funnel_capacity_ok,
            aggregate_funnel_capacity_ok,
        ))
    if (
        data.risers_count > 0
        or data.selected_riser_dn_mm > 0
        or data.max_riser_flow_lps is not None
    ):
        required_checks.extend((
            riser_capacity_ok,
            aggregate_riser_capacity_ok,
        ))
    verified = (
        bool(required_checks)
        and all(value is True for value in required_checks)
        and not failed
    )
    status = "fail" if failed else "verified" if verified else "stage_r"
    if not notes and status == "verified":
        notes.append("заданные решения К2 соответствуют проверяемым требованиям")

    return StormNetworkAssessment(
        roof_sections=data.roof_sections,
        funnels_count=data.funnels_count,
        minimum_funnels=minimum_funnels,
        funnels_count_ok=funnels_ok,
        max_funnel_spacing_m=data.max_funnel_spacing_m,
        spacing_ok=spacing_ok,
        selected_funnel_capacity_lps=data.selected_funnel_capacity_lps,
        max_funnel_flow_lps=data.max_funnel_flow_lps,
        funnel_capacity_ok=funnel_capacity_ok,
        aggregate_funnel_capacity_lps=aggregate_funnel_capacity,
        aggregate_funnel_capacity_ok=aggregate_funnel_capacity_ok,
        risers_count=data.risers_count,
        selected_riser_dn_mm=data.selected_riser_dn_mm,
        base_riser_capacity_lps=base_capacity,
        effective_riser_capacity_lps=effective_capacity,
        max_riser_flow_lps=data.max_riser_flow_lps,
        riser_capacity_ok=riser_capacity_ok,
        aggregate_riser_capacity_lps=aggregate_riser_capacity,
        aggregate_riser_capacity_ok=aggregate_riser_capacity_ok,
        status=status,
        notes=tuple(notes),
    )

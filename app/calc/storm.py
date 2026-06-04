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
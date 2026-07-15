"""Расчёт максимального расхода хозяйственно-бытовых стоков.

СП 30.13330.2020, п. 5.5, формула (5):
    q_s = q_tot + q_0s,
где q_0s принимают по таблице А.1 для фактически установленного прибора с
максимальным водоотведением. Legacy-калькулятор всегда подставлял 1,6 л/с;
здесь величина является явным входом расчёта.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DomesticSewageResult:
    q_water_total_lps: float
    q_fixture_max_lps: float
    q_sewage_lps: float


def calculate_domestic_sewage(
    q_water_total_lps: float,
    q_fixture_max_lps: float,
) -> DomesticSewageResult:
    """Рассчитать q_s по формуле (5) п. 5.5 СП 30.13330.2020."""
    if q_water_total_lps < 0:
        raise ValueError("Расход воды q_tot не может быть отрицательным")
    if q_fixture_max_lps < 0:
        raise ValueError("Расход стоков q_0s не может быть отрицательным")
    return DomesticSewageResult(
        q_water_total_lps=round(q_water_total_lps, 3),
        q_fixture_max_lps=round(q_fixture_max_lps, 3),
        q_sewage_lps=round(q_water_total_lps + q_fixture_max_lps, 3),
    )

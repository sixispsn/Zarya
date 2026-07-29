"""Нормативные пропускные способности канализационных стояков.

Источник: СП 30.13330.2020 (с изменениями № 1–5), приложение К,
таблицы К.1–К.4 и К.8. Значения используются только для проверки явно
заданного проектировщиком стояка. Интерполяция и экстраполяция запрещены.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


MATERIAL_LABELS = {
    "pvc": "ПВХ",
    "pp": "ПП",
    "cast_iron_socket": "чугун раструбный",
    "sml": "чугун безраструбный SML",
}

VENTILATION_LABELS = {
    "ventilated": "вентилируемый",
    "vacuum_valve": "невентилируемый с воздушным клапаном",
    "unventilated": "невентилируемый без воздушного клапана",
}


@dataclass(frozen=True)
class RiserCapacity:
    material: str
    ventilation: str
    riser_dn_mm: int
    branch_dn_mm: int
    branch_angle_deg: float
    capacity_lps: float
    table: str


def _rows(
    material: str,
    ventilation: str,
    table: str,
    values: dict[tuple[int, int], tuple[float, float, float]],
) -> list[RiserCapacity]:
    result: list[RiserCapacity] = []
    for (branch_dn, riser_dn), capacities in values.items():
        for angle, capacity in zip((45.0, 60.0, 87.5), capacities):
            result.append(RiserCapacity(
                material=material,
                ventilation=ventilation,
                riser_dn_mm=riser_dn,
                branch_dn_mm=branch_dn,
                branch_angle_deg=angle,
                capacity_lps=capacity,
                table=table,
            ))
    return result


_CAPACITIES = [
    *_rows("pvc", "ventilated", "К.1", {
        (50, 50): (1.10, 1.03, 0.69),
        (50, 110): (8.22, 7.24, 4.83),
        (110, 110): (5.85, 5.37, 3.58),
    }),
    *_rows("pp", "ventilated", "К.2", {
        (40, 50): (1.23, 1.14, 0.76),
        (40, 110): (8.95, 8.25, 5.50),
        (50, 50): (1.10, 1.03, 0.69),
        (50, 110): (8.40, 7.80, 5.20),
        (110, 110): (5.90, 5.40, 3.60),
    }),
    *_rows("cast_iron_socket", "ventilated", "К.3", {
        (50, 50): (0.96, 0.84, 0.56),
        (50, 100): (6.26, 5.50, 3.67),
        (50, 150): (19.90, 17.60, 11.70),
        (100, 100): (5.50, 4.90, 3.20),
        (100, 150): (14.50, 12.80, 8.62),
        (150, 150): (12.60, 11.00, 7.20),
    }),
    *_rows("sml", "ventilated", "К.4", {
        (50, 50): (1.42, 1.25, 0.87),
        (50, 100): (7.79, 6.85, 4.76),
        (50, 125): (12.94, 11.37, 7.91),
        (50, 150): (20.01, 17.58, 12.23),
        (100, 100): (5.79, 5.08, 3.54),
        (100, 125): (9.61, 8.45, 5.88),
        (100, 150): (14.86, 13.50, 9.08),
        (125, 125): (8.80, 7.73, 5.38),
        (125, 150): (13.01, 11.43, 7.95),
        (150, 150): (12.60, 11.07, 7.70),
    }),
    *_rows("pp", "vacuum_valve", "К.8", {
        (50, 50): (1.10, 1.03, 0.69),
        (50, 110): (6.81, 5.98, 4.16),
        (110, 110): (4.83, 4.24, 2.95),
    }),
    *_rows("pvc", "vacuum_valve", "К.8", {
        (50, 50): (1.10, 1.03, 0.69),
        (50, 110): (6.69, 5.87, 4.09),
        (110, 110): (4.76, 4.18, 2.91),
    }),
    *_rows("sml", "vacuum_valve", "К.8", {
        (50, 50): (0.96, 0.84, 0.56),
        (50, 100): (6.83, 6.01, 4.18),
        (110, 100): (4.72, 4.15, 2.88),
    }),
]

_INDEX = {
    (
        row.material,
        row.ventilation,
        row.riser_dn_mm,
        row.branch_dn_mm,
        row.branch_angle_deg,
    ): row
    for row in _CAPACITIES
}


def get_riser_capacity(
    *,
    material: str,
    ventilation: str,
    riser_dn_mm: int,
    branch_dn_mm: int,
    branch_angle_deg: float,
) -> Optional[RiserCapacity]:
    """Вернуть только точное табличное значение, без интерполяции."""
    return _INDEX.get((
        material,
        ventilation,
        int(riser_dn_mm),
        int(branch_dn_mm),
        float(branch_angle_deg),
    ))


def list_supported_materials() -> list[tuple[str, str]]:
    return list(MATERIAL_LABELS.items())


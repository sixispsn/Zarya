"""Единый каталог геометрии труб для спецификации и расчётных модулей.

Для стальных сетей принято конкретное исполнение: труба ВГП обыкновенная
по ГОСТ 3262-75. Внутренний диаметр вычисляется как Dн - 2s.
PE-X задан фактическим размером Dн×s, уже применявшимся в спецификации.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipeSize:
    dn: int
    outer_mm: float
    wall_mm: float
    standard: str
    series: str
    mass_kg_m: float | None = None

    @property
    def inner_mm(self) -> float:
        return round(self.outer_mm - 2 * self.wall_mm, 1)

    @property
    def size_label(self) -> str:
        return f"Ø{self.outer_mm:g}×{self.wall_mm:g}"


# ГОСТ 3262-75, таблица 1 — трубы обыкновенные.
STEEL_VGP_ORDINARY: dict[int, PipeSize] = {
    15: PipeSize(15, 21.3, 2.8, "ГОСТ 3262-75", "обыкновенная", 1.28),
    20: PipeSize(20, 26.8, 2.8, "ГОСТ 3262-75", "обыкновенная", 1.66),
    25: PipeSize(25, 33.5, 3.2, "ГОСТ 3262-75", "обыкновенная", 2.39),
    32: PipeSize(32, 42.3, 3.2, "ГОСТ 3262-75", "обыкновенная", 3.09),
    40: PipeSize(40, 48.0, 3.5, "ГОСТ 3262-75", "обыкновенная", 3.84),
    50: PipeSize(50, 60.0, 3.5, "ГОСТ 3262-75", "обыкновенная", 4.88),
    65: PipeSize(65, 75.5, 4.0, "ГОСТ 3262-75", "обыкновенная", 7.05),
    80: PipeSize(80, 88.5, 4.0, "ГОСТ 3262-75", "обыкновенная", 8.34),
    90: PipeSize(90, 101.3, 4.0, "ГОСТ 3262-75", "обыкновенная", 9.60),
    100: PipeSize(100, 114.0, 4.5, "ГОСТ 3262-75", "обыкновенная", 12.15),
    125: PipeSize(125, 140.0, 4.5, "ГОСТ 3262-75", "обыкновенная", 15.04),
    150: PipeSize(150, 165.0, 4.5, "ГОСТ 3262-75", "обыкновенная", 17.81),
}


PEX: dict[int, PipeSize] = {
    16: PipeSize(16, 16.0, 2.0, "по системе изготовителя", "PE-X"),
    20: PipeSize(20, 20.0, 2.0, "по системе изготовителя", "PE-X"),
    25: PipeSize(25, 25.0, 2.3, "по системе изготовителя", "PE-X"),
    32: PipeSize(32, 32.0, 3.0, "по системе изготовителя", "PE-X"),
    40: PipeSize(40, 40.0, 3.7, "по системе изготовителя", "PE-X"),
    50: PipeSize(50, 50.0, 4.6, "по системе изготовителя", "PE-X"),
}


def steel_vgp_ordinary(dn: int) -> PipeSize:
    try:
        return STEEL_VGP_ORDINARY[int(dn)]
    except KeyError as exc:
        raise ValueError(f"В каталоге ВГП обыкновенных нет DN{dn}") from exc


def pipe_size(material: str, dn: int) -> PipeSize:
    """Разрешить фактическую геометрию по принятому материалу спецификации."""
    label = (material or "").lower()
    if "сталь" in label or "3262" in label:
        return steel_vgp_ordinary(dn)
    if "pe-x" in label or "сшит" in label:
        try:
            return PEX[int(dn)]
        except KeyError as exc:
            raise ValueError(f"В принятом сортаменте PE-X нет Ø{dn}") from exc
    raise ValueError(
        f"Для материала '{material}' не задан точный сортамент; "
        "наружный и внутренний диаметры нельзя подменять DN"
    )


def sleeve_for(pipe: PipeSize, diametral_clearance_mm: float = 8.0) -> PipeSize:
    """Минимальная ВГП-гильза с заданной разницей внутреннего и наружного диаметров."""
    required_inner = pipe.outer_mm + diametral_clearance_mm
    for size in STEEL_VGP_ORDINARY.values():
        if size.inner_mm >= required_inner:
            return size
    raise ValueError(
        f"Для трубы {pipe.size_label} нет гильзы с разницей диаметров "
        f"{diametral_clearance_mm:g} мм"
    )

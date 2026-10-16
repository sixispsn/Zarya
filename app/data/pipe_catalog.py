"""Единый каталог геометрии труб для спецификации и расчётных модулей.

Для стальных сетей принято конкретное исполнение: труба ВГП обыкновенная
по ГОСТ 3262-75. Внутренний диаметр вычисляется как Dн - 2s.
PE-X задан фактическим размером Dн×s, уже применявшимся в спецификации.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


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


@dataclass(frozen=True)
class NominalConnection:
    """DN of an exact steel connection, not a pipe manufacturing standard."""
    dn: int
    basis: str


# ГОСТ 17375-2001, table 2, execution 2: DN65, D=76, T=3.5 mm.
# Official-edition scan, printed page 4 (PDF page 6):
# https://meganorm.ru/Data2/1/4294846/4294846099.pdf
# This identifies the butt-weld connection only. It neither selects a pipe
# manufacturing process/standard nor substitutes VGP 75.5×4 for 76×3.5.
STEEL_WELD_CONNECTIONS = {
    (76.0, 3.5): NominalConnection(65, "ГОСТ 17375-2001, табл. 2, исполнение 2 (DN соединения)"),
}


def steel_nominal_connection(outer_mm: float, wall_mm: float, material: str):
    """Resolve exact geometry only; respect an explicitly stated VGP series."""
    name = material.casefold()
    if "вгп" not in name and "3262" not in name:
        connection = STEEL_WELD_CONNECTIONS.get((outer_mm, wall_mm))
        if connection:
            return connection
    for pipe in STEEL_VGP_ORDINARY.values():
        if (pipe.outer_mm, pipe.wall_mm) == (outer_mm, wall_mm):
            return NominalConnection(pipe.dn, "ГОСТ 3262-75, табл. 1 (размеры ВГП)")
    return None


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


def _sleeve_in_range(pipe: PipeSize, minimum: float, maximum: float) -> PipeSize | None:
    if not isfinite(pipe.outer_mm) or pipe.outer_mm <= 0:
        raise ValueError("Для подбора гильзы нужен положительный наружный диаметр трубы")
    return next((size for size in sorted(STEEL_VGP_ORDINARY.values(), key=lambda s: s.inner_mm)
                 if minimum <= size.inner_mm - pipe.outer_mm <= maximum), None)


def sleeve_for(pipe: PipeSize) -> PipeSize | None:
    """Внутренняя проходка: разница диаметров 5–10 мм (СП 30, п. 11.5).

    Нет подходящей ВГП-гильзы — нет подбора, а не следующий больший DN.
    Это подбор геометрии, не подтверждение огнестойкости узла проходки.
    """
    return _sleeve_in_range(pipe, 5.0, 10.0)


def preliminary_inlet_sleeve_for(pipe: PipeSize) -> PipeSize | None:
    """Наружный ввод: прежняя предварительная геометрия с минимумом 8 мм.

    Не является проверкой п. 11.5 для внутренних пересечений. Герметизация,
    грунты, фундамент и окончательный размер определяются узлом ввода.
    """
    return _sleeve_in_range(pipe, 8.0, float("inf"))

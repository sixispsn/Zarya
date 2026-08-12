"""Общий архитектурный каркас принципиальных схем ВК на листе А1.

Модуль хранит только геометрию разреза: границы здания, характерные этажные
полосы, шахты и слоты помещений. Инженерные системы рисуются поверх каркаса
своими генераторами. Благодаря этому В1/В2 и К1/К2 используют один масштаб и
одинаковый графический ритм, не обмениваясь расчётной логикой.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from app.pz.project import Project


W, H = 2803, 1980
PXMM = W / 841


@dataclass(frozen=True)
class SectionRoomSlot:
    x0: float
    x1: float
    role: str
    default_label: Optional[str] = None


@dataclass(frozen=True)
class SectionBand:
    floor: int
    bottom_y: float
    room_top_y: float
    room_bottom_y: float
    corridor_y: float


@dataclass(frozen=True)
class SectionScaffold:
    floors: int
    floor_height_m: float
    x_left: float
    x_right: float
    x_mark: float
    roof_y: float
    tech_y: float
    zero_y: float
    ground_bottom_y: float
    basement_y: float
    floor_band_h: float
    room_h: float
    corridor_h: float
    bands: Tuple[SectionBand, ...]
    room_slots: Tuple[SectionRoomSlot, ...]
    shaft_left_x: float
    shaft_right_x: float
    has_rupture: bool

    def level_mark_m(self, floor: int, *, ground_h_m: float = 5.2) -> float:
        if floor <= 1:
            return 0.0
        return ground_h_m + 0.7 + (floor - 2) * self.floor_height_m


def build_section_scaffold(project: Project) -> SectionScaffold:
    """Вернуть геометрию, исторически принятую эталонной схемой В1/В2."""
    building = project.building
    floors = max(1, int(building.floors_above or 1))
    floor_height_m = (
        float(building.height_m) / floors
        if float(building.height_m or 0.0) > 0
        else 3.0
    )

    floor_band_h = 260.0
    room_h = 200.0
    corridor_h = 56.0
    raw_bands = []
    if floors >= 2:
        raw_bands.append((2, 980.0))
    if floors >= 3:
        raw_bands.append((3, 720.0))
    if floors > 3:
        raw_bands.append((floors, 390.0))
    elif floors == 3:
        raw_bands[-1] = (3, 720.0)

    bands = tuple(
        SectionBand(
            floor=floor,
            bottom_y=bottom_y,
            room_top_y=bottom_y - floor_band_h + 4.0,
            room_bottom_y=bottom_y - floor_band_h + 4.0 + room_h,
            corridor_y=bottom_y - floor_band_h + 4.0 + room_h + corridor_h / 2,
        )
        for floor, bottom_y in raw_bands
    )
    tech_y = 1000.0
    zero_y = 1250.0
    ground_bottom_y = 1380.0
    basement_y = 1730.0
    roof_y = (
        (bands[-1].bottom_y - floor_band_h - 40.0)
        if bands and floors <= 3
        else (90.0 if bands else tech_y - 40.0)
    )

    room_slots = (
        SectionRoomSlot(200, 462, "apartment_left_1", "Пом. 01; 02"),
        SectionRoomSlot(472, 734, "apartment_left_2", "Пом. 03; 04"),
        SectionRoomSlot(744, 1054, "shaft_left"),
        SectionRoomSlot(1064, 1242, "service", "Мусорокамера"),
        SectionRoomSlot(1252, 1396, "lift", "Лифтовой холл"),
        SectionRoomSlot(1406, 1716, "shaft_right"),
        SectionRoomSlot(1726, 1988, "apartment_right_1", "Пом. 05; 06"),
        SectionRoomSlot(1998, 2260, "apartment_right_2", "Пом. 07; 08"),
    )
    return SectionScaffold(
        floors=floors,
        floor_height_m=floor_height_m,
        x_left=200.0,
        x_right=2260.0,
        x_mark=170.0,
        roof_y=roof_y,
        tech_y=tech_y,
        zero_y=zero_y,
        ground_bottom_y=ground_bottom_y,
        basement_y=basement_y,
        floor_band_h=floor_band_h,
        room_h=room_h,
        corridor_h=corridor_h,
        bands=bands,
        room_slots=room_slots,
        shaft_left_x=940.0,
        shaft_right_x=1520.0,
        has_rupture=floors > 3,
    )

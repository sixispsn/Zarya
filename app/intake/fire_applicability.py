"""Единый переход от намерения проекта к нормативному расчёту В2."""
from __future__ import annotations

from app.calc.fire import FireInput, FireResult, calculate_fire
from app.intake.request_dto import IOS2Request


FIRE_CATEGORY_MAP = {
    "residential_f13": "f13",
    "office_public": "f_office",
    "hospital_f11": "f11",
    "theatre_f21": "f21_theater",
    "library_sport": "f21_lib",
    "museum_trade": "f22",
    "dormitory_f12": "f12_hostel",
}


def calculate_request_fire(request: IOS2Request) -> FireResult:
    """Рассчитать автоматический режим В2 без дублирования маппинга Builder."""
    category = request.fire_category or "residential_f13"
    fire_type = FIRE_CATEGORY_MAP[category]
    corridor_length = next(
        (
            room.length_m
            for room in request.rooms
            if room.space_kind == "corridor"
        ),
        None,
    )
    return calculate_fire(FireInput(
        building_type=fire_type,
        floors=request.floors,
        height_m=request.fire_height_m,
        corridor_length_m=corridor_length,
        seats=request.fire_hall_seats,
        area_m2=(request.fire_area_m2 or request.total_area_m2 or None),
        dn=request.cabinet_dn,
        nozzle_mm=request.nozzle_mm,
        hose_m=request.hose_length_m,
        jet_m=request.compact_jet_m,
    ))

"""Построение доказуемого архитектурного каркаса схемы К1/К2/К3."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.pz.project import Project
from app.pz.wastewater_layout import (
    RectMm,
    WastewaterFloorGroup,
    WastewaterLayoutMode,
    WastewaterSchemeLayout,
    WastewaterSlab,
)


@dataclass(frozen=True)
class WastewaterFloorStackConfig:
    """Границы вертикальной компоновки одного листа А1."""

    # В приложении В разрез занимает около 59,5 % ширины страницы. Каркас
    # центрирован и повторяет эту пропорцию вместо растяжения на весь А1.
    building_left_mm: float = 170.0
    building_right_mm: float = 671.0
    roof_level_y_mm: float = 60.0
    first_floor_level_y_mm: float = 360.0
    basement_level_y_mm: float = 465.0
    foundation_slab_thickness_mm: float = 20.0
    minimum_floor_band_mm: float = 12.0
    lower_level_elevation_m: float | None = None


@dataclass
class WastewaterFloorStackResult:
    layout: WastewaterSchemeLayout
    warnings: List[str] = field(default_factory=list)


def _has_confirmed_lower_level(project: Project) -> bool:
    if int(project.building.floors_below or 0) > 0:
        return True
    lower_words = ("подвал", "подполь", "цоколь", "подзем")
    for pipe in project.sewage.pipes:
        if any(word in (pipe.room or "").lower() for word in lower_words):
            return True
        if any(
            value is not None and value < 0
            for value in (pipe.elevation_start_m, pipe.elevation_end_m)
        ):
            return True
    for element in project.sewage.elements:
        if any(word in (element.room_name or "").lower() for word in lower_words):
            return True
        if element.floor_from <= 0:
            return True
    return False


def build_wastewater_floor_stack(
    project: Project,
    config: WastewaterFloorStackConfig | None = None,
) -> WastewaterFloorStackResult:
    """Создать каркас, в котором каждый надземный этаж показан отдельно.

    Функция не создаёт трассы и помещения. Она использует только подтверждённую
    этажность/высоту здания и наличие нижнего технического уровня в реестре.
    """
    cfg = config or WastewaterFloorStackConfig()
    floors = max(1, int(project.building.floors_above or 1))
    building_height_m = float(project.building.height_m or floors * 3.0)
    real_floor_height_m = building_height_m / floors
    graphic_band_mm = (
        cfg.first_floor_level_y_mm - cfg.roof_level_y_mm
    ) / floors
    warnings: List[str] = []
    if graphic_band_mm < cfg.minimum_floor_band_mm:
        warnings.append(
            f"{floors} этажей не помещаются на одном А1 при минимальной полосе "
            f"{cfg.minimum_floor_band_mm:g} мм; требуется многостраничная схема"
        )

    layout = WastewaterSchemeLayout(
        mode=WastewaterLayoutMode.STANDALONE,
        individual_floors_required=True,
    )
    layout.floor_groups.append(WastewaterFloorGroup(
        group_id="roof",
        label="Кровля",
        floors=(),
        elevation_m=building_height_m,
        y_mm=cfg.roof_level_y_mm,
        kind="roof",
        source_ref="building.height_m",
    ))
    for floor in range(floors, 0, -1):
        level_y = cfg.roof_level_y_mm + (floors - floor + 1) * graphic_band_mm
        layout.floor_groups.append(WastewaterFloorGroup(
            group_id=f"floor-{floor}",
            label=f"{floor} этаж",
            floors=(floor,),
            elevation_m=(floor - 1) * real_floor_height_m,
            y_mm=level_y,
            kind="floor",
            source_ref="building.floors_above; building.height_m",
        ))

    if _has_confirmed_lower_level(project):
        kind = "basement" if int(project.building.floors_below or 0) > 0 else "technical"
        label = "Подвал" if kind == "basement" else "Техническое подполье"
        layout.floor_groups.append(WastewaterFloorGroup(
            group_id="lower-level",
            label=label,
            floors=(0,),
            elevation_m=cfg.lower_level_elevation_m,
            y_mm=cfg.basement_level_y_mm,
            kind=kind,
            source_ref=(
                "АР: отметка нижнего уровня"
                if cfg.lower_level_elevation_m is not None
                else "sewage.pipes: подтверждено наличие нижнего уровня; отметка требуется из АР"
            ),
        ))
        layout.slabs.append(WastewaterSlab(
            slab_id="basement-foundation-slab",
            frame=RectMm(
                cfg.building_left_mm,
                cfg.basement_level_y_mm,
                cfg.building_right_mm - cfg.building_left_mm,
                cfg.foundation_slab_thickness_mm,
            ),
            kind="basement_foundation_slab",
            hatch="diagonal",
            source_ref="ГОСТ Р 21.620-2023, приложение В; конструкция уточняется по АР/КР",
        ))

    return WastewaterFloorStackResult(layout=layout, warnings=warnings)

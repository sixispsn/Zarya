"""Построение доказуемого архитектурного каркаса схемы К1/К2/К3."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.pz.project import Project
from app.pz.wastewater_layout import (
    PointMm,
    RectMm,
    WastewaterFloorGroup,
    WastewaterLayoutMode,
    WastewaterNodePlacement,
    WastewaterRoutePlacement,
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


@dataclass(frozen=True)
class WastewaterBasementMainConfig:
    """Композиция одного подтверждённого участка в нижнем уровне.

    Доли ширины взяты из композиции приложения В и не являются координатами
    здания. Фактическое положение стояков должно быть заменено по АР.
    """

    section_id: str = "К1-М1"
    start_x_ratio: float = 0.28
    end_x_ratio: float = 0.72
    clearance_above_slab_mm: float = 36.0


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


def add_basement_k1_main(
    project: Project,
    layout: WastewaterSchemeLayout,
    config: WastewaterBasementMainConfig | None = None,
) -> WastewaterSchemeLayout:
    """Разместить только реальную подвальную магистраль К1 из реестра.

    Функция не добавляет выпуск, стояки или ответвления. Участок, его концевые
    узлы, диаметр и уклон читаются из ``Project.sewage.pipes``. Координаты по X
    являются промежуточной компоновкой по приложению В до получения АР.
    """
    cfg = config or WastewaterBasementMainConfig()
    pipe = next(
        (row for row in project.sewage.pipes if row.section_id == cfg.section_id),
        None,
    )
    if pipe is None:
        raise ValueError(f"участок {cfg.section_id!r} отсутствует в реестре проекта")
    if pipe.system != "K1":
        raise ValueError(f"участок {cfg.section_id!r} не относится к системе K1")
    if not pipe.from_node or not pipe.to_node:
        raise ValueError(f"для участка {cfg.section_id!r} не заданы концевые узлы")
    if not 0.0 < cfg.start_x_ratio < cfg.end_x_ratio < 1.0:
        raise ValueError("доли положения магистрали должны возрастать внутри здания")

    lower = next(
        (row for row in layout.floor_groups if row.kind in {"basement", "technical"}),
        None,
    )
    foundation = next(
        (row for row in layout.slabs if row.kind == "basement_foundation_slab"),
        None,
    )
    if lower is None or foundation is None:
        raise ValueError("для подвальной магистрали требуется нижний уровень и фундаментная плита")
    if any(row.section_id == pipe.section_id for row in layout.routes):
        raise ValueError(f"участок {pipe.section_id!r} уже размещён на схеме")

    x1 = foundation.frame.x + foundation.frame.width * cfg.start_x_ratio
    x2 = foundation.frame.x + foundation.frame.width * cfg.end_x_ratio
    y1 = foundation.frame.y - cfg.clearance_above_slab_mm
    # Сохраняем направление уклона на схеме. Это графическое отображение
    # реестрового значения, а не восстановление фактической длины по АР.
    slope = float(pipe.slope_per_mille or 0.0) / 1000.0
    y2 = y1 + (x2 - x1) * slope
    start = WastewaterNodePlacement(
        placement_id=f"lower-{pipe.from_node}",
        node_id=pipe.from_node,
        system=pipe.system,
        point=PointMm(x1, y1),
        group_id=lower.group_id,
        kind="riser_base",
        source_ref=(
            f"sewage.pipes:{pipe.section_id}.from_node; "
            "композиционная координата по ГОСТ Р 21.620-2023, приложение В; уточнить по АР"
        ),
    )
    end = WastewaterNodePlacement(
        placement_id=f"lower-{pipe.to_node}",
        node_id=pipe.to_node,
        system=pipe.system,
        point=PointMm(x2, y2),
        group_id=lower.group_id,
        kind="riser_base",
        source_ref=(
            f"sewage.pipes:{pipe.section_id}.to_node; "
            "композиционная координата по ГОСТ Р 21.620-2023, приложение В; уточнить по АР"
        ),
    )
    layout.nodes.extend((start, end))
    layout.routes.append(WastewaterRoutePlacement(
        route_id=f"route-{pipe.section_id}",
        section_id=pipe.section_id,
        system=pipe.system,
        from_placement_id=start.placement_id,
        to_placement_id=end.placement_id,
        points=(start.point, end.point),
        group_id=lower.group_id,
        source_ref=(
            f"sewage.pipes:{pipe.section_id}; геометрический уклон из slope_per_mille; "
            "положение по композиционному шаблону приложения В, уточнить по АР"
        ),
    ))
    return layout

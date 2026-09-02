"""Registry-driven combined building schematic for internal K1 and K2.

The drawing composes the accepted K1 floor modules on one architectural
storey grid and adds only the K2 topology explicitly declared by the project
register.  It does not invent K2 revisions, fitting arrangements, floor
coordinates or external sewer runs.  Lower nodes are selected by graph
topology: a capped cleanout is allowed only at a terminal start, while an
incoming horizontal main forces an open through junction.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from app.pz.project import DocumentInfo, Project
from app.pz.wastewater_drafting import (
    BLACK,
    FONT,
    GRAY,
    build_lower_turn_cleanout_assembly,
    build_lower_turn_through_junction_assembly,
    render_inline_pipe_label,
    render_lower_turn_assembly_svg,
)
from app.pz.wastewater_floor_drafting import render_typical_floor_assembly_svg
from app.pz.wastewater_project_inputs import (
    BuildingK1RiserProjectInput,
    BuildingK2RiserProjectInput,
    BuildingPipeProjectInput,
    BuildingTransitionProjectInput,
    WastewaterBuildingProjectInputs,
    resolve_wastewater_building_project_inputs,
)
from app.pz.wastewater_revision_placement import (
    REVISION_PLACEMENT_RULE_ID,
    resolve_riser_revision_placement,
    revision_y_from_clean_floor,
)
from app.pz.wastewater_stack_drafting import (
    WastewaterStackAssembly,
    build_wastewater_stack_assembly,
)
from app.pz.wastewater_ugo import render_ugo


_ROOF_VENT_HEIGHT_M = {
    "flat_non_accessible": 0.2,
    "pitched": 0.2,
    "collecting_vent_shaft": 0.1,
    "flat_accessible": 3.0,
}

_SHEET_SCALE = 10.0 / 3.0
_FRAME_LEFT = 20.0 * _SHEET_SCALE
_FRAME_TOP = 5.0 * _SHEET_SCALE
_FRAME_RIGHT = 2800.0 - 5.0 * _SHEET_SCALE
_FRAME_BOTTOM = 1980.0 - 5.0 * _SHEET_SCALE
_FLOOR_K1_PAGE_CAPACITY = 2
_FLOOR_K2_PAGE_CAPACITY = 2
_BASEMENT_RISER_PAGE_CAPACITY = 4


def _chunks(values: tuple, size: int) -> tuple[tuple, ...]:
    return tuple(values[index:index + size] for index in range(0, len(values), size))


def _spread_positions(count: int, start: float, end: float) -> tuple[float, ...]:
    if count <= 0:
        return ()
    if count == 1:
        return ((start + end) / 2.0,)
    step = (end - start) / (count - 1)
    return tuple(start + index * step for index in range(count))


def _short(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _title_block_svg(
    document: DocumentInfo,
    *,
    sheet_no: int,
    sheet_total: int,
    title: str,
    system_label: str = "К1, К2",
) -> str:
    """Основная надпись формы 3 в координатах листа A1."""
    doc = document
    scale = _SHEET_SCALE
    x0 = _FRAME_RIGHT - 185.0 * scale
    y0 = _FRAME_BOTTOM - 55.0 * scale

    def x(mm: float) -> float:
        return x0 + mm * scale

    def y(mm: float) -> float:
        return y0 + mm * scale

    def line(x1: float, y1: float, x2: float, y2: float, width: float = 1.0) -> str:
        return (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
            f'y2="{y2:.1f}" stroke="{BLACK}" stroke-width="{width:.1f}"/>'
        )

    def text_svg(
        px: float,
        py: float,
        value: str,
        size: float,
        anchor: str = "middle",
        weight: str = "normal",
    ) -> str:
        return (
            f'<text x="{px:.1f}" y="{py:.1f}" font-family="{FONT}" '
            f'font-size="{size:.1f}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{escape(value)}</text>'
        )

    rows = [
        f'<g data-title-block="form-3" data-sheet-no="{sheet_no}" '
        f'data-sheet-total="{sheet_total}">',
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{185*scale:.1f}" '
        f'height="{55*scale:.1f}" fill="white" stroke="{BLACK}" '
        'stroke-width="2.0"/>',
        line(x(65), y(0), x(65), y(55), 1.5),
    ]
    for column in (7, 17, 25, 37, 53):
        rows.append(line(x(column), y(0), x(column), y(25)))
    for column in (17, 37, 53):
        rows.append(line(x(column), y(25), x(column), y(55)))
    rows.append(line(x(135), y(25), x(135), y(55), 1.4))
    for column in (150, 165):
        rows.append(line(x(column), y(25), x(column), y(40)))
    for row_mm in range(5, 55, 5):
        rows.append(line(x(0), y(row_mm), x(65), y(row_mm)))
    for row_mm, start_mm in ((10, 65), (25, 65), (30, 135), (40, 65)):
        rows.append(line(x(start_mm), y(row_mm), x(185), y(row_mm)))
    for label, c0, c1 in (
        ("Изм.", 0, 7), ("Кол.уч.", 7, 17), ("Лист", 17, 25),
        ("№ док.", 25, 37), ("Подп.", 37, 53), ("Дата", 53, 65),
    ):
        rows.append(text_svg(x((c0 + c1) / 2), y(23.4), label, 7.0))
    signers = (
        ("Разраб.", doc.developer_name, 30),
        ("Проверил", doc.inspector_name, 35),
        ("Нач. отдела", doc.dept_head_name, 40),
        ("ГИП", doc.gip_name, 45),
        ("Н. контр.", doc.norm_control_name, 55),
    )
    for label, name, row_mm in signers:
        rows.append(text_svg(x(1), y(row_mm - 1.5), label, 7.4, "start"))
        if name:
            rows.append(text_svg(x(27), y(row_mm - 1.5), _short(name, 18), 7.4))
    rows.extend((
        text_svg(x(125), y(7), _short(doc.cipher or "", 34), 13.0),
        text_svg(x(125), y(18), _short(doc.object_name or "", 68), 8.5),
        text_svg(x(100), y(34.5), _short(doc.object_part or "", 38), 9.5),
        text_svg(x(142.5), y(28.5), "Стадия", 6.7),
        text_svg(x(157.5), y(28.5), "Лист", 6.7),
        text_svg(x(175), y(28.5), "Листов", 6.7),
        text_svg(x(142.5), y(37.3), doc.stage_label or "П", 10.0),
        text_svg(x(157.5), y(37.3), str(sheet_no), 10.0),
        text_svg(x(175), y(37.3), str(sheet_total), 10.0),
        text_svg(x(100), y(47), _short(title, 48), 8.8),
        text_svg(x(100), y(53), system_label, 10.5, weight="bold"),
        text_svg(x(160), y(49), _short(doc.organization or "", 28), 8.0),
        "</g>",
    ))
    return "".join(rows)


@dataclass(frozen=True)
class WastewaterBuildingAssembly:
    project_inputs: WastewaterBuildingProjectInputs
    k1_stacks: tuple[WastewaterStackAssembly, ...]
    floor_height_m: float
    roof_kind: str
    document: DocumentInfo

    @property
    def displayed_floor_numbers(self) -> tuple[int, ...]:
        return self.k1_stacks[0].displayed_floor_numbers

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.project_inputs.complete:
            errors.extend(self.project_inputs.diagnostics)
        if self.floor_height_m <= 0:
            errors.append("floor height must be positive")
        if self.roof_kind not in _ROOF_VENT_HEIGHT_M:
            errors.append("unsupported roof kind")
        if not self.k1_stacks:
            errors.append("combined sheet needs at least one K1 stack")
            return errors
        if len(self.k1_stacks) != len(self.project_inputs.k1_risers):
            errors.append("K1 semantic stacks differ from the registry selection")
        expected_displayed = self.k1_stacks[0].displayed_floor_numbers
        for stack, source in zip(
            self.k1_stacks,
            self.project_inputs.k1_risers,
        ):
            errors.extend(stack.validate())
            if stack.displayed_floor_numbers != expected_displayed:
                errors.append("K1 stacks use different characteristic floors")
            if stack.revision_floors != source.revision_floors:
                errors.append(
                    f"{stack.riser_id}: calculated revision floors differ from "
                    "the explicit project register"
                )
        for riser in self.project_inputs.k2_risers:
            for revision in riser.revisions:
                relative_height_m = revision.elevation_m - (
                    revision.floor_no - 1
                ) * self.floor_height_m
                try:
                    resolve_riser_revision_placement(
                        floor_height_m=self.floor_height_m,
                        requested_height_m=relative_height_m,
                    )
                except ValueError as exc:
                    errors.append(
                        f"{revision.element_id}: недоступная высота ревизии "
                        f"{relative_height_m:.3f} м над чистым полом ({exc})"
                    )
        return list(dict.fromkeys(errors))


def build_wastewater_building_assembly(
    project_inputs: WastewaterBuildingProjectInputs,
    *,
    floor_height_m: float,
    roof_kind: str,
    document: DocumentInfo | None = None,
) -> WastewaterBuildingAssembly:
    """Build a combined semantic assembly from confirmed register values."""
    if not project_inputs.complete:
        detail = "; ".join(project_inputs.diagnostics) or "неполный реестр К1/К2"
        raise ValueError("project data are insufficient for the K1/K2 sheet: " + detail)
    stacks = tuple(
        build_wastewater_stack_assembly(
            floors_above=row.stack.floors_above,
            floor_height_m=floor_height_m,
            riser_id=row.stack.riser_id,
            riser_dn_mm=int(row.stack.riser_dn_mm or 0),
            roof_kind=roof_kind,
            fixtures_by_floor=row.stack.fixtures_by_floor,
            floor_slope_dn50=float(row.stack.slope_dn50 or 0),
            floor_slope_dn100=float(row.stack.slope_dn100 or 0),
            collapse_typical_floors=True,
            assembly_id=f"{row.stack.riser_id}-Сборка",
            basement_floor_elevation_m=(
                row.stack.basement.basement_floor_elevation_m
            ),
            outlet_invert_elevation_m=(
                row.stack.basement.outlet_invert_elevation_m
            ),
            basement_collector_slope_per_mille=(
                row.stack.basement.collector_slope_per_mille
            ),
            outlet_id=row.stack.basement.outlet_id,
            outlet_dn_mm=row.stack.basement.outlet_dn_mm,
        )
        for row in project_inputs.k1_risers
    )
    assembly = WastewaterBuildingAssembly(
        project_inputs=project_inputs,
        k1_stacks=stacks,
        floor_height_m=floor_height_m,
        roof_kind=roof_kind,
        document=document or DocumentInfo(),
    )
    errors = assembly.validate()
    if errors:
        raise ValueError("invalid wastewater building assembly: " + "; ".join(errors))
    return assembly


def _fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _system_mark(system: str) -> str:
    return {"K1": "К1", "K2": "К2", "K3": "К3"}.get(system, system)


def _line_with_label(
    *,
    line_id: str,
    system: str,
    dn_mm: int,
    start: tuple[float, float],
    end: tuple[float, float],
    position: float = 0.5,
    stroke_width: float = 4.0,
    font_size: float = 14.0,
    extra_attributes: str = "",
) -> str:
    label = f"{_system_mark(system)} ⌀{dn_mm}"
    return "".join(
        (
            f'<g data-building-pipe-line="{escape(line_id)}"{extra_attributes}>',
            f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
            f'x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="{BLACK}" '
            f'stroke-width="{stroke_width:g}"/>',
            render_inline_pipe_label(
                line_id=line_id,
                label=label,
                start=start,
                end=end,
                position=position,
                font_size=font_size,
                padding=4.0,
            ),
            "</g>",
        )
    )


def _break_overlay(
    *,
    break_id: str,
    x: float,
    y: float,
    label: str,
) -> str:
    return "".join(
        (
            f'<g data-building-riser-break="{escape(break_id)}">',
            f'<rect x="{x-15:.1f}" y="{y-46:.1f}" width="30" height="92" '
            'fill="white"/>',
            f'<path d="M{x-12:.1f},{y-38:.1f} L{x+12:.1f},{y-22:.1f}" '
            f'stroke="{BLACK}" stroke-width="2" fill="none"/>',
            f'<path d="M{x-12:.1f},{y+22:.1f} L{x+12:.1f},{y+38:.1f}" '
            f'stroke="{BLACK}" stroke-width="2" fill="none"/>',
            f'<text x="{x-30:.1f}" y="{y+5:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="14">{escape(label)}</text>',
            "</g>",
        )
    )


def _revision_svg(
    *,
    riser_id: str,
    floor_no: int,
    x: float,
    slab_y: float,
    floor_height_m: float,
    dimension: bool,
    element_id: str = "",
    requested_height_m: float | None = None,
) -> str:
    placement = resolve_riser_revision_placement(
        floor_height_m=floor_height_m,
        requested_height_m=requested_height_m,
    )
    revision_y = revision_y_from_clean_floor(
        clean_floor_y=slab_y,
        graphic_floor_height=247.0,
        real_floor_height_m=floor_height_m,
        placement=placement,
    )
    height_mm = int(round(placement.height_above_clean_floor_m * 1000))
    revision_key = element_id or f"{riser_id}-{floor_no}"
    body = [
        f'<g data-building-revision="{escape(revision_key)}" '
        f'data-floor-reference="clean-floor" '
        f'data-height-above-floor-mm="{height_mm}" '
        f'data-height-source="{escape(placement.source)}" '
        f'data-height-rule="{REVISION_PLACEMENT_RULE_ID}">',
        render_ugo("revision", x, revision_y, scale=0.72, rotation=90.0),
        f'<text x="{x+23:.1f}" y="{revision_y-10:.1f}" '
        f'font-family="{FONT}" font-size="10" font-weight="bold">Р</text>',
    ]
    if dimension:
        dim_x = x + 55.0
        body.extend(
            (
                f'<line x1="{dim_x:.1f}" y1="{revision_y:.1f}" '
                f'x2="{dim_x:.1f}" y2="{slab_y:.1f}" stroke="{BLACK}" '
                'stroke-width="1"/>',
                f'<line x1="{dim_x-8:.1f}" y1="{revision_y:.1f}" '
                f'x2="{dim_x+8:.1f}" y2="{revision_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="1"/>',
                f'<line x1="{dim_x-8:.1f}" y1="{slab_y:.1f}" '
                f'x2="{dim_x+8:.1f}" y2="{slab_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="1"/>',
                f'<text x="{dim_x+12:.1f}" y="{(revision_y+slab_y)/2+4:.1f}" '
                f'font-family="{FONT}" font-size="10">{height_mm}</text>',
            )
        )
    body.append("</g>")
    return "".join(body)


def _floor_origins(floors: tuple[int, ...]) -> dict[int, float]:
    presets = {
        1: (760.0,),
        2: (480.0, 1110.0),
        3: (315.0, 900.0, 1250.0),
    }
    if len(floors) not in presets:
        raise ValueError("combined A1 sheet supports up to three characteristic floors")
    return dict(zip(floors, presets[len(floors)]))


def build_wastewater_building_floors_svg(
    assembly: WastewaterBuildingAssembly,
    *,
    k1_stacks: tuple[WastewaterStackAssembly, ...] | None = None,
    k2_risers: tuple[BuildingK2RiserProjectInput, ...] | None = None,
    sheet_no: int = 1,
    sheet_total: int = 3,
    fragment_index: int = 1,
    fragment_total: int = 1,
    basement_first_sheet_no: int = 2,
    basement_sheet_by_riser_id: dict[str, int] | None = None,
) -> str:
    """Render the shared roof and characteristic-floor sheet."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid building assembly: " + "; ".join(errors))
    width, height = 2800, 1980
    margin = 50
    floors = assembly.displayed_floor_numbers
    origins = _floor_origins(floors)
    selected_k1 = assembly.k1_stacks if k1_stacks is None else k1_stacks
    selected_k2 = (
        assembly.project_inputs.k2_risers if k2_risers is None else k2_risers
    )
    if len(selected_k1) > _FLOOR_K1_PAGE_CAPACITY:
        raise ValueError("floor fragment contains too many K1 stacks")
    if len(selected_k2) > _FLOOR_K2_PAGE_CAPACITY:
        raise ValueError("floor fragment contains too many K2 stacks")
    # Выноска начальной этажной прочистки уходит влево от сборки; оси
    # сдвинуты внутрь рабочей рамки, чтобы полка и текст не пересекали поле
    # подшивки формы А1.
    k1_origins_x = (
        (550.0,) if len(selected_k1) == 1 else (160.0, 950.0)
    )[:len(selected_k1)]
    k2_xs = (
        (2260.0,) if len(selected_k2) == 1 else (2110.0, 2400.0)
    )[:len(selected_k2)]
    scale = 1.0
    roof_y = 220.0
    bottom_y = 1660.0
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        f'viewBox="0 0 2800 1980" data-sheet-role="floors" '
        f'data-fragment-index="{fragment_index}" '
        f'data-fragment-total="{fragment_total}">',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Принципиальная схема внутренних систем '
        'канализации и водоотведения. Надземная часть</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">Этажей: {assembly.project_inputs.floors_above}; '
        f'фрагмент {fragment_index}/{fragment_total}; характерные этажи; '
        'самотечная К1 и внутренний водосток К2</text>',
        f'<line data-architecture="roof" x1="{margin+30}" y1="{roof_y}" '
        f'x2="{width-margin-30}" y2="{roof_y}" stroke="#777" stroke-width="2"/>',
        f'<text x="{margin+38}" y="{roof_y-18}" font-family="{FONT}" '
        'font-size="15" font-weight="bold">Кровля</text>',
    ]

    for floor_no, origin_y in origins.items():
        slab_y = origin_y + 228.0 * scale
        elevation = (floor_no - 1) * assembly.floor_height_m
        body.extend(
            (
                f'<line data-building-floor="{floor_no}" x1="{margin+30}" '
                f'y1="{slab_y:.1f}" x2="{width-margin-30}" y2="{slab_y:.1f}" '
                'stroke="#aaa" stroke-width="1"/>',
                f'<text x="{margin+38}" y="{slab_y-28:.1f}" font-family="{FONT}" '
                f'font-size="15" font-weight="bold">{floor_no} этаж</text>',
                f'<text x="{margin+38}" y="{slab_y-9:.1f}" font-family="{FONT}" '
                f'font-size="12">отм. {_fmt(elevation)}</text>',
            )
        )

    for stack_index, stack in enumerate(selected_k1):
        origin_x = k1_origins_x[stack_index]
        riser_x = origin_x + stack.floor(floors[0]).port("riser_join").point.x_mm
        for floor_no in floors:
            floor = stack.floor(floor_no)
            body.append(
                render_typical_floor_assembly_svg(
                    floor,
                    diagnostics=False,
                    x=origin_x,
                    y=origins[floor_no],
                    scale=scale,
                )
            )
            if floor_no in stack.revision_floors:
                body.append(
                    _revision_svg(
                        riser_id=stack.riser_id,
                        floor_no=floor_no,
                        x=riser_x,
                        slab_y=origins[floor_no] + 228.0,
                        floor_height_m=assembly.floor_height_m,
                        dimension=floor_no == 1,
                    )
                )

        top_floor = stack.floor(floors[0])
        top_y = origins[floors[0]] + top_floor.port("riser_top").point.y_mm
        body.append(
            _line_with_label(
                line_id=f"{stack.riser_id}-roof-vent",
                system="K1",
                dn_mm=stack.riser_dn_mm,
                start=(riser_x, roof_y - 55.0),
                end=(riser_x, top_y),
                position=0.55,
            )
        )
        body.append(
            f'<line data-vent-cap="{escape(stack.riser_id)}" '
            f'x1="{riser_x-13:.1f}" y1="{roof_y-55:.1f}" '
            f'x2="{riser_x+13:.1f}" y2="{roof_y-55:.1f}" '
            f'stroke="{BLACK}" stroke-width="2"/>'
        )
        body.append(
            f'<text x="{riser_x+22:.1f}" y="{roof_y-68:.1f}" '
            f'font-family="{FONT}" font-size="13">{escape(stack.riser_id)}; '
            f'h={_fmt(stack.vent_height_above_roof_m, 1)} м</text>'
        )
        for upper, lower in zip(floors, floors[1:]):
            upper_bottom = origins[upper] + stack.floor(upper).port("riser_bottom").point.y_mm
            lower_top = origins[lower] + stack.floor(lower).port("riser_top").point.y_mm
            line_id = f"{stack.riser_id}-between-{upper}-{lower}"
            body.append(
                _line_with_label(
                    line_id=line_id,
                    system="K1",
                    dn_mm=stack.riser_dn_mm,
                    start=(riser_x, upper_bottom),
                    end=(riser_x, lower_top),
                    position=0.35 if upper - lower > 1 else 0.5,
                )
            )
            if upper - lower > 1:
                body.append(
                    _break_overlay(
                        break_id=line_id,
                        x=riser_x,
                        y=(upper_bottom + lower_top) / 2,
                        label=f"этажи {lower+1}-{upper-1} - типовые, не показаны",
                    )
                )
        last_floor = stack.floor(floors[-1])
        last_bottom = origins[floors[-1]] + last_floor.port("riser_bottom").point.y_mm
        body.append(
            _line_with_label(
                line_id=f"{stack.riser_id}-to-basement",
                system="K1",
                dn_mm=stack.riser_dn_mm,
                start=(riser_x, last_bottom),
                end=(riser_x, bottom_y),
                position=0.58,
            )
        )
        body.append(
            # Каждый стояк ссылается на тот подвальный фрагмент, где показан
            # его нижний узел; при одном фрагменте это обычный лист 2.
            f'<text data-continuation-riser="{escape(stack.riser_id)}" '
            f'data-target-sheet="{(basement_sheet_by_riser_id or {}).get(stack.riser_id, basement_first_sheet_no)}" '
            f'x="{riser_x+20:.1f}" y="{bottom_y-12:.1f}" '
            f'font-family="{FONT}" font-size="13">{escape(stack.riser_id)}; '
            f'продолжение на листе '
            f'{(basement_sheet_by_riser_id or {}).get(stack.riser_id, basement_first_sheet_no)}</text>'
        )

    first_origin = origins[floors[0]]
    last_origin = origins[floors[-1]]
    for index, riser in enumerate(selected_k2):
        x = k2_xs[index]
        body.append(
            _line_with_label(
                line_id=f"{riser.riser_id}-roof-to-basement",
                system="K2",
                dn_mm=riser.riser_dn_mm,
                start=(x, roof_y),
                end=(x, bottom_y),
                position=0.64,
            )
        )
        body.append(
            render_ugo(
                riser.funnel_symbol_kind,
                x,
                roof_y,
                scale=1.15,
            )
        )
        body.append(
            f'<text x="{x+35:.1f}" y="{roof_y-36:.1f}" font-family="{FONT}" '
            f'font-size="13" font-weight="bold">{escape(riser.funnel_id)}</text>'
        )
        body.append(
            f'<text x="{x+35:.1f}" y="{roof_y-17:.1f}" font-family="{FONT}" '
            f'font-size="12">{riser.funnel_quantity} шт.; DN{riser.funnel_dn_mm}; '
            'с электрообогревом</text>'
        )
        if floors[0] - floors[1] > 1:
            break_y = (
                first_origin
                + 252.0
                + origins[floors[1]]
                + 5.0
            ) / 2
            body.append(
                _break_overlay(
                    break_id=f"{riser.riser_id}-typical-break",
                    x=x,
                    y=break_y,
                    label=f"этажи {floors[1]+1}-{floors[0]-1} - не показаны",
                )
            )
        body.append(
            render_inline_pipe_label(
                line_id=f"{riser.riser_id}-upper-mark",
                label=f"К2 ⌀{riser.riser_dn_mm}",
                start=(x, roof_y),
                end=(x, first_origin + 5.0),
                position=0.55,
                font_size=14,
            )
        )
        for revision in riser.revisions:
            relative_height_m = revision.elevation_m - (
                revision.floor_no - 1
            ) * assembly.floor_height_m
            if revision.floor_no in origins:
                body.append(
                    _revision_svg(
                        riser_id=riser.riser_id,
                        floor_no=revision.floor_no,
                        x=x,
                        slab_y=origins[revision.floor_no] + 228.0,
                        floor_height_m=assembly.floor_height_m,
                        dimension=revision.floor_no == 1,
                        element_id=revision.element_id,
                        requested_height_m=relative_height_m,
                    )
                )
                continue
            omitted_range = next((
                (upper, lower)
                for upper, lower in zip(floors, floors[1:])
                if lower < revision.floor_no < upper
            ), None)
            if omitted_range is None:
                continue
            upper, lower = omitted_range
            upper_bottom = origins[upper] + 252.0
            lower_top = origins[lower] + 5.0
            revision_y = (upper_bottom + lower_top) / 2 - 66.0
            placement = resolve_riser_revision_placement(
                floor_height_m=assembly.floor_height_m,
                requested_height_m=relative_height_m,
            )
            height_mm = int(round(placement.height_above_clean_floor_m * 1000))
            body.extend((
                f'<g data-building-revision="{escape(revision.element_id)}" '
                f'data-revision-on-break="true" '
                f'data-floor-reference="clean-floor" '
                f'data-height-above-floor-mm="{height_mm}" '
                f'data-height-source="{escape(placement.source)}" '
                f'data-height-rule="{REVISION_PLACEMENT_RULE_ID}">',
                render_ugo("revision", x, revision_y, scale=0.72, rotation=90.0),
                f'<text x="{x+24:.1f}" y="{revision_y-7:.1f}" '
                f'font-family="{FONT}" font-size="11" font-weight="bold">Р · '
                f'эт. {revision.floor_no}; отм. {_fmt(revision.elevation_m)}</text>',
                '</g>',
            ))
        body.append(
            f'<text data-continuation-riser="{escape(riser.riser_id)}" '
            f'data-target-sheet="{(basement_sheet_by_riser_id or {}).get(riser.riser_id, basement_first_sheet_no)}" '
            f'x="{x+20:.1f}" y="{bottom_y-12:.1f}" '
            f'font-family="{FONT}" font-size="13">{escape(riser.riser_id)}; '
            f'продолжение на листе '
            f'{(basement_sheet_by_riser_id or {}).get(riser.riser_id, basement_first_sheet_no)}</text>'
        )

    body.extend(
        (
            f'<line x1="{margin+30}" y1="{bottom_y+35:.1f}" '
            f'x2="{_FRAME_RIGHT-650:.1f}" y2="{bottom_y+35:.1f}" stroke="#777"/>',
            f'<text x="{margin+38}" y="{bottom_y+78:.1f}" font-family="{FONT}" '
            'font-size="13">Все показанные приборы и количества получены из реестра проекта. '
            'К2 не соединяется с К1.</text>',
            f'<text x="{margin+38}" y="{bottom_y+112:.1f}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Графический язык — приложение В '
            'ГОСТ Р 21.620-2023; элементы получены из реестра проекта.</text>',
            _title_block_svg(
                assembly.document,
                sheet_no=sheet_no,
                sheet_total=sheet_total,
                title=(
                    "Принципиальная схема. Надземная часть"
                    if fragment_total == 1
                    else f"Надземная часть. Фрагмент {fragment_index}"
                ),
            ),
            "</svg>",
        )
    )
    return "".join(body)


def _slope_sign_svg(
    *,
    marker_id: str,
    value_per_mille: float,
    start: tuple[float, float],
    end: tuple[float, float],
    position: float = 0.5,
) -> str:
    x = start[0] + (end[0] - start[0]) * position
    y = start[1] + (end[1] - start[1]) * position - 28.0
    direction = 1 if end[0] >= start[0] else -1
    apex_x = x + 18.0 * direction
    heel_x = x
    value = _fmt(value_per_mille / 1000.0)
    anchor = "end" if direction > 0 else "start"
    text_x = heel_x - 6.0 * direction
    return "".join(
        (
            f'<g data-slope-marker="{escape(marker_id)}" data-placement="above" '
            f'data-sign-shape="acute-angle" '
            f'data-lower-leg-horizontal="true" '
            f'data-lower-leg-parallel-to-text="true" '
            f'data-label-underline="false">',
            f'<path d="M{heel_x:.1f},{y-9:.1f} L{apex_x:.1f},{y:.1f} '
            f'L{heel_x:.1f},{y:.1f}" fill="none" stroke="{BLACK}" '
            'stroke-width="1.5"/>',
            f'<text x="{text_x:.1f}" y="{y-2:.1f}" text-anchor="{anchor}" '
            f'font-family="{FONT}" font-size="13">{value}</text>',
            "</g>",
        )
    )


def _transition_svg(
    *,
    element_id: str,
    x: float,
    y: float,
    upstream_dn: int,
    downstream_dn: int,
    placement: str,
) -> str:
    return "".join(
        (
            f'<g data-building-transition="{escape(element_id)}" '
            f'data-upstream-dn="{upstream_dn}" data-downstream-dn="{downstream_dn}" '
            f'data-transition-placement="{escape(placement)}" '
            f'data-transition-shape="open-triangle" '
            f'data-transition-fill="none">',
            f'<path d="M{x-12:.1f},{y-10:.1f} L{x+12:.1f},{y:.1f} '
            f'L{x-12:.1f},{y+10:.1f} Z" fill="white" stroke="white" '
            'stroke-width="4"/>',
            f'<path data-diameter-transition="{escape(element_id)}" '
            f'd="M{x-12:.1f},{y-10:.1f} L{x+12:.1f},{y:.1f} '
            f'L{x-12:.1f},{y+10:.1f} Z" fill="none" stroke="{BLACK}" '
            'stroke-width="1.7"/>',
            f'<text x="{x:.1f}" y="{y-18:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11">DN{upstream_dn}×{downstream_dn}</text>',
            "</g>",
        )
    )


def _fitting_boundary(
    *,
    fitting_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
    position: float,
) -> str:
    from math import hypot

    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    x = start[0] + dx * position
    y = start[1] + dy * position
    half = 13.0
    return (
        f'<line data-fitting-boundary="{escape(fitting_id)}" '
        f'x1="{x-px*half:.1f}" y1="{y-py*half:.1f}" '
        f'x2="{x+px*half:.1f}" y2="{y+py*half:.1f}" '
        f'stroke="{BLACK}" stroke-width="2"/>'
    )


def _pipe_caption(
    pipe: BuildingPipeProjectInput,
    *,
    x: float,
    y: float,
) -> str:
    start = "—" if pipe.elevation_start_m is None else _fmt(pipe.elevation_start_m)
    end = "—" if pipe.elevation_end_m is None else _fmt(pipe.elevation_end_m)
    return "".join(
        (
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" '
            f'font-size="13" font-weight="bold">{escape(pipe.section_id)}</text>',
            f'<text x="{x:.1f}" y="{y+19:.1f}" font-family="{FONT}" '
            f'font-size="11">отм. {start} → {end}</text>',
        )
    )


def _build_two_riser_basement_reference_svg(
    assembly: WastewaterBuildingAssembly,
) -> str:
    """Render the confirmed internal basement topology and both outlets."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid building assembly: " + "; ".join(errors))
    inputs = assembly.project_inputs
    if len(inputs.k1_risers) != 2 or len(inputs.k2_risers) != 2:
        raise ValueError("current basement sheet requires two K1 and two K2 risers")
    if len(inputs.k1_collectors) != 1 or len(inputs.k2_collectors) != 1:
        raise ValueError("current basement sheet requires one collector per system")
    assert inputs.k1_outlet is not None
    assert inputs.k2_outlet is not None
    width, height = 2800, 1980
    margin = 50
    first_floor_y = 260.0
    basement_floor_y = 1560.0
    wall_left, wall_right = 230.0, 2440.0
    k1_xs = (650.0, 1240.0)
    k2_xs = (1760.0, 2110.0)
    k1_collector = inputs.k1_collectors[0]
    k2_collector = inputs.k2_collectors[0]
    k1_outlet = inputs.k1_outlet
    k2_outlet = inputs.k2_outlet
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        'viewBox="0 0 2800 1980">',
        '<defs><pattern id="basement-hatch" width="22" height="22" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(35)">'
        '<line x1="0" y1="0" x2="0" y2="22" stroke="#777" stroke-width="2"/>'
        '</pattern></defs>',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Принципиальная схема внутренних систем '
        'канализации и водоотведения. Подвал и выпуски</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">Лист 2; подтверждённые участки реестра; '
        'граница — наружная грань здания</text>',
        f'<line data-architecture="first-floor" x1="{wall_left}" y1="{first_floor_y}" '
        f'x2="{wall_right}" y2="{first_floor_y}" stroke="#777" stroke-width="2"/>',
        f'<text x="{wall_left-20}" y="{first_floor_y-14}" text-anchor="end" '
        f'font-family="{FONT}" font-size="13">1 этаж; отм. 0,000</text>',
        f'<rect data-architecture="basement-slab" x="{wall_left}" '
        f'y="{basement_floor_y}" width="{wall_right-wall_left}" height="82" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-left" x="{wall_left-55}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-right" x="{wall_right}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<text x="{wall_left-20}" y="{basement_floor_y-10}" text-anchor="end" '
        f'font-family="{FONT}" font-size="13">Пол подвала; отм. '
        f'{_fmt(float(inputs.basement_floor_elevation_m or 0))}</text>',
        f'<text x="{wall_right+82}" y="{first_floor_y+35}" font-family="{FONT}" '
        'font-size="12">наружная грань здания</text>',
    ]

    k1_turn_ends: list[tuple[float, float]] = []
    for index, riser in enumerate(inputs.k1_risers):
        x = k1_xs[index]
        main_y = 900.0 + index * 40.0
        scale = 2.0
        turn_origin_y = main_y - 76.0 * scale
        end = (x + 38.0 * scale, main_y)
        k1_turn_ends.append(end)
        riser_id = riser.stack.riser_id
        dn = int(riser.stack.riser_dn_mm or 0)
        body.append(
            _line_with_label(
                line_id=f"{riser_id}-basement-riser",
                system="K1",
                dn_mm=dn,
                start=(x, first_floor_y),
                end=(x, turn_origin_y),
                position=0.55,
            )
        )
        if riser.lower_cleanout_element_ids:
            cleanout_id = riser.lower_cleanout_element_ids[0]
            node = build_lower_turn_cleanout_assembly(
                assembly_id=f"{riser_id}-Узел-НП",
                system="K1",
                dn_mm=dn,
            )
            body.append(
                f'<g data-basement-cleanout="{escape(cleanout_id)}" '
                f'data-cleanout-axis="collinear">'
                + render_lower_turn_assembly_svg(
                    node,
                    pipe_labels=False,
                    annotations=False,
                    flow_direction=False,
                    visible_segment_ids=("riser", "diagonal", "cleanout_access"),
                    x=x,
                    y=turn_origin_y,
                    scale=scale,
                    pipe_width=4.0,
                )
                + '</g>'
            )
            body.append(
                f'<text x="{x-10:.1f}" y="{main_y-55:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="12">Прочистка '
                f'{escape(cleanout_id)}; соосно магистрали</text>'
            )
        else:
            junction_id = riser.lower_junction_element_ids[0]
            node = build_lower_turn_through_junction_assembly(
                assembly_id=f"{riser_id}-Узел-НП-Проточный",
                system="K1",
                dn_mm=dn,
            )
            body.append(
                f'<g data-basement-through-junction="{escape(junction_id)}" '
                'data-through-axis="open">'
                + render_lower_turn_assembly_svg(
                    node,
                    pipe_labels=False,
                    annotations=False,
                    flow_direction=False,
                    visible_segment_ids=("riser", "diagonal"),
                    x=x,
                    y=turn_origin_y,
                    scale=scale,
                    pipe_width=4.0,
                )
                + '</g>'
            )

    k1_collector_start, k1_collector_end = tuple(k1_turn_ends)
    body.append(
        _line_with_label(
            line_id=k1_collector.section_id,
            system="K1",
            dn_mm=k1_collector.dn_mm,
            start=k1_collector_start,
            end=k1_collector_end,
            position=0.52,
        )
    )
    body.append(
        _slope_sign_svg(
            marker_id=f"{k1_collector.section_id}-slope",
            value_per_mille=float(k1_collector.slope_per_mille or 0),
            start=k1_collector_start,
            end=k1_collector_end,
        )
    )
    body.append(_pipe_caption(k1_collector, x=820.0, y=1000.0))
    k1_outlet_start = k1_collector_end
    k1_outlet_end = (2660.0, 1040.0)
    body.append(
        _line_with_label(
            line_id=k1_outlet.section_id,
            system="K1",
            dn_mm=k1_outlet.dn_mm,
            start=k1_outlet_start,
            end=k1_outlet_end,
            position=0.64,
        )
    )
    body.append(
        _slope_sign_svg(
            marker_id=f"{k1_outlet.section_id}-slope",
            value_per_mille=float(k1_outlet.slope_per_mille or 0),
            start=k1_outlet_start,
            end=k1_outlet_end,
            position=0.68,
        )
    )
    body.append(
        _transition_svg(
            element_id=inputs.k1_transition_element_ids[0],
            # Увеличение DN выполняется на входящей магистрали до проходного
            # редукционного тройника второго стояка.
            x=(
                k1_collector_start[0]
                + (k1_collector_end[0] - k1_collector_start[0]) * 0.90
            ),
            y=(
                k1_collector_start[1]
                + (k1_collector_end[1] - k1_collector_start[1]) * 0.90
            ),
            upstream_dn=k1_collector.dn_mm,
            downstream_dn=k1_outlet.dn_mm,
            placement="upstream-before-junction",
        )
    )
    body.append(_pipe_caption(k1_outlet, x=2130.0, y=940.0))
    body.append(
        f'<path data-flow-direction="{escape(k1_outlet.section_id)}" '
        f'd="M2633,1027 L2660,1040 L2631,1051 Z" fill="{BLACK}"/>'
    )
    body.append(
        f'<text x="{2475:.1f}" y="{1090:.1f}" font-family="{FONT}" '
        f'font-size="13" font-weight="bold">Выпуск {escape(k1_outlet.section_id)} '
        f'DN{k1_outlet.dn_mm} за грань здания</text>'
    )

    k2_joins: list[tuple[float, float]] = []
    for index, riser in enumerate(inputs.k2_risers):
        x = k2_xs[index]
        main_y = 1200.0 + index * 40.0
        scale = 2.0
        turn_origin_y = main_y - 76.0 * scale
        end = (x + 38.0 * scale, main_y)
        k2_joins.append(end)
        body.append(
            _line_with_label(
                line_id=f"{riser.riser_id}-basement-riser",
                system="K2",
                dn_mm=riser.riser_dn_mm,
                start=(x, first_floor_y),
                end=(x, turn_origin_y),
                position=0.53,
            )
        )
        if riser.lower_cleanout_element_ids:
            cleanout_id = riser.lower_cleanout_element_ids[0]
            node = build_lower_turn_cleanout_assembly(
                assembly_id=f"{riser.riser_id}-Узел-НП",
                system="K2",
                dn_mm=riser.riser_dn_mm,
            )
            body.append(
                f'<g data-basement-cleanout="{escape(cleanout_id)}" '
                f'data-cleanout-axis="collinear">'
                + render_lower_turn_assembly_svg(
                    node,
                    pipe_labels=False,
                    annotations=False,
                    flow_direction=False,
                    visible_segment_ids=("riser", "diagonal", "cleanout_access"),
                    x=x,
                    y=turn_origin_y,
                    scale=scale,
                    pipe_width=4.0,
                )
                + '</g>'
            )
            body.append(
                f'<text x="{x-10:.1f}" y="{main_y-55:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="12">Прочистка '
                f'{escape(cleanout_id)}; соосно магистрали</text>'
            )
        else:
            junction_id = riser.lower_junction_element_ids[0]
            node = build_lower_turn_through_junction_assembly(
                assembly_id=f"{riser.riser_id}-Узел-НП-Проточный",
                system="K2",
                dn_mm=riser.riser_dn_mm,
            )
            body.append(
                f'<g data-basement-through-junction="{escape(junction_id)}" '
                'data-through-axis="open">'
                + render_lower_turn_assembly_svg(
                    node,
                    pipe_labels=False,
                    annotations=False,
                    flow_direction=False,
                    visible_segment_ids=("riser", "diagonal"),
                    x=x,
                    y=turn_origin_y,
                    scale=scale,
                    pipe_width=4.0,
                )
                + '</g>'
            )
        # Этажная ревизия не переносится к нижнему повороту. Если она задана
        # на первом этаже, её показывает надземный лист на реальной высоте над
        # чистым полом. Здесь остаётся только подвальная трасса и её фасонные
        # части.

    k2_join_1, k2_join_2 = tuple(k2_joins)
    body.append(
        _line_with_label(
            line_id=k2_collector.section_id,
            system="K2",
            dn_mm=k2_collector.dn_mm,
            start=k2_join_1,
            end=k2_join_2,
            position=0.55,
        )
    )
    body.append(
        _slope_sign_svg(
            marker_id=f"{k2_collector.section_id}-slope",
            value_per_mille=float(k2_collector.slope_per_mille or 0),
            start=k2_join_1,
            end=k2_join_2,
        )
    )
    body.append(
        _transition_svg(
            element_id=inputs.k2_transition_element_ids[0],
            x=1865.0,
            y=1204.0,
            upstream_dn=inputs.k2_risers[0].riser_dn_mm,
            downstream_dn=k2_collector.dn_mm,
            placement="downstream-after-terminal-turn",
        )
    )
    body.append(_pipe_caption(k2_collector, x=1870.0, y=1300.0))
    k2_outlet_end = (2660.0, 1310.0)
    body.append(
        _line_with_label(
            line_id=k2_outlet.section_id,
            system="K2",
            dn_mm=k2_outlet.dn_mm,
            start=k2_join_2,
            end=k2_outlet_end,
            position=0.55,
        )
    )
    body.append(
        _slope_sign_svg(
            marker_id=f"{k2_outlet.section_id}-slope",
            value_per_mille=float(k2_outlet.slope_per_mille or 0),
            start=k2_join_2,
            end=k2_outlet_end,
        )
    )
    body.append(_pipe_caption(k2_outlet, x=2260.0, y=1355.0))
    body.append(
        f'<path data-flow-direction="{escape(k2_outlet.section_id)}" '
        'd="M2633,1296 L2660,1310 L2630,1321 Z" fill="#000"/>'
    )
    body.append(
        f'<text x="2475" y="1405" font-family="{FONT}" font-size="13" '
        f'font-weight="bold">Выпуск {escape(k2_outlet.section_id)} '
        f'DN{k2_outlet.dn_mm} за грань здания</text>'
    )

    body.extend(
        (
            f'<rect x="{margin+35}" y="{1680}" width="{2010}" '
            'height="215" fill="white" stroke="#777" stroke-width="1"/>',
            f'<text x="{margin+58}" y="1715" font-family="{FONT}" '
            'font-size="14" font-weight="bold">Граница детализации</text>',
            f'<text x="{margin+58}" y="1745" font-family="{FONT}" '
            'font-size="12">Начальный узел: косой тройник с соосным заглушённым концом - по логика1.pdf.</text>',
            f'<text x="{margin+58}" y="1770" font-family="{FONT}" '
            'font-size="12">Промежуточный узел: проточный косой тройник без заглушки; ось магистрали открыта.</text>',
            f'<text x="{margin+58}" y="1795" font-family="{FONT}" '
            'font-size="12">Доступ к промежуточному повороту К2 обеспечивает отдельная доступная ревизия.</text>',
            f'<text x="{margin+58}" y="1875" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Графический язык — приложение В '
            'ГОСТ Р 21.620-2023; выпуск заканчивается за наружной гранью здания.</text>',
            _title_block_svg(
                assembly.document,
                sheet_no=2,
                sheet_total=3,
                title="Принципиальная схема. Подвал и выпуски",
            ),
            "</svg>",
        )
    )
    return "".join(body)


def _riser_id(
    row: BuildingK1RiserProjectInput | BuildingK2RiserProjectInput,
) -> str:
    if isinstance(row, BuildingK1RiserProjectInput):
        return row.stack.riser_id
    return row.riser_id


def _riser_dn(
    row: BuildingK1RiserProjectInput | BuildingK2RiserProjectInput,
) -> int:
    if isinstance(row, BuildingK1RiserProjectInput):
        return int(row.stack.riser_dn_mm or 0)
    return row.riser_dn_mm


def _transition_for_node(
    transitions: tuple[BuildingTransitionProjectInput, ...],
    *,
    node_id: str,
    section_id: str,
) -> BuildingTransitionProjectInput | None:
    key = " ".join(node_id.strip().casefold().split())
    section_key = " ".join(section_id.strip().casefold().split())
    return next(
        (
            row for row in transitions
            if " ".join(row.node_id.strip().casefold().split()) == key
            and " ".join(row.section_id.strip().casefold().split()) == section_key
        ),
        None,
    )


def _render_basement_system_fragment(
    *,
    body: list[str],
    system: str,
    risers: tuple[BuildingK1RiserProjectInput | BuildingK2RiserProjectInput, ...],
    collectors: tuple[BuildingPipeProjectInput, ...],
    outlet: BuildingPipeProjectInput,
    transitions: tuple[BuildingTransitionProjectInput, ...],
    start_index: int,
    end_index: int,
    base_y: float,
    first_floor_y: float,
    wall_left: float,
    wall_right: float,
    previous_sheet_no: int | None,
    next_sheet_no: int | None,
) -> None:
    """Draw one paginated fragment of a confirmed linear system chain."""
    fragment = risers[start_index:end_index]
    if not fragment:
        return
    xs = _spread_positions(len(fragment), 470.0, 2090.0)
    turn_scale = 2.0
    turn_offset_x = 38.0 * turn_scale
    turn_offset_y = 76.0 * turn_scale
    node_ys = [base_y]
    for local_index in range(1, len(fragment)):
        edge = collectors[start_index + local_index - 1]
        dx = xs[local_index] - xs[local_index - 1]
        drop = max(2.0, min(12.0, dx * float(edge.slope_per_mille or 0) / 1000.0))
        node_ys.append(node_ys[-1] + drop)
    joins = tuple((x + turn_offset_x, y) for x, y in zip(xs, node_ys))

    range_label = (
        f"стояк {start_index+1}"
        if end_index - start_index == 1
        else f"стояки {start_index+1}-{end_index}"
    )
    body.append(
        f'<text x="{wall_left+45:.1f}" y="{base_y-205:.1f}" '
        f'font-family="{FONT}" font-size="20" font-weight="bold">'
        f'{_system_mark(system)} · {range_label}</text>'
    )

    incoming_stub: tuple[tuple[float, float], tuple[float, float]] | None = None
    if start_index > 0:
        incoming = collectors[start_index - 1]
        end = joins[0]
        start = (wall_left + 78.0, end[1] - 5.0)
        incoming_stub = (start, end)
        body.append(
            _line_with_label(
                line_id=incoming.section_id,
                system=system,
                dn_mm=incoming.dn_mm,
                start=start,
                end=end,
                position=0.42,
            )
        )
        body.append(
            _slope_sign_svg(
                marker_id=f"{incoming.section_id}-slope-in-{start_index}",
                value_per_mille=float(incoming.slope_per_mille or 0),
                start=start,
                end=end,
                position=0.38,
            )
        )
        body.append(
            f'<text x="{start[0]:.1f}" y="{start[1]-34:.1f}" '
            f'font-family="{FONT}" font-size="12">с листа '
            f'{previous_sheet_no or "—"}</text>'
        )

    for local_index, riser in enumerate(fragment):
        global_index = start_index + local_index
        x = xs[local_index]
        main_y = node_ys[local_index]
        turn_origin_y = main_y - turn_offset_y
        riser_id = _riser_id(riser)
        dn = _riser_dn(riser)
        body.append(
            _line_with_label(
                line_id=f"{riser_id}-basement-riser",
                system=system,
                dn_mm=dn,
                start=(x, first_floor_y),
                end=(x, turn_origin_y),
                position=0.52,
            )
        )
        if riser.lower_cleanout_element_ids:
            cleanout_id = riser.lower_cleanout_element_ids[0]
            node = build_lower_turn_cleanout_assembly(
                assembly_id=f"{riser_id}-Узел-НП",
                system=system,
                dn_mm=dn,
            )
            body.append(
                f'<g data-basement-cleanout="{escape(cleanout_id)}" '
                'data-cleanout-axis="collinear">'
                + render_lower_turn_assembly_svg(
                    node,
                    pipe_labels=False,
                    annotations=False,
                    flow_direction=False,
                    visible_segment_ids=("riser", "diagonal", "cleanout_access"),
                    x=x,
                    y=turn_origin_y,
                    scale=turn_scale,
                    pipe_width=4.0,
                )
                + '</g>'
            )
            body.append(
                f'<text x="{x-12:.1f}" y="{main_y-55:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="11">Прочистка '
                f'{escape(cleanout_id)}; соосно</text>'
            )
        else:
            junction_id = riser.lower_junction_element_ids[0]
            node = build_lower_turn_through_junction_assembly(
                assembly_id=f"{riser_id}-Узел-НП-Проточный",
                system=system,
                dn_mm=dn,
            )
            body.append(
                f'<g data-basement-through-junction="{escape(junction_id)}" '
                'data-through-axis="open">'
                + render_lower_turn_assembly_svg(
                    node,
                    pipe_labels=False,
                    annotations=False,
                    flow_direction=False,
                    visible_segment_ids=("riser", "diagonal"),
                    x=x,
                    y=turn_origin_y,
                    scale=turn_scale,
                    pipe_width=4.0,
                )
                + '</g>'
            )

        outgoing = collectors[global_index] if global_index < len(collectors) else outlet
        outgoing_start = joins[local_index]
        if local_index + 1 < len(fragment):
            outgoing_end = joins[local_index + 1]
        elif global_index < len(collectors):
            outgoing_end = (wall_right - 80.0, outgoing_start[1] + 5.0)
        else:
            horizontal = 2660.0 - outgoing_start[0]
            drop = max(
                2.0,
                min(14.0, horizontal * float(outgoing.slope_per_mille or 0) / 1000.0),
            )
            outgoing_end = (2660.0, outgoing_start[1] + drop)

        body.append(
            _line_with_label(
                line_id=outgoing.section_id,
                system=system,
                dn_mm=outgoing.dn_mm,
                start=outgoing_start,
                end=outgoing_end,
                position=0.52,
            )
        )
        body.append(
            _slope_sign_svg(
                marker_id=f"{outgoing.section_id}-slope-{global_index}",
                value_per_mille=float(outgoing.slope_per_mille or 0),
                start=outgoing_start,
                end=outgoing_end,
                position=0.55,
            )
        )

        transition = _transition_for_node(
            transitions,
            node_id=riser_id,
            section_id=outgoing.section_id,
        )
        if transition is not None:
            if transition.placement == "upstream-before-junction":
                if local_index > 0:
                    transition_start = joins[local_index - 1]
                    transition_end = joins[local_index]
                elif incoming_stub is not None:
                    transition_start, transition_end = incoming_stub
                else:
                    raise ValueError(
                        f"{transition.element_id}: no incoming graphic segment"
                    )
                position = 0.86
            else:
                transition_start, transition_end = outgoing_start, outgoing_end
                position = 0.18
            transition_x = transition_start[0] + (
                transition_end[0] - transition_start[0]
            ) * position
            transition_y = transition_start[1] + (
                transition_end[1] - transition_start[1]
            ) * position
            body.append(
                _transition_svg(
                    element_id=transition.element_id,
                    x=transition_x,
                    y=transition_y,
                    upstream_dn=transition.upstream_dn_mm,
                    downstream_dn=transition.downstream_dn_mm,
                    placement=transition.placement,
                )
            )

        if global_index < len(collectors) and local_index == len(fragment) - 1:
            body.append(
                f'<text x="{outgoing_end[0]-12:.1f}" y="{outgoing_end[1]-66:.1f}" '
                f'text-anchor="end" font-family="{FONT}" font-size="12">'
                f'продолжение на листе {next_sheet_no or "—"}</text>'
            )
        if global_index == len(risers) - 1:
            body.append(
                f'<path data-flow-direction="{escape(outlet.section_id)}" '
                f'd="M{outgoing_end[0]-28:.1f},{outgoing_end[1]-12:.1f} '
                f'L{outgoing_end[0]:.1f},{outgoing_end[1]:.1f} '
                f'L{outgoing_end[0]-29:.1f},{outgoing_end[1]+11:.1f} Z" '
                f'fill="{BLACK}"/>'
            )
            body.append(
                f'<text x="{outgoing_end[0]-185:.1f}" y="{outgoing_end[1]+52:.1f}" '
                f'font-family="{FONT}" font-size="13" font-weight="bold">'
                f'Выпуск {escape(outlet.section_id)} DN{outlet.dn_mm} '
                'за грань здания</text>'
            )


def build_wastewater_building_basement_fragment_svg(
    assembly: WastewaterBuildingAssembly,
    *,
    k1_start_index: int,
    k1_end_index: int,
    k2_start_index: int,
    k2_end_index: int,
    sheet_no: int,
    sheet_total: int,
    fragment_index: int,
    fragment_total: int,
) -> str:
    """Render one A1 fragment of the complete lower-node chain."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid building assembly: " + "; ".join(errors))
    inputs = assembly.project_inputs
    assert inputs.k1_outlet is not None
    assert inputs.k2_outlet is not None
    width = 2800
    margin = 50
    first_floor_y = 260.0
    basement_floor_y = 1560.0
    wall_left, wall_right = 230.0, 2440.0
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        f'viewBox="0 0 2800 1980" data-sheet-role="basement" '
        f'data-fragment-index="{fragment_index}" '
        f'data-fragment-total="{fragment_total}">',
        '<defs><pattern id="basement-hatch" width="22" height="22" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(35)">'
        '<line x1="0" y1="0" x2="0" y2="22" stroke="#777" stroke-width="2"/>'
        '</pattern></defs>',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Принципиальная схема внутренних систем '
        'канализации и водоотведения. Подвал и выпуски</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">Фрагмент {fragment_index}/{fragment_total}; '
        'подтверждённая линейная топология реестра</text>',
        f'<line data-architecture="first-floor" x1="{wall_left}" y1="{first_floor_y}" '
        f'x2="{wall_right}" y2="{first_floor_y}" stroke="#777" stroke-width="2"/>',
        f'<text x="{wall_left-20}" y="{first_floor_y-14}" text-anchor="end" '
        f'font-family="{FONT}" font-size="13">1 этаж; отм. 0,000</text>',
        f'<rect data-architecture="basement-slab" x="{wall_left}" '
        f'y="{basement_floor_y}" width="{wall_right-wall_left}" height="82" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-left" x="{wall_left-55}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-right" x="{wall_right}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<text x="{wall_left-20}" y="{basement_floor_y-10}" text-anchor="end" '
        f'font-family="{FONT}" font-size="13">Пол подвала; отм. '
        f'{_fmt(float(inputs.basement_floor_elevation_m or 0))}</text>',
        f'<text x="{wall_right+82}" y="{first_floor_y+35}" font-family="{FONT}" '
        'font-size="12">наружная грань здания</text>',
    ]
    previous_sheet_no = sheet_no - 1 if fragment_index > 1 else None
    next_sheet_no = sheet_no + 1 if fragment_index < fragment_total else None
    _render_basement_system_fragment(
        body=body,
        system="K1",
        risers=inputs.k1_risers,
        collectors=inputs.k1_collectors,
        outlet=inputs.k1_outlet,
        transitions=inputs.k1_transitions,
        start_index=k1_start_index,
        end_index=k1_end_index,
        base_y=820.0,
        first_floor_y=first_floor_y,
        wall_left=wall_left,
        wall_right=wall_right,
        previous_sheet_no=previous_sheet_no,
        next_sheet_no=next_sheet_no,
    )
    _render_basement_system_fragment(
        body=body,
        system="K2",
        risers=inputs.k2_risers,
        collectors=inputs.k2_collectors,
        outlet=inputs.k2_outlet,
        transitions=inputs.k2_transitions,
        start_index=k2_start_index,
        end_index=k2_end_index,
        base_y=1210.0,
        first_floor_y=first_floor_y,
        wall_left=wall_left,
        wall_right=wall_right,
        previous_sheet_no=previous_sheet_no,
        next_sheet_no=next_sheet_no,
    )
    body.extend((
        f'<rect x="{margin+35}" y="1680" width="2010" height="215" '
        'fill="white" stroke="#777" stroke-width="1"/>',
        f'<text x="{margin+58}" y="1715" font-family="{FONT}" '
        'font-size="14" font-weight="bold">Граница детализации</text>',
        f'<text x="{margin+58}" y="1745" font-family="{FONT}" font-size="12">'
        'Начальный узел: соосная заглушённая прочистка только на свободном конце.</text>',
        f'<text x="{margin+58}" y="1770" font-family="{FONT}" font-size="12">'
        'Промежуточный узел: проточный косой тройник без заглушки; ось открыта.</text>',
        f'<text x="{margin+58}" y="1795" font-family="{FONT}" font-size="12">'
        'Уклон показан нормативным острым углом; геометрический наклон не преувеличен.</text>',
        _title_block_svg(
            assembly.document,
            sheet_no=sheet_no,
            sheet_total=sheet_total,
            title=(
                "Принципиальная схема. Подвал и выпуски"
                if fragment_total == 1
                else f"Подвал и выпуски. Фрагмент {fragment_index}"
            ),
        ),
        '</svg>',
    ))
    return "".join(body)


def build_wastewater_building_basement_svg(
    assembly: WastewaterBuildingAssembly,
) -> str:
    """Render a single basement sheet when the topology fits one A1 fragment.

    Full production generation must use :func:`build_wastewater_building_svgs`,
    which paginates longer chains instead of shrinking or omitting them.
    """
    if (
        len(assembly.project_inputs.k1_risers) > _BASEMENT_RISER_PAGE_CAPACITY
        or len(assembly.project_inputs.k2_risers) > _BASEMENT_RISER_PAGE_CAPACITY
    ):
        raise ValueError(
            "basement topology requires multiple A1 fragments; "
            "use build_wastewater_building_svgs"
        )
    return build_wastewater_building_basement_fragment_svg(
        assembly,
        k1_start_index=0,
        k1_end_index=len(assembly.project_inputs.k1_risers),
        k2_start_index=0,
        k2_end_index=len(assembly.project_inputs.k2_risers),
        sheet_no=2,
        sheet_total=3,
        fragment_index=1,
        fragment_total=1,
    )


def build_wastewater_building_svgs(
    assembly: WastewaterBuildingAssembly,
) -> tuple[str, ...]:
    """Compose as many A1 fragments as the confirmed riser count requires."""
    k1_floor_chunks = _chunks(assembly.k1_stacks, _FLOOR_K1_PAGE_CAPACITY)
    k2_floor_chunks = _chunks(
        assembly.project_inputs.k2_risers,
        _FLOOR_K2_PAGE_CAPACITY,
    )
    floor_page_count = max(len(k1_floor_chunks), len(k2_floor_chunks), 1)

    k1_basement_chunks = _chunks(
        assembly.project_inputs.k1_risers,
        _BASEMENT_RISER_PAGE_CAPACITY,
    )
    k2_basement_chunks = _chunks(
        assembly.project_inputs.k2_risers,
        _BASEMENT_RISER_PAGE_CAPACITY,
    )
    basement_page_count = max(
        len(k1_basement_chunks),
        len(k2_basement_chunks),
        1,
    )
    drawing_page_count = floor_page_count + basement_page_count
    sheet_total = drawing_page_count + 1  # отдельный лист УГО комплекта
    basement_sheet_by_riser_id: dict[str, int] = {}
    for index in range(basement_page_count):
        sheet_no = floor_page_count + index + 1
        for row in assembly.project_inputs.k1_risers[
            index * _BASEMENT_RISER_PAGE_CAPACITY:
            (index + 1) * _BASEMENT_RISER_PAGE_CAPACITY
        ]:
            basement_sheet_by_riser_id[row.stack.riser_id] = sheet_no
        for row in assembly.project_inputs.k2_risers[
            index * _BASEMENT_RISER_PAGE_CAPACITY:
            (index + 1) * _BASEMENT_RISER_PAGE_CAPACITY
        ]:
            basement_sheet_by_riser_id[row.riser_id] = sheet_no
    pages: list[str] = []
    for index in range(floor_page_count):
        pages.append(
            build_wastewater_building_floors_svg(
                assembly,
                k1_stacks=(
                    k1_floor_chunks[index]
                    if index < len(k1_floor_chunks)
                    else ()
                ),
                k2_risers=(
                    k2_floor_chunks[index]
                    if index < len(k2_floor_chunks)
                    else ()
                ),
                sheet_no=index + 1,
                sheet_total=sheet_total,
                fragment_index=index + 1,
                fragment_total=floor_page_count,
                basement_first_sheet_no=floor_page_count + 1,
                basement_sheet_by_riser_id=basement_sheet_by_riser_id,
            )
        )
    for index in range(basement_page_count):
        k1_start = index * _BASEMENT_RISER_PAGE_CAPACITY
        k2_start = index * _BASEMENT_RISER_PAGE_CAPACITY
        pages.append(
            build_wastewater_building_basement_fragment_svg(
                assembly,
                k1_start_index=min(k1_start, len(assembly.project_inputs.k1_risers)),
                k1_end_index=min(
                    k1_start + _BASEMENT_RISER_PAGE_CAPACITY,
                    len(assembly.project_inputs.k1_risers),
                ),
                k2_start_index=min(k2_start, len(assembly.project_inputs.k2_risers)),
                k2_end_index=min(
                    k2_start + _BASEMENT_RISER_PAGE_CAPACITY,
                    len(assembly.project_inputs.k2_risers),
                ),
                sheet_no=floor_page_count + index + 1,
                sheet_total=sheet_total,
                fragment_index=index + 1,
                fragment_total=basement_page_count,
            )
        )
    return tuple(pages)


def audit_wastewater_building_svgs(
    assembly: WastewaterBuildingAssembly,
    svgs: tuple[str, ...],
) -> tuple[str, ...]:
    """Fail-fast graphic audit for the complete paginated assembly."""
    findings: list[str] = []
    try:
        roots = tuple(ElementTree.fromstring(svg) for svg in svgs)
    except ElementTree.ParseError as exc:
        return (f"combined sheet SVG is invalid: {exc}",)
    floor_roots = tuple(
        row for row in roots if row.get("data-sheet-role") == "floors"
    )
    basement_roots = tuple(
        row for row in roots if row.get("data-sheet-role") == "basement"
    )
    if not floor_roots:
        findings.append("assembly has no above-ground sheet")
    if not basement_roots:
        findings.append("assembly has no basement sheet")

    expected_sheet_total = str(len(roots) + 1)
    for page_no, root in enumerate(roots, start=1):
        visible_text = " ".join(root.itertext())
        title_blocks = [
            row for row in root.iter()
            if row.get("data-title-block") == "form-3"
        ]
        if len(title_blocks) != 1:
            findings.append(
                f"sheet {page_no}: expected exactly one form-3 title block"
            )
        elif (
            title_blocks[0].get("data-sheet-no") != str(page_no)
            or title_blocks[0].get("data-sheet-total") != expected_sheet_total
        ):
            findings.append(f"sheet {page_no}: title block numbering is invalid")
        if "i=" in visible_text or "i =" in visible_text:
            findings.append(f"sheet {page_no}: legacy i= slope notation remains")
        for group in root.iter():
            line_id = group.get("data-building-pipe-line")
            if not line_id:
                continue
            labels = {
                child.get("data-pipe-line-id")
                for child in group.iter()
                if child.get("data-pipe-line-id")
            }
            if line_id not in labels:
                findings.append(
                    f"sheet {page_no}: pipe line {line_id} has no inline system/DN mark"
                )

    floor_assembly_ids = {
        row.get("data-floor-assembly")
        for root in floor_roots
        for row in root.iter()
        if row.get("data-floor-assembly")
    }
    for stack in assembly.k1_stacks:
        for floor_no in assembly.displayed_floor_numbers:
            expected = f"{stack.riser_id}-Сборка-Этаж-{floor_no:02d}"
            if expected not in floor_assembly_ids:
                findings.append(f"sheet 1: missing floor assembly {expected}")

    basement_sheet_by_riser: dict[str, int] = {}
    for page_no, root in enumerate(roots, start=1):
        if root.get("data-sheet-role") != "basement":
            continue
        for row in root.iter():
            line_id = row.get("data-building-pipe-line", "")
            if line_id.endswith("-basement-riser"):
                basement_sheet_by_riser[line_id[:-len("-basement-riser")]] = page_no
    continuation_targets = {
        row.get("data-continuation-riser"): int(row.get("data-target-sheet", "0"))
        for root in floor_roots
        for row in root.iter()
        if row.get("data-continuation-riser")
    }
    if continuation_targets != basement_sheet_by_riser:
        findings.append("above-ground continuation references do not match basement sheets")

    drawn_k2_floor_revisions = {
        row.get("data-building-revision")
        for root in floor_roots
        for row in root.iter()
        if row.get("data-building-revision", "").startswith("К2")
    }
    expected_k2_floor_revisions = {
        revision.element_id
        for riser in assembly.project_inputs.k2_risers
        for revision in riser.revisions
    }
    if drawn_k2_floor_revisions != expected_k2_floor_revisions:
        findings.append("sheet 1: K2 revisions differ from project registry")
    drawn_k2_lower_revisions = {
        row.get("data-basement-revision")
        for root in basement_roots
        for row in root.iter()
        if row.get("data-basement-revision", "").startswith("К2")
    }
    if drawn_k2_lower_revisions:
        findings.append("sheet 2: floor K2 revision was moved into the basement")
    cleanout_ids = {
        row.get("data-basement-cleanout")
        for root in basement_roots
        for row in root.iter()
        if row.get("data-basement-cleanout")
    }
    expected_cleanout_ids = {
        element_id
        for row in (
            assembly.project_inputs.k1_risers
            + assembly.project_inputs.k2_risers
        )
        for element_id in row.lower_cleanout_element_ids
    }
    if cleanout_ids != expected_cleanout_ids:
        findings.append("sheet 2: lower-turn cleanouts differ from project registry")
    for root in basement_roots:
        for row in root.iter():
            if (
                row.get("data-basement-cleanout")
                and row.get("data-cleanout-axis") != "collinear"
            ):
                findings.append("basement: lower-turn cleanout is not collinear with main")
    junction_ids = {
        row.get("data-basement-through-junction")
        for root in basement_roots
        for row in root.iter()
        if row.get("data-basement-through-junction")
    }
    expected_junction_ids = {
        element_id
        for row in (
            assembly.project_inputs.k1_risers
            + assembly.project_inputs.k2_risers
        )
        for element_id in row.lower_junction_element_ids
    }
    if junction_ids != expected_junction_ids:
        findings.append("sheet 2: through junctions differ from project registry")
    for root in basement_roots:
        for row in root.iter():
            if (
                row.get("data-basement-through-junction")
                and row.get("data-through-axis") != "open"
            ):
                findings.append("basement: through junction was incorrectly capped")

    basement_line_ids = {
        row.get("data-building-pipe-line")
        for root in basement_roots
        for row in root.iter()
        if row.get("data-building-pipe-line")
    }
    expected_edges = {
        row.section_id
        for row in (
            assembly.project_inputs.k1_collectors
            + assembly.project_inputs.k2_collectors
            + tuple(
                row
                for row in (
                    assembly.project_inputs.k1_outlet,
                    assembly.project_inputs.k2_outlet,
                )
                if row is not None
            )
        )
    }
    missing_edges = sorted(expected_edges - basement_line_ids)
    if missing_edges:
        findings.append(
            "sheet 2: registry edges are not drawn: " + ", ".join(missing_edges)
        )

    drawn_transition_ids = {
        row.get("data-building-transition")
        for root in basement_roots
        for row in root.iter()
        if row.get("data-building-transition")
    }
    expected_transition_ids = {
        row.element_id
        for row in (
            assembly.project_inputs.k1_transitions
            + assembly.project_inputs.k2_transitions
        )
    }
    if drawn_transition_ids != expected_transition_ids:
        findings.append("basement: DN transitions differ from project registry")

    for outlet in (
        assembly.project_inputs.k1_outlet,
        assembly.project_inputs.k2_outlet,
    ):
        if outlet is None:
            continue
        root_and_group = next(
            (
                (root, row)
                for root in basement_roots
                for row in root.iter()
                if row.get("data-building-pipe-line") == outlet.section_id
            ),
            None,
        )
        if root_and_group is None:
            findings.append(f"basement: outlet {outlet.section_id} is not drawn")
            continue
        root, group = root_and_group
        right_wall = next(
            (
                row for row in root.iter()
                if row.get("data-architecture") == "foundation-right"
            ),
            None,
        )
        wall_x = (
            float(right_wall.get("x", "inf"))
            if right_wall is not None
            else float("inf")
        )
        line = next(
            (row for row in group.iter() if row.tag.endswith("line")),
            None,
        )
        if line is None or float(line.get("x2", "-inf")) <= wall_x:
            findings.append(
                f"basement: outlet {outlet.section_id} does not cross the building face"
            )
    return tuple(dict.fromkeys(findings))


def generate_wastewater_building_pdf_from_project(
    output_path: str,
    project: Project,
    *,
    floor_height_m: float,
    roof_kind: str,
) -> str:
    """Write the combined registry-backed paginated vector PDF."""
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    inputs = resolve_wastewater_building_project_inputs(project)
    assembly = build_wastewater_building_assembly(
        inputs,
        floor_height_m=floor_height_m,
        roof_kind=roof_kind,
        document=project.document,
    )
    svgs = build_wastewater_building_svgs(assembly)
    findings = audit_wastewater_building_svgs(assembly, svgs)
    if findings:
        raise ValueError("combined K1/K2 graphic audit failed: " + "; ".join(findings))
    writer = PdfWriter()
    for svg in svgs:
        page_pdf = BytesIO()
        cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=page_pdf)
        page_pdf.seek(0)
        writer.append(PdfReader(page_pdf))
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)
    return str(path)

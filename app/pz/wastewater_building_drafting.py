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
from math import isfinite
from pathlib import Path
from xml.etree import ElementTree

from app.pz.drafting_font import ensure_drafting_font_registered
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
    validate_wastewater_building_system_isolation,
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

_SHEET_WIDTH_MM = 841.0
_SHEET_HEIGHT_MM = 594.0
_SHEET_SCALE = 10.0 / 3.0
_SHEET_WIDTH = _SHEET_WIDTH_MM * _SHEET_SCALE
_SHEET_HEIGHT = _SHEET_HEIGHT_MM * _SHEET_SCALE
_FRAME_LEFT = 20.0 * _SHEET_SCALE
_FRAME_TOP = 5.0 * _SHEET_SCALE
_FRAME_RIGHT = _SHEET_WIDTH - 5.0 * _SHEET_SCALE
_FRAME_BOTTOM = _SHEET_HEIGHT - 5.0 * _SHEET_SCALE
_OPENGOST_CAP_HEIGHT_RATIO = 0.823


def _font_size_for_height(height_mm: float) -> float:
    """SVG font-size that gives the requested OpenGOST capital height in mm."""
    return height_mm * _SHEET_SCALE / _OPENGOST_CAP_HEIGHT_RATIO


_FONT_H_2_5 = _font_size_for_height(2.5)
_FONT_H_3_5 = _font_size_for_height(3.5)
_FONT_H_5 = _font_size_for_height(5.0)
_FONT_H_7 = _font_size_for_height(7.0)
_LINE_THIN = 0.35 * _SHEET_SCALE
_LINE_MAIN = 0.7 * _SHEET_SCALE
_FLOOR_K1_PAGE_CAPACITY = 2
_FLOOR_K2_PAGE_CAPACITY = 2
_BASEMENT_RISER_PAGE_CAPACITY = 2

# The same axis register is used on the above-ground and basement sheets.
# K2 occupies the left lanes and K1 the right lanes so that independent
# collectors never cross the other system's vertical risers.
_K2_RISER_LANES = {
    0: (),
    1: (370.0,),
    2: (260.0, 500.0),
}
_K1_RISER_LANES = {
    0: (),
    1: (1690.0,),
    2: (1300.0, 2090.0),
}


def _chunks(values: tuple, size: int) -> tuple[tuple, ...]:
    return tuple(values[index:index + size] for index in range(0, len(values), size))


def _riser_axis_register(
    *,
    k1_ids: tuple[str, ...],
    k2_ids: tuple[str, ...],
) -> dict[str, float]:
    """Return the canonical page axis for each continued building riser."""
    if len(k1_ids) not in _K1_RISER_LANES or len(k2_ids) not in _K2_RISER_LANES:
        raise ValueError("one drawing fragment supports one or two K1/K2 risers")
    if len(set(k1_ids + k2_ids)) != len(k1_ids + k2_ids):
        raise ValueError("riser identifiers in one drawing fragment must be unique")
    return {
        **dict(zip(k2_ids, _K2_RISER_LANES[len(k2_ids)])),
        **dict(zip(k1_ids, _K1_RISER_LANES[len(k1_ids)])),
    }


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

    def line(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        width: float = _LINE_THIN,
    ) -> str:
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
        f'stroke-width="{_LINE_MAIN:.1f}"/>',
        line(x(65), y(0), x(65), y(55), _LINE_MAIN),
    ]
    for column in (7, 17, 25, 37, 53):
        rows.append(line(x(column), y(0), x(column), y(25)))
    for column in (17, 37, 53):
        rows.append(line(x(column), y(25), x(column), y(55)))
    rows.append(line(x(135), y(25), x(135), y(55), _LINE_MAIN))
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
        rows.append(text_svg(x((c0 + c1) / 2), y(23.4), label, _FONT_H_2_5))
    signers = (
        ("Разраб.", doc.developer_name, 30),
        ("Проверил", doc.inspector_name, 35),
        ("Нач. отдела", doc.dept_head_name, 40),
        ("ГИП", doc.gip_name, 45),
        ("Н. контр.", doc.norm_control_name, 55),
    )
    for label, name, row_mm in signers:
        rows.append(text_svg(
            x(1), y(row_mm - 1.5), label, _FONT_H_2_5, "start"
        ))
        if name:
            rows.append(text_svg(
                x(27), y(row_mm - 1.5), _short(name, 18), _FONT_H_2_5
            ))
    rows.extend((
        text_svg(x(125), y(7), _short(doc.cipher or "", 34), _FONT_H_3_5),
        text_svg(x(125), y(18), _short(doc.object_name or "", 68), _FONT_H_2_5),
        text_svg(x(100), y(34.5), _short(doc.object_part or "", 38), _FONT_H_2_5),
        text_svg(x(142.5), y(28.5), "Стадия", _FONT_H_2_5),
        text_svg(x(157.5), y(28.5), "Лист", _FONT_H_2_5),
        text_svg(x(175), y(28.5), "Листов", _FONT_H_2_5),
        text_svg(x(142.5), y(37.3), doc.stage_label or "П", _FONT_H_3_5),
        text_svg(x(157.5), y(37.3), str(sheet_no), _FONT_H_3_5),
        text_svg(x(175), y(37.3), str(sheet_total), _FONT_H_3_5),
        text_svg(x(100), y(47), _short(title, 48), _FONT_H_2_5),
        text_svg(x(100), y(53), system_label, _FONT_H_3_5),
        text_svg(x(160), y(49), _short(doc.organization or "", 28), _FONT_H_2_5),
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
        errors.extend(
            validate_wastewater_building_system_isolation(self.project_inputs)
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
            f'<g data-building-pipe-line="{escape(line_id)}" '
            f'data-building-system="{escape(system)}"{extra_attributes}>',
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


def _revision_on_break_svg(
    *,
    revision_key: str,
    floor_no: int,
    x: float,
    y: float,
    floor_height_m: float,
    label_suffix: str = "",
) -> str:
    """Show a registered revision on an omitted run without inventing a floor."""
    placement = resolve_riser_revision_placement(
        floor_height_m=floor_height_m,
        requested_height_m=None,
    )
    height_mm = int(round(placement.height_above_clean_floor_m * 1000))
    suffix = f"; {label_suffix}" if label_suffix else ""
    return "".join((
        f'<g data-building-revision="{escape(revision_key)}" '
        'data-revision-on-break="true" '
        f'data-revision-floor="{floor_no}" '
        'data-floor-reference="clean-floor" '
        f'data-height-above-floor-mm="{height_mm}" '
        f'data-height-source="{escape(placement.source)}" '
        f'data-height-rule="{REVISION_PLACEMENT_RULE_ID}">',
        render_ugo("revision", x, y, scale=0.72, rotation=90.0),
        f'<text x="{x+24:.1f}" y="{y-7:.1f}" '
        f'font-family="{FONT}" font-size="11" font-weight="bold">Р · '
        f'эт. {floor_no}{escape(suffix)}</text>',
        '</g>',
    ))


def _floor_origins(floors: tuple[int, ...]) -> dict[int, float]:
    presets = {
        1: (760.0,),
        2: (480.0, 1110.0),
        3: (315.0, 900.0, 1250.0),
    }
    if len(floors) not in presets:
        raise ValueError("combined A1 sheet supports up to three characteristic floors")
    return dict(zip(floors, presets[len(floors)]))


def _fmt_level(value: float) -> str:
    """Format an architectural level mark in the GOST section style."""
    if abs(value) < 0.0005:
        return "±0,000"
    sign = "+" if value > 0 else "-"
    return f"{sign}{_fmt(abs(value))}"


def _building_level_mark_svg(
    *,
    marker_id: str,
    y: float,
    elevation_m: float,
    caption: str,
    wall_x: float,
    line_start_x: float = 88.0,
) -> str:
    """Draw an elevation/storey mark terminating at the building contour."""
    text_x = (line_start_x + wall_x - 18.0) / 2
    return "".join((
        f'<g data-building-level-mark="{escape(marker_id)}" '
        'data-level-reference="clean-floor">',
        f'<line x1="{line_start_x:.1f}" y1="{y:.1f}" '
        f'x2="{wall_x-11.0:.1f}" y2="{y:.1f}" stroke="{BLACK}" '
        f'stroke-width="{_LINE_THIN:.3f}"/>',
        f'<path d="M{wall_x-19.0:.1f},{y-8.0:.1f} '
        f'L{wall_x-3.0:.1f},{y:.1f} L{wall_x-19.0:.1f},{y+8.0:.1f}" '
        f'fill="none" stroke="{BLACK}" stroke-width="{_LINE_THIN:.3f}"/>',
        f'<text x="{text_x:.1f}" y="{y-10.0:.1f}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="{_FONT_H_3_5:.3f}">'
        f'{_fmt_level(elevation_m)}</text>',
        f'<text x="{text_x:.1f}" y="{y+19.0:.1f}" text-anchor="middle" '
        f'font-family="{FONT}" font-size="{_FONT_H_2_5:.3f}">'
        f'{escape(caption)}</text>',
        '</g>',
    ))


def _building_storey_svg(
    *,
    floor_no: int,
    origin_y: float,
    elevation_m: float,
    wall_left: float,
    wall_right: float,
    k2_axes: tuple[tuple[str, float], ...],
) -> str:
    """Draw one confirmed storey cell behind the engineering topology."""
    storey_top = origin_y + 20.0
    slab_y = origin_y + 228.0
    rows = [
        f'<g data-building-storey="{floor_no}" data-floor-no="{floor_no}">',
        f'<rect data-architecture="storey-contour" x="{wall_left:.1f}" '
        f'y="{storey_top:.1f}" width="{wall_right-wall_left:.1f}" '
        f'height="{slab_y-storey_top:.1f}" fill="none" stroke="{BLACK}" '
        f'stroke-width="{_LINE_THIN:.3f}"/>',
    ]
    for riser_id, axis_x in k2_axes:
        shaft_left = max(wall_left, axis_x - 28.0)
        shaft_right = min(wall_right, axis_x + 28.0)
        rows.append(
            f'<rect data-building-shaft="{escape(riser_id)}" '
            f'data-building-shaft-system="K2" data-floor-no="{floor_no}" '
            f'x="{shaft_left:.1f}" y="{storey_top:.1f}" '
            f'width="{shaft_right-shaft_left:.1f}" '
            f'height="{slab_y-storey_top:.1f}" fill="none" stroke="{BLACK}" '
            f'stroke-width="{_LINE_THIN:.3f}"/>'
        )
    rows.extend((
        f'<rect data-building-slab="{floor_no}" '
        f'data-building-floor="{floor_no}" x="{wall_left:.1f}" '
        f'y="{slab_y:.1f}" width="{wall_right-wall_left:.1f}" height="10" '
        'fill="url(#building-slab-hatch)" stroke="black" '
        f'stroke-width="{_LINE_THIN:.3f}"/>',
        _building_level_mark_svg(
            marker_id=f"floor-{floor_no}",
            y=slab_y,
            elevation_m=elevation_m,
            caption=f"{floor_no} этаж",
            wall_x=wall_left,
        ),
        '</g>',
    ))
    return "".join(rows)


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
    riser_axis_by_id: dict[str, float] | None = None,
) -> str:
    """Render the shared roof and characteristic-floor sheet."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid building assembly: " + "; ".join(errors))
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
    k1_ids = tuple(stack.riser_id for stack in selected_k1)
    k2_ids = tuple(riser.riser_id for riser in selected_k2)
    axis_register = riser_axis_by_id or _riser_axis_register(
        k1_ids=k1_ids,
        k2_ids=k2_ids,
    )
    if set(axis_register) != set(k1_ids + k2_ids):
        raise ValueError("floor fragment riser-axis register is incomplete")
    scale = 1.0
    roof_y = 220.0
    bottom_y = 1660.0
    wall_left, wall_right = 230.0, 2440.0
    roof_elevation_m = assembly.project_inputs.floors_above * assembly.floor_height_m
    k2_architecture_axes = tuple(
        (riser.riser_id, axis_register[riser.riser_id]) for riser in selected_k2
    )
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_SHEET_WIDTH_MM:g}mm" height="{_SHEET_HEIGHT_MM:g}mm" '
        f'viewBox="0 0 {_SHEET_WIDTH:.3f} {_SHEET_HEIGHT:.3f}" '
        'data-sheet-format="A1" data-sheet-units="mm" '
        f'data-units-per-mm="{_SHEET_SCALE:.6f}" data-schematic-scale="not-to-scale" '
        'data-font-standard="GOST-2.304-81" data-font-type="B" '
        f'data-sheet-role="floors" '
        f'data-fragment-index="{fragment_index}" '
        f'data-fragment-total="{fragment_total}">',
        '<defs><pattern id="building-slab-hatch" width="16" height="16" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="16" stroke="#8a8a8a" '
        'stroke-width="1"/></pattern></defs>',
        f'<rect width="{_SHEET_WIDTH:.3f}" height="{_SHEET_HEIGHT:.3f}" fill="white"/>',
        f'<rect data-drawing-frame="GOST-R-21.101" '
        f'data-left-margin-mm="20" data-other-margin-mm="5" '
        f'x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="{_LINE_MAIN:.3f}"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        f'font-size="{_FONT_H_7:.3f}">Принципиальная схема внутренних систем '
        'канализации и водоотведения. Надземная часть</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="{_FONT_H_3_5:.3f}" fill="{GRAY}">Этажей: {assembly.project_inputs.floors_above}; '
        f'фрагмент {fragment_index}/{fragment_total}; характерные этажи; '
        'самотечная К1 и внутренний водосток К2; схема без масштаба</text>',
        f'<rect data-building-roof-boundary="true" data-architecture="roof-slab" '
        f'x="{wall_left:.1f}" y="{roof_y-5.0:.1f}" '
        f'width="{wall_right-wall_left:.1f}" height="10" '
        'fill="url(#building-slab-hatch)" stroke="black" '
        f'stroke-width="{_LINE_THIN:.3f}"/>',
        f'<line data-building-envelope="left" x1="{wall_left:.1f}" '
        f'y1="{roof_y:.1f}" x2="{wall_left:.1f}" y2="{bottom_y-130:.1f}" '
        f'stroke="{BLACK}" stroke-width="{_LINE_MAIN:.3f}"/>',
        f'<line data-building-envelope="right" x1="{wall_right:.1f}" '
        f'y1="{roof_y:.1f}" x2="{wall_right:.1f}" y2="{bottom_y-130:.1f}" '
        f'stroke="{BLACK}" stroke-width="{_LINE_MAIN:.3f}"/>',
        _building_level_mark_svg(
            marker_id="roof",
            y=roof_y,
            elevation_m=roof_elevation_m,
            caption="кровля",
            wall_x=wall_left,
        ),
    ]

    for floor_no, origin_y in origins.items():
        elevation = (floor_no - 1) * assembly.floor_height_m
        body.append(
            _building_storey_svg(
                floor_no=floor_no,
                origin_y=origin_y,
                elevation_m=elevation,
                wall_left=wall_left,
                wall_right=wall_right,
                k2_axes=k2_architecture_axes,
            )
        )

    for stack in selected_k1:
        local_riser_x = stack.floor(floors[0]).port("riser_join").point.x_mm
        riser_x = axis_register[stack.riser_id]
        origin_x = riser_x - local_riser_x
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
                omitted_revisions = tuple(
                    floor_no
                    for floor_no in stack.revision_floors
                    if lower < floor_no < upper
                )
                if omitted_revisions:
                    # Registered revisions on collapsed typical floors remain
                    # visible and are spread along the omitted run.
                    available_top = upper_bottom + 42.0
                    available_bottom = lower_top - 42.0
                    step = (
                        (available_bottom - available_top)
                        / (len(omitted_revisions) - 1)
                        if len(omitted_revisions) > 1
                        else 0.0
                    )
                    for revision_index, revision_floor in enumerate(
                        sorted(omitted_revisions, reverse=True)
                    ):
                        revision_y = (
                            (upper_bottom + lower_top) / 2
                            if len(omitted_revisions) == 1
                            else available_top + step * revision_index
                        )
                        body.append(
                            _revision_on_break_svg(
                                revision_key=f"{stack.riser_id}-{revision_floor}",
                                floor_no=revision_floor,
                                x=riser_x,
                                y=revision_y,
                                floor_height_m=assembly.floor_height_m,
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
                extra_attributes=(
                    f' data-riser-axis-id="{escape(stack.riser_id)}" '
                    f'data-riser-axis-x="{riser_x:.1f}"'
                ),
            )
        )
        body.append(
            # Каждый стояк ссылается на тот подвальный фрагмент, где показан
            # его нижний узел; при одном фрагменте это обычный лист 2.
            f'<text data-continuation-riser="{escape(stack.riser_id)}" '
            f'data-riser-axis-x="{riser_x:.1f}" '
            f'data-target-sheet="{(basement_sheet_by_riser_id or {}).get(stack.riser_id, basement_first_sheet_no)}" '
            f'x="{riser_x+20:.1f}" y="{bottom_y-12:.1f}" '
            f'font-family="{FONT}" font-size="13">{escape(stack.riser_id)}; '
            f'продолжение на листе '
            f'{(basement_sheet_by_riser_id or {}).get(stack.riser_id, basement_first_sheet_no)}</text>'
        )

    first_origin = origins[floors[0]]
    for riser in selected_k2:
        x = axis_register[riser.riser_id]
        body.append(
            _line_with_label(
                line_id=f"{riser.riser_id}-roof-to-basement",
                system="K2",
                dn_mm=riser.riser_dn_mm,
                start=(x, roof_y),
                end=(x, bottom_y),
                position=0.64,
                extra_attributes=(
                    f' data-riser-axis-id="{escape(riser.riser_id)}" '
                    f'data-riser-axis-x="{x:.1f}"'
                ),
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
            f'data-riser-axis-x="{x:.1f}" '
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
            f'data-transition-fill="none" data-flat-side="downstream" '
            f'data-apex-side="upstream">',
            f'<path d="M{x-12:.1f},{y:.1f} L{x+12:.1f},{y-10:.1f} '
            f'L{x+12:.1f},{y+10:.1f} Z" fill="white" stroke="white" '
            'stroke-width="4"/>',
            f'<path data-diameter-transition="{escape(element_id)}" '
            f'd="M{x-12:.1f},{y:.1f} L{x+12:.1f},{y-10:.1f} '
            f'L{x+12:.1f},{y+10:.1f} Z" fill="none" stroke="{BLACK}" '
            'stroke-width="1.7"/>',
            f'<text x="{x:.1f}" y="{y-18:.1f}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11">DN{upstream_dn}×{downstream_dn}</text>',
            "</g>",
        )
    )


def _direct_transition_svg(
    *,
    element_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
    upstream_dn: int,
    downstream_dn: int,
    placement: str,
    adjacent_node_id: str,
) -> str:
    """Draw a reducer directly against the adjacent junction fitting.

    A diameter increase on an incoming main ends at the junction coordinate.
    Its flat side faces the larger downstream diameter; its apex faces the
    smaller upstream diameter.  No graphic pipe spool is left between the
    transition and the adjacent fitting.
    """
    from math import hypot

    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    if length <= 1e-9:
        raise ValueError(f"{element_id}: transition segment has zero length")
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    depth = min(24.0, length)
    half_width = 10.0
    if placement == "upstream-before-junction":
        base_x, base_y = end
        apex_x, apex_y = end[0] - ux * depth, end[1] - uy * depth
    elif placement == "downstream-after-terminal-turn":
        apex_x, apex_y = start
        base_x, base_y = start[0] + ux * depth, start[1] + uy * depth
    else:
        raise ValueError(f"{element_id}: unsupported transition placement {placement}")
    triangle = (
        f"M{base_x+px*half_width:.1f},{base_y+py*half_width:.1f} "
        f"L{apex_x:.1f},{apex_y:.1f} "
        f"L{base_x-px*half_width:.1f},{base_y-py*half_width:.1f} Z"
    )
    label_x = (base_x + apex_x) / 2 + px * 20.0
    label_y = (base_y + apex_y) / 2 + py * 20.0
    return "".join(
        (
            f'<g data-building-transition="{escape(element_id)}" '
            f'data-upstream-dn="{upstream_dn}" data-downstream-dn="{downstream_dn}" '
            f'data-transition-placement="{escape(placement)}" '
            f'data-transition-shape="open-triangle" data-transition-fill="none" '
            f'data-flat-side="downstream" data-apex-side="upstream" '
            f'data-transition-joint="direct" '
            f'data-adjacent-node="{escape(adjacent_node_id)}" '
            'data-fitting-gap-mm="0">',
            f'<path d="{triangle}" fill="white" stroke="white" stroke-width="4"/>',
            f'<path data-diameter-transition="{escape(element_id)}" '
            f'd="{triangle}" fill="none" stroke="{BLACK}" stroke-width="1.7"/>',
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="middle" '
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
        f'<rect data-drawing-frame="GOST-R-21.101" '
        f'data-left-margin-mm="20" data-other-margin-mm="5" '
        f'x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
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
    floor_height_m: float,
    previous_sheet_no: int | None,
    next_sheet_no: int | None,
    riser_axis_by_id: dict[str, float],
) -> None:
    """Draw one paginated fragment of a confirmed linear system chain."""
    fragment = risers[start_index:end_index]
    if not fragment:
        return
    riser_ids = tuple(_riser_id(row) for row in fragment)
    try:
        xs = tuple(riser_axis_by_id[row] for row in riser_ids)
    except KeyError as exc:
        raise ValueError(f"missing basement riser axis for {exc.args[0]}") from exc
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
        f'<g data-basement-system="{escape(system)}" '
        'data-system-isolated="true">'
    )
    body.append(
        f'<text x="{wall_left+45:.1f}" y="{base_y-205:.1f}" '
        f'font-family="{FONT}" font-size="20" font-weight="bold">'
        f'{_system_mark(system)} · {range_label}</text>'
    )

    def first_floor_revision_reference(
        row: BuildingK1RiserProjectInput | BuildingK2RiserProjectInput,
    ) -> tuple[str, int] | None:
        if isinstance(row, BuildingK1RiserProjectInput):
            if 1 not in row.revision_floors:
                return None
            placement = resolve_riser_revision_placement(
                floor_height_m=floor_height_m,
                requested_height_m=None,
            )
            return f"{row.stack.riser_id}-1", int(
                round(placement.height_above_clean_floor_m * 1000)
            )
        revision = next(
            (revision for revision in row.revisions if revision.floor_no == 1),
            None,
        )
        if revision is None:
            return None
        return revision.element_id, int(round(revision.elevation_m * 1000))

    def wall_sleeve_svg(
        *,
        section_id: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> str:
        if not (start[0] < wall_right < end[0]):
            return ""
        ratio = (wall_right - start[0]) / (end[0] - start[0])
        sleeve_y = start[1] + (end[1] - start[1]) * ratio
        wall_width = 55.0
        outer_x = wall_right + wall_width
        outer_y = sleeve_y + (end[1] - start[1]) * (
            wall_width / (end[0] - start[0])
        )
        return "".join((
            f'<g data-wall-sleeve="{escape(section_id)}" '
            'data-sleeve-scope="foundation-crossing">',
            f'<rect x="{wall_right-8:.1f}" y="{sleeve_y-15:.1f}" '
            f'width="{wall_width+16:.1f}" height="30" fill="white" '
            f'stroke="{BLACK}" stroke-width="1.7"/>',
            f'<line x1="{wall_right-8:.1f}" y1="{sleeve_y:.1f}" '
            f'x2="{outer_x+8:.1f}" y2="{outer_y:.1f}" '
            f'stroke="{BLACK}" stroke-width="4"/>',
            f'<path d="M{wall_right+wall_width/2:.1f},{sleeve_y-16:.1f} '
            f'V{sleeve_y-52:.1f} H{wall_right-26:.1f}" fill="none" '
            f'stroke="{BLACK}" stroke-width="1.2"/>',
            f'<text x="{wall_right-34:.1f}" y="{sleeve_y-58:.1f}" '
            f'text-anchor="end" font-family="{FONT}" font-size="12">'
            'Гильза в фундаментной стене; по узлу КР/ИОС3</text>',
            '</g>',
        ))

    incoming_stub: tuple[tuple[float, float], tuple[float, float]] | None = None
    if start_index > 0:
        incoming = collectors[start_index - 1]
        end = joins[0]
        # A continued K1 collector enters inside the dedicated K1 lane band;
        # starting it at the left building wall would cross the independent K2
        # risers shown on the same fragment.
        incoming_x = (
            max(wall_left + 78.0, min(xs) - 260.0)
            if system == "K1"
            else wall_left + 78.0
        )
        start = (incoming_x, end[1] - 5.0)
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
                line_id=f"{riser_id}-basement-riser",
                system=system,
                dn_mm=dn,
                start=(x, first_floor_y),
                end=(x, turn_origin_y),
                position=0.52,
                extra_attributes=(
                    f' data-riser-axis-id="{escape(riser_id)}" '
                    f'data-riser-axis-x="{x:.1f}"'
                ),
            )
        )
        revision_reference = first_floor_revision_reference(riser)
        if revision_reference is not None:
            revision_id, revision_height_mm = revision_reference
            reference_offset_y = 42.0 if system == "K1" else 72.0
            body.append(
                f'<g data-basement-revision-reference="{escape(revision_id)}" '
                f'data-height-above-floor-mm="{revision_height_mm}">'
                f'<path d="M{x:.1f},{first_floor_y+12:.1f} '
                f'H{x+28:.1f} V{first_floor_y+reference_offset_y:.1f}" fill="none" '
                f'stroke="{BLACK}" stroke-width="1.1"/>'
                f'<text x="{x+36:.1f}" y="{first_floor_y+reference_offset_y+6:.1f}" '
                f'font-family="{FONT}" font-size="12">Ревизия на 1 этаже '
                f'+{revision_height_mm} — см. лист 1</text></g>'
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
            elbow_ids = ", ".join(riser.lower_elbow_element_ids)
            cleanout_target_x = x + 12.0 * turn_scale
            cleanout_target_y = main_y
            body.append(
                f'<g data-lower-node-callout="{escape(cleanout_id)}" '
                f'data-callout-target-id="{escape(cleanout_id)}" '
                f'data-callout-target-kind="cleanout-cap" '
                f'data-callout-target-x="{cleanout_target_x:.1f}" '
                f'data-callout-target-y="{cleanout_target_y:.1f}">'
                f'<path d="M{cleanout_target_x:.1f},{cleanout_target_y:.1f} '
                f'L{x+82:.1f},{main_y-96:.1f} H{x+345:.1f}" '
                f'fill="none" stroke="{BLACK}" stroke-width="{_LINE_THIN:.3f}"/>'
                f'<text x="{x+336:.1f}" y="{main_y-105:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="{_FONT_H_3_5:.3f}">'
                f'Прочистка {escape(cleanout_id)} DN{dn}</text>'
                f'<text x="{x+336:.1f}" y="{main_y-72:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="{_FONT_H_2_5:.3f}">'
                f'косой тройник 45° с заглушкой, DN{dn}; '
                'свободный соосный конец</text>'
                f'<text data-lower-elbow-reference="{escape(elbow_ids)}" '
                f'x="{x+336:.1f}" y="{main_y-49:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="{_FONT_H_2_5:.3f}">Отвод 45° DN{dn}: '
                f'{escape(elbow_ids)}</text></g>'
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
                f'data-through-axis="open" data-main-dn="{outgoing.dn_mm}" '
                f'data-branch-dn="{dn}">'
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
            elbow_ids = ", ".join(riser.lower_elbow_element_ids)
            junction_target_x = x + turn_offset_x
            junction_target_y = main_y
            junction_dn = (
                f"DN{outgoing.dn_mm}×{dn}"
                if outgoing.dn_mm != dn
                else f"DN{dn}"
            )
            body.append(
                f'<g data-lower-node-callout="{escape(junction_id)}" '
                f'data-callout-target-id="{escape(junction_id)}" '
                f'data-callout-target-kind="through-wye" '
                f'data-callout-target-x="{junction_target_x:.1f}" '
                f'data-callout-target-y="{junction_target_y:.1f}">'
                f'<path d="M{junction_target_x:.1f},{junction_target_y:.1f} '
                f'L{x+74:.1f},{main_y+48:.1f} H{x-155:.1f}" '
                f'fill="none" stroke="{BLACK}" stroke-width="{_LINE_THIN:.3f}"/>'
                f'<text x="{x+65:.1f}" y="{main_y+39:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="{_FONT_H_3_5:.3f}">'
                f'Проточный узел {escape(junction_id)}</text>'
                f'<text x="{x+65:.1f}" y="{main_y+72:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="{_FONT_H_2_5:.3f}">'
                f'косой тройник {junction_dn}, 45°; '
                'проходная ось открыта, без заглушки</text>'
                f'<text data-lower-elbow-reference="{escape(elbow_ids)}" '
                f'x="{x+65:.1f}" y="{main_y+95:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="{_FONT_H_2_5:.3f}">'
                f'Отвод 45° DN{dn}: '
                f'{escape(elbow_ids)}</text></g>'
            )

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
        if global_index == len(risers) - 1:
            body.append(
                wall_sleeve_svg(
                    section_id=outlet.section_id,
                    start=outgoing_start,
                    end=outgoing_end,
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
            else:
                transition_start, transition_end = outgoing_start, outgoing_end
            body.append(
                _direct_transition_svg(
                    element_id=transition.element_id,
                    start=transition_start,
                    end=transition_end,
                    upstream_dn=transition.upstream_dn_mm,
                    downstream_dn=transition.downstream_dn_mm,
                    placement=transition.placement,
                    adjacent_node_id=riser_id,
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
    body.append('</g>')


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
    riser_axis_by_id: dict[str, float] | None = None,
) -> str:
    """Render one A1 fragment of the complete lower-node chain."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid building assembly: " + "; ".join(errors))
    inputs = assembly.project_inputs
    assert inputs.k1_outlet is not None
    assert inputs.k2_outlet is not None
    margin = 50
    first_floor_y = 260.0
    basement_floor_y = 1560.0
    wall_left, wall_right = 230.0, 2440.0
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_SHEET_WIDTH_MM:g}mm" height="{_SHEET_HEIGHT_MM:g}mm" '
        f'viewBox="0 0 {_SHEET_WIDTH:.3f} {_SHEET_HEIGHT:.3f}" '
        'data-sheet-format="A1" data-sheet-units="mm" '
        f'data-units-per-mm="{_SHEET_SCALE:.6f}" data-schematic-scale="not-to-scale" '
        'data-font-standard="GOST-2.304-81" data-font-type="B" '
        f'data-sheet-role="basement" '
        f'data-fragment-index="{fragment_index}" '
        f'data-fragment-total="{fragment_total}">',
        '<defs><pattern id="basement-hatch" width="22" height="22" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(35)">'
        '<line x1="0" y1="0" x2="0" y2="22" stroke="#777" stroke-width="2"/>'
        '</pattern></defs>',
        f'<rect width="{_SHEET_WIDTH:.3f}" height="{_SHEET_HEIGHT:.3f}" fill="white"/>',
        f'<rect data-drawing-frame="GOST-R-21.101" '
        f'data-left-margin-mm="20" data-other-margin-mm="5" '
        f'x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="{_LINE_MAIN:.3f}"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        f'font-size="{_FONT_H_7:.3f}">Принципиальная схема внутренних систем '
        'канализации и водоотведения. Подвал и выпуски</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="{_FONT_H_3_5:.3f}" fill="{GRAY}">Фрагмент {fragment_index}/{fragment_total}; '
        'подтверждённая линейная топология реестра; схема без масштаба</text>',
        f'<rect data-building-slab="first-floor" '
        f'data-architecture="first-floor-slab" x="{wall_left}" '
        f'y="{first_floor_y-5.0:.1f}" width="{wall_right-wall_left}" height="10" '
        'fill="url(#basement-hatch)" stroke="black" '
        f'stroke-width="{_LINE_THIN:.3f}"/>',
        f'<rect data-building-storey="basement" data-architecture="basement-contour" '
        f'x="{wall_left}" y="{first_floor_y+5.0:.1f}" '
        f'width="{wall_right-wall_left}" '
        f'height="{basement_floor_y-first_floor_y-5.0:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="{_LINE_MAIN:.3f}"/>',
        _building_level_mark_svg(
            marker_id="floor-1",
            y=first_floor_y,
            elevation_m=0.0,
            caption="1 этаж",
            wall_x=wall_left,
        ),
        f'<rect data-architecture="basement-slab" x="{wall_left}" '
        f'y="{basement_floor_y}" width="{wall_right-wall_left}" height="82" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-left" x="{wall_left-55}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-right" x="{wall_right}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        _building_level_mark_svg(
            marker_id="basement-floor",
            y=basement_floor_y,
            elevation_m=float(inputs.basement_floor_elevation_m or 0),
            caption="пол подвала",
            wall_x=wall_left,
        ),
        f'<text x="{wall_left+24:.1f}" y="{first_floor_y+42:.1f}" '
        f'font-family="{FONT}" font-size="{_FONT_H_3_5:.3f}">Подвал</text>',
        f'<text x="{wall_right+82}" y="{first_floor_y+35}" font-family="{FONT}" '
        f'font-size="{_FONT_H_2_5:.3f}">наружная грань здания</text>',
    ]
    previous_sheet_no = sheet_no - 1 if fragment_index > 1 else None
    next_sheet_no = sheet_no + 1 if fragment_index < fragment_total else None
    selected_k1_ids = tuple(
        row.stack.riser_id for row in inputs.k1_risers[k1_start_index:k1_end_index]
    )
    selected_k2_ids = tuple(
        row.riser_id for row in inputs.k2_risers[k2_start_index:k2_end_index]
    )
    axis_register = riser_axis_by_id or _riser_axis_register(
        k1_ids=selected_k1_ids,
        k2_ids=selected_k2_ids,
    )
    if set(axis_register) != set(selected_k1_ids + selected_k2_ids):
        raise ValueError("basement fragment riser-axis register is incomplete")
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
        floor_height_m=assembly.floor_height_m,
        previous_sheet_no=previous_sheet_no,
        next_sheet_no=next_sheet_no,
        riser_axis_by_id=axis_register,
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
        floor_height_m=assembly.floor_height_m,
        previous_sheet_no=previous_sheet_no,
        next_sheet_no=next_sheet_no,
        riser_axis_by_id=axis_register,
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


def build_confirmed_architecture_basement_svgs(
    assembly: WastewaterBuildingAssembly,
    *,
    riser_axis_ratio_by_id: dict[str, float],
    first_sheet_no: int = 2,
    sheet_total: int | None = None,
) -> tuple[str, ...]:
    """Render lower K1/K2 sheets on axes confirmed by the AR section.

    K1 and K2 are intentionally placed on separate sheets.  Actual confirmed
    axes may alternate across the building; combining both systems on one
    schematic section would create false-looking intersections.  The lower
    topology, fittings, cleanouts, transitions and outlets still come only
    from the checked project register.
    """
    errors = assembly.validate()
    if errors:
        raise ValueError(
            "cannot render confirmed-architecture basement: "
            + "; ".join(errors)
        )
    k1_ids = tuple(row.stack.riser_id for row in assembly.project_inputs.k1_risers)
    k2_ids = tuple(row.riser_id for row in assembly.project_inputs.k2_risers)
    expected_ids = set(k1_ids + k2_ids)
    if set(riser_axis_ratio_by_id) != expected_ids:
        missing = sorted(expected_ids - set(riser_axis_ratio_by_id))
        extra = sorted(set(riser_axis_ratio_by_id) - expected_ids)
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if extra:
            detail.append("unexpected: " + ", ".join(extra))
        raise ValueError("confirmed riser-axis register is incomplete (" + "; ".join(detail) + ")")
    for riser_id, ratio in riser_axis_ratio_by_id.items():
        if not isfinite(ratio) or not 0.0 <= ratio <= 1.0:
            raise ValueError(
                f"{riser_id}: confirmed riser-axis ratio must be within 0..1"
            )

    wall_left, wall_right = 230.0, 2440.0

    def page_axes(ids: tuple[str, ...]) -> dict[str, float]:
        return {
            riser_id: wall_left + (wall_right - wall_left) * riser_axis_ratio_by_id[riser_id]
            for riser_id in ids
        }

    k1_chunks = _chunks(assembly.project_inputs.k1_risers, _BASEMENT_RISER_PAGE_CAPACITY)
    k2_chunks = _chunks(assembly.project_inputs.k2_risers, _BASEMENT_RISER_PAGE_CAPACITY)
    page_count = len(k1_chunks) + len(k2_chunks)
    resolved_sheet_total = sheet_total or (first_sheet_no - 1 + page_count)
    pages: list[str] = []
    sheet_no = first_sheet_no
    for chunk_index, chunk in enumerate(k1_chunks):
        start = chunk_index * _BASEMENT_RISER_PAGE_CAPACITY
        end = start + len(chunk)
        ids = tuple(row.stack.riser_id for row in chunk)
        pages.append(build_wastewater_building_basement_fragment_svg(
            assembly,
            k1_start_index=start,
            k1_end_index=end,
            k2_start_index=0,
            k2_end_index=0,
            sheet_no=sheet_no,
            sheet_total=resolved_sheet_total,
            fragment_index=chunk_index + 1,
            fragment_total=len(k1_chunks),
            riser_axis_by_id=page_axes(ids),
        ))
        sheet_no += 1
    for chunk_index, chunk in enumerate(k2_chunks):
        start = chunk_index * _BASEMENT_RISER_PAGE_CAPACITY
        end = start + len(chunk)
        ids = tuple(row.riser_id for row in chunk)
        pages.append(build_wastewater_building_basement_fragment_svg(
            assembly,
            k1_start_index=0,
            k1_end_index=0,
            k2_start_index=start,
            k2_end_index=end,
            sheet_no=sheet_no,
            sheet_total=resolved_sheet_total,
            fragment_index=chunk_index + 1,
            fragment_total=len(k2_chunks),
            riser_axis_by_id=page_axes(ids),
        ))
        sheet_no += 1
    return tuple(pages)


def audit_confirmed_architecture_basement_svgs(
    assembly: WastewaterBuildingAssembly,
    svgs: tuple[str, ...],
    *,
    riser_axis_ratio_by_id: dict[str, float],
) -> tuple[str, ...]:
    """Check that AR axes and every registered lower element reached the PDF."""
    findings: list[str] = []
    try:
        roots = tuple(ElementTree.fromstring(svg) for svg in svgs)
    except ElementTree.ParseError as exc:
        return (f"confirmed basement SVG is invalid: {exc}",)
    expected_systems = {
        system
        for system, rows in (
            ("K1", assembly.project_inputs.k1_risers),
            ("K2", assembly.project_inputs.k2_risers),
        )
        if rows
    }
    drawn_systems: set[str] = set()
    drawn_axes: dict[str, float] = {}
    for root in roots:
        page_systems = {
            row.get("data-basement-system")
            for row in root.iter()
            if row.get("data-basement-system")
        }
        if len(page_systems) > 1:
            findings.append("confirmed basement sheet mixes K1 and K2")
        drawn_systems.update(str(row) for row in page_systems)
        for row in root.iter():
            riser_id = row.get("data-riser-axis-id")
            axis_x = row.get("data-riser-axis-x")
            if riser_id and axis_x is not None:
                drawn_axes[riser_id] = float(axis_x)
    if drawn_systems != expected_systems:
        findings.append("confirmed basement sheets do not cover all K1/K2 systems")

    wall_left, wall_right = 230.0, 2440.0
    expected_axes = {
        riser_id: wall_left + (wall_right - wall_left) * ratio
        for riser_id, ratio in riser_axis_ratio_by_id.items()
    }
    if set(drawn_axes) != set(expected_axes):
        findings.append("confirmed basement riser-axis register is incomplete")
    for riser_id in sorted(set(drawn_axes) & set(expected_axes)):
        if abs(drawn_axes[riser_id] - expected_axes[riser_id]) > 0.05:
            findings.append(f"{riser_id}: basement axis differs from confirmed AR axis")

    def drawn(attribute: str) -> set[str]:
        return {
            str(row.get(attribute))
            for root in roots
            for row in root.iter()
            if row.get(attribute)
        }

    inputs = assembly.project_inputs
    expected_cleanouts = {
        element_id
        for row in inputs.k1_risers + inputs.k2_risers
        for element_id in row.lower_cleanout_element_ids
    }
    expected_junctions = {
        element_id
        for row in inputs.k1_risers + inputs.k2_risers
        for element_id in row.lower_junction_element_ids
    }
    expected_transitions = {
        row.element_id for row in inputs.k1_transitions + inputs.k2_transitions
    }
    expected_outlets = {
        row.section_id for row in (inputs.k1_outlet, inputs.k2_outlet) if row
    }
    if drawn("data-basement-cleanout") != expected_cleanouts:
        findings.append("confirmed basement cleanouts differ from project register")
    if drawn("data-basement-through-junction") != expected_junctions:
        findings.append("confirmed basement through junctions differ from project register")
    if drawn("data-building-transition") != expected_transitions:
        findings.append("confirmed basement transitions differ from project register")
    if drawn("data-wall-sleeve") != expected_outlets:
        findings.append("confirmed basement outlet sleeves differ from project register")
    return tuple(dict.fromkeys(findings))


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
    if floor_page_count != basement_page_count:
        raise ValueError(
            "above-ground and basement pagination must use the same riser batches"
        )
    riser_axis_registers = tuple(
        _riser_axis_register(
            k1_ids=tuple(
                stack.riser_id
                for stack in (
                    k1_floor_chunks[index]
                    if index < len(k1_floor_chunks)
                    else ()
                )
            ),
            k2_ids=tuple(
                riser.riser_id
                for riser in (
                    k2_floor_chunks[index]
                    if index < len(k2_floor_chunks)
                    else ()
                )
            ),
        )
        for index in range(floor_page_count)
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
                riser_axis_by_id=riser_axis_registers[index],
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
                riser_axis_by_id=riser_axis_registers[index],
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

    expected_storeys = {str(row) for row in assembly.displayed_floor_numbers}
    expected_level_marks = {"roof"} | {
        f"floor-{row}" for row in assembly.displayed_floor_numbers
    }
    for page_no, root in enumerate(floor_roots, start=1):
        storeys = {
            row.get("data-building-storey")
            for row in root.iter()
            if row.get("data-building-storey")
        }
        slabs = {
            row.get("data-building-slab")
            for row in root.iter()
            if row.get("data-building-slab")
        }
        level_marks = {
            row.get("data-building-level-mark")
            for row in root.iter()
            if row.get("data-building-level-mark")
        }
        envelope_sides = {
            row.get("data-building-envelope")
            for row in root.iter()
            if row.get("data-building-envelope")
        }
        roof_boundaries = [
            row for row in root.iter()
            if row.get("data-building-roof-boundary") == "true"
        ]
        if storeys != expected_storeys:
            findings.append(
                f"sheet {page_no}: architectural storey boundaries are incomplete"
            )
        if slabs != expected_storeys:
            findings.append(
                f"sheet {page_no}: floor slab boundaries are incomplete"
            )
        if level_marks != expected_level_marks:
            findings.append(
                f"sheet {page_no}: storey/elevation marks are incomplete"
            )
        if envelope_sides != {"left", "right"}:
            findings.append(
                f"sheet {page_no}: building envelope boundaries are incomplete"
            )
        if len(roof_boundaries) != 1:
            findings.append(
                f"sheet {page_no}: roof boundary is missing or duplicated"
            )
    for fragment_no, root in enumerate(basement_roots, start=1):
        storeys = {
            row.get("data-building-storey")
            for row in root.iter()
            if row.get("data-building-storey")
        }
        slabs = {
            row.get("data-building-slab")
            for row in root.iter()
            if row.get("data-building-slab")
        }
        level_marks = {
            row.get("data-building-level-mark")
            for row in root.iter()
            if row.get("data-building-level-mark")
        }
        if "basement" not in storeys or "first-floor" not in slabs:
            findings.append(
                f"basement fragment {fragment_no}: architectural boundaries are incomplete"
            )
        if not {"floor-1", "basement-floor"}.issubset(level_marks):
            findings.append(
                f"basement fragment {fragment_no}: elevation marks are incomplete"
            )

    expected_sheet_total = str(len(roots) + 1)
    for page_no, root in enumerate(roots, start=1):
        visible_text = " ".join(root.itertext())
        if (
            root.get("width") != f"{_SHEET_WIDTH_MM:g}mm"
            or root.get("height") != f"{_SHEET_HEIGHT_MM:g}mm"
            or root.get("viewBox")
            != f"0 0 {_SHEET_WIDTH:.3f} {_SHEET_HEIGHT:.3f}"
            or root.get("data-sheet-format") != "A1"
            or root.get("data-schematic-scale") != "not-to-scale"
        ):
            findings.append(
                f"sheet {page_no}: A1 physical page geometry is not canonical"
            )
        frames = [
            row for row in root.iter()
            if row.get("data-drawing-frame") == "GOST-R-21.101"
        ]
        if len(frames) != 1 or (
            frames[0].get("data-left-margin-mm") != "20"
            or frames[0].get("data-other-margin-mm") != "5"
        ):
            findings.append(
                f"sheet {page_no}: drawing frame margins are not canonical"
            )
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

    def axis_register(
        page_roots: tuple[ElementTree.Element, ...],
        role: str,
    ) -> dict[str, float]:
        result: dict[str, float] = {}
        for root in page_roots:
            for row in root.iter():
                riser_id = row.get("data-riser-axis-id")
                axis_x = row.get("data-riser-axis-x")
                if not riser_id or axis_x is None:
                    continue
                value = float(axis_x)
                if riser_id in result and abs(result[riser_id] - value) > 0.05:
                    findings.append(
                        f"{role}: riser {riser_id} is drawn on multiple axes"
                    )
                result[riser_id] = value
        return result

    floor_axes = axis_register(floor_roots, "above-ground")
    basement_axes = axis_register(basement_roots, "basement")
    if set(floor_axes) != set(basement_axes):
        findings.append("above-ground and basement riser axis registers differ")
    for riser_id in sorted(set(floor_axes) & set(basement_axes)):
        if abs(floor_axes[riser_id] - basement_axes[riser_id]) > 0.05:
            findings.append(
                f"riser {riser_id}: above-ground and basement axes do not match"
            )

    for root in basement_roots:
        system_groups = {
            row.get("data-basement-system"): row.get("data-system-isolated")
            for row in root.iter()
            if row.get("data-basement-system")
        }
        if system_groups and system_groups != {"K1": "true", "K2": "true"}:
            findings.append("basement: K1 and K2 are not isolated drawing groups")

        segments: list[tuple[str, str, tuple[float, float], tuple[float, float]]] = []
        for group in root.iter():
            line_id = group.get("data-building-pipe-line")
            if not line_id:
                continue
            system = group.get("data-building-system", "")
            if system not in {"K1", "K2"}:
                findings.append(
                    f"basement: pipe line {line_id} has no K1/K2 ownership"
                )
                continue
            line = next(
                (child for child in group if child.tag.endswith("line")),
                None,
            )
            if line is None:
                continue
            segments.append((
                system,
                line_id,
                (float(line.get("x1", "0")), float(line.get("y1", "0"))),
                (float(line.get("x2", "0")), float(line.get("y2", "0"))),
            ))

        def intersects(
            first: tuple[tuple[float, float], tuple[float, float]],
            second: tuple[tuple[float, float], tuple[float, float]],
        ) -> bool:
            (a, b), (c, d) = first, second

            def cross(
                p: tuple[float, float],
                q: tuple[float, float],
                r: tuple[float, float],
            ) -> float:
                return (q[0] - p[0]) * (r[1] - p[1]) - (
                    q[1] - p[1]
                ) * (r[0] - p[0])

            def side(value: float) -> int:
                return 1 if value > 0.05 else -1 if value < -0.05 else 0

            return (
                side(cross(a, b, c)) * side(cross(a, b, d)) <= 0
                and side(cross(c, d, a)) * side(cross(c, d, b)) <= 0
                and max(min(a[0], b[0]), min(c[0], d[0]))
                <= min(max(a[0], b[0]), max(c[0], d[0])) + 0.05
                and max(min(a[1], b[1]), min(c[1], d[1]))
                <= min(max(a[1], b[1]), max(c[1], d[1])) + 0.05
            )

        for index, (system, line_id, start, end) in enumerate(segments):
            for other_system, other_id, other_start, other_end in segments[index + 1:]:
                if system == other_system:
                    continue
                if intersects((start, end), (other_start, other_end)):
                    findings.append(
                        f"basement: {line_id} ({system}) intersects "
                        f"{other_id} ({other_system}); K1/K2 must stay separate"
                    )

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
    drawn_k1_floor_revisions = {
        row.get("data-building-revision")
        for root in floor_roots
        for row in root.iter()
        if row.get("data-building-revision", "").startswith("К1")
    }
    expected_k1_floor_revisions = {
        f"{riser.stack.riser_id}-{floor_no}"
        for riser in assembly.project_inputs.k1_risers
        for floor_no in riser.revision_floors
    }
    if drawn_k1_floor_revisions != expected_k1_floor_revisions:
        findings.append("sheet 1: K1 revisions differ from project registry")
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

    sleeve_ids = {
        row.get("data-wall-sleeve")
        for root in basement_roots
        for row in root.iter()
        if row.get("data-wall-sleeve")
    }
    expected_sleeve_ids = {
        row.section_id
        for row in (
            assembly.project_inputs.k1_outlet,
            assembly.project_inputs.k2_outlet,
        )
        if row is not None
    }
    if sleeve_ids != expected_sleeve_ids:
        findings.append("sheet 2: foundation sleeves differ from building outlets")

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
    expected_transitions = {
        row.element_id: row
        for row in (
            assembly.project_inputs.k1_transitions
            + assembly.project_inputs.k2_transitions
        )
    }
    for root in basement_roots:
        for group in root.iter():
            transition_id = group.get("data-building-transition")
            if not transition_id:
                continue
            expected = expected_transitions.get(transition_id)
            if expected is None:
                continue
            if (
                group.get("data-transition-joint") != "direct"
                or group.get("data-fitting-gap-mm") != "0"
                or group.get("data-adjacent-node") != expected.node_id
                or group.get("data-flat-side") != "downstream"
                or group.get("data-apex-side") != "upstream"
            ):
                findings.append(
                    f"basement: transition {transition_id} must directly adjoin "
                    f"junction {expected.node_id} with zero pipe gap and face "
                    "its flat side toward the larger downstream diameter"
                )

    for root in basement_roots:
        for group in root.iter():
            callout_id = group.get("data-lower-node-callout")
            if not callout_id:
                continue
            target_x = group.get("data-callout-target-x")
            target_y = group.get("data-callout-target-y")
            path = next(
                (row for row in group if row.tag.endswith("path")),
                None,
            )
            if (
                not target_x
                or not target_y
                or path is None
                or not (path.get("d") or "").startswith(f"M{target_x},{target_y}")
            ):
                findings.append(
                    f"basement: callout {callout_id} is not anchored to its element"
                )

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
    ensure_drafting_font_registered()
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

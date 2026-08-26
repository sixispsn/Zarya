"""Registry-driven combined building schematic for internal K1 and K2.

The drawing composes the accepted K1 floor modules on one architectural
storey grid and adds only the K2 topology explicitly declared by the project
register.  It intentionally does not invent K2 revisions, cleanouts, fitting
arrangements, floor coordinates or external sewer runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from app.pz.project import Project
from app.pz.wastewater_drafting import (
    BLACK,
    FONT,
    GRAY,
    render_inline_pipe_label,
)
from app.pz.wastewater_floor_drafting import render_typical_floor_assembly_svg
from app.pz.wastewater_project_inputs import (
    BuildingPipeProjectInput,
    WastewaterBuildingProjectInputs,
    resolve_wastewater_building_project_inputs,
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


@dataclass(frozen=True)
class WastewaterBuildingAssembly:
    project_inputs: WastewaterBuildingProjectInputs
    k1_stacks: tuple[WastewaterStackAssembly, ...]
    floor_height_m: float
    roof_kind: str

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
        if len(self.k1_stacks) > 2:
            errors.append("current A1 building sheet supports at most two K1 stacks")
        if len(self.project_inputs.k2_risers) > 2:
            errors.append("current A1 building sheet supports at most two K2 stacks")
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
        return list(dict.fromkeys(errors))


def build_wastewater_building_assembly(
    project_inputs: WastewaterBuildingProjectInputs,
    *,
    floor_height_m: float,
    roof_kind: str,
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
    dimension: bool,
) -> str:
    revision_y = slab_y - 82.0
    body = [
        f'<g data-building-revision="{escape(riser_id)}-{floor_no}">',
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
                f'font-family="{FONT}" font-size="10">1000</text>',
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
) -> str:
    """Render the shared roof and characteristic-floor sheet."""
    errors = assembly.validate()
    if errors:
        raise ValueError("cannot render invalid building assembly: " + "; ".join(errors))
    width, height = 2800, 1980
    margin = 50
    floors = assembly.displayed_floor_numbers
    origins = _floor_origins(floors)
    k1_origins_x = (90.0, 880.0)
    k2_xs = (2110.0, 2400.0)
    scale = 1.0
    roof_y = 220.0
    bottom_y = 1775.0
    body: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        'viewBox="0 0 2800 1980">',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Принципиальная схема систем К1 и К2. Надземная часть</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">Этажей: {assembly.project_inputs.floors_above}; '
        'характерные этажи; самотечная К1 и внутренний водосток К2</text>',
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

    for stack_index, stack in enumerate(assembly.k1_stacks):
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
            f'<text x="{riser_x+20:.1f}" y="{bottom_y-12:.1f}" '
            f'font-family="{FONT}" font-size="13">{escape(stack.riser_id)}; '
            'продолжение на листе 2</text>'
        )

    first_origin = origins[floors[0]]
    last_origin = origins[floors[-1]]
    for index, riser in enumerate(assembly.project_inputs.k2_risers):
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
        body.append(
            f'<text x="{x+20:.1f}" y="{bottom_y-12:.1f}" '
            f'font-family="{FONT}" font-size="13">{escape(riser.riser_id)}; '
            'продолжение на листе 2</text>'
        )

    body.extend(
        (
            f'<line x1="{margin+30}" y1="{bottom_y+45:.1f}" '
            f'x2="{width-margin-30}" y2="{bottom_y+45:.1f}" stroke="#777"/>',
            f'<text x="{margin+38}" y="{bottom_y+78:.1f}" font-family="{FONT}" '
            'font-size="13">Все показанные приборы и количества получены из реестра проекта. '
            'К2 не соединяется с К1.</text>',
            f'<text x="{margin+38}" y="{height-margin-24}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Графический язык — приложение В '
            'ГОСТ Р 21.620-2023; контрольная сборка генератора.</text>',
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
    arm_x = apex_x - 11.0 * direction
    value = _fmt(value_per_mille / 1000.0)
    anchor = "end" if direction > 0 else "start"
    text_x = arm_x - 6.0 * direction
    return "".join(
        (
            f'<g data-slope-marker="{escape(marker_id)}" data-placement="above" '
            f'data-sign-shape="open-angle" data-label-underline="false">',
            f'<path d="M{arm_x:.1f},{y-7:.1f} L{apex_x:.1f},{y:.1f} '
            f'L{arm_x:.1f},{y+7:.1f}" fill="none" stroke="{BLACK}" '
            'stroke-width="1.5"/>',
            f'<text x="{text_x:.1f}" y="{y+4:.1f}" text-anchor="{anchor}" '
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
) -> str:
    return "".join(
        (
            f'<g data-building-transition="{escape(element_id)}" '
            f'data-upstream-dn="{upstream_dn}" data-downstream-dn="{downstream_dn}">',
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


def build_wastewater_building_basement_svg(
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
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" '
        f'height="{height-2*margin}" fill="none" stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Принципиальная схема систем К1 и К2. Подвал и выпуски</text>',
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

    k1_turn_ends = ((750.0, 900.0), (1170.0, 940.0))
    for index, riser in enumerate(inputs.k1_risers):
        x = k1_xs[index]
        turn_start = (x, 790.0 + index * 20.0)
        mid = (
            x + (50.0 if index == 0 else -35.0),
            turn_start[1] + 55.0,
        )
        end = k1_turn_ends[index]
        riser_id = riser.stack.riser_id
        dn = int(riser.stack.riser_dn_mm or 0)
        body.append(
            _line_with_label(
                line_id=f"{riser_id}-basement-riser",
                system="K1",
                dn_mm=dn,
                start=(x, first_floor_y),
                end=turn_start,
                position=0.55,
            )
        )
        body.extend(
            (
                f'<line data-lower-turn="{escape(riser_id)}-elbow-1" '
                f'x1="{turn_start[0]:.1f}" y1="{turn_start[1]:.1f}" '
                f'x2="{mid[0]:.1f}" y2="{mid[1]:.1f}" stroke="{BLACK}" '
                'stroke-width="4"/>',
                _fitting_boundary(
                    fitting_id=f"{riser_id}-elbow-45-1",
                    start=turn_start,
                    end=mid,
                    position=0.68,
                ),
                f'<line data-lower-turn="{escape(riser_id)}-elbow-2" '
                f'x1="{mid[0]:.1f}" y1="{mid[1]:.1f}" '
                f'x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="{BLACK}" '
                'stroke-width="4"/>',
                _fitting_boundary(
                    fitting_id=f"{riser_id}-elbow-45-2",
                    start=mid,
                    end=end,
                    position=0.34,
                ),
                f'<text x="{x+18:.1f}" y="{turn_start[1]-20:.1f}" '
                f'font-family="{FONT}" font-size="12">2 отвода 45°; '
                f'{escape(riser.lower_elbow_element_ids[0])}</text>',
            )
        )

    k1_collector_start, k1_collector_end = k1_turn_ends
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
            x=1350.0,
            y=953.0,
            upstream_dn=k1_collector.dn_mm,
            downstream_dn=k1_outlet.dn_mm,
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

    k2_join_1 = (1830.0, 1200.0)
    k2_join_2 = (2160.0, 1240.0)
    for index, riser in enumerate(inputs.k2_risers):
        x = k2_xs[index]
        end = k2_join_1 if index == 0 else k2_join_2
        body.append(
            _line_with_label(
                line_id=f"{riser.riser_id}-basement-riser",
                system="K2",
                dn_mm=riser.riser_dn_mm,
                start=(x, first_floor_y),
                end=(x, end[1] - 65.0),
                position=0.53,
            )
        )
        body.append(
            f'<line data-topology-only-node="{escape(riser.riser_id)}" '
            f'x1="{x:.1f}" y1="{end[1]-65.0:.1f}" x2="{end[0]:.1f}" '
            f'y2="{end[1]:.1f}" stroke="{BLACK}" stroke-width="4"/>'
        )
        body.append(
            f'<circle data-topology-status="fitting-not-declared" '
            f'cx="{end[0]:.1f}" cy="{end[1]:.1f}" r="9" fill="white" '
            f'stroke="{BLACK}" stroke-width="1.5" stroke-dasharray="4 3"/>'
        )

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
            f'<rect x="{margin+35}" y="{1680}" width="{width-2*margin-70}" '
            'height="155" fill="white" stroke="#777" stroke-width="1"/>',
            f'<text x="{margin+58}" y="1715" font-family="{FONT}" '
            'font-size="14" font-weight="bold">Граница детализации</text>',
            f'<text x="{margin+58}" y="1745" font-family="{FONT}" '
            'font-size="12">К1: два нижних поворота показаны по явным строкам реестра — по 2 отвода 45°.</text>',
            f'<text x="{margin+58}" y="1770" font-family="{FONT}" '
            'font-size="12">К2: пунктирные окружности — подтверждённые топологические узлы без выдуманной конфигурации фасонных частей.</text>',
            f'<text x="{margin+58}" y="1795" font-family="{FONT}" '
            'font-size="12">Ревизии и прочистки К2 не показаны: соответствующие элементы отсутствуют в реестре проекта.</text>',
            f'<text x="{margin+38}" y="{height-margin-24}" font-family="{FONT}" '
            f'font-size="12" fill="{GRAY}">Графический язык — приложение В '
            'ГОСТ Р 21.620-2023; выпуск заканчивается за наружной гранью здания.</text>',
            "</svg>",
        )
    )
    return "".join(body)


def build_wastewater_building_svgs(
    assembly: WastewaterBuildingAssembly,
) -> tuple[str, str]:
    return (
        build_wastewater_building_floors_svg(assembly),
        build_wastewater_building_basement_svg(assembly),
    )


def audit_wastewater_building_svgs(
    assembly: WastewaterBuildingAssembly,
    svgs: tuple[str, str],
) -> tuple[str, ...]:
    """Fail-fast graphic audit for the combined two-sheet assembly."""
    findings: list[str] = []
    try:
        floors_root, basement_root = (
            ElementTree.fromstring(svg) for svg in svgs
        )
    except ElementTree.ParseError as exc:
        return (f"combined sheet SVG is invalid: {exc}",)

    for page_no, root in enumerate((floors_root, basement_root), start=1):
        visible_text = " ".join(root.itertext())
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
        for row in floors_root.iter()
        if row.get("data-floor-assembly")
    }
    for stack in assembly.k1_stacks:
        for floor_no in assembly.displayed_floor_numbers:
            expected = f"{stack.riser_id}-Сборка-Этаж-{floor_no:02d}"
            if expected not in floor_assembly_ids:
                findings.append(f"sheet 1: missing floor assembly {expected}")

    for row in floors_root.iter():
        revision_id = row.get("data-building-revision", "")
        if revision_id.startswith("К2"):
            findings.append("sheet 1: undeclared K2 revision was drawn")
    if any(row.get("data-basement-cleanout") for row in basement_root.iter()):
        findings.append("sheet 2: undeclared basement cleanout was drawn")

    basement_line_ids = {
        row.get("data-building-pipe-line")
        for row in basement_root.iter()
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

    right_wall = next(
        (
            row
            for row in basement_root.iter()
            if row.get("data-architecture") == "foundation-right"
        ),
        None,
    )
    wall_x = float(right_wall.get("x", "inf")) if right_wall is not None else float("inf")
    for outlet in (
        assembly.project_inputs.k1_outlet,
        assembly.project_inputs.k2_outlet,
    ):
        if outlet is None:
            continue
        group = next(
            (
                row
                for row in basement_root.iter()
                if row.get("data-building-pipe-line") == outlet.section_id
            ),
            None,
        )
        line = next(
            (row for row in group.iter() if row.tag.endswith("line")),
            None,
        ) if group is not None else None
        if line is None or float(line.get("x2", "-inf")) <= wall_x:
            findings.append(
                f"sheet 2: outlet {outlet.section_id} does not cross the building face"
            )
    return tuple(dict.fromkeys(findings))


def generate_wastewater_building_pdf_from_project(
    output_path: str,
    project: Project,
    *,
    floor_height_m: float,
    roof_kind: str,
) -> str:
    """Write the combined registry-backed two-sheet vector PDF."""
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    inputs = resolve_wastewater_building_project_inputs(project)
    assembly = build_wastewater_building_assembly(
        inputs,
        floor_height_m=floor_height_m,
        roof_kind=roof_kind,
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

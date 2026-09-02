"""Registry-driven A1 drafting for the separate gravity K3 system."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from app.pz.project import DocumentInfo, Project, SewerElementSpec
from app.pz.wastewater_building_drafting import (
    _FRAME_BOTTOM,
    _FRAME_LEFT,
    _FRAME_RIGHT,
    _FRAME_TOP,
    _break_overlay,
    _line_with_label,
    _slope_sign_svg,
    _title_block_svg,
    _transition_svg,
)
from app.pz.wastewater_drafting import (
    BLACK,
    FONT,
    GRAY,
    build_lower_turn_cleanout_assembly,
    build_lower_turn_through_junction_assembly,
    render_lower_turn_assembly_svg,
)
from app.pz.wastewater_k3_project_inputs import (
    K3BranchProjectInput,
    K3RiserProjectInput,
    WastewaterK3ProjectInputs,
    resolve_wastewater_k3_project_inputs,
)
from app.pz.wastewater_revision_placement import (
    REVISION_PLACEMENT_RULE_ID,
    resolve_riser_revision_placement,
    revision_y_from_clean_floor,
)
from app.pz.wastewater_ugo import (
    fixture_trap_mode,
    get_ugo_connection_anchor,
    render_ugo,
)


_FLOOR_PAGE_RISER_CAPACITY = 2
_FLOOR_PAGE_LEVEL_CAPACITY = 3
_BASEMENT_PAGE_RISER_CAPACITY = 4


def _chunks(values: tuple, size: int) -> tuple[tuple, ...]:
    return tuple(values[index:index + size] for index in range(0, len(values), size))


def _fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _short(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _floor_origins(floors: tuple[int, ...]) -> dict[int, float]:
    presets = {
        1: (690.0,),
        2: (390.0, 1020.0),
        3: (270.0, 760.0, 1210.0),
    }
    try:
        values = presets[len(floors)]
    except KeyError as exc:
        raise ValueError("K3 floor fragment supports one to three levels") from exc
    return dict(zip(floors, values))


def _riser_positions(count: int) -> tuple[float, ...]:
    if count == 1:
        return (1510.0,)
    if count == 2:
        return (1020.0, 2260.0)
    raise ValueError("K3 floor fragment supports up to two risers")


def _element_map(project: Project) -> dict[str, SewerElementSpec]:
    return {
        row.element_id: row
        for row in project.sewage.elements
        if row.system.strip().upper() == "K3" and row.element_id
    }


def _fixture_symbol_svg(
    element: SewerElementSpec,
    *,
    x: float,
    outlet_y: float,
) -> tuple[str, tuple[float, float]]:
    scale = 0.82
    try:
        anchor_x, anchor_y = get_ugo_connection_anchor(element.kind)
    except KeyError:
        anchor_x, anchor_y = 0.0, 18.0
    symbol_x = x - anchor_x * scale
    symbol_y = outlet_y - anchor_y * scale
    return render_ugo(element.kind, symbol_x, symbol_y, scale=scale), (x, outlet_y)


def _branch_svg(
    branch: K3BranchProjectInput,
    *,
    floor_no: int,
    x1: float,
    riser_x: float,
    y: float,
    row_index: int,
) -> str:
    """Draw one explicit fixture/equipment chain and its registered joint."""
    source = branch.elements[0]
    dn = branch.pipe.dn_mm
    source_x = x1 + 92.0
    elbow_x = riser_x - 52.0
    main_end_y = y + max(
        2.0,
        min(7.0, (elbow_x - source_x) * float(branch.pipe.slope_per_mille or 0) / 1000.0),
    )
    junction_y = main_end_y + 31.0
    main_start = (source_x, y)
    main_end = (elbow_x, main_end_y)
    room = " · ".join(
        value for value in (branch.room_number, branch.room_name) if value
    )
    rows = [
        f'<g data-k3-branch="{escape(branch.pipe.section_id)}" '
        f'data-k3-floor="{floor_no}" data-k3-riser="{escape(branch.riser_id)}">',
        f'<rect x="{x1+24:.1f}" y="{y-106:.1f}" '
        f'width="{riser_x-x1-92:.1f}" height="128" fill="white" '
        'stroke="#aaa" stroke-width="1"/>',
        f'<text x="{x1+38:.1f}" y="{y-84:.1f}" font-family="{FONT}" '
        f'font-size="12" font-weight="bold">{escape(_short(room, 62))}</text>',
        _line_with_label(
            line_id=f"{branch.pipe.section_id}-floor-{floor_no}-{row_index}",
            system="K3",
            dn_mm=dn,
            start=main_start,
            end=main_end,
            position=0.63,
            stroke_width=3.2,
            font_size=12.0,
            extra_attributes=(
                f' data-source-section="{escape(branch.pipe.section_id)}"'
            ),
        ),
        _slope_sign_svg(
            marker_id=f"{branch.pipe.section_id}-slope-{floor_no}-{row_index}",
            value_per_mille=float(branch.pipe.slope_per_mille or 0),
            start=main_start,
            end=main_end,
            position=0.34,
        ),
    ]

    fixture_outlet_y = y - 46.0
    symbol, fixture_outlet = _fixture_symbol_svg(
        source,
        x=source_x,
        outlet_y=fixture_outlet_y,
    )
    rows.append(
        f'<g data-k3-source-element="{escape(source.element_id)}">{symbol}'
    )
    if fixture_trap_mode(source.kind) == "external":
        trap_y = y - 25.0
        rows.extend((
            f'<line x1="{fixture_outlet[0]:.1f}" y1="{fixture_outlet[1]:.1f}" '
            f'x2="{fixture_outlet[0]:.1f}" y2="{trap_y-12:.1f}" '
            f'stroke="{BLACK}" stroke-width="2.2"/>',
            render_ugo("trap", fixture_outlet[0], trap_y, scale=0.48),
            f'<line x1="{fixture_outlet[0]:.1f}" y1="{trap_y+12:.1f}" '
            f'x2="{source_x:.1f}" y2="{y:.1f}" stroke="{BLACK}" '
            'stroke-width="2.2"/>',
        ))
    else:
        rows.append(
            f'<line x1="{fixture_outlet[0]:.1f}" y1="{fixture_outlet[1]:.1f}" '
            f'x2="{source_x:.1f}" y2="{y:.1f}" stroke="{BLACK}" '
            'stroke-width="2.2"/>'
        )
    rows.extend((
        f'<text x="{source_x+28:.1f}" y="{y-56:.1f}" font-family="{FONT}" '
        f'font-size="10">{escape(_short(source.name, 34))}; '
        f'{source.typical_quantity or source.quantity} шт.; DN{source.dn_mm or dn}</text>',
        '</g>',
    ))

    inline_equipment = [
        row for row in branch.elements[1:] if row.kind == "grease_trap"
    ]
    for index, equipment in enumerate(inline_equipment, start=1):
        fraction = 0.42 + (index - 1) * 0.16
        equipment_x = source_x + (elbow_x - source_x) * fraction
        equipment_y = y + (main_end_y - y) * fraction
        rows.extend((
            f'<g data-k3-treatment-element="{escape(equipment.element_id)}">',
            render_ugo("grease_trap", equipment_x, equipment_y, scale=0.72),
            f'<text x="{equipment_x:.1f}" y="{equipment_y-31:.1f}" '
            f'text-anchor="middle" font-family="{FONT}" font-size="10" '
            f'font-weight="bold">{escape(_short(equipment.name, 32))}</text>',
            f'<text x="{equipment_x:.1f}" y="{equipment_y+42:.1f}" '
            f'text-anchor="middle" font-family="{FONT}" font-size="9">'
            f'{escape(_short(equipment.type_mark or "тип по проекту", 28))}</text>',
            '</g>',
        ))

    # The last 45° elbow and the oblique riser junction are not decorative:
    # both IDs come from the project register and their fitting boundaries are
    # shown by short perpendicular ticks.
    rows.extend((
        f'<g data-k3-branch-elbow="{escape(branch.connection_elbow_element_id)}" '
        f'data-k3-branch-junction="{escape(branch.connection_junction_element_id)}">',
        f'<line x1="{elbow_x:.1f}" y1="{main_end_y:.1f}" '
        f'x2="{riser_x:.1f}" y2="{junction_y:.1f}" stroke="{BLACK}" '
        'stroke-width="3.2"/>',
        f'<line x1="{elbow_x-5:.1f}" y1="{main_end_y-6:.1f}" '
        f'x2="{elbow_x+5:.1f}" y2="{main_end_y+6:.1f}" '
        f'stroke="{BLACK}" stroke-width="1.6"/>',
        f'<line x1="{riser_x-7:.1f}" y1="{junction_y-7:.1f}" '
        f'x2="{riser_x+7:.1f}" y2="{junction_y+7:.1f}" '
        f'stroke="{BLACK}" stroke-width="1.6"/>',
        '</g>',
        '<path d="M0,0"/>',
        '</g>',
    ))
    return "".join(rows)


def _revision_svg(
    element: SewerElementSpec,
    *,
    x: float,
    slab_y: float,
    floor_height_m: float,
) -> str:
    requested = element.elevation_m
    placement = resolve_riser_revision_placement(
        floor_height_m=floor_height_m,
        requested_height_m=requested,
    )
    revision_y = revision_y_from_clean_floor(
        clean_floor_y=slab_y,
        graphic_floor_height=228.0,
        real_floor_height_m=floor_height_m,
        placement=placement,
    )
    height_mm = int(round(placement.height_above_clean_floor_m * 1000))
    return "".join((
        f'<g data-k3-revision="{escape(element.element_id)}" '
        f'data-floor-reference="clean-floor" '
        f'data-height-above-floor-mm="{height_mm}" '
        f'data-height-rule="{REVISION_PLACEMENT_RULE_ID}">',
        render_ugo("revision", x, revision_y, scale=0.72, rotation=90),
        f'<text x="{x+24:.1f}" y="{revision_y-8:.1f}" '
        f'font-family="{FONT}" font-size="10" font-weight="bold">Р</text>',
        f'<line x1="{x+54:.1f}" y1="{revision_y:.1f}" '
        f'x2="{x+54:.1f}" y2="{slab_y:.1f}" stroke="{BLACK}" '
        'stroke-width="1"/>',
        f'<text x="{x+66:.1f}" y="{(revision_y+slab_y)/2+4:.1f}" '
        f'font-family="{FONT}" font-size="10">{height_mm}</text>',
        '</g>',
    ))


def build_wastewater_k3_floor_fragment_svg(
    project: Project,
    inputs: WastewaterK3ProjectInputs,
    *,
    risers: tuple[K3RiserProjectInput, ...],
    floors: tuple[int, ...],
    sheet_no: int,
    sheet_total: int,
    fragment_index: int,
    fragment_total: int,
    basement_sheet_by_riser_id: dict[str, int],
) -> str:
    if not inputs.complete:
        raise ValueError("cannot render incomplete K3 project inputs")
    origins = _floor_origins(floors)
    riser_xs = _riser_positions(len(risers))
    width = 2800
    margin = 50
    roof_y = 190.0
    continuation_y = 1635.0
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        f'viewBox="0 0 2800 1980" data-sheet-role="k3-floors" '
        f'data-fragment-index="{fragment_index}" data-fragment-total="{fragment_total}">',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        f'<text x="{margin+38}" y="{margin+50}" font-family="{FONT}" '
        'font-size="30" font-weight="bold">Принципиальная схема '
        'производственной канализации К3. Надземная часть</text>',
        f'<text x="{margin+38}" y="{margin+84}" font-family="{FONT}" '
        f'font-size="16" fill="{GRAY}">Фрагмент {fragment_index}/{fragment_total}; '
        'только подтверждённые приёмники, оборудование, фасонные части и связи</text>',
        f'<line data-architecture="roof" x1="{margin+30}" y1="{roof_y}" '
        f'x2="{width-margin-30}" y2="{roof_y}" stroke="#777" stroke-width="2"/>',
        f'<text x="{margin+38}" y="{roof_y-16}" font-family="{FONT}" '
        'font-size="14" font-weight="bold">Кровля / верхняя граница листа</text>',
    ]
    for floor_no, origin_y in origins.items():
        slab_y = origin_y + 228.0
        elevation = (floor_no - 1) * float(inputs.floor_height_m or 0)
        body.extend((
            f'<line data-k3-floor-level="{floor_no}" x1="{margin+30}" '
            f'y1="{slab_y:.1f}" x2="{width-margin-30}" y2="{slab_y:.1f}" '
            'stroke="#999" stroke-width="1.2"/>',
            f'<text x="{margin+38}" y="{slab_y-27:.1f}" font-family="{FONT}" '
            f'font-size="14" font-weight="bold">{floor_no} этаж</text>',
            f'<text x="{margin+38}" y="{slab_y-9:.1f}" font-family="{FONT}" '
            f'font-size="11">отм. {_fmt(elevation)}</text>',
        ))

    element_by_id = _element_map(project)
    for riser, riser_x in zip(risers, riser_xs):
        body.append(
            _line_with_label(
                line_id=f"{riser.riser_id}-fragment-{fragment_index}",
                system="K3",
                dn_mm=riser.riser_dn_mm,
                start=(riser_x, roof_y),
                end=(riser_x, continuation_y),
                position=0.54,
                stroke_width=4.0,
                font_size=13.0,
                extra_attributes=f' data-source-section="{escape(riser.riser_id)}"',
            )
        )
        if "вент" in riser.pipe.from_node.casefold():
            body.extend((
                f'<line x1="{riser_x-14:.1f}" y1="{roof_y:.1f}" '
                f'x2="{riser_x+14:.1f}" y2="{roof_y:.1f}" '
                f'stroke="{BLACK}" stroke-width="2"/>',
                f'<text x="{riser_x+25:.1f}" y="{roof_y-25:.1f}" '
                f'font-family="{FONT}" font-size="11">{escape(riser.pipe.from_node)}</text>',
            ))
        for floor_no, origin_y in origins.items():
            applicable = [
                row for row in riser.branches if row.applies_to_floor(floor_no)
            ]
            slab_y = origin_y + 228.0
            for row_index, branch in enumerate(applicable[:3]):
                branch_y = slab_y - 42.0 - row_index * 64.0
                body.append(_branch_svg(
                    branch,
                    floor_no=floor_no,
                    x1=riser_x - 930.0,
                    riser_x=riser_x,
                    y=branch_y,
                    row_index=row_index,
                ))
            if len(applicable) > 3:
                raise ValueError(
                    f"{riser.riser_id}, этаж {floor_no}: more than three K3 branches"
                )
            for revision in riser.revision_elements:
                if revision.floor_from == floor_no:
                    body.append(_revision_svg(
                        revision,
                        x=riser_x,
                        slab_y=slab_y,
                        floor_height_m=float(inputs.floor_height_m or 0),
                    ))
            for collar_id in riser.fire_collar_element_ids:
                collar = element_by_id.get(collar_id)
                if collar is None:
                    continue
                floor_to = collar.floor_to or collar.floor_from
                if collar.floor_from <= floor_no <= floor_to:
                    body.append(
                        f'<g data-k3-fire-collar="{escape(collar_id)}">'
                        + render_ugo("fire_collar", riser_x, slab_y, scale=0.56, rotation=90)
                        + '</g>'
                    )
        for upper, lower in zip(floors, floors[1:]):
            if upper - lower > 1:
                upper_bottom = origins[upper] + 250.0
                lower_top = origins[lower] + 8.0
                body.append(_break_overlay(
                    break_id=f"{riser.riser_id}-{upper}-{lower}",
                    x=riser_x,
                    y=(upper_bottom + lower_top) / 2,
                    label=f"этажи {lower+1}-{upper-1} не показаны",
                ))
        target_sheet = basement_sheet_by_riser_id[riser.riser_id]
        body.append(
            f'<text data-k3-continuation-riser="{escape(riser.riser_id)}" '
            f'data-target-sheet="{target_sheet}" x="{riser_x+22:.1f}" '
            f'y="{continuation_y-12:.1f}" font-family="{FONT}" font-size="12">'
            f'{escape(riser.riser_id)}; продолжение на листе {target_sheet}</text>'
        )

    body.extend((
        f'<line x1="{margin+30}" y1="1692" x2="{_FRAME_RIGHT-650:.1f}" '
        'y2="1692" stroke="#777"/>',
        f'<text x="{margin+38}" y="1730" font-family="{FONT}" font-size="12">'
        'К3 показана самостоятельной системой; подключение к бытовой канализации автоматически не выполняется.</text>',
        f'<text x="{margin+38}" y="1760" font-family="{FONT}" font-size="11" '
        f'fill="{GRAY}">Графический язык — приложение В ГОСТ Р 21.620-2023; '
        'положение помещений композиционное до подтверждения подложки АР.</text>',
        _title_block_svg(
            project.document,
            sheet_no=sheet_no,
            sheet_total=sheet_total,
            title=(
                "Принципиальная схема К3. Надземная часть"
                if fragment_total == 1
                else f"К3. Надземная часть. Фрагмент {fragment_index}"
            ),
            system_label="К3",
        ),
        '</svg>',
    ))
    return "".join(body)


def _transition_for_node(inputs: WastewaterK3ProjectInputs, node_id: str, section_id: str):
    node_key = " ".join(node_id.strip().casefold().split())
    section_key = " ".join(section_id.strip().casefold().split())
    return next((
        row for row in inputs.transitions
        if " ".join(row.node_id.strip().casefold().split()) == node_key
        and " ".join(row.section_id.strip().casefold().split()) == section_key
    ), None)


def build_wastewater_k3_basement_fragment_svg(
    project: Project,
    inputs: WastewaterK3ProjectInputs,
    *,
    start_index: int,
    end_index: int,
    sheet_no: int,
    sheet_total: int,
    fragment_index: int,
    fragment_total: int,
    previous_sheet_no: int | None,
    next_sheet_no: int | None,
) -> str:
    if not inputs.complete or inputs.outlet is None:
        raise ValueError("cannot render incomplete K3 basement inputs")
    fragment = inputs.risers[start_index:end_index]
    count = len(fragment)
    if not fragment:
        raise ValueError("empty K3 basement fragment")
    if count == 1:
        xs = (720.0,)
    else:
        step = 1500.0 / (count - 1)
        xs = tuple(430.0 + index * step for index in range(count))
    base_y = 980.0
    first_floor_y = 300.0
    basement_floor_y = 1540.0
    wall_left, wall_right = 230.0, 2440.0
    turn_scale = 2.0
    turn_dx, turn_dy = 76.0, 152.0
    node_ys = [base_y]
    for local_index in range(1, count):
        edge = inputs.collectors[start_index + local_index - 1]
        dx = xs[local_index] - xs[local_index - 1]
        node_ys.append(node_ys[-1] + max(
            2.0,
            min(12.0, dx * float(edge.slope_per_mille or 0) / 1000.0),
        ))
    joins = tuple((x + turn_dx, y) for x, y in zip(xs, node_ys))
    body = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
        f'viewBox="0 0 2800 1980" data-sheet-role="k3-basement" '
        f'data-fragment-index="{fragment_index}" data-fragment-total="{fragment_total}">',
        '<defs><pattern id="k3-basement-hatch" width="22" height="22" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(35)">'
        '<line x1="0" y1="0" x2="0" y2="22" stroke="#777" stroke-width="2"/>'
        '</pattern></defs>',
        '<rect width="2800" height="1980" fill="white"/>',
        f'<rect x="{_FRAME_LEFT:.1f}" y="{_FRAME_TOP:.1f}" '
        f'width="{_FRAME_RIGHT-_FRAME_LEFT:.1f}" '
        f'height="{_FRAME_BOTTOM-_FRAME_TOP:.1f}" fill="none" '
        f'stroke="{BLACK}" stroke-width="3"/>',
        '<text x="88" y="100" font-family="osifont" font-size="30" '
        'font-weight="bold">Принципиальная схема производственной канализации К3. '
        'Подвал и выпуск</text>',
        f'<text x="88" y="134" font-family="{FONT}" font-size="16" '
        f'fill="{GRAY}">Фрагмент {fragment_index}/{fragment_total}; '
        'линейная топология от стояков до подтверждённой точки сброса</text>',
        f'<line data-architecture="first-floor" x1="{wall_left}" y1="{first_floor_y}" '
        f'x2="{wall_right}" y2="{first_floor_y}" stroke="#777" stroke-width="2"/>',
        f'<text x="{wall_left-20}" y="{first_floor_y-12}" text-anchor="end" '
        f'font-family="{FONT}" font-size="12">1 этаж; отм. 0,000</text>',
        f'<rect data-architecture="basement-slab" x="{wall_left}" '
        f'y="{basement_floor_y}" width="{wall_right-wall_left}" height="82" '
        'fill="url(#k3-basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-left" x="{wall_left-55}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#k3-basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<rect data-architecture="foundation-right" x="{wall_right}" '
        f'y="{first_floor_y}" width="55" height="{basement_floor_y-first_floor_y+82}" '
        'fill="url(#k3-basement-hatch)" stroke="#777" stroke-width="1.5"/>',
        f'<text x="{wall_left-20}" y="{basement_floor_y-10}" text-anchor="end" '
        f'font-family="{FONT}" font-size="12">Пол подвала; отм. '
        f'{_fmt(float(inputs.basement_floor_elevation_m or 0))}</text>',
        f'<text x="{wall_right+80}" y="{first_floor_y+36}" '
        f'font-family="{FONT}" font-size="11">наружная грань здания</text>',
    ]

    incoming_stub = None
    if start_index > 0:
        incoming = inputs.collectors[start_index - 1]
        start = (wall_left + 80.0, joins[0][1] - 5.0)
        end = joins[0]
        incoming_stub = (start, end)
        body.extend((
            _line_with_label(
                line_id=f"{incoming.section_id}-fragment-{fragment_index}",
                system="K3",
                dn_mm=incoming.dn_mm,
                start=start,
                end=end,
                position=0.42,
                extra_attributes=f' data-source-section="{escape(incoming.section_id)}"',
            ),
            _slope_sign_svg(
                marker_id=f"{incoming.section_id}-slope-in-{start_index}",
                value_per_mille=float(incoming.slope_per_mille or 0),
                start=start,
                end=end,
                position=0.36,
            ),
            f'<text x="{start[0]:.1f}" y="{start[1]-36:.1f}" '
            f'font-family="{FONT}" font-size="11">с листа '
            f'{previous_sheet_no or "—"}</text>',
        ))

    for local_index, riser in enumerate(fragment):
        global_index = start_index + local_index
        x = xs[local_index]
        main_y = node_ys[local_index]
        turn_origin_y = main_y - turn_dy
        body.append(_line_with_label(
            line_id=f"{riser.riser_id}-basement",
            system="K3",
            dn_mm=riser.riser_dn_mm,
            start=(x, first_floor_y),
            end=(x, turn_origin_y),
            position=0.50,
            extra_attributes=f' data-source-section="{escape(riser.riser_id)}"',
        ))
        if riser.lower_cleanout_element_ids:
            cleanout_id = riser.lower_cleanout_element_ids[0]
            node = build_lower_turn_cleanout_assembly(
                assembly_id=f"{riser.riser_id}-Узел-НП",
                system="K3",
                dn_mm=riser.riser_dn_mm,
            )
            body.append(
                f'<g data-k3-basement-cleanout="{escape(cleanout_id)}" '
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
                f'<text x="{x-10:.1f}" y="{main_y-55:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="11">Прочистка '
                f'{escape(cleanout_id)}; соосно</text>'
            )
        else:
            junction_id = riser.lower_junction_element_ids[0]
            node = build_lower_turn_through_junction_assembly(
                assembly_id=f"{riser.riser_id}-Узел-НП-Проточный",
                system="K3",
                dn_mm=riser.riser_dn_mm,
            )
            body.append(
                f'<g data-k3-basement-through-junction="{escape(junction_id)}" '
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

        outgoing = (
            inputs.collectors[global_index]
            if global_index < len(inputs.collectors)
            else inputs.outlet
        )
        start = joins[local_index]
        if local_index + 1 < len(fragment):
            end = joins[local_index + 1]
        elif global_index < len(inputs.collectors):
            end = (wall_right - 70.0, start[1] + 5.0)
        else:
            run = 2670.0 - start[0]
            end = (
                2670.0,
                start[1] + max(
                    2.0,
                    min(14.0, run * float(outgoing.slope_per_mille or 0) / 1000.0),
                ),
            )
        body.extend((
            _line_with_label(
                line_id=f"{outgoing.section_id}-fragment-{fragment_index}",
                system="K3",
                dn_mm=outgoing.dn_mm,
                start=start,
                end=end,
                position=0.54,
                extra_attributes=f' data-source-section="{escape(outgoing.section_id)}"',
            ),
            _slope_sign_svg(
                marker_id=f"{outgoing.section_id}-slope-{global_index}",
                value_per_mille=float(outgoing.slope_per_mille or 0),
                start=start,
                end=end,
                position=0.55,
            ),
        ))
        transition = _transition_for_node(
            inputs, riser.riser_id, outgoing.section_id
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
                        f"{transition.element_id}: no incoming K3 graphic segment"
                    )
                fraction = 0.86
            else:
                transition_start, transition_end = start, end
                fraction = 0.18
            tx = transition_start[0] + (
                transition_end[0] - transition_start[0]
            ) * fraction
            ty = transition_start[1] + (
                transition_end[1] - transition_start[1]
            ) * fraction
            body.append(_transition_svg(
                element_id=transition.element_id,
                x=tx,
                y=ty,
                upstream_dn=transition.upstream_dn_mm,
                downstream_dn=transition.downstream_dn_mm,
                placement=transition.placement,
            ))
        if global_index < len(inputs.collectors) and local_index == count - 1:
            body.append(
                f'<text x="{end[0]-10:.1f}" y="{end[1]-55:.1f}" '
                f'text-anchor="end" font-family="{FONT}" font-size="11">'
                f'продолжение на листе {next_sheet_no or "—"}</text>'
            )
        if global_index == len(inputs.risers) - 1:
            body.extend((
                f'<path data-k3-flow-direction="{escape(inputs.outlet.section_id)}" '
                f'd="M{end[0]-28:.1f},{end[1]-12:.1f} L{end[0]:.1f},{end[1]:.1f} '
                f'L{end[0]-29:.1f},{end[1]+11:.1f} Z" fill="{BLACK}"/>',
                f'<text x="{end[0]-245:.1f}" y="{end[1]+50:.1f}" '
                f'font-family="{FONT}" font-size="12" font-weight="bold">'
                f'Выпуск {escape(inputs.outlet.section_id)} DN{inputs.outlet.dn_mm}; '
                f'к {escape(inputs.discharge_point)}</text>',
            ))

    treatment_note = (
        f"Локальная очистка: {project.sewage.treatment_type}; "
        f"{project.sewage.treatment_location}."
        if project.sewage.treatment_required
        else "Локальная очистка показана только зарегистрированным оборудованием."
    )
    body.extend((
        '<rect x="88" y="1665" width="1910" height="210" fill="white" '
        'stroke="#777" stroke-width="1"/>',
        f'<text x="112" y="1700" font-family="{FONT}" font-size="13" '
        'font-weight="bold">Данные К3</text>',
        f'<text x="112" y="1730" font-family="{FONT}" font-size="11">'
        f'Точка сброса: {escape(inputs.discharge_point)}. '
        f'{escape(_short(treatment_note, 120))}</text>',
        f'<text x="112" y="1758" font-family="{FONT}" font-size="11">'
        f'Qmax = {escape(_fmt(project.sewage.k3_max_hourly_m3h, 3) if project.sewage.k3_max_hourly_m3h is not None else "не задан")} м³/ч; '
        f'Qmin = {escape(_fmt(project.sewage.k3_min_hourly_m3h, 3) if project.sewage.k3_min_hourly_m3h is not None else "не задан")} м³/ч.</text>',
        f'<text x="112" y="1786" font-family="{FONT}" font-size="11">'
        'Заглушённая прочистка применяется только в начальном терминальном узле; '
        'проходной поток не перекрывается.</text>',
        f'<text x="112" y="1814" font-family="{FONT}" font-size="11">'
        'Напорная канализация и насосная рабочая точка в этот самотечный лист не включаются.</text>',
        _title_block_svg(
            project.document,
            sheet_no=sheet_no,
            sheet_total=sheet_total,
            title=(
                "Принципиальная схема К3. Подвал и выпуск"
                if fragment_total == 1
                else f"К3. Подвал и выпуск. Фрагмент {fragment_index}"
            ),
            system_label="К3",
        ),
        '</svg>',
    ))
    return "".join(body)


def build_wastewater_k3_svgs(
    project: Project,
    inputs: WastewaterK3ProjectInputs,
) -> tuple[str, ...]:
    """Build all A1 K3 fragments with stable cross-sheet references."""
    if not inputs.complete:
        detail = "; ".join(inputs.diagnostics) or "неполные данные К3"
        raise ValueError("cannot render K3 scheme: " + detail)
    floors = inputs.characteristic_floors
    if not floors:
        raise ValueError("K3 scheme has no confirmed floor levels")
    riser_chunks = _chunks(inputs.risers, _FLOOR_PAGE_RISER_CAPACITY)
    floor_chunks = _chunks(floors, _FLOOR_PAGE_LEVEL_CAPACITY)
    floor_combinations = tuple(
        (riser_chunk, floor_chunk)
        for riser_chunk in riser_chunks
        for floor_chunk in floor_chunks
    )
    basement_chunks = _chunks(inputs.risers, _BASEMENT_PAGE_RISER_CAPACITY)
    sheet_total = len(floor_combinations) + len(basement_chunks)
    basement_sheet_by_riser_id: dict[str, int] = {}
    for index, chunk in enumerate(basement_chunks):
        sheet_no = len(floor_combinations) + index + 1
        for riser in chunk:
            basement_sheet_by_riser_id[riser.riser_id] = sheet_no

    pages: list[str] = []
    for index, (riser_chunk, floor_chunk) in enumerate(floor_combinations):
        pages.append(build_wastewater_k3_floor_fragment_svg(
            project,
            inputs,
            risers=riser_chunk,
            floors=floor_chunk,
            sheet_no=index + 1,
            sheet_total=sheet_total,
            fragment_index=index + 1,
            fragment_total=len(floor_combinations),
            basement_sheet_by_riser_id=basement_sheet_by_riser_id,
        ))
    for index, chunk in enumerate(basement_chunks):
        start = index * _BASEMENT_PAGE_RISER_CAPACITY
        pages.append(build_wastewater_k3_basement_fragment_svg(
            project,
            inputs,
            start_index=start,
            end_index=start + len(chunk),
            sheet_no=len(floor_combinations) + index + 1,
            sheet_total=sheet_total,
            fragment_index=index + 1,
            fragment_total=len(basement_chunks),
            previous_sheet_no=(
                len(floor_combinations) + index if index > 0 else None
            ),
            next_sheet_no=(
                len(floor_combinations) + index + 2
                if index + 1 < len(basement_chunks) else None
            ),
        ))
    return tuple(pages)


def audit_wastewater_k3_svgs(
    project: Project,
    inputs: WastewaterK3ProjectInputs,
    svgs: tuple[str, ...],
) -> tuple[str, ...]:
    """Fail-fast structural audit of every K3 page."""
    findings: list[str] = []
    try:
        roots = tuple(ElementTree.fromstring(svg) for svg in svgs)
    except ElementTree.ParseError as exc:
        return (f"K3 SVG is invalid: {exc}",)
    expected_total = str(len(roots))
    for page_no, root in enumerate(roots, start=1):
        visible = " ".join(root.itertext())
        blocks = [
            row for row in root.iter() if row.get("data-title-block") == "form-3"
        ]
        if len(blocks) != 1:
            findings.append(f"K3 sheet {page_no}: expected one title block")
        elif (
            blocks[0].get("data-sheet-no") != str(page_no)
            or blocks[0].get("data-sheet-total") != expected_total
        ):
            findings.append(f"K3 sheet {page_no}: invalid sheet numbering")
        if "i=" in visible or "i =" in visible:
            findings.append(f"K3 sheet {page_no}: legacy slope notation remains")
        if "К1" in visible or "К2" in visible:
            findings.append(f"K3 sheet {page_no}: another sewer system leaked in")
        for group in root.iter():
            line_id = group.get("data-building-pipe-line")
            if not line_id:
                continue
            if not any(
                child.get("data-pipe-line-id") == line_id
                for child in group.iter()
            ):
                findings.append(
                    f"K3 sheet {page_no}: line {line_id} has no vector K3/DN mark"
                )

    all_groups = [row for root in roots for row in root.iter()]
    source_sections = {
        row.get("data-source-section") for row in all_groups
        if row.get("data-source-section")
    }
    expected_sections = {
        row.section_id
        for row in project.sewage.pipes
        if row.system.strip().upper() == "K3"
    }
    missing_sections = sorted(expected_sections - source_sections)
    if missing_sections:
        findings.append(
            "K3 registry sections are not drawn: " + ", ".join(missing_sections)
        )
    source_elements = {
        row.get("data-k3-source-element") for row in all_groups
        if row.get("data-k3-source-element")
    }
    expected_sources = {
        branch.elements[0].element_id
        for riser in inputs.risers
        for branch in riser.branches
    }
    if source_elements != expected_sources:
        findings.append("K3 source receivers differ from the project register")
    treatment_elements = {
        row.get("data-k3-treatment-element") for row in all_groups
        if row.get("data-k3-treatment-element")
    }
    if treatment_elements != set(inputs.treatment_element_ids):
        findings.append("K3 treatment equipment differs from the project register")
    elbow_ids = {
        row.get("data-k3-branch-elbow") for row in all_groups
        if row.get("data-k3-branch-elbow")
    }
    junction_ids = {
        row.get("data-k3-branch-junction") for row in all_groups
        if row.get("data-k3-branch-junction")
    }
    expected_elbows = {
        branch.connection_elbow_element_id
        for riser in inputs.risers for branch in riser.branches
    }
    expected_junctions = {
        branch.connection_junction_element_id
        for riser in inputs.risers for branch in riser.branches
    }
    if elbow_ids != expected_elbows:
        findings.append("K3 branch elbows differ from the project register")
    if junction_ids != expected_junctions:
        findings.append("K3 branch junctions differ from the project register")
    cleanout_ids = {
        row.get("data-k3-basement-cleanout") for row in all_groups
        if row.get("data-k3-basement-cleanout")
    }
    expected_cleanouts = {
        element_id
        for riser in inputs.risers
        for element_id in riser.lower_cleanout_element_ids
    }
    if cleanout_ids != expected_cleanouts:
        findings.append("K3 lower cleanouts differ from the project register")
    if any(
        row.get("data-k3-basement-cleanout")
        and row.get("data-cleanout-axis") != "collinear"
        for row in all_groups
    ):
        findings.append("K3 lower cleanout is not collinear with the main")
    through_ids = {
        row.get("data-k3-basement-through-junction") for row in all_groups
        if row.get("data-k3-basement-through-junction")
    }
    expected_through = {
        element_id
        for riser in inputs.risers
        for element_id in riser.lower_junction_element_ids
    }
    if through_ids != expected_through:
        findings.append("K3 through junctions differ from the project register")
    drawn_transitions = {
        row.get("data-building-transition") for row in all_groups
        if row.get("data-building-transition")
    }
    if drawn_transitions != {row.element_id for row in inputs.transitions}:
        findings.append("K3 DN transitions differ from the project register")

    if inputs.outlet is not None:
        root_and_group = next(
            (
                (root, row)
                for root in roots
                for row in root.iter()
                if row.get("data-building-pipe-line", "").startswith(
                    f"{inputs.outlet.section_id}-fragment-"
                )
            ),
            None,
        )
        if root_and_group is None:
            findings.append(f"K3 outlet {inputs.outlet.section_id} is not drawn")
        else:
            root, group = root_and_group
            right_wall = next(
                (
                    row for row in root.iter()
                    if row.get("data-architecture") == "foundation-right"
                ),
                None,
            )
            line = next(
                (row for row in group.iter() if row.tag.endswith("line")),
                None,
            )
            wall_x = (
                float(right_wall.get("x", "inf"))
                if right_wall is not None
                else float("inf")
            )
            if line is None or float(line.get("x2", "-inf")) <= wall_x:
                findings.append(
                    f"K3 outlet {inputs.outlet.section_id} does not cross "
                    "the building face"
                )
    return tuple(dict.fromkeys(findings))


def generate_wastewater_k3_pdf_from_project(
    output_path: str,
    project: Project,
) -> str:
    """Write the strict paginated K3 vector PDF."""
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    inputs = resolve_wastewater_k3_project_inputs(project)
    svgs = build_wastewater_k3_svgs(project, inputs)
    findings = audit_wastewater_k3_svgs(project, inputs, svgs)
    if findings:
        raise ValueError("K3 graphic audit failed: " + "; ".join(findings))
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

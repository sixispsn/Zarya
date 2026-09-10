"""SVG/PDF-контроль архитектурного каркаса схемы К1/К2/К3."""
from __future__ import annotations

from dataclasses import replace
from enum import Enum
from html import escape

from app.pz.drafting_font import (
    DRAFTING_FONT_FAMILY,
    ensure_drafting_font_registered,
)
from app.pz.project import Project
from app.pz.wastewater_layout import (
    PointMm,
    WastewaterSchemeLayout,
    audit_wastewater_layout,
)
from app.pz.wastewater_ugo import (
    fixture_trap_mode,
    get_ugo_connection_anchor,
    render_ugo,
)


FONT = DRAFTING_FONT_FAMILY
BLACK = "#000"


class WastewaterStructureScope(str, Enum):
    """Объём промежуточной отрисовки при поступенчатой сборке схемы."""

    FOUNDATION = "foundation"
    BASEMENT_K1_MAIN = "basement_k1_main"
    FULL_FLOOR_STACK = "full_floor_stack"


def build_wastewater_structure_svg(
    project: Project,
    layout: WastewaterSchemeLayout,
    scope: WastewaterStructureScope = WastewaterStructureScope.FOUNDATION,
    *,
    sheet_no: int = 1,
    sheet_total: int = 1,
) -> str:
    """Отрисовать один из проверочных этапов принципиальной схемы."""
    audit = audit_wastewater_layout(project, layout)
    if not audit.ready:
        raise ValueError("каркас схемы не прошёл проверку: " + "; ".join(
            row.message for row in audit.errors
        ))

    if scope == WastewaterStructureScope.BASEMENT_K1_MAIN:
        from app.pz.generator import _document_cipher, _wastewater_document_cipher
        from app.pz.wastewater_scheme import (
            WastewaterSchemeScope,
            build_wastewater_scheme,
        )

        focus = next(
            (row.section_id for row in layout.routes if row.system == "K1"),
            None,
        )
        wastewater_project = replace(
            project,
            document=replace(
                project.document,
                cipher=_document_cipher(
                    _wastewater_document_cipher(project.document.cipher or ""),
                    ".СК",
                ),
                sheet_title="Принципиальная схема внутренних систем К1",
            ),
        )
        return build_wastewater_scheme(
            wastewater_project,
            WastewaterSchemeScope.BASEMENT_K1_MAIN,
            focus_section_id=focus,
        ).svg

    width, height = layout.sheet_width_mm, layout.sheet_height_mm
    G = [
        '<defs><pattern id="diagonal-hatch" width="6" height="6" '
        'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="6" stroke="#000" '
        'stroke-width="0.35"/></pattern></defs>',
        f'<rect width="{width:g}" height="{height:g}" fill="white"/>',
    ]

    def line(x1, y1, x2, y2, sw=0.35, dash=""):
        attr = f' stroke-dasharray="{dash}"' if dash else ""
        G.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{BLACK}" stroke-width="{sw:.2f}"{attr}/>'
        )

    def rect(x, y, w, h, sw=0.35, fill="none"):
        G.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'stroke="{BLACK}" stroke-width="{sw:.2f}" fill="{fill}"/>'
        )

    def polyline(points, sw=0.35):
        value = " ".join(f"{point.x:.2f},{point.y:.2f}" for point in points)
        G.append(
            f'<polyline points="{value}" fill="none" stroke="{BLACK}" '
            f'stroke-width="{sw:.2f}" stroke-linejoin="miter"/>'
        )

    def text(x, y, value, size=3.5, anchor="start", weight="normal"):
        G.append(
            f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" '
            f'font-size="{size:.2f}" text-anchor="{anchor}" '
            f'font-weight="{weight}" fill="{BLACK}">{escape(str(value))}</text>'
        )

    frame = layout.drawing_frame
    rect(frame.x, frame.y, frame.width, frame.height, sw=0.7)
    floor_groups = sorted(layout.floor_groups, key=lambda row: row.y_mm)
    if not floor_groups:
        raise ValueError("в каркасе нет этажных уровней")
    foundation = next(
        (slab for slab in layout.slabs if slab.kind == "basement_foundation_slab"),
        None,
    )
    x1 = foundation.frame.x if foundation else 170.0
    x2 = foundation.frame.x2 if foundation else 671.0
    if scope == WastewaterStructureScope.FULL_FLOOR_STACK:
        shown_groups = floor_groups
        shown_group_ids = {row.group_id for row in shown_groups}
        shown_spaces = [
            row for row in layout.spaces if row.group_id in shown_group_ids
        ]
        structure_top_y = min(
            (row.frame.y for row in shown_spaces),
            default=floor_groups[0].y_mm,
        )
        text(170, 28, "Принципиальная схема систем канализации и водоотведения", 4.0, weight="bold")
    else:
        shown_groups = [
            group for group in floor_groups
            if group.kind in {"basement", "technical"}
        ]
        structure_top_y = max(row.y_mm for row in floor_groups) - 78.0
    lower_y = (
        foundation.frame.y2
        if foundation is not None
        else max(row.y_mm for row in floor_groups)
    )
    line(x1, structure_top_y, x1, lower_y, 0.5)
    line(x2, structure_top_y, x2, lower_y, 0.5)
    if scope == WastewaterStructureScope.FULL_FLOOR_STACK:
        G.append(
            f'<g data-building-roof-boundary="true">'
            f'<line x1="{x1:.2f}" y1="{structure_top_y:.2f}" '
            f'x2="{x2:.2f}" y2="{structure_top_y:.2f}" '
            f'stroke="{BLACK}" stroke-width="0.70"/>'
            f'<line x1="{x1:.2f}" y1="{structure_top_y+1.2:.2f}" '
            f'x2="{x2:.2f}" y2="{structure_top_y+1.2:.2f}" '
            f'stroke="{BLACK}" stroke-width="0.22"/></g>'
        )
    else:
        line(x1, structure_top_y, x2, structure_top_y, 0.35)

    for group in shown_groups:
        y = group.y_mm
        if group.kind == "roof":
            line(x1, y, x2, y, 0.7)
        elif group.kind == "floor":
            G.append(
                f'<g data-building-storey-boundary="{escape(group.group_id, quote=True)}">'
                f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" '
                f'y2="{y:.2f}" stroke="{BLACK}" stroke-width="0.55"/>'
                f'<line x1="{x1:.2f}" y1="{y+1.2:.2f}" x2="{x2:.2f}" '
                f'y2="{y+1.2:.2f}" stroke="{BLACK}" stroke-width="0.22"/></g>'
            )
        else:
            line(x1, y, x2, y, 0.55)
        # Отметка уровня в стиле строительного разреза.
        mark_x = x1 - 10.0
        line(x1 - 28.0, y, x1, y, 0.25)
        line(mark_x - 2.0, y - 2.0, mark_x, y, 0.3)
        line(mark_x + 2.0, y - 2.0, mark_x, y, 0.3)
        if group.elevation_m is None:
            mark = "отм. по АР"
        elif abs(group.elevation_m) < 0.0005:
            mark = "±0,000"
        else:
            mark = f"{group.elevation_m:+.3f}".replace(".", ",")
        text(x1 - 7, y - 2.6, mark, 2.5, "end")
        text(x1 - 7, y + 3.7, group.label, 2.2, "end")

    if scope == WastewaterStructureScope.FULL_FLOOR_STACK:
        space_top_by_group = {
            group.group_id: min(
                row.frame.y
                for row in layout.spaces
                if row.group_id == group.group_id
            )
            for group in shown_groups
            if any(row.group_id == group.group_id for row in layout.spaces)
        }
        numbered_floor_groups = [
            group for group in shown_groups
            if group.kind == "floor" and group.floors
        ]
        for upper, lower in zip(numbered_floor_groups, numbered_floor_groups[1:]):
            upper_floor = min(upper.floors)
            lower_floor = max(lower.floors)
            if upper_floor - lower_floor <= 1:
                continue
            break_y = (
                upper.y_mm + space_top_by_group.get(lower.group_id, lower.y_mm)
            ) / 2
            omitted = f"этажи {lower_floor+1}-{upper_floor-1} не показаны"
            G.append(
                f'<g data-collapsed-architecture-floors="{lower_floor+1}-'
                f'{upper_floor-1}"><path d="M{x1-2:.2f},{break_y-2:.2f} '
                f'L{x1+2:.2f},{break_y:.2f} L{x1-2:.2f},{break_y+2:.2f}" '
                f'fill="white" stroke="{BLACK}" stroke-width="0.35"/>'
                f'<path d="M{x2-2:.2f},{break_y-2:.2f} '
                f'L{x2+2:.2f},{break_y:.2f} L{x2-2:.2f},{break_y+2:.2f}" '
                f'fill="white" stroke="{BLACK}" stroke-width="0.35"/>'
                f'<text x="{x1+6:.2f}" y="{break_y+1.2:.2f}" '
                f'font-family="{FONT}" font-size="2.2">{omitted}</text></g>'
            )

    for slab in layout.slabs:
        fill = "url(#diagonal-hatch)" if slab.hatch == "diagonal" else "white"
        rect(slab.frame.x, slab.frame.y, slab.frame.width, slab.frame.height, 0.55, fill)
        if (
            slab.kind == "basement_foundation_slab"
            and scope != WastewaterStructureScope.BASEMENT_K1_MAIN
        ):
            text(
                slab.frame.x + slab.frame.width / 2,
                slab.frame.y + slab.frame.height / 2 + 1.2,
                "Фундаментная плита подвала - диагональная штриховка",
                2.5,
                "middle",
            )

    if scope == WastewaterStructureScope.FULL_FLOOR_STACK:
        for space in layout.spaces:
            rect(
                space.frame.x,
                space.frame.y,
                space.frame.width,
                space.frame.height,
                0.3,
                "white" if space.kind != "shaft" else "#f3f3f3",
            )
            text(
                space.frame.x + space.frame.width / 2,
                space.frame.y + 6.0,
                space.label,
                2.1,
                "middle",
            )

        pipes = {row.section_id: row for row in project.sewage.pipes}
        for route in layout.routes:
            G.append(
                f'<g data-bound-section="{escape(route.section_id, quote=True)}" '
                f'data-bound-system="{escape(route.system, quote=True)}">'
            )
            polyline(route.points, 0.7)
            pipe = pipes[route.section_id]
            middle = PointMm(
                (route.points[0].x + route.points[-1].x) / 2,
                (route.points[0].y + route.points[-1].y) / 2,
            )
            dn = pipe.nominal_diameter_mm or round(pipe.outer_diameter_mm)
            system_mark = {"K1": "К1", "K2": "К2", "K3": "К3"}.get(
                route.system,
                route.system,
            )
            mark = f"{system_mark} ⌀{dn:g}"
            text(middle.x, middle.y - 3.2, mark, 2.2, "middle")
            if pipe.slope_per_mille is not None:
                slope_segment = next(
                    (
                        (start, end)
                        for start, end in zip(route.points, route.points[1:])
                        if abs(end.x - start.x) > 0.2
                    ),
                    None,
                )
                if slope_segment is not None:
                    start, end = slope_segment
                    direction = 1 if end.x >= start.x else -1
                    marker_x = (start.x + end.x) / 2
                    marker_y = (start.y + end.y) / 2 - 7.0
                    heel_x = marker_x - 3.0 * direction
                    apex_x = marker_x + 3.0 * direction
                    value = f"{pipe.slope_per_mille/1000:.3f}".replace(".", ",")
                    G.append(
                        f'<g data-slope-marker="{escape(route.route_id, quote=True)}" '
                        'data-sign-shape="acute-angle" '
                        'data-lower-leg-horizontal="true" '
                        'data-lower-leg-parallel-to-text="true">'
                        f'<path d="M{heel_x:.2f},{marker_y:.2f} '
                        f'L{apex_x:.2f},{marker_y:.2f} '
                        f'L{heel_x:.2f},{marker_y-2.4:.2f}" fill="none" '
                        f'stroke="{BLACK}" stroke-width="0.35"/>'
                        f'<text x="{heel_x-1.2*direction:.2f}" y="{marker_y-0.8:.2f}" '
                        f'text-anchor="{("end" if direction > 0 else "start")}" '
                        f'font-family="{FONT}" font-size="2.0">{value}</text></g>'
                    )
            G.append("</g>")

        elements = {row.element_id: row for row in project.sewage.elements}
        for placement in layout.elements:
            element = elements[placement.element_id]
            connection = placement.point
            route = next(
                (
                    row
                    for row in layout.routes
                    if row.section_id == element.section_id
                    and row.system == element.system
                    and row.group_id == placement.group_id
                ),
                None,
            )
            downstream_x = route.points[-1].x if route is not None else connection.x
            side = 1 if downstream_x >= connection.x else -1
            fixture_scale = 0.13
            trap_scale = 0.08
            trap_svg = ""
            fixture_outlet = connection
            if fixture_trap_mode(element.kind) == "external":
                trap_center = PointMm(
                    connection.x - side * 23.0 * trap_scale,
                    connection.y - 20.0 * trap_scale,
                )
                fixture_outlet = PointMm(
                    trap_center.x - side * 14.0 * trap_scale,
                    trap_center.y - 20.0 * trap_scale,
                )
                trap_svg = render_ugo(
                    "trap",
                    trap_center.x,
                    trap_center.y,
                    scale=trap_scale,
                    mirror_x=side < 0,
                )
            try:
                anchor_x, anchor_y = get_ugo_connection_anchor(element.kind)
                symbol_x = fixture_outlet.x - anchor_x * fixture_scale
                symbol_y = fixture_outlet.y - anchor_y * fixture_scale
            except KeyError:
                symbol_x, symbol_y = fixture_outlet.x, fixture_outlet.y
            route_connection = next(
                (
                    point
                    for point in (route.points if route is not None else ())
                    if abs(point.x - connection.x) <= 0.2
                ),
                None,
            )
            connector_svg = ""
            if route_connection is not None and abs(route_connection.y - connection.y) > 0.2:
                connector_svg = (
                    f'<line data-fixture-connection="{escape(placement.placement_id, quote=True)}" '
                    f'x1="{connection.x:.2f}" y1="{connection.y:.2f}" '
                    f'x2="{route_connection.x:.2f}" y2="{route_connection.y:.2f}" '
                    f'stroke="{BLACK}" stroke-width="0.70"/>'
                )
            G.append(
                f'<g data-bound-element="{escape(element.element_id, quote=True)}">'
                f'{connector_svg}'
                f'{render_ugo(element.kind, symbol_x, symbol_y, scale=fixture_scale)}'
                f'{trap_svg}'
            )
            text(
                symbol_x,
                symbol_y - 7.0,
                element.element_id,
                1.9,
                "middle",
            )
            G.append("</g>")

    if scope == WastewaterStructureScope.BASEMENT_K1_MAIN:
        pipes = {row.section_id: row for row in project.sewage.pipes}
        routes = [
            row for row in layout.routes
            if row.system == "K1" and row.group_id in {
                group.group_id for group in shown_groups
            }
        ]
        if not routes:
            raise ValueError("для этапа подвальной магистрали К1 не размещён ни один участок")
        for route in routes:
            pipe = pipes[route.section_id]
            polyline(route.points, 0.7)
            start, end = route.points[0], route.points[-1]
            mid_x = (start.x + end.x) / 2
            mid_y = (start.y + end.y) / 2
            # Направление движения стоков вдоль реестрового from_node -> to_node.
            line(mid_x - 1.8, mid_y - 1.2, mid_x + 2.0, mid_y, 0.35)
            line(mid_x - 1.8, mid_y + 1.2, mid_x + 2.0, mid_y, 0.35)
            diameter = (
                f"Ø{pipe.outer_diameter_mm:g}×{pipe.wall_thickness_mm:g}"
                .replace(".", ",")
            )
            slope = (
                f"; i={pipe.slope_per_mille:g}‰"
                if pipe.slope_per_mille is not None else ""
            ).replace(".", ",")
            text(mid_x, mid_y - 5.0, f"{pipe.section_id} {diameter}{slope}", 2.5, "middle")

    # Упрощённая основная надпись для контрольного листа этапа компоновки.
    stamp_x, stamp_y, stamp_w, stamp_h = 651.0, 534.0, 185.0, 55.0
    rect(stamp_x, stamp_y, stamp_w, stamp_h, 0.7, "white")
    line(stamp_x, stamp_y + 25, stamp_x + stamp_w, stamp_y + 25, 0.4)
    line(stamp_x, stamp_y + 40, stamp_x + stamp_w, stamp_y + 40, 0.4)
    line(stamp_x + 135, stamp_y + 25, stamp_x + 135, stamp_y + stamp_h, 0.4)
    line(stamp_x + 152, stamp_y + 25, stamp_x + 152, stamp_y + stamp_h, 0.3)
    line(stamp_x + 169, stamp_y + 25, stamp_x + 169, stamp_y + stamp_h, 0.3)
    cipher = project.document.cipher or ""
    text(stamp_x + 92.5, stamp_y + 10, cipher, 3.5, "middle")
    text(stamp_x + 92.5, stamp_y + 20, project.document.object_name or "", 2.5, "middle")
    text(stamp_x + 67.5, stamp_y + 34, "Принципиальная схема К1/К2", 2.5, "middle")
    text(stamp_x + 143.5, stamp_y + 31, "Стадия", 1.8, "middle")
    text(stamp_x + 160.5, stamp_y + 31, "Лист", 1.8, "middle")
    text(stamp_x + 177, stamp_y + 31, "Листов", 1.8, "middle")
    text(stamp_x + 143.5, stamp_y + 37.5, project.document.stage_label or "П", 2.5, "middle")
    text(stamp_x + 160.5, stamp_y + 37.5, str(sheet_no), 2.5, "middle")
    text(stamp_x + 177, stamp_y + 37.5, str(sheet_total), 2.5, "middle")
    stage_name = (
        "Подвальная магистраль К1"
        if scope == WastewaterStructureScope.BASEMENT_K1_MAIN
        else (
            "По подтверждённой архитектуре"
            if scope == WastewaterStructureScope.FULL_FLOOR_STACK
            else "Начало схемы: плита подвала"
        )
    )
    text(stamp_x + 92.5, stamp_y + 49, stage_name, 2.5, "middle")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}mm" '
        f'height="{height:g}mm" viewBox="0 0 {width:g} {height:g}" '
        f'data-layout-mode="{escape(layout.mode.value, quote=True)}">'
        + "".join(G)
        + "</svg>"
    )


def generate_wastewater_structure_pdf(
    project: Project,
    layout: WastewaterSchemeLayout,
    output_path: str,
    scope: WastewaterStructureScope = WastewaterStructureScope.FOUNDATION,
    *,
    sheet_no: int = 1,
    sheet_total: int = 1,
) -> str:
    ensure_drafting_font_registered()
    import cairosvg

    svg = build_wastewater_structure_svg(
        project,
        layout,
        scope=scope,
        sheet_no=sheet_no,
        sheet_total=sheet_total,
    )
    if scope == WastewaterStructureScope.BASEMENT_K1_MAIN:
        svg = svg.replace(
            'width="2803" height="1980"',
            'width="841mm" height="594mm"',
            1,
        )
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path

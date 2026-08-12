"""SVG/PDF-контроль архитектурного каркаса схемы К1/К2/К3."""
from __future__ import annotations

from dataclasses import replace
from enum import Enum
from html import escape

from app.pz.project import Project
from app.pz.wastewater_layout import (
    WastewaterSchemeLayout,
    audit_wastewater_layout,
)


FONT = "osifont"
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
    roof_y = floor_groups[0].y_mm
    lower_y = max(row.y_mm for row in floor_groups)
    if scope == WastewaterStructureScope.FULL_FLOOR_STACK:
        shown_groups = floor_groups
        structure_top_y = roof_y
        text(170, 28, "Принципиальная схема систем канализации и водоотведения", 4.0, weight="bold")
    else:
        shown_groups = [
            group for group in floor_groups
            if group.kind in {"basement", "technical"}
        ]
        structure_top_y = lower_y - 78.0
    line(x1, structure_top_y, x1, lower_y, 0.5)
    line(x2, structure_top_y, x2, lower_y, 0.5)
    if scope in {
        WastewaterStructureScope.FOUNDATION,
        WastewaterStructureScope.BASEMENT_K1_MAIN,
    }:
        line(x1, structure_top_y, x2, structure_top_y, 0.35)

    for group in shown_groups:
        y = group.y_mm
        if group.kind == "roof":
            line(x1, y, x2, y, 0.7)
        elif group.kind == "floor":
            line(x1, y, x2, y, 0.55)
            line(x1, y + 1.2, x2, y + 1.2, 0.22)
        else:
            line(x1, y, x2, y, 0.55)
        # Отметка уровня в стиле строительного разреза.
        mark_x = x1 - 10.0
        line(x1 - 28.0, y, x1, y, 0.25)
        line(mark_x - 2.0, y - 2.0, mark_x, y, 0.3)
        line(mark_x + 2.0, y - 2.0, mark_x, y, 0.3)
        mark = (
            f"{group.elevation_m:+.3f}".replace(".", ",")
            if group.elevation_m is not None
            else "отм. по АР"
        )
        text(x1 - 7, y - 2.6, mark, 2.5, "end")
        text(x1 - 7, y + 3.7, group.label, 2.2, "end")

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
    text(stamp_x + 160.5, stamp_y + 37.5, "1", 2.5, "middle")
    text(stamp_x + 177, stamp_y + 37.5, "1", 2.5, "middle")
    stage_name = (
        "Подвальная магистраль К1"
        if scope == WastewaterStructureScope.BASEMENT_K1_MAIN
        else "Начало схемы: плита подвала"
    )
    text(stamp_x + 92.5, stamp_y + 49, stage_name, 2.5, "middle")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}mm" '
        f'height="{height:g}mm" viewBox="0 0 {width:g} {height:g}">'
        + "".join(G)
        + "</svg>"
    )


def generate_wastewater_structure_pdf(
    project: Project,
    layout: WastewaterSchemeLayout,
    output_path: str,
    scope: WastewaterStructureScope = WastewaterStructureScope.FOUNDATION,
) -> str:
    import cairosvg

    svg = build_wastewater_structure_svg(project, layout, scope=scope)
    if scope == WastewaterStructureScope.BASEMENT_K1_MAIN:
        svg = svg.replace(
            'width="2803" height="1980"',
            'width="841mm" height="594mm"',
            1,
        )
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path

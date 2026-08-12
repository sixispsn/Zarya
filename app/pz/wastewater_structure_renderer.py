"""SVG/PDF-контроль архитектурного каркаса схемы К1/К2/К3."""
from __future__ import annotations

from html import escape

from app.pz.project import Project
from app.pz.wastewater_layout import (
    WastewaterSchemeLayout,
    audit_wastewater_layout,
)


FONT = "osifont"
BLACK = "#000"


def build_wastewater_structure_svg(
    project: Project,
    layout: WastewaterSchemeLayout,
) -> str:
    """Отрисовать проверочный лист каркаса без инженерных трасс."""
    audit = audit_wastewater_layout(project, layout)
    if not audit.ready:
        raise ValueError("каркас схемы не прошёл проверку: " + "; ".join(
            row.message for row in audit.errors
        ))

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

    def text(x, y, value, size=3.5, anchor="start", weight="normal"):
        G.append(
            f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" '
            f'font-size="{size:.2f}" text-anchor="{anchor}" '
            f'font-weight="{weight}" fill="{BLACK}">{escape(str(value))}</text>'
        )

    frame = layout.drawing_frame
    rect(frame.x, frame.y, frame.width, frame.height, sw=0.7)
    text(85, 22, "Каркас принципиальной схемы систем канализации и водоотведения", 6.0, weight="bold")
    text(85, 29, "Каждый этаж показан отдельной полосой; нижняя конструкция - фундаментная плита подвала", 3.2)

    floor_groups = sorted(layout.floor_groups, key=lambda row: row.y_mm)
    if not floor_groups:
        raise ValueError("в каркасе нет этажных уровней")
    x1, x2 = 85.0, 735.0
    roof_y = floor_groups[0].y_mm
    lower_y = max(row.y_mm for row in floor_groups)
    line(x1, roof_y, x1, lower_y, 0.55)
    line(x2, roof_y, x2, lower_y, 0.55)

    for group in floor_groups:
        y = group.y_mm
        if group.kind == "roof":
            line(x1, y, x2, y, 0.7)
        elif group.kind == "floor":
            line(x1, y, x2, y, 0.55)
            line(x1, y + 1.2, x2, y + 1.2, 0.22)
        else:
            line(x1, y, x2, y, 0.55)
        # Отметка уровня в стиле строительного разреза.
        line(62, y, x1, y, 0.25)
        line(78.5, y - 2.0, 80.5, y, 0.3)
        line(82.5, y - 2.0, 80.5, y, 0.3)
        mark = (
            f"{group.elevation_m:+.3f}".replace(".", ",")
            if group.elevation_m is not None
            else "отм. по АР"
        )
        text(78, y - 2.8, mark, 3.0, "end")
        text(78, y + 4.2, group.label, 2.8, "end")

    for slab in layout.slabs:
        fill = "url(#diagonal-hatch)" if slab.hatch == "diagonal" else "white"
        rect(slab.frame.x, slab.frame.y, slab.frame.width, slab.frame.height, 0.55, fill)
        if slab.kind == "basement_foundation_slab":
            text(
                slab.frame.x + slab.frame.width / 2,
                slab.frame.y + slab.frame.height / 2 + 1.2,
                "Фундаментная плита подвала - диагональная штриховка",
                3.0,
                "middle",
            )

    floor_count = sum(1 for row in layout.floor_groups if row.kind == "floor")
    text(85, 520, f"Контроль этажности: сформировано этажей - {floor_count}", 3.5, weight="bold")
    text(85, 527, "Трассы и УГО будут добавляться после подтверждения координат узлов.", 3.2)

    # Упрощённая основная надпись для контрольного листа этапа компоновки.
    stamp_x, stamp_y, stamp_w, stamp_h = 651.0, 534.0, 185.0, 55.0
    rect(stamp_x, stamp_y, stamp_w, stamp_h, 0.7, "white")
    line(stamp_x, stamp_y + 25, stamp_x + stamp_w, stamp_y + 25, 0.4)
    line(stamp_x, stamp_y + 40, stamp_x + stamp_w, stamp_y + 40, 0.4)
    line(stamp_x + 135, stamp_y + 25, stamp_x + 135, stamp_y + stamp_h, 0.4)
    line(stamp_x + 152, stamp_y + 25, stamp_x + 152, stamp_y + stamp_h, 0.3)
    line(stamp_x + 169, stamp_y + 25, stamp_x + 169, stamp_y + stamp_h, 0.3)
    cipher = project.document.cipher or ""
    text(stamp_x + 92.5, stamp_y + 10, cipher, 4.2, "middle")
    text(stamp_x + 92.5, stamp_y + 20, project.document.object_name or "", 2.8, "middle")
    text(stamp_x + 67.5, stamp_y + 34, "Каркас этажности и подвала К1/К2", 3.2, "middle")
    text(stamp_x + 143.5, stamp_y + 31, "Стадия", 2.2, "middle")
    text(stamp_x + 160.5, stamp_y + 31, "Лист", 2.2, "middle")
    text(stamp_x + 177, stamp_y + 31, "Листов", 2.2, "middle")
    text(stamp_x + 143.5, stamp_y + 37.5, project.document.stage_label or "П", 3.2, "middle")
    text(stamp_x + 160.5, stamp_y + 37.5, "1", 3.2, "middle")
    text(stamp_x + 177, stamp_y + 37.5, "1", 3.2, "middle")
    text(stamp_x + 92.5, stamp_y + 49, "Принципиальная схема К1, К2", 3.4, "middle")

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
) -> str:
    import cairosvg

    svg = build_wastewater_structure_svg(project, layout)
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path

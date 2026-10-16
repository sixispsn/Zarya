"""Paper-size form 3, GOST R 21.101-2026 Appendix E and figure Zh.1.

Only presentation: no diagram geometry, topology or calculation is inferred.
Text is measured in the actual drafting font; oversized values fail visibly.
"""

from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.pz.drafting_font import DRAFTING_FONT_PATH


def drawing_frame_svg(
    document, *, width_mm, height_mm, title, system_label, sheet_no=1, sheet_total=1
):
    """Full graphic frame in physical millimetres; reserve the stamp in the body."""
    return (
        f'<g data-drawing-frame="spds-form-3">'
        f'<rect data-sheet-border="true" x="20" y="5" width="{width_mm - 25:g}" '
        f'height="{height_mm - 10:g}" fill="none" stroke="black" stroke-width=".7"/>'
        + title_block_svg(
            document,
            sheet_no=sheet_no,
            sheet_total=sheet_total,
            title=title,
            system_label=system_label,
            sheet_width_mm=width_mm,
            sheet_height_mm=height_mm,
            units_per_mm=1,
        )
        + "</g>"
    )


def title_block_svg(
    document,
    *,
    sheet_no,
    sheet_total,
    title,
    system_label,
    sheet_width_mm,
    sheet_height_mm,
    units_per_mm,
):
    if sheet_total < 1 or not 1 <= sheet_no <= sheet_total:
        raise ValueError("Неверная нумерация графических листов")
    font = "ZaryaGraphicFrame"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, str(DRAFTING_FONT_PATH)))
    scale = units_per_mm
    left, top = sheet_width_mm - 190, sheet_height_mm - 60
    rows = [
        f'<g data-title-block="form-3" data-sheet-no="{sheet_no}" '
        f'data-sheet-total="{sheet_total}">',
        f'<rect x="{left * scale:.3f}" y="{top * scale:.3f}" width="{185 * scale:.3f}" '
        f'height="{55 * scale:.3f}" fill="white" stroke="black" stroke-width="{0.5 * scale:.3f}"/>',
    ]

    def line(x1, y1, x2, y2, thick=False):
        rows.append(
            f'<line x1="{(left + x1) * scale:.3f}" y1="{(top + y1) * scale:.3f}" '
            f'x2="{(left + x2) * scale:.3f}" y2="{(top + y2) * scale:.3f}" '
            f'stroke="black" stroke-width="{(0.5 if thick else 0.25) * scale:.3f}"/>'
        )

    def cell(value, x, y, width, height, cap=2.5):
        if not value:
            return
        value = " ".join(str(value).split())
        for h in dict.fromkeys((cap, 2.5)):
            size, leading = h / 0.823, h * 1.4
            lines, current = [], ""
            for word in value.split():
                candidate = (current + " " + word).strip()
                if pdfmetrics.stringWidth(candidate, font, size) <= width - 1.5:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            if len(lines) * leading <= height - 0.6 and all(
                pdfmetrics.stringWidth(t, font, size) <= width - 1.5 for t in lines
            ):
                for i, text in enumerate(lines):
                    baseline = (
                        top
                        + y
                        + height / 2
                        - (len(lines) - 1) * leading / 2
                        + h / 2
                        + i * leading
                    )
                    rows.append(
                        f'<text x="{(left + x + width / 2) * scale:.3f}" y="{baseline * scale:.3f}" '
                        f'font-family="OpenGOST type B" font-size="{size * scale:.3f}" '
                        f'text-anchor="middle">{escape(text)}</text>'
                    )
                return
        raise ValueError("Текст не помещается в графу основной надписи: " + value)

    line(65, 0, 65, 55, True)
    xs = (0, 10, 20, 30, 40, 55, 65)
    for x in xs[1:-1]:
        line(x, 0, x, 25 if x in (10, 30) else 55)
    for y in range(5, 55, 5):
        line(0, y, 65, y)
    for i, label in enumerate(("Изм.", "Кол.уч.", "Лист", "№ док.", "Подп.", "Дата")):
        cell(label, xs[i], 20, xs[i + 1] - xs[i], 5)
    for y in (10, 25, 40):
        line(65, y, 185, y, True)
    line(135, 25, 135, 55, True)
    for x in (150, 165):
        line(x, 25, x, 40)
    line(135, 30, 185, 30)
    for y, label, name in (
        (25, "Разраб.", document.developer_name),
        (30, "Проверил", document.inspector_name),
        (35, "Нач. отд.", document.dept_head_name),
        (45, "Н. контр.", document.norm_control_name),
        (50, "ГИП", document.gip_name),
    ):
        cell(label, 0, y, 20, 5)
        cell(name, 20, y, 20, 5)
    cell(document.cipher, 65, 0, 120, 10, 3.5)
    cell(document.object_name, 65, 10, 120, 15)
    cell(document.object_part, 65, 25, 70, 15)
    cell(" ".join(filter(None, (title, system_label))), 65, 40, 70, 15)
    cell(document.organization, 135, 40, 50, 15)
    for x, width, label, value in (
        (135, 15, "Стадия", document.stage_label),
        (150, 15, "Лист", str(sheet_no) if sheet_total > 1 else ""),
        (165, 20, "Листов", str(sheet_total) if sheet_no == 1 else ""),
    ):
        cell(label, x, 25, width, 5)
        cell(value, x, 30, width, 10, 3.5)

    # Additional columns stay at the left sheet edge, not next to the stamp.
    bottom = sheet_height_mm - 5
    rows.append('<g data-inventory-columns="20-22">')
    for x in (8, 13):
        line(x - left, bottom - 85 - top, x - left, bottom - top)
    for y in (bottom - 85, bottom - 60, bottom - 25, bottom):
        line(8 - left, y - top, 20 - left, y - top)
    for label, y in (
        ("Взам. инв. №", bottom - 72.5),
        ("Подп. и дата", bottom - 42.5),
        ("Инв. № подл.", bottom - 12.5),
    ):
        rows.append(
            f'<text transform="translate({11.5 * scale:.3f} {y * scale:.3f}) rotate(-90)" '
            f'font-family="OpenGOST type B" font-size="{2.5 / 0.823 * scale:.3f}" '
            f'text-anchor="middle">{label}</text>'
        )
    rows.append("</g>")
    paper = {
        (210, 297): "А4",
        (297, 420): "А3",
        (420, 594): "А2",
        (594, 841): "А1",
        (841, 1189): "А0",
    }.get(tuple(sorted((sheet_width_mm, sheet_height_mm))))
    if paper:
        rows.append(
            f'<text x="{(sheet_width_mm - 5.75) * scale:.3f}" y="{(sheet_height_mm - 1.3) * scale:.3f}" '
            f'font-family="OpenGOST type B" font-size="{2.5 / 0.823 * scale:.3f}" '
            f'text-anchor="end">Формат {paper}</text>'
        )
    rows.append("</g>")
    return "".join(rows)

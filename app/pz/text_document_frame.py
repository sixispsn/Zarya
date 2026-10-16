"""Measured frames for title-less A4/A3 text and A3 graphic balance sheets.

GOST R 21.101-2026, 5.2.2-5.2.3, Appendix E forms 3/6, Appendix Zh figure Zh.1.
The body is paginated first. Vector frames use actual PDF page numbers, not
CSS table minimum heights or a saved project's unrelated sheet count.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph

from app.pz.drafting_font import DRAFTING_FONT_PATH

FONT = 'ZaryaFrameGOST'


def frame_pdf(doc, page_number, total, *, layout='a4_text'):
    if layout not in ('a4_text', 'a3_text', 'a3_graphic'):
        raise ValueError('Неизвестный формат рамки: ' + layout)
    sheet_width = 420 if layout.startswith('a3_') else 210
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(DRAFTING_FONT_PATH)))
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=(sheet_width * mm, 297 * mm), pageCompression=1)

    def line(x1, y1, x2, y2, width=.25):
        c.setLineWidth(width * mm)
        c.line(x1 * mm, (297 - y1) * mm, x2 * mm, (297 - y2) * mm)

    def cell(value, x, y, width, height, cap=2.5):
        if not value:
            return
        # OpenGOST's capital height is 0.823 em. Never shrink below h=2.5 mm
        # or silently clip an oversized project name / designation.
        for h in dict.fromkeys((cap, 2.5)):
            style = ParagraphStyle('frame', fontName=FONT, fontSize=h / .823 * mm,
                                   leading=h * 1.4 * mm, alignment=1)
            paragraph = Paragraph(escape(str(value)), style)
            _, used = paragraph.wrap((width - 1.5) * mm, height * mm)
            if used <= (height - .6) * mm:
                paragraph.drawOn(c, (x + .75) * mm, (297 - y - height / 2) * mm - used / 2)
                return
        raise ValueError('Текст не помещается в графу основной надписи: ' + str(value))

    # Main frame, measured from the physical sheet edge; no CSS background scaling.
    right = sheet_width - 5
    for segment in ((20, 5, right, 5), (right, 5, right, 292),
                    (right, 292, 20, 292), (20, 292, 20, 5)):
        line(*segment, .5)
    # Additional columns 20-22, 5 + 7 mm; heights 25 / 35 / 25 mm.
    for x in (8, 13):
        line(x, 207, x, 292)
    for y in (207, 232, 267, 292):
        line(8, y, 20, y)
    for label, center in (('Взам. инв. №', 219.5), ('Подп. и дата', 249.5), ('Инв. № подл.', 279.5)):
        c.saveState()
        c.translate(11.5 * mm, (297 - center) * mm)
        c.rotate(90)
        c.setFont(FONT, 2.5 / .823 * mm)
        c.drawCentredString(0, 0, label)
        c.restoreState()
    c.setFont(FONT, 2.5 / .823 * mm)
    c.drawRightString(right * mm, 1.3 * mm, 'Формат А3' if sheet_width == 420 else 'Формат А4')

    # Graphic balance sheets use form 3 on every sheet (5.2.2).
    # Shift only the title block, never the left filing/inventory columns.
    c.translate((sheet_width - 210) * mm, 0)
    first = page_number == 1 or layout == 'a3_graphic'
    top, height = (237, 55) if first else (277, 15)
    line(20, top, 205, top, .5)
    if sheet_width == 420:
        line(20, top, 20, 292, .5)
    line(85, top, 85, 292, .5)
    # Change register: 10+10+10+10+15+10 = 65 mm.
    register_height = 25 if first else 15
    xs = (20, 30, 40, 50, 60, 75, 85)
    for x in xs[1:-1]:
        end = top + register_height if x in (30, 50) else 292
        line(x, top, x, end)
    for offset in range(5, height, 5):
        line(20, top + offset, 85, top + offset)
    for i, label in enumerate(('Изм.', 'Кол.уч.', 'Лист', '№ док.', 'Подп.', 'Дата')):
        cell(label, xs[i], top + register_height - 5, xs[i + 1] - xs[i], 5)

    if first:
        # Form 3: right block widths 70 + 15 + 15 + 20; heights 10/15/15/15.
        for y in (247, 262, 277):
            line(85, y, 205, y, .5)
        line(155, 262, 155, 292, .5)
        for x in (170, 185):
            line(x, 262, x, 277)
        line(155, 267, 205, 267)
        cell(doc.cipher, 85, 237, 120, 10, cap=3.5)
        cell(doc.object_name, 85, 247, 120, 15)
        cell(doc.object_part, 85, 262, 70, 15)
        cell(doc.sheet_title, 85, 277, 70, 15)
        cell(doc.organization, 155, 277, 50, 15)
        for x, width, label, value in ((155, 15, 'Стадия', doc.stage_label),
                (170, 15, 'Лист', str(page_number) if total > 1 else ''),
                (185, 20, 'Листов', str(total) if page_number == 1 else '')):
            cell(label, x, 262, width, 5)
            cell(value, x, 267, width, 10, cap=3.5)
        for y, role, name in ((262, 'Разраб.', doc.developer_name),
                (267, 'Проверил', doc.inspector_name), (272, 'Нач. отд.', doc.dept_head_name),
                (282, 'Н. контр.', doc.norm_control_name), (287, 'ГИП', doc.gip_name)):
            cell(role, 20, y, 20, 5)
            cell(name, 40, y, 20, 5)
    else:
        # Form 6: designation 110 mm, sheet field 10 mm; split 7 / 8 mm.
        line(195, 277, 195, 292, .5)
        line(195, 284, 205, 284)
        cell(doc.cipher, 85, 277, 110, 15, cap=3.5)
        cell('Лист', 195, 277, 10, 7)
        cell(str(page_number), 195, 284, 10, 8, cap=3.5)
    c.showPage()
    c.save()
    return output.getvalue()


def apply_frame(pdf, doc, *, layout='a4_text'):
    if layout not in ('a4_text', 'a3_text', 'a3_graphic'):
        raise ValueError('Неизвестный формат рамки: ' + layout)
    width = 420 if layout.startswith('a3_') else 210
    reader = PdfReader(BytesIO(pdf))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    total = len(reader.pages)
    for i, page in enumerate(writer.pages, 1):
        if (abs(float(page.mediabox.width) - width * mm) > .1
                or abs(float(page.mediabox.height) - 297 * mm) > .1
                or page.rotation or float(page.mediabox.left) or float(page.mediabox.bottom)):
            raise ValueError(f'Рамка {layout} требует лист {width}×297 мм без поворота и смещения')
        overlay = PdfReader(BytesIO(frame_pdf(doc, i, total, layout=layout)))
        page.merge_page(overlay.pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()

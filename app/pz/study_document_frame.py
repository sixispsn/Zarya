"""Forms 3/6 for educational text attachments, without a project release claim."""
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

from app.pz.drafting_font import DRAFTING_FONT_PATH
from app.pz.project import DocumentInfo
from app.pz.text_document_frame import apply_frame


class _StudyDocumentInfo(DocumentInfo):
    @property
    def stage_label(self) -> str:
        # An opt-in study is neither an assigned P nor an assigned R stage.
        return ""


def build_study_text_pdf(story, *, title: str, sheet_title: str, cipher: str,
                         layout: str = "a4_text", detail: str = "") -> bytes:
    if layout not in ("a4_text", "a3_text"):
        raise ValueError("Учебное текстовое приложение требует А4 или А3")
    width = 210 if layout == "a4_text" else 420
    font = "StudyFrameNotice"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, str(DRAFTING_FONT_PATH)))
    notice = "Учебная проверка. Не для выпуска и заказа материалов."
    for line in (notice, detail):
        if pdfmetrics.stringWidth(line, font, 10) > (width - 35) * mm:
            raise ValueError("Служебная подпись учебного приложения не помещается")

    def header(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 10)
        canvas.drawString(25 * mm, 284 * mm, notice)
        if detail:
            canvas.drawString(25 * mm, 278 * mm, detail)
        canvas.restoreState()

    output = BytesIO()
    document = BaseDocTemplate(output, pagesize=(width * mm, 297 * mm),
                               title=title, author="ЗАРЯ")
    templates = []
    for name, bottom in (("first", 65), ("continuation", 25)):
        # Body ends >= 5 mm above the form-3/form-6 top (237/277 mm).
        frame = Frame(25 * mm, bottom * mm, (width - 35) * mm,
                      (275 - bottom) * mm, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, id=name)
        templates.append(PageTemplate(id=name, frames=[frame], onPage=header,
                                      autoNextPageTemplate="continuation"))
    document.addPageTemplates(templates)
    document.build(story)
    reader = PdfReader(BytesIO(output.getvalue()))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.add_outline_item(title, 0)
    bookmarked = BytesIO()
    writer.write(bookmarked)
    return apply_frame(bookmarked.getvalue(), _StudyDocumentInfo(
        cipher=cipher, object_name="Учебная модель. Не для выпуска",
        sheet_title=sheet_title, organization="ЗАРЯ"), layout=layout)

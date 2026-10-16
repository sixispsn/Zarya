"""Paginated non-release status sheets; no engineering geometry or calculations."""
from dataclasses import asdict
from html import escape
from io import BytesIO
from itertools import groupby
from pathlib import Path
import os
import tempfile

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.pz.drafting_font import DRAFTING_FONT_PATH, ensure_drafting_font_registered
from app.pz.graphic_document_frame import drawing_frame_svg
from app.pz.project import DocumentInfo

FONT = "WastewaterStatusGOST"
SIZE, LEADING, LEFT, RIGHT = 5., 8., 30., 826.
TOP, BOTTOM = 100., 508.
NOTICE = "Контроль исходных данных. Не проектная документация. Схема не сформирована."
KINDS = {
    "k1-k2": ("К1/К2", "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА",
              "Рендерер не добавляет условные трубы, прочистки, переходы и отметки."),
    "k3": ("К3", "СХЕМА К3 НЕ СФОРМИРОВАНА",
           "Генератор не добавляет условные трубы, оборудование, прочистки и напорные участки."),
    "pressure": ("К1н/К3н", "СХЕМА НЕ СФОРМИРОВАНА",
                 "Генератор не подбирает условный насос и не достраивает напорную сеть."),
}


class _StatusDocumentInfo(DocumentInfo):
    @property
    def stage_label(self):
        return ""


def wrap_measured(value, width=RIGHT - LEFT, size=SIZE):
    """Wrap by actual font width, including long identifiers; never ellipsize."""
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(DRAFTING_FONT_PATH)))
    text = " ".join(str(value).split())
    lines = []
    while text:
        end = 0
        for index in range(1, len(text) + 1):
            if pdfmetrics.stringWidth(text[:index], FONT, size) > width:
                break
            end = index
        if not end:
            raise ValueError("Строка контрольного листа не помещается")
        if end < len(text):
            space = text.rfind(" ", 0, end + 1)
            if space > 0:
                end = space
        lines.append(text[:end])
        text = text[end:].lstrip()
    return lines or [""]


def _text(x, y, value, size=SIZE, attributes=""):
    return (f'<text x="{x:g}" y="{y:g}" font-family="OpenGOST type B" '
            f'font-size="{size:g}" {attributes}>{escape(value)}</text>')


def build_status_svgs(document, reasons, *, kind):
    system, title, explanation = KINDS[kind]
    # A status sheet is not an assigned design stage. Keep object/cipher intact.
    doc = _StatusDocumentInfo(**asdict(document))
    rows = []
    for key, value in (("object", f"Объект: {document.object_name or 'Объект не указан'}"),
                       ("cipher", f"Шифр: {document.cipher or 'Шифр не указан'}")):
        rows.extend((key, line) for line in wrap_measured(value))
    rows.append(("heading", "Замечания, препятствующие формированию схемы:"))
    for index, reason in enumerate(reasons, 1):
        rows.extend((str(index), line) for line in wrap_measured(f"{index}. {reason}"))
    if not reasons:
        rows.append(("missing", "Причины неполноты не переданы. Готовность схемы не подтверждена."))
    capacity = int((BOTTOM - TOP) / LEADING) + 1
    chunks, current = [], []
    for _, group in groupby(rows, key=lambda row: row[0]):
        block = list(group)
        # Keep an ordinary reason together; only a reason longer than a page
        # may continue, with an explicit continuation label below.
        if current and len(block) <= capacity and len(current) + len(block) > capacity:
            chunks.append(current)
            current = []
        while block:
            room = capacity - len(current)
            current.extend(block[:room])
            block = block[room:]
            if len(current) == capacity:
                chunks.append(current)
                current = []
    if current:
        chunks.append(current)
    pages = []
    for number, chunk in enumerate(chunks, 1):
        continuation = " · Продолжение списка" if number > 1 else ""
        if number > 1 and chunk[0][0].isdigit() and chunks[number - 2][-1][0] == chunk[0][0]:
            continuation = f" · Продолжение замечания {chunk[0][0]}"
        body = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="841mm" height="594mm" '
            f'viewBox="0 0 841 594" data-status-document="{kind}" data-release-ready="false">',
            '<rect width="841" height="594" fill="white"/>',
            _text(LEFT, 23, f"ИОС3 · {system} · КОНТРОЛЬ ПОЛНОТЫ ИСХОДНЫХ ДАННЫХ"),
            _text(LEFT, 40, title, 8),
            _text(LEFT, 54, explanation),
            _text(LEFT, 68, NOTICE, 4),
            _text(LEFT, 85, f"Лист {number} из {len(chunks)}" + continuation, 4),
        ]
        body.extend(_text(LEFT, TOP + i * LEADING, value,
                          attributes=f'data-status-row="{key}"') for i, (key, value) in enumerate(chunk))
        body.extend((
            _text(LEFT, 523, "Требуется дополнить исходные данные и повторить проверку. Этот лист не разрешает выпуск схемы.", 4),
            drawing_frame_svg(doc, width_mm=841, height_mm=594,
                              title="Контроль исходных данных. Не для выпуска", system_label=system,
                              sheet_no=number, sheet_total=len(chunks)),
            '</svg>',
        ))
        pages.append("".join(body))
    return tuple(pages)


def generate_status_pdf(document, reasons, output_path, *, kind):
    """Render completely in memory; atomically replace only after success."""
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    ensure_drafting_font_registered()
    pages = build_status_svgs(document, reasons, kind=kind)
    writer = PdfWriter()
    for svg in pages:
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    writer.add_metadata({"/Title": f"Контроль исходных данных {KINDS[kind][0]}. Не проектная документация"})
    writer.add_outline_item("Схема не сформирована. Полный список замечаний", 0)
    data = BytesIO()
    writer.write(data)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data.getvalue())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return str(path)

"""Measure and paginate existing specification rows in paper millimetres.

WeasyPrint measures the same columns/fonts/wrapped text it prints. Only page
breaks, repeated headings and empty grid rows change, never spec.py's data.
"""
from pathlib import Path
import re

from weasyprint import CSS, HTML
from weasyprint.formatting_structure.boxes import TableRowBox

MM = 96 / 25.4
FIRST_HEIGHT_MM = 232.0  # y=5..237, above the 55 mm title block
NEXT_HEIGHT_MM = 272.0   # y=5..277, above the 15 mm continuation block
BORDER_MM = .3
TEMPLATES = Path(__file__).parent / 'templates'


def specification_pages(spec, env):
    sections, measured = [], []
    for si, section in enumerate(spec.sections):
        if not section.rows:
            continue
        prefixes = {}
        for continued in (False, True):
            suffix = ' (продолжение)' if continued else ''
            entries = []
            if section.division:
                entries.append(dict(kind='division', key=f'd{si}-{continued}', title=section.division+suffix))
            entries.append(dict(kind='section', key=f's{si}-{continued}', title=section.title+suffix))
            prefixes[continued] = entries
            measured.extend(entries)
        rows = [dict(kind='item', key=f'r{si}-{ri}', row=row) for ri, row in enumerate(section.rows)]
        sections.append((prefixes, rows))
        measured.extend(rows)
    note = dict(kind='note', key='note', text=spec.note) if spec.note else None
    if note:
        measured.append(note)
    body = env.get_template('spec_table.html').render(pages=[dict(rows=measured, blanks=[])])
    # This tall canvas is used only for measurement, never exported.
    height = max(2000, (len(measured)+1)*300)
    document = HTML(string='<html><body>'+body+'</body></html>', base_url=str(TEMPLATES)).render(
        stylesheets=[CSS(filename=str(TEMPLATES/'spec_frame.css')),
                     CSS(filename=str(TEMPLATES/'spec.css')),
                     CSS(string=f'@page {{ size: 420mm {height}mm; margin: 5mm 5mm 0 20mm; }}'
                                '@page :first { margin-bottom: 0; }')])
    heights = {}
    for page in document.pages:
        for box in page._page_box.descendants():
            if isinstance(box, TableRowBox) and box.element is not None:
                key = box.element.get('data-layout-key')
                if key:
                    if key in heights:
                        raise ValueError('Строка спецификации выше доступного поля листа: '+key)
                    heights[key] = box.height/MM
    if set(heights) != {'header', *(e['key'] for e in measured)}:
        raise ValueError('Не удалось измерить все строки спецификации')
    pages, current = [], []
    used = heights['header'] + BORDER_MM

    def capacity():
        return FIRST_HEIGHT_MM if not pages else NEXT_HEIGHT_MM

    def total(entries):
        return sum(heights[e['key']] for e in entries)

    def finish():
        nonlocal current, used
        remaining = max(0, capacity()-used-.05)
        count = int(remaining//5)
        blanks = [5.] * count
        rest = remaining-count*5
        if blanks:
            blanks[-1] += rest
        elif current and remaining:
            # Do not draw a hairline-height "empty row" at the title block.
            # Absorb the <5 mm remainder into the final real row instead.
            last = current[-1]
            current[-1] = dict(last, height_mm=heights[last['key']]+remaining)
        pages.append(dict(rows=current, blanks=blanks, height_mm=capacity()))
        current = []
        used = heights['header'] + BORDER_MM

    for prefixes, rows in sections:
        for ri, row in enumerate(rows):
            extra = prefixes[False] if ri == 0 else []
            required = total([*extra, row])
            if used+required > capacity()+1e-5:
                if current:
                    finish()
                extra = prefixes[ri > 0]
                required = total([*extra, row])
            if used+required > capacity()+1e-5:
                raise ValueError('Строка спецификации выше доступного поля листа: '+row['row'].name)
            current.extend([*extra, row])
            used += required
    if note:
        if used+total([note]) > capacity() and current:
            finish()
        if used+total([note]) > capacity():
            raise ValueError('Общие примечания спецификации не помещаются на лист')
        current.append(note)
        used += total([note])
    finish()
    return pages


def render_specification_body(spec, env):
    return env.get_template('spec_table.html').render(pages=specification_pages(spec, env))


def write_specification_pdf(html, output_path, doc):
    """Do not deliver a silently reflowed sheet after a renderer/font change."""
    from weasyprint.formatting_structure.boxes import TableBox
    document = HTML(string=html, base_url=str(TEMPLATES)).render(stylesheets=[
        CSS(filename=str(TEMPLATES/name))
        for name in ('spec_frame.css', 'spec.css', 'measured_spec_frame.css')])
    row_ids = set()
    for index, page in enumerate(document.pages):
        boxes = list(page._page_box.descendants())
        sheets = {b.element.get('data-spec-sheet') for b in boxes
                  if b.element is not None and b.element.get('data-spec-sheet')}
        tables = [b for b in boxes if isinstance(b, TableBox) and b.element.get('class') == 'spec']
        limit = 237 if index == 0 else 277
        if sheets != {str(index+1)} or len(tables) != 1:
            raise ValueError('Нарушена разбивка листов спецификации')
        table = tables[0]
        if (abs((table.position_y+table.border_height())/MM-limit) > .2
                or table.position_y/MM < 4.8):
            raise ValueError('Таблица спецификации вышла за поле до штампа')
        for box in boxes:
            if isinstance(box, TableRowBox) and box.element is not None:
                key = box.element.get('data-layout-key', '')
                if key.startswith('r'):
                    if key in row_ids:
                        raise ValueError('Строка спецификации разбилась между листами: '+key)
                    row_ids.add(key)
    if row_ids != set(re.findall(r'data-layout-key="(r\d+-\d+)"', html)):
        raise ValueError('При выводе спецификации потеряны строки')
    from app.pz.text_document_frame import apply_frame
    Path(output_path).write_bytes(apply_frame(document.write_pdf(), doc, layout='a3_text'))
    return output_path

"""Explicit, reproducible mixed-axis review. Not defaults for customer projects."""
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.preview_metering_detail import catalogue_review_project


def mixed_review_project(direction='vertical_up'):
    p = catalogue_review_project()
    d = p.metering_detail
    d.assembly_orientation = d.meter_mounting = direction
    d.component_orientations = {'filter': 'horizontal_dial_up'}
    d.fitting_items = {'filter_turn_in': 'valtec-vtr090-dn32',
                       'filter_turn_out': 'valtec-vtr090-dn32'}
    d.inlet_dn = d.bypass_dn = 32
    d.reducer_items = {}
    d.connection_items = {}; d.connection_thread_items = {}
    d.catalogue_items.update(inlet_valve='valtec-vt214-dn32',
        bypass_valve='valtec-vt214-dn32', check_valve='itap-europa100-g-dn32')
    # Keep all local pipe inputs consistent with this explicit review DN.
    from copy import deepcopy
    d.pipe_sections = {r:deepcopy(d.pipe_sections['before_meter'])
                       for r in ('inlet','before_meter','after_meter','bypass','outlet')}
    d.mounting.enabled = True
    d.mounting.scale = 10
    p.document.object_name = 'Водомерный узел DN32. Горизонтальный фильтр'
    p.document.object_part = 'Проверка компоновки; не рабочая документация'
    return p


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import build_metering_layout, layout_contents
    ensure_drafting_font_registered()
    writer = PdfWriter()
    for direction in ('vertical_up','vertical_down'):
        p = mixed_review_project(direction)
        layout = build_metering_layout(p)
        if layout.issues:
            raise ValueError(layout.issues)
        start = len(writer.pages)
        contents = layout_contents(p)
        for i,body in enumerate(contents,1):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                   '<rect width="420" height="297" fill="white"/>'+body+_frame(p,i,len(contents))+'</svg>')
            writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
        writer.add_outline_item('Поток '+('снизу вверх' if direction=='vertical_up' else 'сверху вниз'),start)
    output = Path('output/pdf/ВУ_смешанная_компоновка.pdf')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('wb') as f:
        writer.write(f)
    print(output.resolve())


if __name__ == '__main__':
    main()

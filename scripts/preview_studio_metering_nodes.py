"""Reproduce the mixed VU from Studio answers; no hidden product assignments."""
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intake.studio_intake import answer_field, build_handoff_request, calculate_draft
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2


def review_draft():
    d = dict(revision=0, answers={}, documents=[])
    inputs = dict(object_name='Компоновка ВУ из настроек Studio', residents=200, apartments=80,
                  consumer_code='residential_full_bath', floors=10, building_height_m=33,
                  fire_height_m=31, fire_corridor_length_m=10, fire_topology='separate',
                  hws_type='central', guaranteed_head_m=30,
                  h_geom_m=33, pressure_loss_mode='ready', h_il_m=3, h_vvod_m=1,
                  t3_loss_mode='ready', h_il_hot_m=4, hws_heater_in_scope='no',
                  vu_orientation='vertical_up', vu_hot_orientation='horizontal_dial_up',
                  vu_filter_layout='valtec_vt192_vtr090', vu_drawing_scale='10')
    for key, value in inputs.items():
        answer_field(d, key, value)
    d['calculation'] = calculate_draft(d)
    return d


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import build_metering_layout, layout_contents
    ensure_drafting_font_registered()
    p = design_ios2(build_project(build_handoff_request(review_draft())),
                   output_dir=Path('tmp/pdfs/studio-vu-nodes'), render_documents=False).project
    layout = build_metering_layout(p)
    if layout.issues:
        raise ValueError(layout.issues)
    contents = layout_contents(p)
    writer = PdfWriter()
    for i, body in enumerate(contents, 1):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
               '<rect width="420" height="297" fill="white"/>' + body + _frame(p, i, len(contents)) + '</svg>')
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    writer.add_outline_item('Компоновка основного ввода', 0)
    if len(contents) > 1:
        writer.add_outline_item('Состав узла и ограничения', 1)
    output = Path('output/pdf/ВУ_Studio_раздельные_узлы.pdf')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as stream:
        writer.write(stream)
    print(output.resolve())


if __name__ == '__main__':
    main()

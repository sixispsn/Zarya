"""Reproduce separate cold/hot drawings from ordinary Studio inputs."""
from io import BytesIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.preview_studio_metering_nodes import review_draft
from app.intake.studio_intake import build_handoff_request, answer_field
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from app.pz.metering_detail import _frame
from app.pz.metering_hot_node import hot_detail_contents
from app.pz.metering_layout import layout_contents


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    ensure_drafting_font_registered()
    d = review_draft()
    p = design_ios2(build_project(build_handoff_request(d)),
                   output_dir=Path('tmp/pdfs/hot-meter-preview'), render_documents=False).project
    contents = layout_contents(p) + hot_detail_contents(p)
    writer = PdfWriter()
    for i, body in enumerate(contents, 1):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
               '<rect width="420" height="297" fill="white"/>' + body + _frame(p,i,len(contents)) + '</svg>')
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    writer.add_outline_item('ХВС. Вертикальный узел с горизонтальным фильтром',0)
    writer.add_outline_item('ХВС. Состав',1)
    writer.add_outline_item('ГВС. Горизонтальный узел',2)
    writer.add_outline_item('ГВС. Состав',3)
    writer.add_outline_item('ГВС. Данные и условия',4)
    out = Path('output/pdf/ВУ_ХВС_ГВС_раздельная_деталировка.pdf')
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('wb') as f: writer.write(f)
    print(out.resolve())
    # Two additional orientations for visual regression, no hidden geometry.
    for axis in ('vertical_up','vertical_down'):
        answer_field(d,'vu_hot_orientation',axis)
        v = design_ios2(build_project(build_handoff_request(d)),
                       output_dir=Path('tmp/pdfs/hot-meter-preview'), render_documents=False).project
        body = hot_detail_contents(v)[0]
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
               '<rect width="420" height="297" fill="white"/>'+body+_frame(v,1,1)+'</svg>')
        cairosvg.svg2pdf(bytestring=svg.encode(),write_to=f'tmp/pdfs/hot-meter-preview/{axis}.pdf')


if __name__ == '__main__':
    main()

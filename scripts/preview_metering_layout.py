"""Connected catalogue-driven VU layout; no fictitious installation dimensions."""
from pathlib import Path
from io import BytesIO
import argparse
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cairosvg
from pypdf import PdfReader, PdfWriter
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.metering_detail import _frame
from app.pz.metering_layout import layout_contents
from scripts.preview_metering_detail import catalogue_review_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalogue-joints', action='store_true',
                        help='Предложить ниппель по фактическим портам из проверенного каталога')
    parser.add_argument('--service-components', action='store_true',
                        help='Предложить контрольные краны, пробки и манометр по текущему давлению')
    parser.add_argument('--seismicity', type=int, choices=(7, 8, 9, 10),
                        help='Отдельный контрольный случай особых условий; не менять обычный пример')
    args = parser.parse_args()
    project=catalogue_review_project()
    if args.seismicity is not None:
        project.building.seismicity=args.seismicity
    if args.catalogue_joints:
        project.metering_detail.inline_joint_selection_mode='catalogue_proposal'
    if args.service_components:
        project.metering_detail.service_selection_mode='catalogue_proposal'
    project.metering_detail.mounting.enabled=True
    project.document.object_name="Водомерный узел. Размерная компоновка"
    project.document.object_part="Изделия М 1:5; соединения уточнить"
    contents=layout_contents(project)
    ensure_drafting_font_registered()
    writer=PdfWriter()
    for i,content in enumerate(contents,1):
        svg=('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
             '<rect width="420" height="297" fill="white"/>'+content+_frame(project,i,len(contents))+'</svg>')
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    output=Path('output/pdf/ВУ_сейсмические_условия.pdf' if args.seismicity is not None
                else 'output/pdf/ВУ_связная_компоновка.pdf')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('wb') as stream:
        writer.write(stream)
    print(output.resolve())


if __name__=='__main__':
    main()

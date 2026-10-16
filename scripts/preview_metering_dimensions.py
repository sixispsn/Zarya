"""Reproducible PDF QA for the dimensional layer, not a fabrication release."""
from pathlib import Path
import sys
from io import BytesIO

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cairosvg
from pypdf import PdfReader, PdfWriter
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.metering_detail import drawing_state, _frame
from app.pz.metering_mounting import mounting_contents
from scripts.preview_metering_detail import catalogue_review_project


def main():
    p=catalogue_review_project()
    p.metering_detail.mounting.enabled=True
    p.document.object_name="Водомерный узел. Проверка размерной модели"
    p.document.object_part="Паспортные изделия; компоновка не завершена"
    contents=mounting_contents(p,drawing_state(p))
    ensure_drafting_font_registered()
    writer=PdfWriter()
    for i,content in enumerate(contents,1):
        svg=('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
             '<rect width="420" height="297" fill="white"/>'+content+_frame(p,i,len(contents))+'</svg>')
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
    output=Path('output/pdf/ВУ_паспортные_размеры_1-5.pdf')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('wb') as stream: writer.write(stream)
    print(output.resolve())


if __name__=='__main__': main()

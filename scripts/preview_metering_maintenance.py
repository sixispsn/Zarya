"""Reproduce the vertical VU, source-backed composition and service defects."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from scripts.preview_metering_vertical_reference import review_project
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_layout import layout_contents
    from app.pz.metering_detail import _frame
    from app.pz.metering_maintenance import maintenance_contents
    ensure_drafting_font_registered()
    with TemporaryDirectory() as directory:
        p = review_project(Path(directory), maintenance_layout='serviceable')
        p.document.object_name = 'Контроль обслуживания вертикального ВУ'
        p.document.object_part = 'Проверка компоновки; не рабочий проект'
        layout_pages = layout_contents(p)
        bodies = [*layout_pages,*maintenance_contents(p)]
        writer = PdfWriter()
        for index,body in enumerate(bodies,1):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                   '<rect width="420" height="297" fill="white"/>'+body+_frame(p,index,len(bodies))+'</svg>')
            writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
        writer.add_outline_item('Вертикальная компоновка - размеры УГО',0)
        writer.add_outline_item('Состав и паспортные размеры',1)
        writer.add_outline_item('Проверка обслуживания',len(layout_pages))
        output = Path('output/pdf/ВУ_проверка_обслуживания.pdf')
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('wb') as stream:
            writer.write(stream)
        print(output.resolve())
        print(f'{len(bodies)} pages')


if __name__ == '__main__':
    main()

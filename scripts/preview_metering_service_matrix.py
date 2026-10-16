"""Three explicit Studio cases; not defaults or a changed Samara design."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CASES = (
    ('horizontal_dial_up', 'valtec_vt386', 'Горизонтальный узел'),
    ('vertical_up', 'valtec_vt386', 'Вертикальный узел: поток вверх'),
    ('vertical_down', 'valtec_vt192_vtr090', 'Вертикальный узел: поток вниз'),
)


def review_case(folder, orientation, filter_layout):
    from scripts.preview_metering_vertical_reference import review_project
    return review_project(folder, maintenance_layout='serviceable',
                          orientation=orientation, filter_layout=filter_layout)


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import layout_contents, build_metering_layout
    ensure_drafting_font_registered()
    writer = PdfWriter()
    with TemporaryDirectory() as directory:
        for orientation, filter_layout, title in CASES:
            p = review_case(Path(directory), orientation, filter_layout)
            p.document.object_name = title
            p.document.object_part = 'Контроль компоновки ВУ DN15; не рабочий проект'
            layout = build_metering_layout(p)
            if layout.issues or not layout.parts:
                raise ValueError((orientation, layout.issues))
            bodies = layout_contents(p)
            start = len(writer.pages)
            for i, body in enumerate(bodies, 1):
                svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                       '<rect width="420" height="297" fill="white"/>' + body + _frame(p, i, len(bodies)) + '</svg>')
                writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
            writer.add_outline_item(title, start)
    output = Path('output/pdf/ВУ_три_компоновки.pdf')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as stream:
        writer.write(stream)
    print(f'{output.resolve()}: {len(writer.pages)} pages')


if __name__ == '__main__':
    main()

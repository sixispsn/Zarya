"""Reproducible dimensional review, not a completed building design."""
from pathlib import Path
from io import BytesIO
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.data.engineering_catalogue import get_engineering_catalogue
from app.pz.metering_flexible import FlexibleConnectionChoice
from app.pz.metering_pipes import MeteringPipeSection
from scripts.preview_metering_detail import catalogue_review_project
from scripts.preview_metering_flanged import flanged_review_project


def review_case(vertical=False):
    p = catalogue_review_project() if vertical else flanged_review_project(80)
    d = p.metering_detail
    d.mounting.enabled = True
    d.mounting.scale = 10
    if vertical:
        d.assembly_orientation = d.meter_mounting = 'vertical_down'
        d.connection_items = {}; d.connection_thread_items = {}
        p.document.object_name = 'Контроль вертикального ВУ DN32'
    else:
        d.pipe_sections['inlet'] = MeteringPipeSection(material='steel', nominal_dn=80,
            outer_diameter_mm=89,wall_thickness_mm=4,joining='welded',
            geometry_source='Геометрический контрольный пример; не ввод реального объекта')
        p.document.object_name = 'Контроль горизонтального ВУ DN80'
    p.document.object_part = 'Проверка компоновки; не рабочая документация'
    c = get_engineering_catalogue()
    ident = f'rushwork-501-dn{d.inlet_dn}'
    # Explicit fixture inputs. They are NOT defaults of the product.
    d.flexible_connections['inlet'] = FlexibleConnectionChoice(
        catalogue_id=ident,catalogue_fingerprint=c.fingerprint(ident),
        compression_mm=0,extension_mm=0,angular_deg=0,lateral_mm=0,
        movement_basis='Контроль геометрии при нулевых перемещениях; не расчёт КР',
        mating_flange_type='11',mating_flange_face='B',mating_flange_series=2 if d.inlet_dn==80 else 1,
        mounting_precompression_mm=4 if vertical else None)
    return p


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import layout_contents, build_metering_layout
    ensure_drafting_font_registered()
    writer = PdfWriter()
    pictures=[]
    for vertical in (False, True):
        p=review_case(vertical)
        layout=build_metering_layout(p)
        if layout.issues:
            raise ValueError(layout.issues)
        contents=layout_contents(p)
        for i,body in enumerate(contents,1):
            pictures.append((p,body,i,len(contents)))
    for p,body,page,total in pictures:
        svg=('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
             '<rect width="420" height="297" fill="white"/>'+body+_frame(p,page,total)+'</svg>')
        index=len(writer.pages)
        writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
        if page==1:
            writer.add_outline_item(p.document.object_name,index)
    output=Path('output/pdf/ВУ_вертикальная_компоновка_и_гибкие_вставки.pdf')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('wb') as f:
        writer.write(f)
    print(output.resolve())


if __name__=='__main__':
    main()

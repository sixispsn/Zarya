"""Reproduce the upward VU through Studio, not a hand-drawn replacement.

The user's VALTEC-00.2010 sheet 3 is a symbol/arrangement reference only.
Current VT.386 dimensions come from ПС-47335-3, not the historical album.
Explicit review inputs below are not defaults or a finished building design.
"""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def review_project(output_dir, *, maintenance_layout='existing',
                   orientation='vertical_up', filter_layout='valtec_vt386'):
    from app.intake.studio_intake import answer_field, build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    draft = dict(revision=0, answers={}, documents=[])
    values = dict(residents=20, apartments=8, consumer_code='residential_full_bath',
                  floors=2, building_height_m=6.6, fire_height_m=4.8, hws_type='central',
                  guaranteed_head_m=5, h_geom_m=6, pressure_loss_mode='ready',
                  h_il_m=3, h_vvod_m=1, t3_loss_mode='ready', h_il_hot_m=4,
                  hws_heater_in_scope='no', vu_orientation=orientation,
                  vu_hot_orientation='horizontal_dial_up', vu_drawing_scale='5',
                  vu_filter_layout=filter_layout, vu_maintenance_layout=maintenance_layout)
    for key, value in values.items():
        answer_field(draft, key, value)
    request = load_request(dump_request(build_handoff_request(draft)))
    p = design_ios2(build_project(request), output_dir=output_dir, render_documents=False).project
    p.document.object_name = 'Контроль вертикального ВУ DN15'
    p.document.object_part = 'Сравнение УГО с альбомом VALTEC; не рабочий проект'
    d = p.metering_detail
    # Explicit geometry/review choices; existing saved projects are not changed.
    d.room_number, d.room_name = '001', 'Водомерная'
    d.inlet_dn = d.bypass_dn = 15
    d.design_pressure_bar, d.water_temperature_c = 6, 20
    d.catalogue_items = {'meter_valves':'valtec-vt214-dn15',
                         'inlet_valve':'valtec-vt214-dn15',
                         'bypass_valve':'valtec-vt214-dn15',
                         'check_valve':'itap-europa100-g-dn15'}
    return p


def main():
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import _frame
    from app.pz.metering_layout import layout_contents, build_metering_layout
    ensure_drafting_font_registered()
    with TemporaryDirectory() as directory:
        p = review_project(Path(directory))
        layout = build_metering_layout(p)
        if layout.issues:
            raise ValueError(layout.issues)
        pages = layout_contents(p)
        writer = PdfWriter()
        for index, body in enumerate(pages, 1):
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                   '<rect width="420" height="297" fill="white"/>'+body+_frame(p,index,len(pages))+'</svg>')
            writer.append(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))))
        writer.add_outline_item('Вертикальный ВУ: восходящий поток',0)
        if len(pages)>1:
            writer.add_outline_item('Состав и паспортные размеры',1)
        output = Path('output/pdf/ВУ_вертикальный_восходящий_проверка.pdf')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('wb') as stream:
            writer.write(stream)
        print(output.resolve())
        print(f'{len(pages)} pages; meter L={layout.part("meter").length_mm}; filter L={layout.part("filter").length_mm}')


if __name__ == '__main__':
    main()

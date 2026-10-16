"""A paper-space connection sheet for the explicitly configured study station.

Uses the water UGO library and the shared SPDS frame, not another symbol set.
This sheet defines the hydraulic boundary; it is not a manufacturer assembly
drawing or a completed electrical/automation design.
"""
from pathlib import Path
from xml.sax.saxutils import escape

from app.pz import ugo
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.wastewater_building_drafting import drawing_frame_svg


def build_fire_station_study_sheet(project, station):
    p = project.fire_pumps
    parts = []
    def text(x, y, value, size=3.5, anchor="start"):
        parts.append(f'<text x="{x}" y="{y}" font-family="OpenGOST type B" font-size="{size}" '
                     f'text-anchor="{anchor}">{escape(value)}</text>')
    def line(x1,y1,x2,y2,w=.6):
        parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="black" stroke-width="{w}"/>')
    def valve(x,y):
        parts.append(ugo.gate_h(x,y,tri=2.5,bar=3,w=.35))
    def check(x,y):
        parts.append(ugo.check_h(x,y,tri=2.5,w=.35))
    text(25,18,"В2. Расчётная компоновка общей пожарной насосной",5)
    text(25,27,f"Кандидат Q/H: {p.model} · 1 рабочий + 1 резервный",4)
    text(25,35,f"Qрасч={p.q_design_m3h:.2f} м³/ч; Hнас={p.h_design_m:.2f} м; "
         f"N двигателя={p.power_kw:.2f} кВт (не электрическое потребление станции)")
    text(25,43,f"Ось насосов {station.pump_axis_m:+.3f} м; пол насосной -3,250 м; "
         "помещение НС-01 условно, экспликацию подтвердить по АР")
    parts.append('<rect x="155" y="70" width="130" height="93" fill="none" '
                 'stroke="black" stroke-width=".25" stroke-dasharray="3 1"/>')
    text(220,66,"Обвязку и DN патрубков сверить с комплектом поставки",3.3,"middle")
    line(150,90,150,145); line(290,90,290,145)
    for idx,y in enumerate((90,145),1):
        line(32,y,403,y)
        valve(78,y);check(110,y)
        valve(176,y);parts.append(ugo.pump(210,y,r=5,w=.5));check(241,y);valve(270,y)
        valve(340,y)
        parts.append(f'<path d="M379,{y-1.7} L379,{y+1.7} L383,{y} Z" fill="black"/>')
        text(33,y-9,f"Наружный ввод {idx} · DN100 · L=20 м")
        text(33,y+10,"Hгар=30 м; ось -2,195 м")
        text(210,y+13,f"Н{idx} · {'рабочий' if idx==1 else 'резервный'}",3.5,"middle")
        text(323,y-9,f"К кольцу В2, выход {idx} · DN100")
        text(323,y+10,"L=20 м; кольцо на отм. -0,650")
    for x, label in ((131,"PG1"),(314,"PG2")):
        line(x,90,x,75,.25)
        parts.append(f'<circle cx="{x}" cy="71" r="4" fill="white" stroke="black" stroke-width=".25"/>')
        text(x,61,label,3.3,"middle")
        line(x-1.8,73,x+1.8,69,.25)
    text(147,116,"Всасывающий",3.1,"end")
    text(147,121,"коллектор",3.1,"end")
    text(293,116,"Напорный",3.1)
    text(293,121,"коллектор",3.1)
    line(315,145,315,180);line(315,180,392,180);valve(345,180)
    text(315,189,"Испытательный отвод: расходомер и приёмник уточнить",3.1)
    text(25,176,"До насоса при полном расходе одного наружного ввода:")
    text(25,183,f"Hвсас ≥ {station.minimum_suction_head_m:.3f} м; "
         f"после НУ требуется {station.hydraulic.required_head_at_source_m:.3f} м.")
    text(25,198,"1. Входную/выходную арматуру снабдить контролем положения; АВР и пуск — по СП 10, раздел 12.",3.3)
    text(25,205,"2. Предусмотреть дренаж, спуск и удаление воздуха; места и DN уточнить по компоновке и паспорту НУ.",3.3)
    text(25,212,"3. Регулирование и зонирование не завершены. Давление по этажам — см. контрольное приложение.",3.3)
    text(25,219,"4. Схема фиксирует учебные связи. Не подтверждает помещение, монтажную компоновку и полный состав автоматики.",3.3)
    frame = drawing_frame_svg(project.document, width_mm=420,height_mm=297,
        title="Насосная В2: расчётная компоновка",system_label="В2")
    return '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'+ \
        '<rect width="420" height="297" fill="white"/>'+''.join(parts)+frame+'</svg>'


def generate_fire_station_study_sheet(path, project, station):
    import cairosvg
    ensure_drafting_font_registered()
    svg = build_fire_station_study_sheet(project,station)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode(),write_to=str(path))
    return str(path)

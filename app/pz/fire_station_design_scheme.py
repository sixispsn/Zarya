"""Two A3 principle sheets for the bound station and representative V2 network.

No guessed manufacturer assembly dimensions or full-building coverage claim.
Inventory IDs link the drawing to station_spec_rows; geometry is paper-space.
"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from app.pz import ugo
from app.pz.fire_station_binding import station_spec_rows
from app.pz.wastewater_building_drafting import drawing_frame_svg
from app.pz.section_level_mark import level_mark
from app.data.fire_diaphragm_layout import diaphragm_groups, floor_label


class Sheet:
    def __init__(self, project, title, page):
        self.parts = ['<rect width="420" height="297" fill="white"/>']
        self.project, self.title, self.page = project, title, page

    def text(self, x, y, value, size=3.5, anchor='start'):
        self.parts.append(f'<text x="{x}" y="{y}" font-family="OpenGOST type B" '
            f'font-size="{size}" text-anchor="{anchor}">{escape(str(value))}</text>')

    def line(self, x1, y1, x2, y2, width=.6):
        self.parts.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="black" stroke-width="{width}"/>')

    def arrow(self, x, y, direction=1):
        self.parts.append(f'<path d="M{x},{y} l{-direction*3},-1.2 v2.4 Z" fill="black"/>')

    def valve(self, x, y, label, component):
        self.parts.append(f'<g data-component="{component}">'+ugo.gate_h(x,y,tri=2.5,bar=3,w=.25)+'</g>')
        self.text(x,y+9,label,3.5,'middle')

    def pressure(self, x, y, label):
        self.line(x,y,x,y-10,.25)
        self.parts.append(f'<g data-component="pressure"><circle cx="{x}" cy="{y-14}" r="3.5" '
                          'fill="white" stroke="black" stroke-width=".25"/></g>')
        self.line(x-1.5,y-12.5,x+1.5,y-15.5,.25)
        self.text(x,y-21,label,3.5,'middle')

    def svg(self):
        frame = drawing_frame_svg(self.project.document,width_mm=420,height_mm=297,
            title=self.title,system_label='В2',sheet_no=self.page,sheet_total=2)
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'
                + ''.join(self.parts)+frame+'</svg>')


def build_design_sheets(project, station):
    r = project.fire_pumps.station_design
    if not r:
        raise ValueError('Bound station calculation required')
    inventory = {row['id']: row for row in station_spec_rows(r)}
    s = Sheet(project,'Насосная В2. Принципиальная схема',1)
    s.text(25,18,s.title,5)
    s.text(25,27,'CNP CDM32-3: 1 рабочий + 1 установленный резервный. Характеристика одиночного насоса.',4)
    s.text(25,35,f"Qмин={r['required_q_m3h']:.3f} м3/ч; Hнас, треб={r['required_bare_pump_head_m']:.3f} м; N двигателя 5,5 кВт каждый.")
    s.text(25,43,f"Ось насосов {station.pump_axis_m:+.3f} м; пол {project.building.floor_elevations_m[-1]:+.3f} м. Номер помещения - по экспликации АР.")
    # Two feeds combine BEFORE the active branch, two outlets AFTER it.
    for i,y in enumerate((87,146),1):
        s.line(28,y,83,y);s.arrow(47,y)
        supply = station.supplies[i-1]
        s.text(28,y-11,f'Ввод {i} DN100; L=20 м')
        s.text(28,y+10,'Hгар=30 м; отм. -2,195')
        s.line(340,y,402,y);s.arrow(393,y)
        s.text(348,y-11,f'К кольцу: выход {i}')
        s.text(348,y+10,'DN100; L=20 м')
        s.line(139,y,292,y)
        s.valve(162,y,f'З{2 if i==1 else 3}', 'suction-valve-65')
        s.pressure(186,y,f'PG{2*i-1}')
        s.parts.append('<g data-component="pumps">'+ugo.pump(212,y,r=5,w=.5)+'</g>')
        s.parts.append('<g data-component="discharge-check">'+ugo.check_h(237,y,tri=2.5,w=.25)+'</g>')
        s.pressure(251,y,f'PG{2*i}')
        s.valve(277,y,f'З{4 if i==1 else 5}','discharge-valve-65')
        s.text(212,y+10,f'Н{i}: '+('рабочий' if i==1 else 'резервный'),3.5,'middle')
        s.text(237,y+10,f'КО{i}',3.5,'middle')
        s.text(212,y+18,'Ветвь DN65',3.5,'middle')
    for x in (83,139,292,340):s.line(x,87,x,146)
    s.line(83,117,139,117);s.valve(110,117,'З1','suction-valve-100')
    s.line(292,117,340,117);s.valve(317,117,'З6','discharge-valve-100')
    s.text(110,106,'DN100',3.5,'middle');s.text(317,106,'DN100',3.5,'middle')
    s.text(25,174,'Принятая обвязка и состав спецификации',4)
    s.text(25,183,'З1, З6: Kv ≥ 200 м3/ч; З2–З5: Kv ≥ 100 м3/ч; КО1, КО2: эквивалентный Kv ≥ 50 м3/ч.')
    s.text(25,191,'Коллекторы DN100: суммарно 2 м. Ветви DN65: суммарно 2 м на два насоса; в активном пути 1 м.')
    s.text(25,199,'Фасонина: принято суммарное ζ=2 на всасывании и ζ=2 на напоре активной ветви; не ведомость фитингов.')
    s.text(25,207,'Спуск, воздухоудаление, испытательный отвод, дренаж и опоры: состав и DN дополнить по компоновке.')
    s.text(25,215,'PG1–PG4 и положения арматуры - в задание автоматизации. Схема не является монтажным чертежом.')
    s.text(25,223,'Внешняя арматура вводов/кольца вне расчётной обвязки. Принятое сопротивление не является паспортом изделия.')

    t = Sheet(project,'В2. Характерные стояки и кольцо',2)
    t.text(25,18,t.title,5)
    t.text(25,27,'Два расчётных стояка DN65; один насос питает оба выхода общего напорного коллектора.',4)
    # Three representative floors, one cut through the whole section.
    for floor,y in ((16,70),(2,149),(1,187)):
        t.line(58,y,276,y,.25)
        z=project.building.floor_elevations_m[floor]
        t.parts.append(level_mark(f'v2-floor-{floor}',50,y,z,f'{floor} этаж',reference_x=58,decimals=3))
        t.text(168,y-28,'Коридор · характерный фрагмент',3.5,'middle')
        for idx,x in enumerate((93,232),1):
            t.line(x,y-10,x+24,y-10)
            t.parts.append(ugo.pk(x+28,y-10,r=3,w=.35,conn=('l',)))
            t.text(x+10,y-18,f'ПК{idx}; DN50',3.5)
            hole=r['nominal_apertures_mm'].get(str(floor),r['nominal_apertures_mm'].get(floor))
            t.text(x+7,y-3,f'Диафр. {hole:g} мм' if hole else 'Без диафрагмы',3.5)
            if hole:
                t.line(x+6,y-5,x+3,y-10,.25)
                t.parts.append(f'<path d="M{x+3},{y-10} l1,3 l1,-1 Z" fill="black"/>')
    for x in (58,276):
        t.line(x,38,x,92,.25);t.line(x,112,x,187,.25)
    for x in (93,232):
        t.line(x,48,x,92);t.line(x,112,x,200 if x==93 else 220)
        t.text(x-4,45,f'Ст.В2-{1 if x==93 else 2} DN65',3.5,'middle')
    # Architectural cut with tails, no floating pipe tails or individual slashes.
    for y in (92,112):
        t.parts.append(f'<path d="M48,{y} H157 l3,-4 v8 l3,-4 H286" fill="none" stroke="black" stroke-width=".25"/>')
    t.text(168,104,'Этажи 3–15 условно пропущены',3.5)
    # Ring: second riser crosses the near side without connecting there.
    t.line(93,200,227,200);t.line(237,200,266,200)
    t.line(266,200,266,220);t.line(266,220,93,220);t.line(93,220,93,200)
    t.line(28,200,93,200);t.arrow(78,200)
    t.line(308,220,232,220);t.arrow(280,220,-1)
    t.text(28,194,'Выход 1 НС');t.text(275,214,'Выход 2 НС')
    t.text(120,214,'Кольцо В2 DN100; отм. -0,650 м')
    t.text(302,43,'Диафрагмы DN50',4)
    t.text(302,52,'Этажи');t.text(334,52,'Отверстие, мм')
    groups=diaphragm_groups(r['nominal_apertures_mm'])
    for j,group in enumerate(groups):
        t.text(302,63+j*10,floor_label(group));t.text(342,63+j*10,f"{group['aperture_mm']:g}")
    t.text(302,64+10*len(groups),'16');t.text(334,64+10*len(groups),'без шайбы')
    for y,line in enumerate(['Отметка верхнего ПК +46,350.', 'Ствол 13 мм; рукав 20 м.',
        'Два характерных стояка.',
        'Отключения проверены.' if r.get('repair_review') else 'Неповреждённое кольцо.',
        'Полная расстановка ПК,', 'покрытие помещений и', 'количество диафрагм -', 'по окончательным планам.']):
        t.text(302,82+10*len(groups)+8*y,line)
    return [s.svg(),t.svg()]


def generate_design_scheme(path, project, station):
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    ensure_drafting_font_registered()
    writer=PdfWriter()
    for i,svg in enumerate(build_design_sheets(project,station)):
        writer.add_page(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))).pages[0])
        writer.add_outline_item(('Насосная В2','Стояки и кольцо В2')[i],i)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open('wb') as f:writer.write(f)
    return str(path)

"""A3 cabinet detail sheet from the same bound schedule as PZ/spec.

Only named representative terminals; no invented floor distribution or routing.
"""
from io import BytesIO
from pathlib import Path
from textwrap import wrap
from xml.sax.saxutils import escape
import math

from app.pz import ugo
from app.pz.fire_review_binding import validate_binding
from app.pz.wastewater_building_drafting import drawing_frame_svg


def build_review_sheet(project, *, page=2, total=2):
    r = validate_binding(project)
    if r is None:
        raise ValueError("Нужен принятый предварительный вариант В2")
    columns = 1 if len(r['schedule']) <= 4 else 2
    width = 210 if columns == 1 else 420
    out = [f'<rect width="{width}" height="297" fill="white"/>']
    def text(x, y, value, size=3.5):
        out.append(f'<text x="{x}" y="{y}" font-family="OpenGOST type B" font-size="{size}">{escape(str(value))}</text>')
    def line(x,y,x2,y2,w=.25):
        out.append(f'<path d="M{x},{y} L{x2},{y2}" fill="none" stroke="black" stroke-width="{w}"/>')
    text(25,16,"В2. Узлы установки диафрагм",5)
    text(25,25,f"{project.fire_pumps.model}; 1 рабочий + 1 резервный.")
    text(25,32,f"Контрольный режим: Q={project.fire_pumps.wp_q:.3f} м3/ч; H={project.fire_pumps.wp_h:.3f} м.")
    text(25,39,"Между пожарным клапаном и соединительной головкой (СП 10, п. 7.5).")
    for i, row in enumerate(r["schedule"]):
        x, y = 25+(i%columns)*190, 47+(i//columns)*43
        out.append(f'<g data-cabinet="{escape(row["riser"])}" data-position="{row["id"]}" '
                   f'data-aperture-mm="{row["aperture_mm"]}">')
        for j, name in enumerate(wrap(row["riser"], width=36)):
            text(x+2,y+6+4*j,name)
        text(x+2,y+15,f"ПК DN{row['valve_dn']}; отметка {row['elevation_m']:+.3f} м")
        py = y+30
        line(x+3,py,x+3,py-9,.6)
        line(x+3,py,x+125,py,.6)
        out.append(f'<g data-fire-valve-x="{x+40}">'+ugo.pk(x+40,py,r=4,w=.35,conn=("l","r"))+'</g>')
        text(x+134,py-1,"Головка;")
        text(x+134,py+4,"к рукаву",3)
        if row['aperture_mm'] is not None:
            # Leader marks the location; it is not an invented diaphragm UGO.
            out.append(f'<g data-diaphragm-location-x="{x+82}">')
            line(x+82,py,x+91,py-8)
            line(x+91,py-8,x+175,py-8)
            out.append(f'<path d="M{x+82},{py} l1.4,-3 l1.4,1.4 Z" fill="black"/>')
            text(x+93,py-10,f"{row['id']}. Диафрагма")
            text(x+93,py-3,f"Отверстие {row['aperture_mm']:g} мм")
            out.append('</g>')
        else:
            text(x+78,py-7,"Без диафрагмы")
        text(x+2,y+40,"Положение диафрагмы указано выноской; монтажные размеры не заданы.",3)
        out.append('</g>')
    text(25,227,"Позиции едины с ПЗ и спецификацией; число изделий по зданию — по планам.",3)
    text(25,233,"Лист узлов не заменяет схему разводки В2. Посадка и допуски — по изделию.",3)
    out.append(drawing_frame_svg(project.document,width_mm=width,height_mm=297,
        title="В2. Узлы диафрагм",system_label="В2",sheet_no=page,sheet_total=total))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="297mm" viewBox="0 0 {width} 297">'+''.join(out)+'</svg>'


def generate_review_scheme(path, project):
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.fire_principle_scheme import build_principle_sheets
    ensure_drafting_font_registered()
    writer=PdfWriter()
    sheets, graph_page, total = build_principle_sheets(project)
    sheets.extend([(build_network_sheet(project, page=graph_page, total=total), 'В2. Расчётная сеть'),
                   (build_review_sheet(project, page=total, total=total), 'В2. Узлы диафрагм')])
    for svg, title in sheets:
        writer.add_page(PdfReader(BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))).pages[0])
        writer.add_outline_item(title,len(writer.pages)-1)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open('wb') as stream:
        writer.write(stream)
    return str(path)


def build_network_sheet(project, *, page=1, total=2):
    """Exact connectivity, not an invented architectural layout or pipe length.

    Nodes on a ring are paper layout only. Reference codes join the explicit
    graph and cabinet branches; crossing strokes without a dot are not joins.
    """
    r=validate_binding(project)
    model=project.fire_station_model_input
    net=model['network']
    ids={name:f'N{i+1}' for i,name in enumerate(net['node_elevations'])}
    points={name:(112+72*math.cos(2*math.pi*i/len(ids)),112+51*math.sin(2*math.pi*i/len(ids)))
            for i,name in enumerate(ids)}
    out=['<rect width="420" height="297" fill="white"/>']
    def text(x,y,value,size=3.5):
        out.append(f'<text x="{x}" y="{y}" font-family="OpenGOST type B" font-size="{size}">{escape(str(value))}</text>')
    def line(x,y,xx,yy,w=.5):
        out.append(f'<path d="M{x},{y} L{xx},{yy}" stroke="black" fill="none" stroke-width="{w}"/>')
    text(25,16,'В2. Схема соединений расчётной модели',5)
    text(25,25,f"{project.fire_pumps.model}; Н1 рабочий, Н2 резервный. Резерв выключен, расход не суммируется.")
    text(25,34,'Положение узлов условное. Длины и отметки подписаны из исходных, не измеряются по листу.',3)
    for i,s in enumerate(model['supplies']):
        text(25,43+i*7,f"{s['name']}: Hгар={s['guaranteed_head_m']:g} м; Hmax={s['maximum_head_m']:g} м; Z={s['source_elevation_m']:+.3f} м.",3)
    occupied=[(x-5,y-6,x+17,y+5) for x,y in points.values()]
    labels=[]
    for i,e in enumerate(net['runs']):
        a,b=points[e['from_node']],points[e['to_node']]
        out.append(f'<g data-from="{escape(e["from_node"])}" data-to="{escape(e["to_node"])}">')
        line(*a,*b)
        out.append('</g>')
        for t in (.5,.35,.65,.25,.75,.15,.85):
            x,y=a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])
            box=(x-4,y-3,x+5,y+2)
            if not any(box[0]<bb[2] and box[2]>bb[0] and box[1]<bb[3] and box[3]>bb[1] for bb in occupied):
                occupied.append(box)
                labels.append((x,y,f'M{i+1}'))
                break
        # If the graph is dense, the complete M/from/to ledger remains the
        # authority. Never obscure node marks to force a floating label.
    for x,y,label in labels:
        out.append(f'<rect x="{x-4}" y="{y-3}" width="9" height="5" fill="white"/>')
        text(x-3,y+1,label,3)
    for name,(x,y) in points.items():
        out.append(f'<circle cx="{x}" cy="{y}" r="1" fill="black"/>')
        text(x+2,y-2,ids[name],3)
        text(x+2,y+3,f"{net['node_elevations'][name]:+.3f}",2.5)
    text(25,177,f"Общий коллектор Н1/Н2: выходы {ids[net['source_node']]} и {ids[net['second_source_node']]}; ось {model['pump_axis_m']:+.3f} м.",3)
    # These small hydraulic fragments have explicit references into the graph;
    # we never run a fake physical riser to every floor of the building.
    for i,(s,entry) in enumerate(zip(net['risers'],r['schedule'])):
        y=55+i*15
        text(212,y,f"{s['name']} от {ids[s['at_node']]}; DN{s['dn']}; L={s['height_m']:g} м; ПК {s['cabinet_elevation_m']:+.3f} м",3)
        line(215,y+8,278,y+8)
        out.append(ugo.pk(247,y+8,r=2.5,w=.3,conn=('l','r')))
        text(284,y+9,(f"{entry['id']}: отверстие {entry['aperture_mm']:g} мм" if entry['aperture_mm'] is not None else 'Без диафрагмы'),3)
    # All edges are included; do not silently shorten large networks to fit.
    for i,e in enumerate(net['runs']):
        col,row=i//8,i%8
        text(25+col*96,185+row*5,
            f"M{i+1}: {ids[e['from_node']]}-{ids[e['to_node']]} DN{e['dn']} L={e['length_m']:g} м",2.5)
    text(25,228,'Коды N — узлы в порядке исходной модели; рядом указаны отметки. Все магистрали включены в ведомость.',3)
    text(25,234,f'Пересечения без точки не соединены. Узлы ПК — на листе {total}. Положение узлов условное.',3)
    out.append(drawing_frame_svg(project.document,width_mm=420,height_mm=297,title='В2. Расчётная сеть',system_label='В2',sheet_no=page,sheet_total=total))
    return '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297">'+''.join(out)+'</svg>'

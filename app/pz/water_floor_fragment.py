"""Approval-only, compact В1 floor/basement composition in paper millimetres.

The supplied GOST R 21.619-2023 Appendix Б is the composition reference.
This is deliberately NOT a replacement for the production dispatcher. The
explicit full-bath profile is a representative residential group, not inferred
AR, a fixture inventory or a bill of quantities. Hydraulic results are read
only, through the existing binding; no calculation or sizing is performed.
"""
from dataclasses import dataclass
from html import escape
from math import isfinite
from xml.etree import ElementTree as ET

from app.pz import ugo
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.metering_detail import _text, _line, _path, _leader, _label_width, _lines
from app.pz.section_construction import section_slab_svg
from app.pz.water_pipe_binding import bind_v1_pipes
from app.pz.water_regulation_plan import branch_regulation_plan
from app.pz.water_station_drafting import _level, _pipe, _flow
from app.pz.wastewater_building_drafting import drawing_frame_svg


WIDTH, HEIGHT = 420, 297
LEFT, RIGHT, CENTRE = 78., 390., 234.
CUT, FLOOR, MAIN, BASEMENT = 60., 137., 153., 193.
APARTMENT_Y = 127.


@dataclass(frozen=True)
class WaterFixtureGlyph:
    svg: str
    port: tuple[float, float]


def water_fixture(kind, x, branch_y, *, mirrored=False):
    """Adapt existing accepted water UGO, retaining their exact feed ports.

    Mixer tail ends at centre + 3.14*s (NOT the old renderer's 3.04*s).
    The WC symbol has a side feed at 0.32*150 and total height 242 units.
    Those coordinates are shared by the drawing and the connector, so scaling
    a symbol cannot leave an invisible gap between the pipe and its port.
    """
    side = "left" if mirrored else "right"
    if kind in {"sink", "basin", "bath"}:
        s, tail_y = 3.4, branch_y-2
        y = tail_y-3.14*s
        painter = ugo.shower if kind == "bath" else ugo.washbasin
        svg = painter(x,y,s=s,w=.25,side=side)
        port = (x, tail_y)
    elif kind == "wc":
        scale = .07
        # Align the side-fed tank's actual port, not the tank centre.
        top = branch_y-2-242*scale
        sx = -scale if mirrored else scale
        cx = x-48*sx
        svg = (f'<g transform="translate({cx:g},{top:g}) scale({sx:g},{scale:g})">'
               + ugo.toilet(0,0,w=.25/scale) + '</g>')
        port = (x, branch_y-2)
    else:
        raise ValueError(f"Unsupported residential water fixture: {kind}")
    return WaterFixtureGlyph(svg,port)


def _tag(name, body, **attrs):
    data = ' '.join(f'data-{k.replace("_","-")}="{escape(str(v))}"' for k,v in attrs.items())
    return f'<g data-fragment-component="{escape(name)}" {data}>{body}</g>'


def _pipe_label(x, y, label, *, h=3.5):
    width = _label_width(label,h)+2
    return (f'<rect x="{x-width/2:g}" y="{y-h-1:g}" width="{width:g}" '
            f'height="{h+2:g}" fill="white"/>' + _text(x,y+1.2,label,h,"middle"))


def _datum(value, name):
    if type(value) not in (int,float) or not isfinite(value):
        raise ValueError(f"Фрагмент В1: нужна заданная отметка {name}")
    return value


def _callout(ident, target, knee, outer, title, detail):
    """Use the existing leader engine, with the same vector text as pipe labels.

    OpenGOST has no diameter glyph. Preserve the engine's shelf/arrow metadata
    while replacing only text runs needing that glyph, not the shared engine.
    """
    if max(_label_width(title,3.5),_label_width(detail,3.5))+2 > abs(outer-knee[0]):
        raise ValueError(f"Выноска {ident}: недостаточная длина полки")
    root = ET.fromstring(_leader(ident,target,knee,outer,title,detail))
    for index,node in enumerate(list(root)):
        if node.tag != 'text' or not any(c in (node.text or '') for c in ('Ø','⌀')):
            continue
        vector_text = ET.fromstring('<g>'+_text(float(node.get('x')),float(node.get('y')),node.text,3.5)+'</g>')
        vector_text.attrib.update({k:v for k,v in node.attrib.items() if k.startswith('data-')})
        root.remove(node)
        root.insert(index,vector_text)
    return ET.tostring(root,encoding='unicode')


def build_water_floor_fragment(project, *, profile):
    """One first-floor fragment, with two mirrored representative groups.

    Requiring a profile is intentional: drawing a bath because the program
    lacks a fixture schedule must not silently become a project decision.
    Only the observed physical elevations and bound pipe sizes are reused.
    """
    from app.pz.scheme import SchemeResult
    if profile != "residential_full_bath":
        raise ValueError("Для пробного фрагмента выберите residential_full_bath")
    if project.building.purpose.value != "residential" or project.building.floors_below != 1:
        raise ValueError("Этот фрагмент предназначен для жилой части с одним подвалом")
    if project.building.zones != 1:
        raise ValueError("Многозонную схему нельзя заменять однозонным фрагментом")
    if type(project.building.floors_above) is not int or project.building.floors_above < 2:
        raise ValueError("Фрагмент с продолжением стояков предназначен для здания от двух этажей")
    first = _datum(project.building.floor_elevations_m.get(1),"пола первого этажа")
    base = _datum(project.building.floor_elevations_m.get(-1),"пола подвала")
    inlet = _datum(project.metering_detail.inlet_elevation_m,"оси ввода")
    if not base < inlet < first:
        raise ValueError("Для этого фрагмента ось ввода должна находиться между полом подвала и первым этажом")
    input_count = project.source.inputs_count
    if type(input_count) is not int or input_count < 1:
        raise ValueError("Нужно заданное число вводов")
    ensure_drafting_font_registered()
    pipes = bind_v1_pipes(project)
    regulation = branch_regulation_plan(project)
    warnings = [
        "Компоновочный фрагмент В1 для согласования, не полный лист систем здания.",
        "Две зеркальные группы приборов заданы профилем, не распознаны из АР Самары.",
        "Не определяет количество стояков, приборов и метраж труб в спецификации.",
        "Оси магистралей, узлы проходок и конструкция плит требуют АР/КР.",
        *(p.issue for p in pipes.values() if p.issue),
        *([regulation.issue] if regulation.issue else []),
    ]
    g = [_text(28,19,"В1. Характерный этаж и подвал",5),
         _text(28,29,"Фрагмент для согласования компоновки. Без масштаба.",3.5)]

    # Compact room bays. No invented AR room numbers or structural dimensions.
    boundaries = (LEFT,LEFT+2,118,180,202,266,288,350,RIGHT-2,RIGHT)
    for x in boundaries:
        g.append(_line(x,CUT,x,FLOOR,.25))
    for x in (LEFT,LEFT+2,RIGHT-2,RIGHT):
        g.append(_line(x,FLOOR,x,BASEMENT,.25))
    rooms = ((98,"Кухня"),(149,"Санузел"),(234,"Общая зона"),
             (319,"Санузел"),(370,"Кухня"))
    for x,title in rooms:
        g.append(_text(x,72,title,3.5,"middle"))
    g += [section_slab_svg("v1-fragment-first",LEFT,RIGHT,FLOOR),
          section_slab_svg("v1-fragment-base",LEFT,RIGHT,BASEMENT,depth_mm=6,role="basement_floor"),
          _level("v1-fragment-floor",66,FLOOR,first,"1 этаж",reference_x=LEFT),
          _level("v1-fragment-base",66,BASEMENT,base,"Подвал",reference_x=LEFT)]

    for mirror in (False,True):
        side = "right" if mirror else "left"
        xmap = (lambda x:2*CENTRE-x) if mirror else (lambda x:x)
        riser, meter_x = xmap(191),xmap(173)
        g.append(_pipe(f"{side}-riser",[(riser,MAIN),(riser,CUT)],start="main",end=f"{side}-upper"))
        g.append(_flow(riser,65,-90))
        g.append(_text(riser,49,"К верхним этажам",3.5,"middle"))
        # Explicit tee to apartment, leaving the regulated upper-floor transit open.
        g.append(_pipe(f"{side}-apartment-feed",[(riser,79),(meter_x,79),(meter_x,APARTMENT_Y),
                                                  (xmap(99),APARTMENT_Y)],
                       start=f"{side}-riser",end=f"{side}-apartment"))
        g.append(f'<circle cx="{riser:g}" cy="79" r=".8" fill="black"/>')
        chain = [ugo.valve_v(meter_x,85,tri=1.8,dot=.7,w=.25),
                 ugo.filt(meter_x,93,hd=2.5,vd=2,ext=0,rot=90,w=.25),
                 ugo.meter(meter_x,110,rw=6,rh=4,ext=0,rot=90,w=.25),
                 ugo.check_v(meter_x,119,tri=1.8,w=.25)]
        g.append(_tag("apartment-meter-chain",''.join(chain),side=side,system="В1"))
        if regulation.shows("В1",1):
            g.append(_tag("apartment-regulator",ugo.redvalve(meter_x,102,rw=6,rh=4,ext=0,rot=90,w=.25),
                          side=side,system="В1",floor=1,scope="accepted-stage-p-principle"))
            g.append(_text(meter_x+(4 if mirror else -4),103,"РД",2.5,"start" if mirror else "end"))
        g.append(ugo.valve_v(riser,146,tri=1.8,dot=.7,w=.25))
        g.append(_flow(riser,132,-90))
        for kind,xx in (("sink",99),("bath",126),("basin",147),("wc",160)):
            x = xmap(xx)
            fixture = water_fixture(kind,x,APARTMENT_Y,mirrored=mirror)
            key = f"{side}-{kind}"
            g.append(_pipe(f"feed-{key}",[(x,APARTMENT_Y),fixture.port],start=f"{side}-apartment",end=key))
            g.append(_tag("fixture",fixture.svg,kind=kind,side=side,port_x=fixture.port[0],
                          port_y=fixture.port[1],source="explicit-representative-profile"))
            g.append(f'<circle cx="{x:g}" cy="{APARTMENT_Y:g}" r=".55" fill="black"/>')
        g.append(_text(xmap(140),133,"В1 "+pipes["apartment"].label,2.5,"middle"))
    # Leaders in the shared room bay, not across fixture symbols or meter chains.
    g += [_callout("left-riser",(191,87),(207,96),239,"Стояк В1",pipes["riser"].label),
          _callout("right-riser",(277,113),(261,121),229,"Стояк В1",pipes["riser"].label)]

    # One characteristic inlet only: never claim this is the complete two-inlet
    # topology. The detailed VU/pump sheets remain authoritative.
    inlet_y = FLOOR+(BASEMENT-FLOOR)*(first-inlet)/(first-base)
    source_end = (98,inlet_y)
    g.append(_pipe("inlet-fragment",[(58,inlet_y),source_end],start="outside",end="station-reference"))
    g.append(_flow(91,inlet_y))
    # Opening sleeve drawn around the same wall-crossing pipe, not a separate stub.
    g += [_line(LEFT-2,inlet_y-2,LEFT+4,inlet_y-2,.25),
          _line(LEFT-2,inlet_y+2,LEFT+4,inlet_y+2,.25),
          _level("inlet-axis",65,inlet_y,inlet,"Ось ввода",width=28,reference_x=LEFT)]
    pump_caption = "Насосная установка В1" if project.pumps.required else "Водомерный узел В1"
    box_top = inlet_y-8
    g.append(_tag("station-reference",
        f'<rect x="98" y="{box_top:g}" width="66" height="16" fill="white" '
        'stroke="black" stroke-width=".25"/>'
        + _text(131,inlet_y-1,pump_caption,3.5,"middle")
        + _text(131,inlet_y+5,"ВУ / обвязка - отдельные схемы",2.5,"middle"),
        detail="separate-drawing",displayed_inlets=1,total_inlets=input_count))
    g.append(_pipe("station-main",[(164,inlet_y),(171,inlet_y),(171,MAIN),(277,MAIN)],
                   start="station-reference",end="main"))
    for riser in (191,277):
        g.append(f'<circle cx="{riser}" cy="{MAIN:g}" r=".8" fill="black"/>')
    g += [_flow(181,MAIN),_flow(270,MAIN),
          _pipe_label(232,MAIN,"В1 "+pipes["main"].label),
          _text(84,161,"В1 "+pipes["inlet"].label,2.5),
          _text(315,186,"Подвал",3.5,"middle"),
          _callout("suspended-main",(260,MAIN),(297,168),376,"Магистраль под перекрытием","Отметка - по компоновке")]

    # A single cut traverses the entire building and has 10 mm tails. All
    # architectural/riser lines terminate on it (rather than stopping short).
    g.append(_tag("full-width-cut",_path(
        f'M{LEFT-10:g},{CUT:g} H{CENTRE-4:g} l3,-4 v8 l3,-4 H{RIGHT+10:g}',.25),
        left=LEFT-10,right=RIGHT+10,tail_mm=10))

    notes = [
        "Показаны две характерные группы помещений; их компоновка условная, не план АР.",
        f"Показан один характерный ввод; по исходным вводов: {input_count}. Остальные ветви здесь не показаны.",
        "Размеры труб взяты из текущего расчётного примера. Геометрия листа не задаёт длины труб.",
        "Т3/Т4 и В2 в этот фрагмент не входят. Полный состав узлов - на отдельных схемах.",
        "Высоты плит и размещение оборудования условные. Монтажные привязки - по АР/КР.",
    ]
    y = 210.
    for i,note in enumerate(notes,1):
        for line in _lines(f"{i}. {note}",370,h=3.5):
            g.append(_text(28,y,line,3.5)); y += 5.5
    # An explicit key for the existing water-side UGO, not sewer fixture symbols.
    g += [_text(28,253,"Условные обозначения",3.5),
          ugo.washbasin(35,263,s=2.1,w=.25),_text(46,265,"Смеситель мойки / умывальника",2.5),
          ugo.shower(159,263,s=2.1,w=.25),_text(171,265,"Ванна с душем",2.5),
          ugo.meter(35,283,rw=6,rh=4,ext=0,w=.25),_text(46,284,"Счётчик воды",2.5),
          ugo.redvalve(159,283,rw=6,rh=4,ext=0,w=.25),_text(171,284,"РД на ветви",2.5)]
    g.append(drawing_frame_svg(project.document,width_mm=WIDTH,height_mm=HEIGHT,
        title="В1. Этаж и подвал (фрагмент)",system_label="В1"))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
           'viewBox="0 0 420 297" data-water-floor-fragment="approval-only" '
           'data-release-ready="false" data-takeoff-eligible="false" '
           f'data-profile="{profile}"><rect width="420" height="297" fill="white"/>'
           + ''.join(g) + '</svg>')
    return SchemeResult(svg=svg,width=WIDTH,height=HEIGHT,warnings=warnings)

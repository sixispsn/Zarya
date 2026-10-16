"""Compact residential В1/Т3/Т4 cutaway, extending the accepted floor fragment.

Paper-space drawing only. It consumes current pipe bindings and explicit
residential profile, not inferred AR or a fabricated network for takeoff.
Reference: supplied GOST R 21.619-2023 Appendix Б; mixers use the supplied
GOST 21.205-2016 table 6 item 25. The original В1 fragment remains intact.
Only the explicitly selected full-bath residential profile is routed here;
unsupported profiles and topologies retain their existing paths.
"""
from dataclasses import dataclass
from html import escape
from xml.etree import ElementTree as ET

from app.pz import ugo
from app.pz.building_cutaway import representative_floors
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.hws_presentation import hws_principle, hws_zone_count
from app.pz.metering_detail import _text, _line, _path, _lines
from app.pz.section_construction import section_slab_svg
from app.pz.water_floor_fragment import water_fixture, _callout, _pipe_label, _tag, _datum
from app.pz.water_pipe_binding import bind_v1_pipes, bind_t3_pipes
from app.pz.water_regulation_plan import branch_regulation_plan
from app.pz.water_service_assemblies import shows_riser_balance
from app.pz.water_apartment_assembly import apartment_components
from app.pz.section_level_mark import level_text
from app.pz.water_station_drafting import _pipe, _flow, _level
from app.pz.wastewater_building_drafting import drawing_frame_svg


WIDTH, HEIGHT = 594.,420.
LEFT, RIGHT, CENTRE = 78.,572.,325.
ROOF, PITCH = 50.,66.
AXES = {'left':{'В1':250.,'Т3':258.,'Т4':266.},
        'right':{'В1':400.,'Т3':392.,'Т4':384.}}
ROOM_EDGES = (LEFT,LEFT+2,119.,240.,273.,377.,410.,531.,RIGHT-2,RIGHT)
MIXER_HALF_WIDTH = 4.2


def _bound_label(system,binding,svg):
    """Identify the actual annotated role, not any matching number on a sheet."""
    return (f'<g data-pipe-binding="{system}-{binding.role}">'
            +svg+'</g>')


def can_draw_residential_water_section(project):
    """No assistant-prepared geometry: use the actual intake consumer profile.

    Do not replace an explicit fixture schedule with the representative group,
    flatten multiple consumer types, or discard the existing scope guards.
    """
    from app.pz.water_building_section import can_draw_water_section
    if not can_draw_water_section(project) or project.fixtures or not shows_riser_balance(project):
        return False
    if {row[0] for row in project.consumer_groups} != {'residential_full_bath'}:
        return False
    try:
        residential_water_layout(project)
    except (ValueError,TypeError):
        return False
    return True


@dataclass(frozen=True)
class ResidentialWaterLayout:
    floors: tuple[int,...]
    floor_ys: tuple[float,...]
    break_edges: tuple[float,float] | None
    basement_y: float
    main_ys: dict[str,float]


def residential_water_layout(project):
    if project.building.purpose.value != 'residential' or project.building.floors_below != 1:
        raise ValueError('Компоновка предназначена для жилой части с одним подвалом')
    if project.building.zones != 1 or hws_zone_count(project) != 1:
        raise ValueError('Многозонная схема требует отдельной компоновки')
    if project.building.hws_type.value != 'central':
        raise ValueError('Общую Т4 нельзя добавлять при местном ГВС или без ГВС')
    floors = representative_floors(project.building.floors_above)
    compressed = len(floors) < project.building.floors_above
    ys = tuple(ROOF+PITCH*(len(floors)-i)+(18 if compressed and i < len(floors)-1 else 0)
               for i in range(len(floors)))
    first = _datum(project.building.floor_elevations_m.get(1),'первого этажа')
    base = _datum(project.building.floor_elevations_m.get(-1),'пола подвала')
    inlet = _datum(project.metering_detail.inlet_elevation_m,'оси ввода')
    if not base < inlet < first:
        raise ValueError('Ось ввода должна находиться между полом подвала и первым этажом')
    previous = None
    for floor in floors:
        z = _datum(project.building.floor_elevations_m.get(floor),f'{floor} этажа')
        if previous is not None and previous >= z:
            raise ValueError('Отметки этажей должны возрастать')
        previous = z
    roof = _datum(project.sewage.roof_relative_elevation_m,'кровли')
    if roof <= previous:
        raise ValueError('Кровля должна быть выше верхнего этажа')
    count = project.source.inputs_count
    if type(count) is not int or count < 1:
        raise ValueError('Нужно заданное число вводов')
    return ResidentialWaterLayout(floors,ys,(ys[-1]+5,ys[-1]+17) if compressed else None,
        ys[0]+70,{'Т3':ys[0]+13,'Т4':ys[0]+24,'В1':ys[0]+35})


def _horizontal(key,a,b,y,system,*,crossings=(),start='',end=''):
    lo,hi = sorted((a,b))
    d = f'M{lo:g},{y:g}'
    halos = []
    for x in sorted(x for x in crossings if lo+2 < x < hi-2):
        d += f' H{x-1.2:g} A1.2,1.2 0 0 1 {x+1.2:g},{y:g}'
        halos.append(f'<path data-bridge-halo="true" d="M{x-1.2:g},{y:g} A1.2,1.2 0 0 1 {x+1.2:g},{y:g}" '
                     'fill="none" stroke="white" stroke-width="1.6"/>')
    return ''.join(halos)+_path(d+f' H{hi:g}',.6,
        f'data-pipe="{key}" data-system="{system}" data-from="{start}" data-to="{end}" '
        'data-scope="representative" data-crossings="without-connection"')


def _vertical(key,x,a,b,system,*,crossings=(),start='',end=''):
    lo,hi = sorted((a,b))
    d = f'M{x:g},{lo:g}'
    halos = []
    for y in sorted(y for y in crossings if lo+2 < y < hi-2):
        d += f' V{y-1.2:g} A1.2,1.2 0 0 1 {x:g},{y+1.2:g}'
        halos.append(f'<path data-bridge-halo="true" d="M{x:g},{y-1.2:g} A1.2,1.2 0 0 1 {x:g},{y+1.2:g}" '
                     'fill="none" stroke="white" stroke-width="1.6"/>')
    return ''.join(halos)+_path(d+f' V{hi:g}',.6,
        f'data-pipe="{key}" data-system="{system}" data-from="{start}" data-to="{end}" '
        'data-scope="representative" data-crossings="without-connection"')


def _mixer(x,y,*,shower=False,mirror=False):
    """Two separate incoming ports, not a tee merging В1 and Т3.

    Table 6 item 25: two triangles, nozzle below; the feed is at the lateral
    vertices. The fixture's mixed outlet is NOT a third supply pipe.
    """
    # Paper-space dimensions: keep the table-6 proportions, but don't let a
    # fixture disappear beside the 0.6 mm supply pipes at normal PDF zoom.
    s,h,w = MIXER_HALF_WIDTH,2.35,.35
    nozzle = x+(-3.7 if mirror else 3.7)
    svg = [_path(f'M{x-s:g},{y:g} L{x:g},{y-h:g} L{x+s:g},{y:g} L{x:g},{y+h:g} Z',w),
           _line(x,y-h,x,y+h,w),f'<circle cx="{x:g}" cy="{y+h:g}" r=".8" fill="black"/>']
    if shower:
        dx = -3.1 if mirror else 3.1
        svg += [_path(f'M{x:g},{y-h:g} v-3.7 h{dx:g} v1.2',w),
                _path(f'M{x+dx:g},{y-h-2.5:g} l-2.2,1.7 h4.4 Z',w)]
    else:
        svg.append(_line(x,y+h,nozzle,y+h+2.1,w))
    variant = 'shower' if shower else 'swivel-spout'
    return ('<g data-water-ugo="mixer-'+variant+'" '
            'data-ugo-reference="GOST-21.205-2016-table-6-25">'+''.join(svg)+'</g>',
            (x-s,y),(x+s,y))


def _meter_chain(x,feed_y,*,regulator,components,hot=False):
    # Reserve the cold-feed crossing between the hot inlet valve and filter.
    offsets = (2,12,18,24,30) if hot else (5,11,17,23,29)
    a,b,c,d,e = offsets
    symbols = {
        'valve': ugo.valve_v(x,feed_y+a,tri=1.5,dot=.6,w=.25),
        'filter': ugo.filt(x,feed_y+b,hd=2,vd=1.7,ext=0,rot=90,w=.25),
        'meter': ugo.meter(x,feed_y+d,rw=5,rh=3.5,ext=0,rot=90,w=.25),
        'check': ugo.check_v(x,feed_y+e,tri=1.5,w=.25),
    }
    g = [f'<g data-apartment-component="{item.key}">{symbols[item.kind]}</g>'
         for item in components]
    if regulator:
        g.append(ugo.redvalve(x,feed_y+c,rw=5,rh=3.5,ext=0,rot=90,apex='left',w=.25))
    return ''.join(g)


def _apartment(project,floor,y,side,cold,hot,regulation):
    mirror = side == 'right'
    xm = (lambda x:2*CENTRE-x) if mirror else (lambda x:x)
    axes = AXES[side]
    cold_y,hot_y = y-7,y-16
    g = []
    for system,meter_x,feed_y,branch_y,binding in (
        ('В1',xm(222),y-50,cold_y,cold['apartment']),
        ('Т3',xm(235),y-56,hot_y,hot['apartment'])):
        key = f'{side}-{floor}-{system}'
        # Both crossing categories are explicit: the cold feed passes the hot
        # meter drop; the hot feed passes the cold riser except on the top floor.
        crossings = ((xm(235),) if system=='В1' else
                     (axes['В1'],) if floor != project.building.floors_above else ())
        g += [_horizontal(key+'-feed',axes[system],meter_x,feed_y,system,
                          crossings=crossings,
                          start=f'{side}-{system}-riser',end=key+'-meter'),
              _pipe(key+'-drop',[(meter_x,feed_y),(meter_x,branch_y)],system,
                    start=key+'-meter',end=key+'-branch'),
              _horizontal(key+'-branch',xm(99+(-MIXER_HALF_WIDTH if system=='В1' else MIXER_HALF_WIDTH)),meter_x,branch_y,system,
                          crossings=(xm(222),) if system=='Т3' else (),
                          start=key+'-branch',end=key+'-fixture-feeds'),
              f'<circle cx="{axes[system]:g}" cy="{feed_y:g}" r=".65" fill="black"/>',
              _tag('apartment-meter-chain',_meter_chain(meter_x,feed_y,
                   regulator=regulation.shows(system,floor),components=apartment_components(project,system),hot=system=='Т3'),
                   system=system,floor=floor,side=side)]
        if regulation.shows(system,floor):
            g.append(_tag('apartment-regulator','',system=system,floor=floor,side=side))
            g.append(_text(meter_x+(3 if mirror else -3),feed_y+(19 if system=='Т3' else 18),'РД',2.5,'start' if mirror else 'end'))
        g.append(_bound_label(system,binding,_text(xm(164),branch_y+(5 if system=='В1' else -2),
                        '%s %s'%(system,binding.label),2.5,'middle')))

    for kind,xx in (('sink',99),('bath',148),('basin',177),('wc',205)):
        x = xm(xx)
        ident = f'{side}-{floor}-{kind}'
        if kind == 'wc':
            glyph = water_fixture('wc',x,cold_y-5,mirrored=mirror)
            g += [_tag('fixture',glyph.svg,kind=kind,floor=floor,side=side,systems='В1'),
                  _vertical(ident+'-cold',x,cold_y,glyph.port[1],'В1',
                            start=f'{side}-{floor}-В1-fixture-feeds',end=ident+'-cold-port')]
            # Move the tank's valve clear of this intersection. Rebuild only
            # the crossing patch, never erase the valve or join Т3 to a WC.
            g.append(f'<rect x="{x-2:g}" y="{hot_y-2:g}" width="4" height="4" fill="white"/>')
            g.append(_vertical(ident+'-crossing',x,hot_y-2,hot_y+2,'В1',
                               start=ident+'-cold-port',end=ident+'-tank-tail'))
            # The bridge painter excludes endpoints at exactly two mm.
            g.append(_horizontal(ident+'-hot-crossing',x-2.1,x+2.1,hot_y,'Т3',crossings=(x,),
                                 start='hot-branch-continuation',end='hot-branch-continuation'))
            continue
        mixer,port_l,port_r = _mixer(x,y-31,shower=kind=='bath',mirror=mirror)
        pc,ph = (port_r,port_l) if mirror else (port_l,port_r)
        g += [_tag('fixture',mixer,kind=kind,floor=floor,side=side,systems='В1 Т3',
                   cold_port=f'{pc[0]:g},{pc[1]:g}',hot_port=f'{ph[0]:g},{ph[1]:g}'),
              # The end mixer lies outside the hot branch. Its cold leg does
              # not cross Т3, so a bridge here would mark a nonexistent pipe.
              _vertical(ident+'-cold',pc[0],cold_y,pc[1],'В1',crossings=() if kind=='sink' else (hot_y,),
                        start=f'{side}-{floor}-В1-fixture-feeds',end=ident+'-cold-port'),
              _vertical(ident+'-hot',ph[0],hot_y,ph[1],'Т3',
                        start=f'{side}-{floor}-Т3-fixture-feeds',end=ident+'-hot-port')]
    return ''.join(g)


def build_residential_water_section(project,*,profile,sheet_no=1,sheet_total=1):
    from app.pz.scheme import SchemeResult
    if not shows_riser_balance(project):
        raise ValueError('Выбранная схема балансировки требует отдельной компоновки Т3/Т4')
    if profile != 'residential_full_bath':
        raise ValueError('Для этой компоновки требуется явно выбранный residential_full_bath')
    m = residential_water_layout(project)
    ensure_drafting_font_registered()
    cold,hot = bind_v1_pipes(project),bind_t3_pipes(project)
    regulation,principle = branch_regulation_plan(project),hws_principle(project)
    first = m.floor_ys[0]
    g,labels,apartments = [],[],[]
    title = 'В1, Т3, Т4. Принципиальная схема здания'
    body = [_text(28,18,title,5),_text(28,28,'Характерный разрез. Помещения условно объединены. Без масштаба.',3.5)]
    if project.document.review_notes:
        review_lines = _lines(' '.join(project.document.review_notes),540,3.5)
        if len(review_lines)>2:
            review_lines = ['Ограничения контрольной выдачи приведены в пояснительной записке.']
        body += [_text(28,38+5.3*i,line,3.5) for i,line in enumerate(review_lines)]
    for x in ROOM_EDGES:
        g.append(_line(x,ROOF,x,first,.25))
    for x in (LEFT,LEFT+2,RIGHT-2,RIGHT):
        g.append(_line(x,first,x,m.basement_y,.25))
    g.append(_line(LEFT,ROOF,RIGHT,ROOF,.25))
    labels.append(_level('residential-water-roof',66,ROOF,project.sewage.roof_relative_elevation_m,'Кровля',reference_x=LEFT))
    for floor,y in zip(m.floors,m.floor_ys):
        ceiling = y-PITCH
        g += [section_slab_svg(f'water-floor-{floor}',LEFT,RIGHT,y),
              _text(99,ceiling+7,'Кухня',3.5,'middle'),_text(170,ceiling+7,'Санузел',3.5,'middle'),
              _text(CENTRE,ceiling+7,'Общая зона',3.5,'middle'),
              _text(480,ceiling+7,'Санузел',3.5,'middle'),_text(551,ceiling+7,'Кухня',3.5,'middle')]
        labels.append(_level(f'water-level-{floor}',66,y,project.building.floor_elevations_m[floor],f'{floor} этаж',reference_x=LEFT))
        for side in AXES:
            apartments.append(_apartment(project,floor,y,side,cold,hot,regulation))
        for system,row_y in (('В1',ceiling+20),('Т3',ceiling+34),('Т4',ceiling+48)):
            val = ('Размер не задан' if system=='Т4' else (cold if system=='В1' else hot)['riser'].label)
            callout = _callout(f'{floor}-{system}-risers',(AXES['left'][system],row_y-3),
                (286,row_y),329,'Стояк '+system,val)
            labels.append(callout if system=='Т4' else _bound_label(system,
                (cold if system=='В1' else hot)['riser'],callout))
            g.append(_text(AXES['right'][system]+(4 if system=='В1' else -4),ceiling+24,
                           system,2.5,'start' if system=='В1' else 'end'))
        if floor == 1 and regulation.floors:
            labels += [_text(335,ceiling+39,'РД на ветвях',2.5),
                       _text(335,ceiling+45,'этажей '+regulation.floor_text,2.5)]
    g.append(section_slab_svg('water-base',LEFT,RIGHT,m.basement_y,depth_mm=6,role='basement_floor'))
    labels.append(_level('water-base',66,m.basement_y,project.building.floor_elevations_m[-1],'Подвал',reference_x=LEFT))

    # Riser trunks are drawn behind the apartment symbols but above the
    # construction. Reorder via a separate layer to avoid covering devices.
    trunks = []
    for side,axes in AXES.items():
        for system in axes:
            end_y = m.floor_ys[-1]-50 if system=='В1' else ROOF+9
            start,end = (side+'-'+system+'-top',system+'-main') if system=='Т4' else (system+'-main',side+'-'+system+'-top')
            trunks.append(_pipe(f'{side}-{system}-riser',[(axes[system],m.main_ys[system]),(axes[system],end_y)],system,
                                start=start,end=end))
            for y in m.floor_ys:
                trunks.append(_flow(axes[system],y-4,90 if system=='Т4' else -90))
            if system != 'Т4':
                key = 'v1-riser-valve' if system == 'В1' else 't3-riser-valve'
                trunks.append(_tag(key,ugo.valve_v(axes[system],first+6,tri=1.5,dot=.6,w=.25),side=side))
        trunks.append(_pipe(side+'-hws-closure',[(axes['Т3'],ROOF+9),(axes['Т4'],ROOF+9)],'Т4',
                            start=side+'-Т3-top',end=side+'-Т4-top'))
        balance = ugo.balance_v(0,0,tri=16,stem=40,rk=10,w=2.5)
        sx = .1 if side=='left' else -.1
        trunks.append(_tag('circulation-balance',f'<g transform="translate({axes["Т4"]},{first+6}) scale({sx},.1)">{balance}</g>',
                           side=side,status='principle-only',dn='unknown',kv='unknown'))
    # Bring trunks just before floor contents; walls/slabs cannot hide them.
    g += trunks+apartments
    t3,t4,v1 = (m.main_ys[s] for s in ('Т3','Т4','В1'))
    g += [_horizontal('t3-main',258,442,t3,'Т3',crossings=(266,384,400),start='hws-source',end='Т3-main'),
          _horizontal('t4-main',266,442,t4,'Т4',crossings=(400,),start='Т4-main',end='hws-return'),
          _horizontal('v1-main',182,400,v1,'В1',start='station',end='В1-main')]
    for side,axes in AXES.items():
        for system in axes:
            g.append(f'<circle cx="{axes[system]:g}" cy="{m.main_ys[system]:g}" r=".7" fill="black"/>')
    for system,x in (('Т3',352),('Т4',352),('В1',352)):
        g.append(_flow(x,m.main_ys[system],180 if system=='Т3' else 0))
        label = system+' '+(('DN не задан') if system=='Т4' else (cold if system=='В1' else hot)['main'].label)
        pipe_label = _pipe_label(314,m.main_ys[system],label,h=3.5)
        g.append(pipe_label if system=='Т4' else _bound_label(system,
            (cold if system=='В1' else hot)['main'],pipe_label))

    inlet_y = first+(m.basement_y-first)*(project.building.floor_elevations_m[1]-project.metering_detail.inlet_elevation_m)/(
        project.building.floor_elevations_m[1]-project.building.floor_elevations_m[-1])
    g += [_pipe('visible-inlet',[(58,inlet_y),(98,inlet_y)],start='outside',end='station'),
          _pipe('station-out',[(166,inlet_y),(182,inlet_y),(182,v1)],start='station',end='В1-main'),
          _flow(91,inlet_y),_line(LEFT-2,inlet_y-2,LEFT+4,inlet_y-2,.25),
          _line(LEFT-2,inlet_y+2,LEFT+4,inlet_y+2,.25),
          _bound_label('В1',cold['inlet'],_text(84,inlet_y-6,'В1 '+cold['inlet'].label,2.5)),
          _tag('station-reference',f'<rect x="98" y="{inlet_y-8:g}" width="68" height="16" fill="white" stroke="black" stroke-width=".25"/>'
               +_text(132,inlet_y-1,'Насосная В1' if project.pumps.required else 'Водомерный узел',3.5,'middle')
               +_text(132,inlet_y+5,'ВУ / обвязка - отдельно',2.5,'middle'),
               displayed_inlets=1,total_inlets=project.source.inputs_count),
          _text(211,m.basement_y-5,'Подвал',3.5)]
    labels.append(_level('water-inlet',65,inlet_y,project.metering_detail.inlet_elevation_m,'Ось ввода',width=28,reference_x=LEFT))
    if principle.local_circulation_pump:
        g.append(_pipe('cold-to-hws',[(400,v1),(442,v1)],start='В1-main',end='hws-makeup'))
        g.append(_text(418,v1-3,'В1 '+hot['feed'].label,2.5,'middle'))
        source_title,source_note = 'Узел нагрева ГВС','Обвязка и НЦ - отдельно'
    else:
        source_title,source_note = 'Источник ГВС','Условия возврата - по ТУ'
    g += [_tag('hws-source-reference',f'<rect x="442" y="{first+7:g}" width="104" height="43" fill="white" stroke="black" stroke-width=".25"/>'
              +_text(496,first+21,source_title,3.5,'middle')
              +_text(496,first+28,source_note,2.5,'middle'),mode=principle.mode),
          _text(449,t3+1,'Т3',2.5),_text(449,t4+1,'Т4',2.5)]
    if principle.local_circulation_pump:
        g.append(_text(449,v1+1,'В1',2.5))
    labels += [_text(283,first+53,'Т4: ручная балансировка.',3.5),
               _text(283,first+59,'DN, Kv, настройка - по расчёту.',2.5)]

    defs,cut = '',[]
    if m.break_edges:
        upper,lower = m.break_edges
        def edge(y):
            return f'M{LEFT-10:g},{y:g} H{CENTRE-4:g} L{CENTRE:g},{y-4:g} V{y+4:g} L{CENTRE+4:g},{y:g} H{RIGHT+10:g}'
        regions = (f'M0,0 H{WIDTH} V{upper} H{CENTRE+4} L{CENTRE},{upper+4} V{upper-4} L{CENTRE-4},{upper} H0 Z '
                   f'M0,{lower} H{CENTRE-4} L{CENTRE},{lower-4} V{lower+4} L{CENTRE+4},{lower} H{WIDTH} V{HEIGHT} H0 Z')
        defs = '<clipPath id="residential-water-break"><path d="'+regions+'"/></clipPath>'
        cut += [_path(edge(upper),.25,'data-floor-break="upper" data-tail-mm="10"'),
                _path(edge(lower),.25,'data-floor-break="lower" data-tail-mm="10"'),
                _text(421,lower-4,f'Не показано этажей: {project.building.floors_above-len(m.floors)} (3-{m.floors[-1]-1})',2.5)]
    # Composite bridge halos LAST: a later riser/meter drop must not repaint a
    # crossing as a junction. Text leaders are painted after this pipe layer.
    geometry = ''.join(g)
    root = ET.fromstring('<g>'+geometry+'</g>')
    bridges = []
    for halo in root.iter('path'):
        if halo.get('data-bridge-halo'):
            bridges += [ET.tostring(halo,encoding='unicode'),_path(halo.get('d'),.6,'data-bridge-overlay="true"')]
    body.append('<g'+(' clip-path="url(#residential-water-break)"' if defs else '')+'>'+geometry+''.join(bridges)+'</g>')
    body += [*labels,*cut]
    notes = [
        'Показаны характерные группы помещений, а не все квартиры и стояки; число символов не задаёт спецификацию.',
        'Кухни, санузлы и шахты - условная компоновка. Отметки и размеры труб - из текущих исходных примера.',
        f'Показан один характерный ввод из {project.source.inputs_count}. ВУ, насосная и узел ГВС - отдельными схемами. В2 здесь не показан.',
        'Верхняя связь Т3-Т4 показана в зоне шахт; монтажное положение и проходки уточняются по АР/КР.',
        'Т4 не имеет водоразбора. Размер Т4 и напор НЦ не определены; размеры Т3 на Т4 не переносятся.',
        'Дуга - пересечение без соединения; точка - присоединение. Плиты показаны условно, без назначения толщины.',
    ]
    # These are source datums, not an invented match to a particular drawn
    # mixer. Keep them in the control legend until fixture IDs are available.
    fixture_marks = (
        ('dictating','Излив диктующего прибора',project.source.elev_fixture_m),
        ('lowest','Излив нижнего прибора',project.source.lowest_fixture_elevation_m
         if project.source.lowest_fixture_basis.strip() else None),
    )
    for x,(key,caption,value) in zip((28,215),fixture_marks):
        datum = 'не задана' if value is None else level_text(_datum(value,caption))+' м'
        body.append(f'<g data-control-datum="{key}" data-value="{value}">'
                    +_text(x,m.basement_y+12,caption+': '+datum,3.5)+'</g>')
    y = m.basement_y+23
    for i,note in enumerate(notes,1):
        for line in _lines(f'{i}. {note}',367,3.5):
            body.append(_text(28,y,line,3.5)); y += 5.3
    if y > 411:
        raise ValueError('Примечания вышли за доступную область листа')
    body.append(drawing_frame_svg(project.document,width_mm=WIDTH,height_mm=HEIGHT,
        title='Водоснабжение. Характерный разрез',system_label='В1, Т3, Т4',
        sheet_no=sheet_no,sheet_total=sheet_total))
    warnings = [
        'Характерный разрез жилой части. В2, ВУ и насосная - отдельные чертежи; не полный выпуск ИОС2.',
        'Помещения и две группы заданы выбранным профилем; не восстановлены из АР.',
        'Не заданы материал и размер Т4, монтажные отметки магистралей и точная топология циркуляции.',
        'Уклоны горизонтальных труб и абсолютная отметка ввода требуют исходных данных; не назначены по шаблону.',
        *(b.issue for b in (*cold.values(),*hot.values()) if b.issue),
        *([regulation.issue] if regulation.issue else []),
    ]
    return SchemeResult('<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" '
        f'viewBox="0 0 594 420" data-hws-mode="{principle.mode}" '
        'data-residential-water-section="approval" data-takeoff-eligible="false" '
        'data-release-ready="false"><rect width="594" height="420" fill="white"/><defs>'+defs+'</defs>'
        +''.join(body)+'</svg>',WIDTH,HEIGHT,warnings)

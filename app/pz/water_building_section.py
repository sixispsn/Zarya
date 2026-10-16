"""One paper-space residential В1/Т3/Т4 cutaway; no sizing or takeoff.

Only representative ports and functional connections are generated. Existing
station/meter details remain authoritative. Unresolved multi-zone and V2 cases
stay on their existing explicit path; they are never flattened into one ring.

Layout reference: the supplied GOST R 21.619-2023, 5.2.2 and Appendix Б.
This is not a declaration of full compliance: exact rooms, slopes, expansion
compensation, supports, mounting levels and T4 sizes still need project inputs.
Fixtures are aggregate apartment draw-off terminals, not an invented device
schedule. The small QA example explicitly enables central HWS; the user's
source YAML is unchanged. No OCR or assistant-prepared geometry is required.
"""
from dataclasses import dataclass
from html import escape
from math import isfinite

from app.pz import ugo
from app.pz.building_cutaway import representative_floors
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.hws_presentation import hws_pipe_items, hws_zone_count
from app.pz.water_service_assemblies import shows_riser_balance
from app.pz.metering_detail import _text, _line, _path, _leader, _lines
from app.pz.section_construction import section_slab_svg
from app.pz.section_level_mark import level_text
from app.pz.water_pipe_binding import bind_v1_pipes
from app.pz.water_regulation_plan import branch_regulation_plan
from app.pz.water_station_drafting import _pipe, _flow, _level, _notes, _tag
from app.pz.wastewater_building_drafting import drawing_frame_svg


WIDTH, HEIGHT = 594, 420
LEFT, RIGHT = 100., 474.
AXES = {'В1': 300., 'Т3': 325., 'Т4': 351.}
ROOF_PROFILES = ('gable', 'single_slope', 'flat_non_accessible', 'flat_accessible')


def can_draw_water_section(project):
    b = project.building
    # A representative path must not erase explicit pressure-zone assemblies.
    regulators = getattr(project.v1_hydraulic_result, 'zone_regulators', ()) or ()
    return (b.purpose.value == 'residential' and not project.fire.required
            and project.document.stage_label == 'П'
            and not any(getattr(r, 'required', False) for r in regulators)
            # Keep the old drawing of irrigation/reuse interfaces until those
            # branches have an explicit placement in the combined cutaway.
            and not project.flows.irrigation_m3_day and not project.rainwater_reuse.enabled
            and b.zones == 1 and (b.hws_type.value != 'central' or hws_zone_count(project) == 1)
            and type(b.floors_above) is int and 1 <= b.floors_above <= 200
            and b.floors_below in (0, 1))


@dataclass(frozen=True)
class WaterSectionModel:
    floors: tuple[int, ...]
    floor_ys: tuple[float, ...]
    elevations: tuple[float | None, ...]
    roof_y: float
    roof_elevation: float | None
    basement_y: float | None
    basement_elevation: float | None
    main_ys: tuple[tuple[str, float], ...]
    systems: tuple[str, ...]
    break_edges: tuple[float, float] | None
    omitted_count: int
    inlet_elevation: float | None
    inlet_count: int
    warnings: tuple[str, ...]


def _mark(value, name):
    if value is not None and (type(value) not in (int, float) or not isfinite(value)):
        raise ValueError(f'{name}: отметка должна быть конечным числом')
    return value


def water_section_model(project):
    if not can_draw_water_section(project):
        raise ValueError('Общий разрез поддерживает жилую часть с одной зоной В1/ГВС; В2 выпускается отдельно')
    b = project.building
    floors = representative_floors(b.floors_above)
    compressed = b.floors_above > len(floors)
    first = {1: 206., 2: 240., 3: 270.}[len(floors)]
    ys = tuple(first - i * 66 - (14 if compressed and i == len(floors)-1 else 0)
               for i in range(len(floors)))
    marks = tuple(_mark(b.floor_elevations_m.get(f), f'{f} этаж') for f in floors)
    known = [v for v in marks if v is not None]
    if any(a >= c for a, c in zip(known, known[1:])):
        raise ValueError('Отметки показанных этажей должны возрастать')
    roof = _mark(project.sewage.roof_relative_elevation_m, 'Кровля')
    if roof is not None and marks[-1] is not None and roof <= marks[-1]:
        raise ValueError('Отметка кровли должна быть выше верхнего этажа')
    basement = (_mark(b.floor_elevations_m.get(-1, project.sewage.basement_floor_elevation_m), 'Подвал')
                if b.floors_below else None)
    if basement is not None and marks[0] is not None and basement >= marks[0]:
        raise ValueError('Пол подвала должен быть ниже пола первого этажа')
    inlet = _mark(project.metering_detail.inlet_elevation_m, 'Ввод')
    systems = ('В1','Т3','Т4') if b.hws_type.value == 'central' and shows_riser_balance(project) else ('В1',)
    mains = tuple((s, first+18+i*14 if b.floors_below else first+(-10,-22,-6)[i])
                  for i,s in enumerate(systems))
    warnings = ['Характерный разрез, не измеренная сеть: геометрия листа не используется для спецификации.',
                'Номера помещений, пожарные преграды, швы и монтажные привязки требуют АР/КР.']
    if b.hws_type.value == 'central' and not shows_riser_balance(project):
        warnings.append('Т3/Т4: выбрана другая схема балансировки; компоновка циркуляции требует дополнения, см. отдельный лист ГВС.')
    warnings += [f'{f} этаж: отметка по АР не задана' for f,m in zip(floors,marks) if m is None]
    if roof is None:
        warnings.append('Кровля: отметка по АР не задана')
    if project.sewage.roof_kind not in ROOF_PROFILES:
        warnings.append('Геометрия кровли не задана: показана только условная верхняя граница разреза')
    if b.floors_below and basement is None:
        warnings.append('Подвал: отметка пола по АР не задана')
    if not b.floors_below:
        warnings.append('Подвала нет: положение распределительных магистралей на первом этаже уточнить по АР')
    if inlet is None:
        warnings.append('Ввод: относительная отметка не задана')
    count = len(getattr(project.v1_network,'inlets',[]) or []) or project.source.inputs_count
    if type(count) is not int or count < 1:
        raise ValueError('Число вводов должно быть положительным целым')
    return WaterSectionModel(floors,ys,marks,ys[-1]-58,roof,
        first+70 if b.floors_below else None,basement,mains,systems,
        (ys[-1]+5,ys[-1]+17) if compressed else None,b.floors_above-len(floors),
        inlet,count,tuple(warnings))


def water_section_edges(project, model):
    """Abstract display graph; coordinates never imply engineering connections."""
    edges = [('В1:source','В1:main'),('В1:main','В1:riser')]
    terminals = []
    for floor in model.floors:
        for system in ('В1','Т3') if 'Т3' in model.systems else ('В1',):
            end = f'{system}:apartment:{floor}'
            edges.append((f'{system}:riser',end)); terminals.append(end)
    if 'Т3' in model.systems:
        edges += [('Т3:source','Т3:main'),('Т3:main','Т3:riser'),
                  ('Т3:riser','Т4:top'),('Т4:top','Т4:return')]
        terminals.append('Т4:return')
    # T4 is never a source of apartment water. Cold and hot networks do not join.
    for end in terminals:
        start = 'В1:source' if end.startswith('В1:') else 'Т3:source'
        reached, todo = set(), [start]
        while todo:
            node = todo.pop()
            if node in reached:
                continue
            reached.add(node); todo += [b for a,b in edges if a == node]
        if end not in reached:
            raise ValueError(f'Разрыв пути на схеме: {end}')
    return tuple(edges),tuple(terminals)


def _horizontal(key, x1, x2, y, system, *, crossings=(), start='', end=''):
    """Crossing without junction: a visible bridge in one of the two pipes."""
    low,high = sorted((x1,x2))
    d = f'M{low:g},{y:g}'
    for x in sorted(x for x in crossings if low+3 < x < high-3):
        d += f' H{x-2:g} A2,2 0 0 1 {x+2:g},{y:g}'
    d += f' H{high:g}'
    return _path(d,.6,f'data-pipe="{key}" data-system="{system}" data-from="{start}" '
                  f'data-to="{end}" data-crossings="{len(crossings)}" data-scope="representative"')


def build_water_section(project):
    from app.pz.scheme import SchemeResult
    from app.pz.water_document_binding import water_pressure_presentation
    ensure_drafting_font_registered()
    m = water_section_model(project)
    edges,terminals = water_section_edges(project,m)
    cold = bind_v1_pipes(project)
    hot = {r.key:r for r in hws_pipe_items(project)} if 'Т3' in m.systems else {}
    regulation = branch_regulation_plan(project)
    main = dict(m.main_ys)
    first,top = m.floor_ys[0],m.roof_y
    bottom = m.basement_y if m.basement_y is not None else first+3
    title = ', '.join(m.systems)+'. Принципиальная схема здания'
    body = [_text(28,18,title,5),_text(28,28,'Характерные этажи и квартирные ветви. Компоновка условная, без масштаба.')]
    g = []
    for x in (LEFT,LEFT+2,280,369,RIGHT-2,RIGHT):
        g.append(_line(x,top,x,bottom,.25))
    # Roof shape is presentation of the chosen type, never a surveyed ridge level.
    kind = project.sewage.roof_kind
    roof_path = (f'M{LEFT},{top} L{(LEFT+RIGHT)/2},{top-12} L{RIGHT},{top}' if kind == 'gable' else
                 f'M{LEFT},{top} L{RIGHT},{top-10}' if kind == 'single_slope' else
                 f'M{LEFT},{top} H{RIGHT}')
    g.append(_path(roof_path,.35,'data-roof-profile="'+escape(kind)+'"'))
    if kind in ('gable','single_slope'):
        g.append(_line(LEFT,top,RIGHT,top,.25))
    if kind not in ROOF_PROFILES:
        g.append(_text(LEFT+5,top-5,'Верхняя граница условная; профиль кровли по АР',2.5))
    if m.roof_elevation is not None:
        body.append(_level('water-roof',88,top,m.roof_elevation,'Кровля',reference_x=LEFT,width=32))
    else:
        body.append(_text(30,top-4,'Кровля: по АР',3.5))
    for floor,y,mark in zip(m.floors,m.floor_ys,m.elevations):
        ceiling = y-58
        g += [section_slab_svg(f'water-floor-{floor}',LEFT,RIGHT,y),
              _text(108,ceiling+8,'Квартира (характерная)'),
              _text(324,ceiling+8,'Шахта',3.5,'middle'),
              _text(379,ceiling+8,'Общая зона')]
        if mark is None:
            body.append(_text(30,y-4,f'{floor} этаж: по АР',3.5))
        else:
            body.append(_level(f'water-floor-{floor}',88,y,mark,f'{floor} этаж',reference_x=LEFT,width=32))
        for system,offset in (('В1',18),('Т3',33)):
            if system not in m.systems:
                continue
            sy = y-offset
            x = AXES[system]
            binding = cold['apartment'] if system == 'В1' else hot['t3-apartment'].binding
            branch = [_horizontal(f'{system}-apartment-{floor}',148,x,sy,system,
                                  crossings=(AXES['В1'],) if system == 'Т3' and floor != m.floors[-1] else (),
                                  start=f'{system}:riser',end=f'{system}:apartment:{floor}'),
                      ugo.gate_h(270,sy,tri=2.1,bar=1.3,w=.35),_flow(177,sy,180),
                      _text(180,sy+6,system+' '+binding.label,2.5),
                      # Existing tap UGO: representative water draw-off terminal,
                      # not a new fixture count or an inferred apartment layout.
                      ugo.kran(148,sy,s=.15,w=.35,side='left'),
                      _text(108,sy-4,'ХВС к приборам' if system == 'В1' else 'ГВС к приборам',2.5)]
            if project.meters.has_apartment_meters:
                branch.append(ugo.meter(246,sy,rw=6,rh=4.5,ext=0,w=.35))
            if regulation.shows(system,floor):
                branch += [f'<g data-pressure-regulator="stage-p" data-system="{system}" data-floor="{floor}">'
                           + ugo.redvalve(218,sy,rw=6,rh=4.5,ext=0,w=.35,apex='left')+'</g>',
                           _text(218,sy-4,'РД',2.5,'middle')]
            branch.append(f'<circle cx="{x}" cy="{sy}" r=".9" fill="black"/>')
            g.append(_tag(f'{system}-apartment', ''.join(branch),representative_floor=floor,
                          terminal=f'{system}:apartment:{floor}'))
        for system in m.systems:
            x = AXES[system]
            arrow_y = y-27 if system == 'Т3' and floor == 1 and m.basement_y is None else y-14
            g += [_text(x+3,y-7,system,3.5),
                  _tag('water-riser-arrow',_flow(x,arrow_y,90 if system == 'Т4' else -90),
                       system=system,representative_floor=floor,x=x,y=arrow_y)]
    if m.basement_y is not None:
        g += [section_slab_svg('water-base',LEFT,RIGHT,m.basement_y,depth_mm=8,role='base'),
              _text(379,first+10,'Подвал / техподполье')]
        if m.basement_elevation is not None:
            body.append(_level('water-basement',88,m.basement_y,m.basement_elevation,'Пол подвала',reference_x=LEFT,width=32))
        else:
            body.append(_text(30,m.basement_y-4,'Подвал: по АР',3.5))
    # Fixed paper offsets do not become pipe elevations or network lengths.
    g += [_pipe('water-v1-riser',[(AXES['В1'],main['В1']),(AXES['В1'],m.floor_ys[-1]-18)],
                start='В1:main',end='В1:riser'),
          _horizontal('water-v1-main',140,AXES['В1'],main['В1'],'В1',start='В1:source',end='В1:main'),
          _flow(280,main['В1']),ugo.gate_h(290,main['В1'],tri=2.1,bar=1.3,w=.35)]
    # Keep the characteristic inlet crossing the outer wall. Other inlets and
    # their operating topology are shown on the existing meter assembly sheet.
    inlet_y = first+54 if m.basement_y else first+25
    g += [_pipe('water-inlet',[(65,inlet_y),(130,inlet_y),(130,main['В1']),(140,main['В1'])],
                start='external-water',end='В1:source'),_flow(82,inlet_y),
          _text(108,inlet_y+7,'Ввод В1',2.5),
          _text(379,first+44,f'Вводов В1 всего {m.inlet_count}; показан один',2.5),
          _tag('water-meter-interface',ugo.meter(164,main['В1'],rw=7,rh=5,ext=0,w=.35)),
          _leader('water-meter',(164,main['В1']+3),(180,first+60),268,'Узел учёта В1','См. отдельный чертёж')]
    if project.pumps.required:
        g += [_tag('water-pump-interface',ugo.pump(215,main['В1'],r=4,w=.35,ext=0)),
              _text(215,main['В1']-7,'НУ: см. насосную',2.5,'middle')]
    if m.inlet_elevation is not None:
        body.append(_level('water-inlet',78,inlet_y,m.inlet_elevation,'Ввод',reference_x=100,width=32))
    if 'Т3' in m.systems:
        closure = m.floor_ys[-1]-44
        g += [_pipe('water-t3-riser',[(AXES['Т3'],main['Т3']),(AXES['Т3'],closure)],'Т3',start='Т3:main',end='Т3:riser'),
              _pipe('water-t4',[(AXES['Т3'],closure),(AXES['Т4'],closure),(AXES['Т4'],main['Т4'])],
                    'Т4',start='Т3:riser',end='Т4:top',scope='representative'),
              _horizontal('water-t3-main',230,AXES['Т3'],main['Т3'],'Т3',
                          crossings=(AXES['В1'],) if m.floor_ys[-1]-18 < main['Т3'] < main['В1'] else (),
                          start='Т3:source',end='Т3:main'),
              _horizontal('water-t4-return',230,AXES['Т4'],main['Т4'],'Т4',start='Т4:top',end='Т4:return'),
              _flow(275,main['Т3']),_flow(275,main['Т4'],180),
              _tag('t3-riser-valve',ugo.gate_h(314,main['Т3'],tri=2.1,bar=1.3,w=.35)),
              _tag('t4-riser-valve',ugo.gate_h(340,main['Т4'],tri=2.1,bar=1.3,w=.35)),
              _tag('circulation-balance',ugo.balance_h(320,main['Т4'],tri=2.1,stem=5,rk=1.5,w=.35)),
              _text(229,main['Т3']-5,'Т3 от узла ГВС',2.5),
              _text(229,main['Т4']+7 if m.basement_y else first+12,'Т4 к узлу ГВС; см. отдельный чертёж',2.5),
              _text(379,first+25 if m.basement_y else first-20,'Т4: ручной балансир',3.5),
              _text(379,first+32 if m.basement_y else first-13,'DN, Kv - по расчёту',2.5),
              _text(379,top+25,'Верхняя связь Т3-Т4',3.5),
              _text(379,top+32,'Положение уточнить по АР',2.5)]
    elif project.building.hws_type.value == 'local':
        g.append(_text(379,first-18,'ГВС: местные нагреватели',3.5))
        g.append(_text(379,first-11,'Общая Т4 не предусмотрена',2.5))
    defs,cut = '',[]
    if m.break_edges:
        upper,lower = m.break_edges
        center = 235
        def edge(y):
            return f'M{LEFT-10:g},{y:g} H{center-4} L{center},{y-5:g} V{y+5:g} L{center+4},{y:g} H{RIGHT+10:g}'
        regions = (f'M0,0 H594 V{upper} H{center+4} L{center},{upper+5} V{upper-5} L{center-4},{upper} H0 Z '
                   f'M0,{lower} H{center-4} L{center},{lower-5} V{lower+5} L{center+4},{lower} H594 V420 H0 Z')
        defs = '<clipPath id="water-break-clip"><path d="'+regions+'"/></clipPath>'
        cut = [_path(edge(upper),.25,'data-floor-break="upper"'),_path(edge(lower),.25,'data-floor-break="lower"'),
               _text(380,lower-4,f'Этажи 3-{m.floors[-1]-1}: {m.omitted_count} шт. опущены',2.5)]
    geometry = '<g'+(' clip-path="url(#water-break-clip)"' if defs else '')+'>'+''.join(g)+'</g>'
    body += [geometry,*cut]
    # Independent legend lane uses current bindings shared with PZ/specification.
    legend = [_text(493,52,'Размеры труб',3.5)]
    y = 62
    for key,row in cold.items():
        legend += [_text(493,y,'В1 '+{'inlet':'ввод','main':'магистраль','riser':'стояк','apartment':'квартира'}[key],3.5),
                   _text(493,y+6,row.label,3.5)]
        y += 20
    for key,row in hot.items():
        if key == 't4-network':
            continue
        legend += [_text(493,y,row.title,3.5),_text(493,y+6,row.binding.label,3.5)]
        if row.insulation_mm is not None:
            legend.append(_text(493,y+12,f'Изоляция δ{row.insulation_mm} мм',2.5))
        y += 24
    if hot:
        legend += [_text(493,y,'Т4: размер не определён',2.5),_text(493,y+6,'Не принимается по Т3',2.5)]
    y += 18
    pressure = water_pressure_presentation(project)
    for text in pressure.drawing_lines:
        for line in _lines(text,88,3.5):
            legend.append(_text(493,y,line,3.5))
            y += 6
    for caption,value in (('Диктующий прибор',project.source.elev_fixture_m),
                          ('Нижний прибор',project.source.lowest_fixture_elevation_m
                           if project.source.lowest_fixture_basis.strip() else None)):
        legend.append(_text(493,y+6,caption,3.5))
        legend.append(_text(493,y+12,level_text(value) if value is not None else 'Отметка не задана',3.5))
        y += 21
    body += legend
    notes = [
        'Показаны характерные ветви; число символов и размеры на листе не определяют количество и метраж сети.',
        'ВУ и насосная - отдельные чертежи. Уклоны, оси магистралей и проходки назначаются при компоновке.',
        'Номера помещений, пожарные преграды и деформационные швы - по АР/КР; толщины плит условные.',
        ('Магистрали показаны в верхней зоне подвала; свободную высоту и взаимное положение сетей уточнить.'
         if m.basement_y else 'Подвала нет. Расположение магистралей и ввода на первом этаже требует привязки по АР.'),
        ('Т3-Т4: показан принцип циркуляции. Верхняя связь не задаёт фактическую трассу; Т4 не имеет водоразбора.'
         if hot else 'Т3/Т4: компоновка выбранной циркуляции требует дополнения; см. отдельный лист ГВС.'
         if project.building.hws_type.value == 'central' else
         'Общая циркуляционная система Т4 не показана при местном ГВС или отсутствии ГВС.'),
        'Обозначения: дуга на пересечении - без соединения; точка - присоединение; РД - регулятор на ветви.',
    ]
    body.append(_notes(notes,x=28,y=362,width=365))
    warnings = [*m.warnings,*(r.issue for r in cold.values() if r.issue),
                *(r.binding.issue for r in hot.values() if r.binding.issue),pressure.text]
    return SchemeResult(
        '<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
        f'data-water-section="unified" data-release-ready="false" data-takeoff-eligible="false" '
        f'data-terminal-count="{len(terminals)}" data-edge-count="{len(edges)}">'
        '<rect width="594" height="420" fill="white"/><defs>'+defs+'</defs>'+''.join(body)+
        drawing_frame_svg(project.document,width_mm=594,height_mm=420,title=title,
                          system_label=', '.join(m.systems),sheet_no=1,sheet_total=1)+'</svg>',
        width=WIDTH,height=HEIGHT,warnings=list(dict.fromkeys(warnings)))

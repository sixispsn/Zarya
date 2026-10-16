"""Representative T3/T4 building section in paper millimetres (A2).

Floors/levels come from the project. Horizontal placement is schematic, not
an inferred apartment plan or a fabricated bill of quantities.
"""
from app.pz import ugo
from app.pz.hws_presentation import hws_pipe_items, hws_principle, hws_zone_count
from app.pz.metering_detail import _text, _line, _path, _leader
from app.pz.wastewater_building_drafting import drawing_frame_svg
from app.pz.section_construction import section_slab_svg
from app.pz.water_regulation_plan import branch_regulation_plan
from app.pz.water_service_assemblies import shows_riser_balance


def section_floors(project):
    count = int(project.building.floors_above or 0)
    return tuple(range(1, count + 1)) if count <= 4 else (1, 2, 3, count)


def can_draw_hws_section(project):
    return (project.building.hws_type.value == "central"
            and shows_riser_balance(project)
            and hws_zone_count(project) == 1
            and bool(section_floors(project)))


def build_hws_section(project, page, total):
    if not shows_riser_balance(project):
        raise ValueError("Выбранная схема балансировки требует отдельной компоновки Т3/Т4")
    # Import shared graphics here to avoid a circular module dependency.
    from app.pz.water_station_drafting import _tag, _pipe, _flow, _level, _notes
    items = {item.key: item for item in hws_pipe_items(project)}
    principle = hws_principle(project)
    regulation = branch_regulation_plan(project)
    floors = section_floors(project)
    compressed = len(floors) < project.building.floors_above
    levels = project.building.floor_elevations_m
    # All layouts use physical text sizes; no squeezing tall buildings.
    ys = {floor: 280 - index * 55 - (10 if compressed and index == 3 else 0)
          for index, floor in enumerate(floors)}
    top = ys[floors[-1]] - 55
    left, right, t3, t4 = 100, 480, 315, 342
    basement = levels.get(-1, project.sewage.basement_floor_elevation_m)
    body = [_text(28,18,"Т3, Т4. Принципиальная схема на разрезе здания",5),
            _text(28,28,"Характерная ветвь ГВС. Сечения Т3 - по расчётному пути; Т4 требует дополнения.")]
    g = []
    # Thin construction outlines behind the engineering network.
    for x in (left, 285, 360, right):
        g.append(_line(x,top,x,337 if basement is not None else 280,.25))
    g.append(_line(left,top,right,top,.25))
    roof = project.sewage.roof_relative_elevation_m
    if roof is not None:
        body.append(_level("hws-roof",88,top,roof,"Кровля",side=-1,width=35,reference_x=left))
    else:
        body.append(_text(42,top-5,"Кровля: отметка по АР"))
    g += [_text(322,top+8,"Шахта",3.5,"middle"),
          _text(370,top+8,"Общая зона")]
    for floor in floors:
        y = ys[floor]
        ceiling = y-55
        g += [_tag(f"hws-floor-{floor}",section_slab_svg(f"hws-floor-{floor}",left,right,y),floor=floor),
              _text(108,ceiling+9,"Квартира (характерная)")]
        if floor != floors[-1]:
            g += [_text(322,ceiling+9,"Шахта",3.5,"middle"),
                  _text(370,ceiling+9,"Общая зона")]
        if floor in levels:
            body.append(_level(f"hws-level-{floor}",88,y,levels[floor],f"{floor} этаж",
                               side=-1,width=35,reference_x=left))
        else:
            body.append(_text(42,y-5,f"{floor} этаж: по АР"))
        branch_y = y-18
        branch = [_pipe(f"t3-apartment-{floor}",[(t3,branch_y),(137,branch_y)],"Т3",
                       start="t3-riser",end=f"apartment-{floor}"),
                  ugo.gate_h(273,branch_y,tri=2.5,bar=1.5,w=.35),_flow(145,branch_y,180),
                  _text(138,branch_y-8,"К горячим приборам"),
                  _text(148,branch_y+10,"Т3 " + items["t3-apartment"].binding.label)]
        if project.meters.has_apartment_meters:
            branch += [ugo.meter(246,branch_y,rw=7,rh=5,ext=0,w=.35),
                       _text(233,branch_y+10,"Учёт ГВС")]
        if regulation.shows("Т3", floor):
            branch += [f'<g data-pressure-regulator="stage-p" data-system="Т3" data-floor="{floor}">'
                       + ugo.redvalve(207,branch_y,rw=7,rh=5,ext=0,apex="left",w=.35) + '</g>',
                       _text(207,branch_y-8,"РД",3.5,"middle")]
        g.append(_tag("t3-apartment","".join(branch),representative_floor=floor))
        # Labels outside the pipe, without tiny text or arbitrary DN for T4.
        g += [_text(305,branch_y-12,"Т3",3.5,"middle"),
              _text(351,branch_y-12,"Т4",3.5,"middle"),
              _flow(t3,branch_y-8,-90),_flow(t4,branch_y-8,90)]
    supply_y, return_y = 299, 314
    closure_y = top+21
    g += [_tag("t3-riser",_pipe("building-t3-riser",[(t3,supply_y),(t3,closure_y)],"Т3",
                              start="t3-main",end="hws-top")),
          _tag("t4-network",_pipe("building-t4",[(t3,closure_y),(t4,closure_y),(t4,return_y),(124,return_y)],"Т4",
                                  start="hws-top",end="source-return",scope="representative")),
          _tag("t3-main",_pipe("building-t3-main",[(124,supply_y),(t3,supply_y)],"Т3",
                              start="source-supply",end="t3-riser")),
          _flow(197,supply_y),_flow(197,return_y,180),
          _tag("t3-riser-valve",ugo.gate_v(t3,292,tri=2.5,bar=1.5,w=.35)),
          _tag("t4-riser-valve",ugo.gate_v(t4,291,tri=2.5,bar=1.5,w=.35)),
          _text(128,294,"Т3 " + items["t3-main"].binding.label),
          _text(128,324,"Т4 к узлу ГВС (лист 2)"),
          _text(210,294,"От узла ГВС (лист 2)")]
    g += [_tag("circulation-balance",ugo.balance_v(t4,306,tri=2.5,stem=7,rk=2,w=.35)),
          _leader("building-balance",(t4,306),(380,321),469,"Ручная балансировка Т4","DN, Kv - по расчёту")]
    if basement is not None:
        g += [section_slab_svg("hws-base",left,right,337,depth_mm=8,role="base"),
              _text(375,292,"Подвал / техпространство")]
        body.append(_level("hws-basement",88,337,basement,"Пол подвала",side=-1,width=35,reference_x=left))
    else:
        g.append(_text(375,337,"Размещение магистралей по АР"))
    # Break cuts walls AND risers along the same two full-width boundaries.
    # Continuous network geometry remains beneath the visual mask.
    clip = ""
    if compressed:
        x1, x2, center = left-10, right+10, 235
        # Leave the top-floor slab visible before cutting the omitted storeys.
        upper = ys[floors[-1]] + 4
        lower = upper + 10
        def edge(y):
            return f"M{x1},{y} H{center-4} L{center},{y-5} V{y+5} L{center+4},{y} H{x2}"
        # Clip geometry rather than relying on SVG luminance masks (some
        # PDF backends interpret black as opaque alpha and leave pipes intact).
        regions = (f"M0,0 H594 V{upper} H{center+4} L{center},{upper+5} V{upper-5} L{center-4},{upper} H0 Z "
                   f"M0,{lower} H{center-4} L{center},{lower-5} V{lower+5} L{center+4},{lower} H594 V420 H0 Z")
        clip = f'<clipPath id="hws-break-clip"><path d="{regions}"/></clipPath>'
        body += [_path(edge(upper),.25,'data-floor-break="upper"'),
                 _path(edge(lower),.25,'data-floor-break="lower"'),
                 _text(365,lower-3.5,f"Этажи 4-{floors[-1]-1} ({floors[-1]-4} шт.) опущены",2.5)]
    geometry = '<g clip-path="url(#hws-break-clip)">' + ''.join(g) + '</g>' if compressed else ''.join(g)
    # Legend lane: all pipe sizes use the same data as the specification.
    legend = [_text(493,55,"Размеры и решения",3.5)]
    for index, key in enumerate(("t3-main","t3-riser","t3-apartment")):
        item = items[key]
        y = 67+index*27
        size = item.binding.label
        if item.binding.pipe and item.binding.pipe.dn is not None:
            size += f"; DN{item.binding.pipe.dn}"
        legend += [_text(493,y,item.title,3.5),_text(493,y+7,size,3.5)]
        if item.insulation_mm is not None:
            legend.append(_text(493,y+14,f"Изоляция δ{item.insulation_mm} мм",3.5))
        elif key != "t3-apartment":
            legend.append(_text(493,y+14,"Изоляция: уточнить DN",3.5))
    riser_counts = ("не задано" if principle.risers_t3 is None and principle.risers_t4 is None else
                    f"Т3: {principle.risers_t3 or '?'}; Т4: {principle.risers_t4 or '?'}")
    legend += [_text(493,153,"Т4: DN по расчёту"),
               _text(493,160,"НЦ: Q/H не заданы" if principle.local_circulation_pump else "Т4: возврат по ТУ"),
               _text(493,174,"Число стояков"),_text(493,181,riser_counts),
               _text(493,195,"Спецификация:"),_text(493,202,"раздел Т3-Т4")]
    if regulation.floors:
        legend += [_text(493,216,f"РД: эт. {regulation.floor_text}"),
                   _text(493,223,"Квартирные ветви"),
                   _text(493,230,"Не на транзите Т4"),
                   _text(493,237,"Граница по ПЗ")]
    body.append(geometry)
    body += legend
    body.append(_notes([
        principle.drawing_notes[0],
        "Повторяемость квартир и топологию Т4 подтвердить по АР; количество условных ветвей не является объёмом работ.",
        "Магистрали показаны в верхней зоне подвала; отметки осей и уклоны требуют компоновки, а не берутся с В1.",
        "Верхняя связь Т3-Т4 - принцип циркуляции; место её прокладки, пересечения преград и швов уточнить по АР.",
        principle.drawing_notes[2],
        "Толщина плит показана условно; конструкции и проходки - по АР/КР.",
    ],x=28,y=361,width=365))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
            f'data-water-sheet="{page}" data-hws-section="representative" data-hws-mode="{principle.mode}">'
            '<rect width="594" height="420" fill="white"/><defs>' + clip + '</defs>' + ''.join(body) +
            drawing_frame_svg(project.document,width_mm=594,height_mm=420,
                title="Т3, Т4. Схема водоснабжения здания",system_label="Т3, Т4",sheet_no=page,sheet_total=total) + '</svg>')

"""Common VU sheet: explicit G.1 selection or the preserved merge-before graph.

Paper routing has no length meaning. Catalogue-scaled insert sheets retain
actual product dimensions; existing projects are not silently migrated.
"""
from html import escape


def applicable(project, state):
    from app.pz.metering_rules import special_layout_pending
    return state.switching_bridge or (state.common_inlets and state.inputs_count == 2
            and project.metering_detail.assembly_orientation == 'horizontal_dial_up'
            and not special_layout_pending(project))


def common_principle_contents(project, state):
    if state.switching_bridge:
        from app.pz.metering_switching_drawing import switching_contents
        return switching_contents(project, state)
    from app.pz.metering_detail import _text, _line, _path, _arrow, _leader, _pipe_size, _dn
    from app.pz.metering_ugo import shutoff, gauge, flexible_insert
    from app.pz import ugo
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_supply import inlet_feeds
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.drawing_numbers import water_elevation_text

    d = project.metering_detail
    selected = resolve_metering_products(project, state.meter,
        bypass=state.bypass, electric_bypass=state.electric_bypass)
    chain = build_metering_chain(d, state, selected)
    main = chain.paths[0].nodes
    y = 129.
    # Principal equipment uses fixed PAPER symbol envelopes. Small connectors
    # remain graph edges here; their UGO and real L are on the dimension sheet.
    principal = {'inlet_valve', 'bypass_start', 'reducer_in', 'valve_before',
                 'filter', 'meter', 'service_before', 'valve_after', 'reducer_out',
                 'bypass_end', 'service_after', 'check_valve', 'maintenance_in',
                 'maintenance_out', 'outlet_valve', 'flex_inlet', 'flex_before_meter'}
    visible = [n for n in main if n in principal]
    x0, x1 = 154., 386.
    # Reserving a full lane for each branch keeps labels and service taps apart.
    positions = {'inlet': (x0,y), 'outlet': (x1,y)}
    for i,n in enumerate(visible, 1):
        positions[n] = (x0 + (x1-x0)*i/(len(visible)+1), y)
    for a,b in zip(('inlet',*visible),(*visible,'outlet')):
        left, right = main.index(a), main.index(b)
        for j,n in enumerate(main[left+1:right],1):
            xa, xb = positions[a][0], positions[b][0]
            positions[n] = (xa+(xb-xa)*j/(right-left),y)

    room = 'Помещение № ' + d.room_number if d.room_number else 'Номер помещения ВУ - уточнить'
    if d.room_name:
        room += ' · ' + d.room_name
    g = [_text(217,17,'Водомерный узел на вводе в здание',5,'middle'),
         _text(217,26,room,3.5,'middle'),
         '<g data-common-metering="true" data-assembly-count="1" '
         'data-principle-topology="merge-before-meter" data-reference="GOST-R-21.619-2023-G.1">',
         # Room contour and hatched wall, as in the reference. Open contour is
         # architectural context, not an equipment/block rectangle.
         _path('M92 59 H191 M321 59 H405 V218 H321 M191 218 H92 V59',.25,
               'data-vu-room-contour="true"'),
         '<rect x="74" y="74" width="6" height="110" fill="url(#wall)" '
         'stroke="black" stroke-width=".35"/>']
    for feed, fy in zip(inlet_feeds(state),(92,166)):
        g += [f'<g data-inlet="{feed.number}" data-feed-source="{feed.source_id}">',
              f'<rect x="72" y="{fy-2}" width="10" height="4" fill="white"/>',
              _line(72,fy-2,82,fy-2,.25), _line(72,fy+2,82,fy+2,.25),
              _line(30,fy,144,fy,attrs='data-wall-crossing="true"'),
              _path(f'M30 {fy-2} q3 2 0 4',.35), _arrow(66,fy),
              f'<g data-vu-component="{feed.valve_id}">',shutoff(105,fy,size=3),'</g>',
              _text(105,fy-6,'ВВ',2.5,'middle'),
              _text(31,fy-9,f'Ввод водопровода {feed.number}',3.5),
              _text(31,fy-3,_pipe_size(d,'inlet',d.inlet_dn),3.5),
              '</g>']
        if d.inlet_elevation_m is not None:
            g.append(_text(31,fy+8,'Отм. оси ' + water_elevation_text(d.inlet_elevation_m),3.5))
        if state.fire_branch:
            by = 70 if feed.number == 1 else 190
            g += [_path(f'M122 {fy} V{by} H181',.6,
                        f'data-pre-meter-fire="true" data-feed-fire="{feed.fire_ids[2]}"'),
                  shutoff(151,by,size=3,electric=project.fire.branch_electric_valves),
                  _arrow(180,by),
                  _text(184,by+1,f'К В2 · ввод {feed.number}',3.5)]
    g += [_line(144,92,144,166,attrs='data-supply-header="true"'),
          _line(144,y,x0,y), _line(x1,y,400,y), _arrow(399,y),
          _text(367,y-19,'К насосной',3.5),
          _text(367,y-13,'В1+В2' if state.combined else 'В1',3.5)]

    # Draw links before symbols: white symbol faces cover the through-line.
    for a,b in zip(main,main[1:]):
        g.append(_line(*positions[a],*positions[b],attrs=
            f'data-chain-edge="{escape(a)}:{escape(b)}"'))
    valve_ids = {'inlet_valve','valve_before','valve_after','outlet_valve'}
    marks = {'inlet_valve':'1.1','valve_before':'1.2','valve_after':'1.2',
             'filter':'2','meter':'7','check_valve':'5','outlet_valve':'1.3'}
    for n in visible:
        x,_ = positions[n]
        g.append(f'<g data-vu-component="{n}" data-principle-symbol="true">')
        if n in valve_ids:
            g.append(shutoff(x,y,size=3))
        elif n == 'filter':
            g.append(ugo.filt(x,y,hd=3.5,vd=3.5,ext=0,w=.35))
        elif n == 'meter':
            g.append(ugo.meter(x,y,rw=9,rh=5,ext=0,w=.35))
        elif n == 'check_valve':
            g.append(shutoff(x,y,size=3,check=True))
        elif n.startswith('flex_'):
            g.append(flexible_insert(x-4,x+4,y))
        elif n.startswith('reducer_'):
            expands = (n == 'reducer_out') == (d.inlet_dn > state.meter.dn)
            a,b = (x-3,x+3) if expands else (x+3,x-3)
            g.append(f'<path d="M{a} {y} L{b} {y-2} V{y+2} Z" '
                     'fill="white" stroke="black" stroke-width=".35"/>')
        if n in marks:
            # The data cable leaves the meter vertically, so its position mark
            # needs a separate lane rather than sitting on the dashed line.
            g.append(_text(x-6 if n == 'meter' else x,y-6,marks[n],2.5,'middle'))
        g.append('</g>')

    # Service and bypass branches come from the same graph as the detailed
    # sheet/specification; no missing or fictional valve can hide in a block.
    for path in chain.paths[1:]:
        g.append(f'<g data-chain-path="{path.id}" data-chain-nodes="{" ".join(path.nodes)}">')
        if path.id == 'bypass':
            a,b = positions[path.nodes[0]][0],positions[path.nodes[-1]][0]
            by, bx = 188., (a+b)/2
            g += [_path(f'M{a} {y} V{by} H{b} V{y}',.6,'data-bypass="true"'),
                  '<g data-vu-component="bypass_valve">',
                  shutoff(bx,by,size=3,electric=state.electric_bypass),'</g>',
                  _text(bx,by+8,'6',2.5,'middle'),
                  _text(a+8,by-4,_pipe_size(d,'bypass',d.bypass_dn),3.5)]
        elif path.id == 'gauge':
            x = positions[path.nodes[0]][0]
            g += [_line(x,y,x,95,.35),
                  '<g data-vu-component="gauge_cock">',
                  f'<g transform="rotate(90,{x},104)">'+shutoff(x,104,size=2)+'</g></g>',
                  '<g data-vu-component="gauge">',gauge(x,91,radius=4),'</g>',
                  _text(x+6,92,'3.1',2.5),_text(x+5,105,'3.2',2.5)]
        elif path.id.startswith(('control_', 'maintenance_')):
            x = positions[path.nodes[0]][0]
            cy,ey = y+16,y+23
            g += [_line(x,y,x,ey,.35),
                  f'<g data-vu-component="{path.nodes[1]}">',
                  f'<g transform="rotate(90,{x},{cy})">'+shutoff(x,cy,size=2.5,ball=True)+'</g></g>',
                  f'<g data-vu-component="{path.nodes[2]}">',_line(x-2,ey,x+2,ey,.6),'</g>',
                  _text(x+4,cy+1,'4.1' if path.id.startswith('control_') else '4.3',2.5),
                  _text(x+4,ey+1,'4.2' if path.id.startswith('control_') else '4.4',2.5)]
        g.append('</g>')
    meter_x = positions['meter'][0]
    from app.pz.metering_rules import remote_readout_required
    if remote_readout_required(project):
        g += [_path(f'M{meter_x} {y-2.5} V77 H{meter_x+28}',.25,
                    'stroke-dasharray="2 1" data-askue="true"'),
              _text(meter_x-4,72,'Выход данных АСКУЭ*',3.5)]
    # A shelf below the first line of the meter callout, as in Appendix Г.
    g += [_leader('common-meter',(meter_x,y+2.5),(meter_x+12,211),meter_x+55,
                  'Водосчётчик',_dn(state.meter.dn if state.meter else None)),
          _text(152,228,'Вводы объединены перед общим ВУ. Схема без масштаба.',3.5),
          '</g>']
    return ''.join(g)


def common_data_contents(project,state):
    from app.pz.metering_detail import _panel, _text, _lines
    g = [_text(28,17,'Общий водомерный узел. Данные и позиции',5),
         '<g transform="translate(-263,0)">',_panel(project,state),'</g>']
    notes = [
        'На принципиальной схеме показаны реальные условные обозначения элементов, а не блок ВУ.',
        'Принятая топология: два ввода объединяются перед общим узлом. Переключающая обвязка нижнего примера рисунка Г.1 автоматически не назначается.',
        'Габариты оборудования и размерные цепочки сохранены на отдельных листах. Длина линий принципиальной схемы не задаёт длину труб и количество материалов.',
        'Расчёт каждого ввода ведут на полный расход; расход общего счётчика не делится на число вводов.',
        'Запорные элементы перед общим ВУ относятся к вводам (ВВ). Позиции 1.1-7 относятся к одному общему узлу.',
        'Положение обводной, арматуры и соединительных труб на рисунке условное. Режим переключения, защиту от перетоков и границу коммерческого учёта согласовать по ТУ.',
    ]
    if state.switching_bridge:
        notes[1] = 'Принята топология нижнего рисунка Г.1: две проходные магистрали, общий счётчик на перемычке, четыре переключающих затвора, две обводные ветви с обратными клапанами.'
        notes[4] = 'ВВ — входные отсечки; ВВых — выходные; ВПк — переключающая арматура; ОБ — обводная; КО — обратные клапаны магистралей. Позиции 1.2–7 — измерительная вставка.'
        notes[5] = 'В режиме учёта ОБ закрыты и опломбированы. Выбор рабочего ввода, привод и режим переключения согласовать по ТУ. Рисунок не является инструкцией по эксплуатации; потери новой обвязки требуют проверки.'
    y = 42
    for note in notes:
        for line in _lines(note,220,3.5):
            g.append(_text(178,y,line,3.5))
            y += 5.8
        y += 5
    return ''.join(g)

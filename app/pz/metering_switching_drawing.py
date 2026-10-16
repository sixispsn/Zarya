"""Two through mains and one expanded common insert, Appendix Г, figure Г.1."""
from html import escape


def switching_contents(project, state):
    from app.pz.metering_detail import _text, _line, _path, _arrow, _leader, _dn
    from app.pz.metering_ugo import shutoff, gauge, flexible_insert
    from app.pz import ugo
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_switching import external_graph
    from app.pz.drawing_numbers import water_elevation_text

    d = project.metering_detail
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    chain = build_metering_chain(d, state, selection)
    from app.pz.metering_maintenance import network_from_chain
    from app.pz.metering_switching import extend_network, operating_path_check
    network = extend_network(network_from_chain(d, chain), state)
    network.validate()
    if not operating_path_check(network)['passed']:
        raise ValueError('Общий ВУ Г.1: нарушен проход через счётчик; схема не сформирована')
    nodes, paths = external_graph(state)
    from app.pz.metering_modes import valves_for
    tags = {v.id:v.mark for v in valves_for(network)}
    y, left, right = 125., 128., 358.
    positions = {'inlet': (left,y), 'outlet': (right,y)}
    visible_ids = {'reducer_in','valve_before','maintenance_in','filter','meter','service_before',
                   'valve_after','reducer_out','service_after','check_valve','maintenance_out',
                   'outlet_valve','flex_inlet','flex_before_meter','filter_turn_in','filter_turn_out'}
    main = chain.paths[0].nodes
    visible = [n for n in main if n in visible_ids]
    for j,n in enumerate(visible,1):
        positions[n] = (left + (right-left)*j/(len(visible)+1),y)
    for a,b in zip(('inlet',*visible),(*visible,'outlet')):
        ia,ib = main.index(a),main.index(b)
        for j,n in enumerate(main[ia+1:ib],1):
            positions[n] = (positions[a][0]+(positions[b][0]-positions[a][0])*j/(ib-ia),y)
    for i,my in ((1,72.),(2,178.)):
        positions.update({f'supply_source_{i}':(30,my), f'supply_valve_{i}':(92,my),
            f'supply_fire_takeoff_{i}':(110,my), f'g1_left_{i}':(left,my),
            f'g1_bypass_{i}':(220,my), f'g1_check_{i}':(278,my), f'g1_right_{i}':(right,my),
            f'g1_out_valve_{i}':(384,my), f'g1_building_{i}':(403,my),
            f'g1_switch_in_{i}':(left,(my+y)/2), f'g1_switch_out_{i}':(right,(my+y)/2),
            f'supply_fire_valve_{i}':(150,46. if i==1 else 204.),
            f'supply_fire_outlet_{i}':(192,46. if i==1 else 204.)})
    room = 'Помещение № '+d.room_number if d.room_number else 'Помещение ВУ: номер уточнить'
    if d.room_name:
        room += ' · '+d.room_name
    g = [_text(217,17,'Водомерный узел на вводе в здание',5,'middle'), _text(217,26,room,3.5,'middle'),
         '<g data-common-metering="true" data-assembly-count="1" data-principle-topology="gost-g1-switching" '
         'data-reference="GOST-R-21.619-2023-G.1">',
         _path('M83 36 H200 M320 36 H407 V215 H320 M200 215 H83 V36',.25,'data-vu-room-contour="true"'),
         '<rect x="64" y="61" width="6" height="128" fill="url(#wall)" stroke="black" stroke-width=".35"/>']
    for my in (72,178):
        g += [f'<rect x="62" y="{my-2}" width="10" height="4" fill="white"/>',
              _line(62,my-2,72,my-2,.25),_line(62,my+2,72,my+2,.25)]
    # One canonical graph supplies the drawing, quantities and service audit.
    for path in paths:
        g.append(f'<g data-supply-path="{path.id}" data-supply-nodes="{" ".join(path.nodes)}">')
        for a,b in zip(path.nodes,path.nodes[1:]):
            xa,ya = positions[a]; xb,yb = positions[b]
            attrs = f'data-supply-edge="{a}:{b}"'
            if a.startswith('supply_source_'):
                attrs += ' data-wall-crossing="true"'
            if ya != yb and xa != xb:
                g.append(_path(f'M{xa} {ya} V{yb} H{xb}',.6,attrs))
            else:
                g.append(_line(xa,ya,xb,yb,attrs=attrs))
        g.append('</g>')
    for a,b in zip(main,main[1:]):
        g.append(_line(*positions[a],*positions[b],attrs=f'data-chain-edge="{escape(a)}:{escape(b)}"'))
    for n in nodes:
        x,ny = positions[n.id]
        g.append(f'<g data-vu-component="{n.id}">')
        if n.kind in ('isolation','check'):
            vertical = n.id.startswith('g1_switch_')
            electric = (n.id.startswith('g1_bypass_') and state.electric_bypass
                        or n.id.startswith('supply_fire_valve_') and project.fire.branch_electric_valves)
            symbol = shutoff(x,ny,size=3,check=n.kind=='check',electric=electric)
            g.append(f'<g transform="rotate(90,{x},{ny})">{symbol}</g>' if vertical else symbol)
            mark = ('ВПк' if vertical else 'ОБ' if n.id.startswith('g1_bypass_') else
                    'КО'+n.id.rsplit('_',1)[-1] if n.kind=='check' else 'ВВых' if n.id.startswith('g1_out_valve_') else
                    'ВП' if n.id.startswith('supply_fire_') else 'ВВ')
            tag = tags.get(n.id,mark)
            attrs = f'data-operating-tag="{tag}" data-operating-component="{n.id}"' if n.id in tags else ''
            g.append(f'<g {attrs}>')
            g.append(_text(x+5,ny+1,tag,3.5) if vertical else _text(x,ny+9,tag,3.5,'middle'))
            g.append('</g>')
        g.append('</g>')
    marks = {'valve_before':'1.2','valve_after':'1.2','outlet_valve':'1.3',
             'filter':'2','meter':'7','check_valve':'5'}
    for n in visible:
        x,_ = positions[n]
        g.append(f'<g data-vu-component="{n}">')
        if n in ('valve_before','valve_after','outlet_valve','check_valve'):
            g.append(shutoff(x,y,size=3,check=n=='check_valve'))
        elif n=='filter':
            g.append(ugo.filt(x,y,hd=3.5,vd=3.5,ext=0,w=.35))
        elif n=='meter':
            g.append(ugo.meter(x,y,rw=9,rh=5,ext=0,w=.35))
        elif n.startswith('flex_'):
            g.append(flexible_insert(x-4,x+4,y))
        elif n.startswith('reducer_'):
            expands = (n=='reducer_out') == (d.inlet_dn > state.meter.dn)
            a,b = (x-3,x+3) if expands else (x+3,x-3)
            g.append(f'<path d="M{a} {y} L{b} {y-2} V{y+2} Z" fill="white" stroke="black" stroke-width=".35"/>')
        if n in marks:
            tag = tags.get(n)
            if tag:
                g.append(f'<g data-operating-tag="{tag}" data-operating-component="{n}">'+
                         _text(x,y-6,tag,3.5,'middle')+'</g>')
            else:
                g.append(_text(x-6 if n=='meter' else x,y-6,marks[n],2.5,'middle'))
        g.append('</g>')
    for path in chain.paths[1:]:
        g.append(f'<g data-chain-path="{path.id}" data-chain-nodes="{" ".join(path.nodes)}">')
        x = positions[path.nodes[0]][0]
        if path.id=='gauge':
            g += [_line(x,y,x,105,.35),'<g data-vu-component="gauge_cock">',
                  f'<g transform="rotate(90,{x},114)">'+shutoff(x,114,size=2)+'</g></g>',
                  '<g data-vu-component="gauge">',gauge(x,101,radius=4),'</g>',
                  _text(x+5,102,'3.1',2.5),
                  '<g data-operating-tag="КМ1" data-operating-component="gauge_cock">'+_text(x+5,114,'КМ1',3.5)+'</g>']
        else:
            g += [_line(x,y,x,149,.35),f'<g data-vu-component="{path.nodes[1]}">',
                  f'<g transform="rotate(90,{x},139)">'+shutoff(x,139,size=2.5,ball=True)+'</g></g>',
                  f'<g data-vu-component="{path.nodes[2]}">',_line(x-2,149,x+2,149,.6),'</g>',
                  f'<g data-operating-tag="{tags[path.nodes[1]]}" data-operating-component="{path.nodes[1]}">'+
                  _text(x+4,140,tags[path.nodes[1]],3.5)+'</g>',
                  _text(x+4,150,'4.2' if path.id.startswith('control_') else '4.4',2.5)]
        g.append('</g>')
    for i,my in ((1,72),(2,178)):
        g += [_arrow(58,my),_arrow(400,my),_text(30,my-12,f'Ввод {i}',3.5),
              _text(30,my-6,_dn(d.inlet_dn),3.5),_text(342,my-6,('В1+В2' if state.combined else 'В1')+f' · выход {i}',3.5),
              _text(213 if i==1 else 285,my-10,_dn(d.bypass_dn),3.5)]
        if d.inlet_elevation_m is not None:
            g.append(_text(30,my+9,'Отм. '+water_elevation_text(d.inlet_elevation_m),3.5))
        if state.fire_branch:
            fy=46 if i==1 else 204
            g += [_arrow(190,fy),_text(197,fy+1,f'К В2 · ввод {i}',3.5)]
    mx = positions['meter'][0]
    from app.pz.metering_rules import remote_readout_required
    if remote_readout_required(project):
        g += [_path(f'M{mx} {y-2.5} V94 H{mx-32}',.25,'stroke-dasharray="2 1" data-askue="true"'),
              _text(mx-47,89,'Выход АСКУЭ*',3.5)]
    g += [_leader('common-meter',(mx,y+2.5),(mx-13,160),mx+55,'Общая измерительная вставка',_dn(state.meter.dn if state.meter else None)),
          _text(88,224,'З7/З8 - обводы, штатно закрыты и опломбированы. Метки З/К - см. таблицу режимов.',3.5),'</g>']
    return ''.join(g)

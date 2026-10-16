"""Paper annotation layout for a vertical VU; topology lives in metering_chain.

Only symbol ink is rotated. Fonts, references, lengths and the sheet frame keep
their paper sizes. No drawing coordinate becomes a construction dimension.
"""
from dataclasses import replace
from math import atan2, degrees, dist


def _ink(part, scale):
    from app.pz.metering_layout import _part_svg
    a, b = part.points[0], part.points[-1]
    if part.kind == 'meter' and a[0] == b[0]:
        # A meter's filled half is a paper symbol, not its flow direction.
        # Rotating the horizontal symbol mirrors the supplied vertical UGO.
        return _part_svg(part, scale, symbols_only=True)
    if len(part.points) > 2:
        return _part_svg(part, scale, symbols_only=True)
    length = dist(a,b)
    angle = degrees(atan2(b[1]-a[1],b[0]-a[0]))
    # Gauge's native geometry is a radial stem pointing upwards, not a
    # flow-through rectangle. Rotate its entire stem/circle as one symbol.
    if part.kind == 'gauge':
        local = replace(part, points=((0,0),(0,-length)))
        angle += 90
    else:
        local = replace(part, points=((0,0),(length,0)))
    return (f'<g transform="translate({a[0]:g},{a[1]:g}) rotate({angle:g})">'
            + _part_svg(local,scale,symbols_only=True) + '</g>')


def vertical_contents(project, state, layout, *, include_notes=True, include_heading=True,
                      continuation_pages=None):
    from app.pz.metering_detail import _text, _line, _lines, _leader
    from app.pz.metering_layout import _connection_svg, _symbol_half_height, _gauge_cock_dimension_notes
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_mounting import resolve_mounting
    down = layout.orientation == 'vertical_down'
    serviceable = project.metering_detail.maintenance_layout == 'serviceable'
    mixed = any(p.kind == 'elbow90' for p in layout.parts)
    direction = 'сверху вниз' if down else 'снизу вверх'
    heading = 'Водомерный узел. Вертикальная компоновка' + (' с горизонтальным фильтром' if mixed else '')
    if getattr(project, "metering_node", ""):
        heading = project.node_title + '. Вертикальная компоновка'
    g = ([_text(28,17,heading,5),
          _text(28,25,f'Поток {direction}. УГО с известной длиной: М 1:{layout.scale}.',3.5)]
         if include_heading else [_text(28,35,f'Поток {direction}. УГО с известной длиной: М 1:{layout.scale}.',3.5)])
    g += ['<g data-vu-layout="connected" data-installation-ready="false" '
          f'data-vu-orientation="{layout.orientation}">']
    g += [_connection_svg(e) for e in layout.links]
    g += [_ink(p,layout.scale) for p in layout.parts]
    # Position leaders have their own lane. Short bodies stay short; only
    # label anchors are separated, with a visible thin leader to the element.
    columns, horizontal_rows = {}, {}
    for p in layout.parts:
        if p.kind == 'elbow90':
            a,c,b = p.points
            # Dedicated oblique leader to the turn, not a stretched fitting.
            arm=p.center_to_face_mm/layout.scale
            r=min(arm*.35,2.)
            # Midpoint of the drawn quadratic fillet, not its empty vertex.
            target=tuple(c[i]+r*((a[i]-c[i])+(b[i]-c[i]))/(4*arm) for i in (0,1))
            side = -1 if p.id == 'filter_turn_in' else 1
            dy = (18 if down else -18) * (-side)
            g.append(_leader('bend-'+p.id,target,(c[0]+side*14,c[1]+dy),c[0]+side*30,
                             p.mark, 'A='+f'{p.center_to_face_mm:g}'.replace('.',',')))
            continue
        if len(p.points)>2 or p.id in ('inlet','outlet'):
            continue
        if p.mark and p.mark != '—' and p.points[0][1]==p.points[-1][1]:
            horizontal_rows.setdefault(round(p.center[1],3), []).append(p)
        elif p.mark and p.mark != '—':
            columns.setdefault(round(p.center[0],3),[]).append(p)
    from app.pz.metering_detail import _label_width, _path
    top_control_y = min((p.center[1] for p in layout.parts if p.id.startswith('control_')),default=None)
    for parts in horizontal_rows.values():
        previous_right = -1e6
        for p in sorted(parts, key=lambda p:p.center[0]):
            x,y = p.center
            if p.kind == 'gauge' and p.gauge_center_height_mm is not None:
                a,b=p.points
                x=a[0]+(1 if b[0]>a[0] else -1)*p.gauge_center_height_mm/layout.scale
            width = _label_width(p.mark,3.5)
            left = max(x-width/2,previous_right+3)
            tx = left+width/2
            previous_right = left+width
            half = _symbol_half_height(p,layout.scale)
            below = p.id=='gauge' or (not serviceable and p.id.startswith('control_') and y==top_control_y)
            if mixed and down and p.id.startswith('control_') and y==top_control_y:
                below = True  # meter's lower end dimension occupies the upper lane
            side = 1 if below else -1
            g += [f'<g data-horizontal-mark="{p.id}" data-label-left="{left:g}" '
                  f'data-label-right="{previous_right:g}" data-label-row="{y:g}">',
                  _path(f'M{x:g} {y+side*(half+.5):g} L{tx:g} {y+side*(half+3):g}',.25),
                  _text(tx,y+half+7 if below else y-half-5,p.mark,3.5,'middle'), '</g>']
    for parts in columns.values():
        previous = -1e6
        for p in sorted(parts,key=lambda p:p.center[1]):
            x,y = p.center
            label_y = max(y,previous+5.5)
            previous = label_y
            right = x <= 140
            if mixed and any(abs(x-layout.part(n).center[0]) < .001 for n in ('inlet','outlet')):
                right = x > 140  # keep the narrow filter bay clear of vertical marks
            side = 1 if right else -1
            offset = max(8,_symbol_half_height(p,layout.scale)+4)
            tx = x+side*offset
            start = x+side*(_symbol_half_height(p,layout.scale)+1)
            g += [_line(start,y,tx-side*1,label_y,.25),
                  _text(tx,label_y+1,p.mark,3.5,'start' if right else 'end')]
    # Axial dimensions use the exact body endpoints and their catalogue L.
    # Repeated side-service bodies carry dimensions on the lowest copy only.
    # Their SO marks still appear on every copy; do not pile four identical
    # dimension rows between adjacent takeoffs or move the actual branch.
    service_dimensions = {}
    if serviceable:
        for part in sorted(layout.parts, key=lambda p:p.center[1]):
            if part.id.startswith(('control_', 'maintenance_cock_', 'maintenance_cap_')):
                service_dimensions[(part.catalogue_id,part.kind,part.length_mm)] = part.id
    dimensioned_services = set(service_dimensions.values())
    for index,p in enumerate(layout.parts):
        if (serviceable and p.id.startswith(('control_', 'maintenance_cock_', 'maintenance_cap_'))
                and p.id not in dimensioned_services):
            continue
        if p.kind == 'elbow90':
            a,c,b=p.points
            # A is dimensioned independently on the two orthogonal axes.
            # Never dimension the diagonal chord or add 2A as an axial L.
            g.append(f'<g data-bend-dimensions="{p.id}">')
            for start,end in ((a,c),(c,b)):
                value=f'{p.center_to_face_mm:g}'.replace('.',',')
                if start[1] == end[1]:
                    left,right=sorted((start[0],end[0]))
                    # Short A/scale legs cannot hold a number between ticks.
                    # Put their number outside. Extend away from the elbow's
                    # vertical leg so dimensions do not run through valves.
                    narrow = right-left < 8
                    side = (1 if down else -1) * (1 if p.id=='filter_turn_in' else -1)
                    dy=start[1]+side*16
                    edge=start[1]+side*2
                    text_x = ((left-3 if p.id=='filter_turn_in' else right+3)
                              if narrow else (left+right)/2)
                    anchor = ('end' if p.id=='filter_turn_in' else 'start') if narrow else 'middle'
                    g.append(f'<g data-bend-horizontal-dimension="{p.id}" data-paper-y="{dy:g}">')
                    g += [_line(left,edge,left,dy,.25),_line(right,edge,right,dy,.25),
                          _line(left,dy,right,dy,.25),_line(left-1,dy+1,left+1,dy-1,.25),
                          _line(right-1,dy+1,right+1,dy-1,.25),_text(text_x,dy-1.5,value,3.5,anchor)]
                    g.append('</g>')
                else:
                    top,bottom=sorted((start[1],end[1])); dx=start[0]+(-11 if p.id=='filter_turn_in' else 11)
                    g += [_line(start[0],top,dx,top,.25),_line(start[0],bottom,dx,bottom,.25),
                          _line(dx,top,dx,bottom,.25),_line(dx-1,top+1,dx+1,top-1,.25),
                          _line(dx-1,bottom+1,dx+1,bottom-1,.25),
                          _text(dx+(-2 if p.id=='filter_turn_in' else 2),(top+bottom)/2+1,value,3.5,
                                'end' if p.id=='filter_turn_in' else 'start')]
            g.append('</g>')
            continue
        if p.length_mm is None or len(p.points) != 2 or p.kind == 'gauge':
            continue
        a,b = p.points; x,y = p.center
        prefix = {'minimum':'≥','maximum':'≤','free':'L0=','installed':'Lм='}.get(p.dimension_basis,'')
        text = prefix + f'{p.length_mm:g}'.replace('.',',')
        half = _symbol_half_height(p,layout.scale)
        if a[0] == b[0]:
            top,bottom = sorted((a[1],b[1]))
            # Bypass is on the opposite side; keep dimensions outward.
            side = -1 if x <= 140 else 1
            if mixed and p.id == 'meter':
                side = -1  # opposite the full-length gauge-cock dimension
            if mixed and down and p.id == 'valve_before':
                side = 1  # clear the upper service-branch marks / elbow A
            if p.id == 'valve_after':
                # The gauge branch occupies the other side of this valve.
                # Its full-size cock/label must not cross this dimension lane.
                side = 1 if layout.part('gauge_cock').center[0] < x else -1
            dx = x+side*(max(22,half+9)+(index%2)*8)
            g += [_line(x+side*(half+1),top,dx+side*2,top,.25),
                  _line(x+side*(half+1),bottom,dx+side*2,bottom,.25),
                  _line(dx,top,dx,bottom,.25),
                  _line(dx-1,top+1,dx+1,top-1,.25),
                  _line(dx-1,bottom+1,dx+1,bottom-1,.25),
                  f'<g data-body-dimension="{p.id}" transform="rotate(-90,{dx-2:g},{y:g})">'
                  + _text(dx-2,y,text,3.5,'middle')+'</g>']
        else:
            # Side service branches keep readable horizontal dimensions.
            from app.pz.metering_layout import _dimension
            above = p.id=='gauge_cock' or (not serviceable and p.id.startswith('control_') and y==top_control_y)
            if mixed and p.id == 'filter':
                above = down  # clear the adjacent meter's end dimension
            lane = 20 if p.id=='gauge_cock' else 11 if above else 14
            dy=y+(-1 if above else 1)*max(lane,half+7)
            g.append('<g data-body-dimension="'+p.id+'">'+
                     _dimension(min(a[0],b[0]),max(a[0],b[0]),dy,text,y,half_height=half)+'</g>')
    inlet,outlet = layout.part('inlet'),layout.part('outlet')
    sign = 1 if down else -1
    system = getattr(project, 'node_system', 'В1')
    for p,title in ((inlet,'Вход '+system),(outlet,'Выход '+system)):
        x,y = p.center
        from app.pz.metering_detail import _dn
        title += ' · '+_dn(project.metering_detail.inlet_dn)
        g.append(_text(x+12,y+1,title + (' · '+p.mark if p.mark and p.mark!='—' else ''),3.5))
        g.append(f'<path data-vu-flow="{p.id}" d="M{x:g},{y+sign*1.5:g} '
                 f'L{x-1.2:g},{y-sign*1.5:g} L{x+1.2:g},{y-sign*1.5:g} Z" fill="black"/>')
    if state.core_bypass:
        p=layout.part('bypass_valve')
        route=layout.part('bypass_route_in')
        top = min(v[1] for ident in ('bypass_route_in','bypass_route_out') for v in layout.part(ident).points)
        title = 'Обводная'+(' · '+route.mark if route.mark and route.mark!='—' else '')
        title += ' · '+_dn(project.metering_detail.bypass_dn)
        g.append(_text(p.center[0],top-7,title,3.5,'middle'))
    if state.fire_branch and not state.common_inlets:
        p=layout.part('fire_outlet')
        g.append(_text(p.center[0],p.center[1]-6,'В2 до учёта',3.5,'middle'))
    g.append('</g>')
    if not include_notes:
        d=project.metering_detail
        g.append(_text(28,43,f'Помещение № {d.room_number or "уточнить"} · {d.room_name or "наименование уточнить"}',3.5))
        return ''.join(g)
    selected = resolve_metering_products(project,state.meter,bypass=state.bypass,electric_bypass=state.electric_bypass)
    notes = ['ГОСТ Р 21.619-2023, п. 5.2.2.6, приложение Г. УГО оборудования: ГОСТ 21.205-2016.',
             'Поз. '+layout.part('meter').mark+' — счётчик. Номера позиций и количество соответствуют листам состава и спецификации.',
             'Размеры относятся к корпусам. Посадки, ответные фланцы, опоры и общий монтажный размер не подтверждены.',
             'Прямые участки и штатный комплект у счётчика сохранены без посторонних врезок.']
    if mixed:
        notes.append('О1, О2 — отдельные повороты 90°. A — расстояние от оси до торца каждой ветви, не длина прямой трубы. Фильтр установлен горизонтально.')
    filt = selected.selected('filter')
    if filt and filt.id.startswith('valtec-vt386-'):
        notes.append('VT.386: пробка вниз, оставить доступ для очистки. Вертикальный монтаж — восходящий поток; ПС-47335-3, п. 6.1.')
    from app.pz.metering_orientation import component_orientation, check_product_orientation
    uncertain = [p.title for p in selected.positions if p.product and
                 check_product_orientation(p.product,component_orientation(project.metering_detail,p.role)).allowed is None]
    if uncertain:
        notes.append('Вертикальное положение ещё не подтверждено паспортом: '+', '.join(uncertain)+'.')
    for c in selected.flexible_connections:
        notes.append('Г1 — вставка на вводе.' if c['role']=='inlet' else 'Г2 — вставка перед прямым участком счётчика.')
        notes.append('L0 — свободная длина; Lм — длина после явно заданного предварительного сжатия. Опоры и стержни — по паспорту и КР.')
    if any(p.dimension_basis=='minimum' for p in layout.parts):
        notes.append('Размеры со знаком ≥ — паспортный минимум, не раскрой трубы.')
    if any(c.status=='incompatible' for c in resolve_mounting(project,state).joint_checks):
        notes.append('Есть несогласованные стыки. Соединённые УГО не означают готовность к монтажу; см. проверку соединений.')
    if project.building.seismic:
        notes.append('Гибкая вставка сама по себе не подтверждает сейсмическую пригодность узла. Нужны перемещения, проходка и опоры по КР.')
    notes.extend(_gauge_cock_dimension_notes(layout))
    if serviceable:
        notes += ['1.3 — отсечка от подпора здания. Отсечки счётчика и обводная сохранены.',
                  '4.3 / 4.4 — сервисные краны с заглушками: перед фильтром и за обратным клапаном. '
                  'При потоке вверх нижний отбор — для слива; верхний — для контроля выходной полости.',
                  'Контрольные краны 4.1 / 4.2 сохранены для поверки. Приём воды, воздушный путь и полости корпусов — по проверке обслуживания.',
                  'Размеры одинаковых сервисных кранов и заглушек показаны на нижнем отборе; позиции указаны у каждого изделия.']
    blocks = [(note,3.5) for note in notes]
    if mixed:
        from app.pz.metering_detail import _panel_rows
        d=project.metering_detail
        blocks.append(('Данные узла учёта',5))
        data=[('Помещение',f'№ {d.room_number or "уточнить"} · {d.room_name or "наименование уточнить"}'),
              *_panel_rows(project,state)]
        for label,value in data:
            if value.endswith('*'):
                value=value[:-1]+'; совместимость с диспетчеризацией уточнить'
            blocks.append((label+': '+value,3.5))
    y=47
    g.append(_text(260,37,'Условия компоновки',5))
    overflow = []
    for index,(text,height) in enumerate(blocks):
        lines = _lines(text,143,height)
        keep_data = (text == 'Данные узла учёта' and
                     y+sum(len(_lines(t,143,h))*5.3+3 for t,h in blocks[index:]) > 218)
        if overflow or keep_data or y+len(lines)*5.3+3 > 218:
            overflow.append((text,height))
            continue
        for line in lines:
            g.append(_text(260,y,line,height)); y+=5.3
        y+=3
    if overflow:
        if continuation_pages is None:
            raise ValueError('Примечания вертикального ВУ не помещаются; требуется отдельный лист')
        g.append(_text(260,228,'Продолжение условий — на следующем листе.',3.5))
        continuation, y = [], 31
        for text,height in overflow:
            lines = _lines(text,375,height)
            if not continuation or y+len(lines)*5.5+4 > 225:
                if continuation:
                    continuation_pages.append(''.join(continuation))
                continuation = [_text(28,17,'ВУ. Условия компоновки (продолжение)',5)]
                y=31
            for line in lines:
                continuation.append(_text(28,y,line,height)); y+=5.5
            y+=4
        if continuation:
            continuation_pages.append(''.join(continuation))
    g += [_text(28,222,'Принципиальная компоновка. Не монтажный чертёж и не ведомость раскроя.',3.5),
          _text(28,229,'Неподтверждённые изделия и соединения не заменяются автоматически.',3.5)]
    return ''.join(g)

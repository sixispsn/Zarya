"""Compact station sheet in the visual grammar of GOST 21.619, figure В.1.

Paper coordinates are not installation coordinates. This view neither sizes
pipework nor certifies the selected pump. Missing architectural datums stay
missing; catalogue port DN is not the DN of an uncalculated external pipe.
"""
from app.data.booster_controls import booster_control
from app.data.booster_geometry import booster_geometry
from app.data.booster_service import booster_service
from app.pz import ugo
from app.pz.metering_detail import _text, _line, _path, _gate, _leader, _lines
from app.pz.water_pipe_binding import bind_v1_pipes, bind_t3_pipes
from app.pz.water_station_review import station_counts, branches, service_access_requirements
from app.pz.pump_validation import check_saved_pump_intersection
from app.pz.water_document_binding import water_pressure_presentation
from app.pz.water_station_components import branch_spec_ids


def _rotate(body, x, y, angle=-90):
    return f'<g transform="rotate({angle},{x},{y})">{body}</g>'


def _label(x, y, value, width=110, height=3.5):
    return ''.join(_text(x,y+5.5*i,line,height) for i,line in enumerate(_lines(value,width,height)))


def station_sheet(project, total):
    # Imported after the parent renderer has loaded, to share tested primitives.
    from app.pz.water_station_drafting import _tag, _pipe, _flow, _level, _sheet, _num, _branch_meter
    from app.pz.metering_detail import drawing_state
    p, s = project.pumps, project.source
    state, count = drawing_state(project), station_counts(p)
    control, geometry = booster_control(p), booster_geometry(p, count)
    service = booster_service(p)
    access = {r['target']: r for r in service_access_requirements(project)}
    cold, hot = bind_v1_pipes(project), bind_t3_pipes(project)
    local_heater = (getattr(project.building.hws_type,'value',project.building.hws_type) == 'central'
                    and s.hws_heater_in_scope)
    zones = max(int(project.building.zones or 1),1)
    g = [_text(28,29,'Схема соединений. Размещение оборудования и высоты показаны условно.',3.5)]

    def instrument(key, x, y, code, down=False):
        sign = 1 if down else -1
        return _tag(key, _line(x,y,x,y+sign*9,.25)
            + f'<circle cx="{x}" cy="{y+sign*12}" r="3.5" fill="white" stroke="black" stroke-width=".25"/>'
            + _text(x,y+sign*12+1,code,2.5,'middle'))

    # Feed lanes end at the actual shared suction node. No decorative source
    # is invented at a VU outlet, and no second meter is added here.
    if state.switching_bridge:
        for i,y in ((1,169),(2,187)):
            g += [_pipe(f'station-feed-{i}',[(35,y),(115,y),(115,175)],
                        start=f'g1_building_{i}',end='suction'),
                  _flow(104,y), _text(35,y-4,f'От ВУ-1 · выход {i}',3.5)]
        g.append(_pipe('station-feed',[(115,175),(130,175)],start='suction',end='suction'))
    else:
        label = 'От общего ВУ-1' if state.common_inlets else 'От узла учёта В1' if state.inputs_count == 1 else 'От ВУ вводов'
        g += [_pipe('station-feed',[(35,175),(130,175)],start='inlet-meter',end='suction'),
              _flow(104,175), _text(35,167,label),
              _tag('station-feed-isolation',_gate(87,175),spec_component='station_feed_isolation')]

    if p.required:
        rows = [(160,'Н1','рабочий'),(215,'Н2','резервный; остановлен')] if count == (1,1) else [(187,'НУ','состав по подбору')]
        g += [_pipe('suction-header',[(130,175),(260,175)],start='suction',end='suction'),
              _pipe('discharge-header',[(130,95),(260,95)],start='discharge',end='discharge')]
        for x,key,role in rows:
            b = next((b for b in branches(project) if b['mark']==key),None)
            pump_symbol = ugo.pump_general(x,137,regulated=bool(control))
            g += [_pipe(key,[(x,175),(x,95)],start='suction',end='discharge'),
                  _tag(key,_tag(b['pump'],pump_symbol) if b else pump_symbol,role=role),
                  _rotate(_gate(x,159),x,159),
                  ugo.check_v(x,119,tri=2.6,flow='up',w=.35),
                  _rotate(_gate(x,105),x,105),
                  _text(x-10,139,key,3.5,'end')]
            if b:
                for kind,y in (('inlet',159),('outlet',105),('check',119)):
                    g.append(_tag(b[kind],_text(x+6,y+1,b[kind+'_mark'],2.5)))
                requirement = access[b['pocket']]
                # A leader to an existing pocket, NOT a drawn tap/valve/port.
                g.append(f'<g data-design-requirement="{requirement["id"]}" '
                         f'data-target-node="{b["pocket"]}">'
                         + _leader(requirement['id'],(x,112),(x-14,116),x-43,requirement['mark']+'*','')
                         + '</g>')
                if service:
                    # Leaders refer to factory provisions in the pump body;
                    # do not invent an automatic air-vent UGO in its threaded
                    # factory plug (explicitly prohibited by the CDM manual).
                    g += [_tag(b['vent'], _leader(b['vent'],(x-3,134),(x-12,129),x-30,b['vent_mark'],''),
                               scope='factory-service-provision'),
                          _tag(b['drain'], _leader(b['drain'],(x-3,140),(x-12,148),x-30,b['drain_mark'],''),
                               scope='factory-service-provision')]
            if key != 'Н2':
                g.append(_flow(x,149,-90))
            if geometry:
                g.append(_tag(f'{key}-nozzle-size',_text(x+7,149,f'DN{geometry["bare_pump_nozzle_dn"]}',3.5),
                              scope='catalogue-pump-port'))
        g += [instrument('PI-inlet',141,175,'PI',True),
              instrument('PI-outlet',139,95,'PI')]
        if control:
            g += [instrument('PSL-master',178,175,'PS1',True),
                  instrument('PSL-reserve',243,175,'PS2',True),
                  instrument('PT-master',230,95,'PT1'),
                  instrument('PT-reserve-master',247,95,'PT2'),
                  _pipe('tank-branch',[(180,95),(180,64.5)],start='discharge',end='station_tank'),
                  _tag('station_tank_valve',_rotate(_gate(180,80,size=2.2),180,80)),
                  _tag('station_tank',ugo.closed_tank(180,60)),
                  _text(191,58,'Б1',3.5),_text(191,64,'12 л',3.5)]
        g += [_tag('station-air',ugo.air_valve(260,95,stem=12,tw=1.8,th=3,w=.35),
                   spec_component='station_air'),
              _text(266,81,'Воздух',2.5),
              _tag('station-drain',_path('M260,95 L270,95 L270,118',.6)
                   +_rotate(_gate(270,109,size=2.2),270,109)+_flow(270,118,90),
                   spec_component='station_drain'),
              _text(276,119,'Спуск коллектора',2.5)]
        if geometry:
            # Labels refer to catalogue PORTS, not the adjacent entire pipes.
            g += [_tag('station-port-suction',_text(121,170,f'DN{geometry["connection_dn"]}*',3.5)),
                  _tag('station-port-discharge',_text(264,91,f'DN{geometry["connection_dn"]}*',3.5)),
                  _text(119,204,'* Присоединения НУ по каталогу.',3.5),
                  _text(119,210,'DN50 у насосов - их патрубки.',3.5)]
        else:
            g.append(_text(119,204,'Присоединения НУ: DN не подтверждён',3.5))
        g += [_leader('station-model',(rows[-1][0]+4.5,137),(278,145),405,
                      'НУ1 · '+(p.model or 'модель не выбрана'),p.count_note or 'Число агрегатов не задано')]
    else:
        g += [_pipe('without-booster',[(130,175),(260,175),(260,95)],start='suction',end='discharge'),
              _text(140,166,'Без повысительной установки')]

    g.append(_pipe('station-discharge',[(260,95),(290,95)],start='discharge',end='split'))
    if zones == 1:
        outputs = [(315,'cold-branch','meter-cold','cold','В1, к приборам',cold['main'].label,'cold-zone-1')]
        if local_heater:
            outputs.append((383,'heater-branch','meter-heater','hot','В ИТП / водонагреватель',hot['feed'].label,'heater-meter-out'))
        for x,key,mkey,node,label,size,end in outputs:
            meter_id, valve_id = branch_spec_ids(project,node)
            g += [_pipe(key,[(290,95),(x,95),(x,48)],start='split',end=end),
                  _tag(key+'-isolation',_rotate(_gate(x,82),x,82),spec_component=valve_id),
                  _flow(x,48,-90),
                  _text(x,38,label,3.5,'middle'), _text(x,44,'Зона 1' if node=='cold' else 'См. лист 2',2.5,'middle'),
                  _text(x-4,91,size,3.5,'end')]
            meter = _branch_meter(project,node)
            if meter:
                g += [_tag(mkey,_rotate(ugo.meter(x,65,rw=8,rh=6,ext=0,w=.35),x,65),
                           dn=meter.dn,spec_component=meter_id),
                      _text(x+6,67,f'DN{meter.dn}',2.5)]
    else:
        g += [_text(290,43,'Распределение по зонам не задано'),
              _text(290,50,f'Всего зон: {zones}'),
              _text(290,57,'Требуется схема присоединений',3.5)]

    # Concise equipment data. P2 is explicitly not electrical input power P1.
    if p.required:
        facts = []
        facts.append(f'Qрасч={_num(p.q_design_m3h,3)} м3/ч; Hтреб={_num(p.h_design_m)} м'
                     if p.q_design_m3h>0 and p.h_design_m>0 else 'Расчётная пара Q/H не определена')
        facts.append(f'Оценочно: Q={_num(p.wp_q)} м3/ч; H={_num(p.wp_h)} м'
                     if check_saved_pump_intersection(p)[0] else 'Пересечение не подтверждено')
        facts.append(f'P2 двигателя одного насоса: {_num(geometry["p2_motor_kw"])} кВт'
                     if geometry else 'Вид каталожной мощности требует подтверждения')
        facts += ['P1 потребляемая: не подтверждена', 'Резерв подачу не увеличивает.']
        for i,txt in enumerate(facts):
            g.append(_text(278,162+6*i,txt,3.5))
        room = 'Помещение № '+s.station_room_number if s.station_room_number else 'Помещение насосной: номер по АР не задан'
        g.append(_label(278,199,room,125))

    # Keep the same verified pressure summary as the building sheet and PZ;
    # simplifying this view must not silently remove the regulation decision.
    y = 214
    for value in water_pressure_presentation(project).drawing_lines:
        g.append(_label(278,y,value,125))
        y += 5.5 * len(_lines(value,125,3.5))

    # Genuine datums have an arrow on their own reference line, not at a
    # made-up mounting height. Unknowns remain words, not zero-level symbols.
    inlet = project.metering_detail.inlet_elevation_m
    if service and branches(project):
        g += [_label(32,42,'Сервисные точки Н1 / Н2',95),
              _label(32,50,'СВ1 / СВ2 - воздушная пробка',95),
              _label(32,58,'СС1 / СС2 - сливная пробка',95),
              _label(32,66,'Штатные части насосов CDM15.',95),
              _label(32,74,'РЭ CDM, рис. 7-Н, поз. 36 / 28.',95),
              _label(32,82,'Порядок и ограничения - лист обслуживания.',95,2.5)]
    if inlet is not None:
        g += [_line(32,125,108,125,.25),_level('station-inlet',38,125,inlet,'Ввод здания',side=1,width=56)]
    if s.station_floor_elevation_m is not None:
        g += [_line(32,150,108,150,.25),_level('station-floor',38,150,s.station_floor_elevation_m,'Пол насосной',side=1,width=56)]
    else:
        g.append(_text(32,146,'Пол насосной: отметка не задана',3.5))
    if s.station_suction_elevation_m is not None:
        g += [_line(32,100,108,100,.25),_level('station-suction',38,100,s.station_suction_elevation_m,'Ось всасывания НУ',side=1,width=56)]
    else:
        g.append(_text(32,96,'Ось всасывания: отметка не задана',3.5))

    # Only drawing-related notes remain. Detailed reviews are separate sheets.
    notes = ['1. DN внешней обвязки не задан; DN присоединений НУ его не заменяет.',
             '2. Q/H сохранённого расчёта; потери новой обвязки Г.1 не подтверждены.' if state.switching_bridge else
             '2. Q/H - по сохранённому расчёту; окончательный подбор требует проверки NPSH.',
             '3. PI - манометр; PS1/2 - реле защиты; PT1/2 - датчики давления.' if control else
             '3. PI - манометр. Автоматика и уставки - по заданию смежникам.',
             '4. Отметки - исходные проекта, не вертикальный масштаб схемы.']
    if access:
        notes.append('5. Т1/Т2* - места сервисного доступа за НОК: только требование, '
                     'не установленная арматура.')
        notes.append('См. лист обслуживания.')
    y = 225
    for txt in notes:
        lines = _lines(txt,185,3.5)
        g.append(_label(28,y,txt,185))
        y += 5.5*len(lines)
    if control:
        g.append(_label(28,y+2,'PBS: ПЧ и Б1 в комплекте. Воздух/спуск коллектора - внешняя обвязка.',185))
    g.append(_label(28,284,'Оформление: ГОСТ Р 21.619-2023, приложение В.',185,2.5))
    return _sheet(project,'В1. Принципиальная схема насосной',''.join(g),1,total)

"""V1 station design review. No new sizing method or controller certification.

The connected graph reuses the authored VU, not drawing coordinates. A stopped
pump is not an isolation valve. Service and delivery are independent checks;
reachability never proves head, capacity, NPSH or a drained casing.
"""
from dataclasses import replace
import re

from app.data.booster_controls import booster_control
from app.data.booster_service import booster_service
from app.pz.maintenance_engine import ServiceNode, ServiceLink, ServicePort, assess_removal
from app.pz.metering_modes import operating_paths


def station_counts(pump):
    if pump.working_units > 0 and pump.reserve_units >= 0:
        return pump.working_units, pump.reserve_units
    if re.fullmatch(r"\s*1 рабочий\s*\+\s*1 резервный\s*", pump.count_note or ""):
        return 1, 1
    return None


def branches(project):
    if not project.pumps.required or station_counts(project.pumps) != (1, 1):
        return ()
    return tuple(dict(number=i, pump=f"station_pump_{i}", mark=f"Н{i}",
        inlet=f"station_in_{i}", inlet_mark=f"НЗ{2*i-1}",
        check=f"station_check_{i}", check_mark=f"НОК{i}",
        pocket=f"station_check_pocket_{i}",
        drain=f"station_pump_drain_{i}", drain_mark=f"СС{i}",
        vent=f"station_pump_vent_{i}", vent_mark=f"СВ{i}",
        outlet=f"station_out_{i}", outlet_mark=f"НЗ{2*i}") for i in (1, 2))


def service_access_requirements(project):
    """Annotation-only design requirements, never installed service ports.

    User decision 2026-10-15: show the pocket and requirement only. These
    records must not enter the physical graph or the equipment takeoff.
    """
    return [dict(id=f'station_service_requirement_{b["number"]}',
        mark=f'Т{b["number"]}', target=b['pocket'],
        location=f'Полость {b["check_mark"]} - {b["outlet_mark"]}',
        requirement='Обеспечить контролируемый сброс давления и опорожнение отсечённой полости '
                    'с впуском воздуха и безопасным отводом воды. Конструкцию доступа и приёмник определить отдельно.',
        status='requires_design', installed=False,
        scope='Только место и требование; арматура не выбрана, в СО не добавлена.')
        for b in branches(project)]


def head_balance_trace(project, paths):
    """Expose the canonical head calculation; never calculate another balance.

    Arithmetic/current-input agreement is separate from coverage of the new
    G.1 pipework. Section totals already include local losses. The report must
    neither add a second allowance nor silently equate missing coverage to 0.
    """
    saved = project.head_paths
    current = saved == paths if saved is not None else None
    rows = []
    for path in paths.paths:
        head = path.head
        missing = list(path.missing)
        if head.h_required_m is None:
            missing.append('неполный баланс напора')
        if head.h_guaranteed_m is None:
            missing.append('гарантированный напор в точке подключения')
        rows.append(dict(code=path.code, label=path.label,
            components=[dict(label=label, value_m=value) for label,value in head.components],
            meter_loss_m=path.meter_loss_m, heater_loss_m=path.heater_loss_m,
            dynamic_loss_m=head.h_losses_dynamic_m,
            required_head_m=head.h_required_m, guaranteed_head_m=head.h_guaranteed_m,
            pump_head_m=head.h_pump_m if not missing else None,
            missing=missing))
    complete = all(not r['missing'] for r in rows)
    # Surface, but do not alter, the existing section calculation. These are
    # descriptive rows, not new additive head components or traced G.1 links.
    sections = []
    for system, result in (('В1',project.v1_hydraulic_result), ('Т3',project.t3_hydraulic_result)):
        for row in getattr(result, 'sections', ()):
            item = row if isinstance(row, dict) else vars(row)
            if item.get('missing'):
                continue
            sections.append(dict(system=system, id=item['section_id'], role=item['role'],
                **{key:item[key] for key in ('length_m','inner_diameter_mm','flow_lps',
                                            'linear_loss_m','local_loss_factor','total_loss_m')}))
    return dict(paths=rows, saved_matches_current=current,
        status='stale' if current is False else 'incomplete' if not complete else
               'current' if current is True else 'not_saved',
        governing=paths.governing.code if complete else None, sections=sections,
        method='Составляющие и округление из calc_head_paths / calc_required_head; отдельной формулы отчёта нет.',
        local_loss_note='Местные сопротивления входят в расчёт труб через k_l. '
                        'Готовые суммы, потери водомеров и теплообменника повторно на (1+k_l) не умножаются.',
        coverage_note='Расчётные участки пока не привязаны к новой обвязке Г.1 и подводкам НУ. '
                      'Добавлять поверх них ещё одну надбавку или считать новую обвязку полностью учтённой нельзя.',
        new_pipework_loss_m=None, new_pipework_covered=False)


def factory_component_ids(project):
    if not booster_control(project.pumps):
        return ()
    service_ids = tuple(b[k] for b in branches(project) for k in ('drain','vent')) if booster_service(project.pumps) else ()
    return service_ids + tuple(b[k] for b in branches(project) for k in ('pump', 'inlet', 'check', 'outlet')) + (
        'PI-inlet', 'PI-outlet', 'PT-master', 'PT-reserve-master', 'PSL-master', 'PSL-reserve',
        'station_tank', 'station_tank_valve')


def connected_network(project):
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_maintenance import network_from_chain
    from app.pz.metering_supply import extend_service_network
    state = drawing_state(project)
    if not branches(project) or (state.inputs_count > 1 and not state.common_inlets):
        return None
    selection = resolve_metering_products(project, state.meter,
        bypass=state.bypass, electric_bypass=state.electric_bypass)
    chain = build_metering_chain(project.metering_detail, state, selection)
    network = extend_service_network(network_from_chain(project.metering_detail, chain), state)
    outputs = ('g1_building_1', 'g1_building_2') if state.switching_bridge else ('outlet',)
    nodes = [replace(n, kind='component', wet=True) if n.id in outputs else n for n in network.nodes]
    nodes += [ServiceNode('station_suction', 'Всасывающий коллектор'),
              ServiceNode('station_discharge', 'Напорный коллектор'),
              ServiceNode('station_building', 'Сеть здания: возможный подпор', 'source', wet=False),
              ServiceNode('station_drain', 'Общий спуск коллектора', 'isolation'),
              ServiceNode('station_drain_end', 'Отвод общего спуска'),
              ServiceNode('station_air', 'Воздушный отбор коллектора')]
    links = [*network.links, *(ServiceLink(o, 'station_suction') for o in outputs),
             ServiceLink('station_discharge', 'station_building'),
             ServiceLink('station_discharge', 'station_drain'),
             ServiceLink('station_drain', 'station_drain_end'),
             ServiceLink('station_discharge', 'station_air')]
    service = booster_service(project.pumps)
    service_ports = []
    for b in branches(project):
        nodes += [ServiceNode(b['inlet'], b['inlet_mark'] + ' Всасывающая отсечка', 'isolation'),
                  ServiceNode(b['pump'], b['mark'] + ' Насос'),
                  ServiceNode(b['check'], b['check_mark'] + ' Обратный клапан', 'check', forward_to=b['pocket']),
                  ServiceNode(b['pocket'], 'Полость между '+b['check_mark']+' и '+b['outlet_mark']),
                  ServiceNode(b['outlet'], b['outlet_mark'] + ' Напорная отсечка', 'isolation')]
        path = ('station_suction', b['inlet'], b['pump'], b['check'], b['pocket'], b['outlet'], 'station_discharge')
        links += [ServiceLink(a, c) for a, c in zip(path, path[1:])]
        if service:
            # Factory endpoints are distinct from the removable body. They
            # are potential service openings, NOT permanently open drains.
            nodes += [ServiceNode(b['drain'], b['drain_mark']+': '+service['drain'], wet=False),
                      ServiceNode(b['vent'], b['vent_mark']+': '+service['vent'], wet=False)]
            links += [ServiceLink(b['pump'], b['drain'], gravity='a_to_b', basis=service['source']),
                      ServiceLink(b['pump'], b['vent'], air_passable=True, basis=service['source'])]
            service_ports += [ServicePort(b['drain'], b['drain'], relief=True, drain=True),
                              ServicePort(b['vent'], b['vent'], relief=True, air=True)]
    if booster_control(project.pumps):
        # Factory tank stores pressurised water; never treat it as an empty end.
        nodes += [ServiceNode('station_tank_valve', 'Отсечка комплектного бака', 'isolation'),
                  ServiceNode('station_tank', 'Б1: мембранный бак, возможный подпор', 'source', wet=False)]
        links += [ServiceLink('station_discharge', 'station_tank_valve'),
                  ServiceLink('station_tank_valve', 'station_tank')]
    result = replace(network, nodes=tuple(nodes), links=tuple(links), ports=(*network.ports,
        ServicePort('station_common_drain', 'station_drain_end', relief=True, drain=True),
        ServicePort('station_common_air', 'station_air', air=True), *service_ports))
    result.validate()
    return result


def evaluate_control(*, demand, suction_ok, sensor_ok, power_ok, ready, failed,
                     preferred=1, maintenance=()):
    """Project interlock truth table for 1 duty + 1 reserve V1 ONLY.

    None is unknown, never permission. 'ready' includes an available water path
    and explicit service release. No thresholds, delays or controller protocol
    are inferred. This function does not actuate anything.
    """
    if (type(preferred) is not int or preferred not in (1, 2) or set(ready) != {1, 2}
            or set(failed) != {1, 2} or any(type(i) is not int for i in (*ready, *failed))):
        raise ValueError('Нужны состояния двух насосов и номер ведущего')
    if any(type(x) is not bool and x is not None for x in
           (demand, suction_ok, sensor_ok, power_ok, *ready.values(), *failed.values())):
        raise ValueError('Состояние должно быть true, false или null')
    if any(type(i) is not int or i not in (1, 2) for i in maintenance):
        raise ValueError('Неизвестный насос в ремонте')
    inhibit = [name for name, value in (('питание', power_ok), ('контроль давления', sensor_ok),
                                      ('разрешение всасывания', suction_ok)) if value is not True]
    faults = [f'Отказ Н{i}' for i in (1, 2) if failed[i] is True]
    if inhibit or demand is not True:
        return dict(run=(), alarm=tuple(inhibit + faults + (['нет сигнала потребности'] if demand is None else [])),
                    state='inhibited' if inhibit or demand is None else 'standby')
    for i in (preferred, 3-preferred):
        if i not in maintenance and ready[i] is True and failed[i] is False:
            return dict(run=(i,), alarm=tuple(faults), state='run')
    return dict(run=(), alarm=('Нет готового разрешённого агрегата',), state='inhibited')


AUTOMATION = (
    ('Потребность в воде', 'Пуск одного готового агрегата при разрешённом всасывании и исправном контроле давления. Регулирование по принятой схеме управления; резерв не добавляет расход.', 'СП 30, 13.21; проектная схема 1+1'),
    ('Отказ рабочего', 'Сигнал аварии; замещение готовым резервным. Агрегат в ремонте или с запретом пуска не выбирать.', 'СП 30, 13.21'),
    ('Недостаточный подпор', 'Запрет пуска/останов обоих агрегатов при отсутствии разрешения всасывания; резерв не устраняет общую нехватку воды.', 'Проектная блокировка; реализация по РЭ'),
    ('Неисправность контроля / питание', 'Без достоверного контроля безопасный регулируемый режим не подтверждён. Для данной проектной логики пуск запрещён; алгоритм возврата согласовать с АТ/ЭОМ.', 'Проектное задание, не паспорт контроллера'),
    ('Обслуживание и возврат', 'Исключить автопуск обслуживаемого агрегата. Возврат только после явного снятия запрета, заполнения и проверки готовности; без выдуманной выдержки времени.', 'Проектное задание АТ'),
    ('Уставки и диспетчеризация', 'Передать сигналы работы/аварии/ремонта, недостаточного подпора и неисправности контроля. Уставку давления, гистерезис, задержки и перезапуск увязать с датчиками, ТУ и РЭ.', 'СП 30, 13.21; ГОСТ Р 21.619, 5.2.2.5'),
)


def review_station(project):
    from app.pz.metering_detail import drawing_state
    if not project.pumps.required:
        return None
    state = drawing_state(project)
    control = booster_control(project.pumps)
    bs = branches(project)
    service = booster_service(project.pumps) if bs else None
    network = connected_network(project)
    scenarios = []
    closed = set()
    if network:
        # Normal G.1 operating closures reused verbatim; closed gauges/service
        # ports are boundaries, not imaginary connections through the building.
        from app.pz.metering_modes import valves_for
        if state.switching_bridge:
            vu_nodes = replace(network, nodes=tuple(n for n in network.nodes if not n.id.startswith('station_')),
                               links=(), ports=())
            closed = {v.id for v in valves_for(vu_nodes) if v.normal in ('closed', 'unknown')}
        else:
            closed = {n.id for n in network.nodes if n.kind == 'isolation' and
                      (n.id in ('bypass_valve', 'gauge_cock') or
                       n.id.startswith(('control_cock_', 'maintenance_cock_', 'supply_fire_valve_')))}
        closed.add('station_drain')
        sources = tuple(n.id for n in network.nodes if n.kind == 'source' and
                        (n.id.startswith('supply_source_') or n.id == 'inlet'))
        for b in bs:
            other = bs[2-b['number']]
            cut = {b['inlet'], b['outlet']}
            isolation_ids = {n.id for n in network.nodes if n.kind == 'isolation'}
            removal = assess_removal(network, b['pump'], closed_valves=(closed | cut) & isolation_ids)
            paths = {s: operating_paths(network, s, closed | cut | {b['pump']}) for s in sources}
            # The surviving path must actually contain the other pump.
            path = next((p['station_building'] for p in paths.values()
                         if 'station_building' in p and other['pump'] in p['station_building']), ())
            scenarios.append(dict(target=b['pump'], title='Обслуживание '+b['mark'],
                close_tags=[b['inlet_mark'], b['outlet_mark']], active=other['mark'],
                delivery_path=list(path), delivery_path_exists=bool(path),
                hydraulic_capacity_confirmed=False, removal=removal.to_dict(),
                live_maintenance_approved=False,
                body_service=(f'{b["drain_mark"]}: сливная пробка; {b["vent_mark"]}: воздушная пробка. '
                              'Штатные точки корпуса по РЭ, приём воды не задан.' if service else
                              'Сервисные точки выбранного насоса не подтверждены.'),
                pocket_note=f'Полость {b["check_mark"]} - {b["outlet_mark"]}: отдельный сброс/слив не подтверждён; сливная пробка насоса не обеспечивает опорожнение этой полости.',
                status='needs_data' if path and removal.isolation == 'checked' else 'blocked'))
    q = project.pumps.q_design_m3h
    hydraulic = [dict(id='duty', title='Расчётная подача всей установки',
                     value=f'{q:.3f} м³/ч' if q > 0 else 'Не задана',
                     note='Резерв выключен; расход не делится на два ввода и не удваивается.'),
        dict(id='inlet_dn', title='DN вводов', value=str(project.metering_detail.inlet_dn or 'Не задан'),
             note='Заданный DN не доказывает пропуск полного расхода одним вводом.'),
        dict(id='bypass_dn', title='DN обводных ВУ', value=str(project.metering_detail.bypass_dn or 'Не задан'),
             note='Не назначается по диаметру счётчика или примеру ГОСТ.'),
        dict(id='new_losses', title='Потери переключающей обвязки и подводок НУ', value='Не подтверждены',
             note='Нет привязки участков к новой топологии. В заданных трубах местные потери уже учтены; дополнительная надбавка без разграничения дала бы повторный учёт. Новые потери не приняты нулевыми.'),
        dict(id='npsh', title='NPSH и отметка всасывания', value='Требует увязки',
             note='Отметка ввода не является отметкой патрубка; давление после ВУ и кавитационный запас проверяются отдельно.'),
        dict(id='gauges', title='Контроль давления каждого насоса', value='Требует проверки',
             note='СП 30, 13.16: манометр на всасывающей и напорной линиях каждого насоса. Два общих манометра PBS сами по себе не подтверждают контроль отсечённых ветвей; точки/переключение согласовать.')]
    # Reuse the accepted head/curve checks without adding new losses or using
    # a saved pair as proof that the new G.1 pipes have been calculated.
    from app.pz.rules import calc_head_paths, project_governing_head
    from app.pz.pump_validation import check_project_booster
    current_paths = calc_head_paths(project.source, project.meters,
        hws_type=project.building.hws_type.value,
        apartment_meter_required=project.meters.has_apartment_meters)
    balance = head_balance_trace(project, current_paths)
    if project.head_paths is not None and current_paths != project.head_paths:
        duty_status, duty_note = 'missing', 'Исходные напора изменились после расчёта; нужен пересчёт путей и насоса.'
    else:
        duty_status, duty_note = check_project_booster(project, project_governing_head(project))
    hydraulic.insert(1, dict(id='existing_duty_check', title='Проверка существующего подбора Q/H',
        value='Пара Q/H подтверждена' if duty_status == 'verified' else 'Требуется пересчёт / проверка',
        status=duty_status, note=duty_note+' Новая обвязка Г.1 этой проверкой не подтверждается.'))
    for i,path in enumerate(balance['paths'], 2):
        head = path['pump_head_m']
        value = f'{head:.2f} м'.replace('.', ',') if head is not None else 'Нужны данные'
        note = ('Hтр='+f'{path["required_head_m"]:.2f}'.replace('.', ',')+' м; '
                'Hгар='+f'{path["guaranteed_head_m"]:.2f}'.replace('.', ',')+' м. '
                if head is not None else '')
        note += ('Диктующий путь. ' if path['code']==balance['governing'] else '')
        note += 'По текущим исходным; готовые потери уже с местными. Новая обвязка не подтверждена.'
        if balance['status']=='stale':
            note += ' Сохранённый расчёт устарел.'
        hydraulic.insert(i,dict(id='head_balance_'+path['code'],title='Hнас: '+path['label'],value=value,note=note))
    if project.source.guaranteed_head_m is not None and project.source.guaranteed_head_m < 5:
        hydraulic.append(dict(id='receiving_tank', title='Низкий напор наружной сети', value='Требуется решение',
            note='СП 30, 13.14: при напоре наружной сети менее 5 м нужен приёмный резервуар. Это не уставка реле сухого хода. Прямое подключение не подтверждено.'))
    from app.data.booster_geometry import booster_geometry
    geometry = booster_geometry(project.pumps, station_counts(project.pumps))
    hydraulic += [dict(id='station_ports', title='Присоединения выбранной НУ',
        value=f'DN{geometry["connection_dn"]}' if geometry else 'Не подтверждены',
        note=geometry['note'] if geometry else 'Нужен каталог принятого исполнения; диаметр из названия модели не выводится.'),
        dict(id='power_input', title='Потребляемая мощность P1', value='Не подтверждена',
             note='P2 двигателя не заменяет P1 установки. Номинальный ток и класс IE3 не определяют потребление в рабочем режиме.'),
        dict(id='station_location', title='Привязка насосной по АР',
             value='Задана' if (project.source.station_room_number and project.source.station_floor_elevation_m is not None
                              and project.source.station_suction_elevation_m is not None) else 'Неполная',
             note='Номер помещения, пол насосной и ось всасывающего патрубка задаются отдельно. Каталожная высота над рамой не является относительной отметкой здания.')]
    automation = [dict(title=t, action=a, basis=b) for t,a,b in AUTOMATION] if bs and not state.combined else []
    from app.pz.water_station_suction import suction_path_manifest
    suction_paths = suction_path_manifest(network, [b['pump'] for b in bs], closed)
    return dict(version='2026-10-15-station-suction-path', scope='Принципиальная схема В1, не монтажная документация',
        supported=network is not None, status='needs_data', branches=list(bs), scenarios=scenarios,
        hydraulic=hydraulic, automation=automation, factory_components=bool(control),
        factory_source=control.source if control else '',
        service=service, access_requirements=service_access_requirements(project), head_balance=balance,
        suction_paths=suction_paths,
        notice='Связность проверена отдельно от гидравлики. Общий слив коллектора не сливает отсечённый насос. Отдельные сервисные точки и порядок опорожнения - по РЭ выбранного оборудования; разборка не разрешается отчётом.',
        unsupported_note='' if network else 'Полная связность для этой компоновки пока не поддержана; схема 1+1 не подставляется вместо заданного числа насосов/отдельных ВУ.',
        operation_approved=False, hydraulic_capacity_confirmed=False,
        catalogue_head_is_connection_approval=False)

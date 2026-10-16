"""Maintenance scenarios from the SAME VU connections used by drawing and SO.

This is a design audit, not permission to shut down a building. It never adds
products to the BOM, substitutes calculation inputs or reads paper coordinates.
Current control taps are only candidates for relief/drainage: their mere
existence does not prove a low drain, vent, safe discharge or a dry body.
"""
from app.pz.maintenance_engine import (
    ServiceNode, ServiceLink, ServicePort, ServiceNetwork, assess_removal,
)


ISOLATORS = frozenset(('inlet_valve','valve_before','valve_after','bypass_valve','outlet_valve'))
SOURCE_IDS = frozenset(('inlet','outlet','fire_outlet'))
NOTICE = ('Проверка проектной компоновки, не инструкция переключений. Перед разборкой '
          'эксплуатация должна исключить повторную подачу, проверить герметичность отсечек, '
          'отсутствие давления и воды, безопасную температуру. Обратный клапан не считается ремонтной отсечкой. '
          'Незакрытые проверки обслуживания не останавливают расчёты стадии П.')
LABELS = {'checked':'Проверено по модели', 'needs_data':'Требуется подтверждение',
          'blocked':'Не обеспечено в модели'}


def network_from_chain(detail, chain):
    main = next(p.nodes for p in chain.paths if p.id == 'main')
    forward = dict(zip(main,main[1:]))
    # Gauge/cock side branches are deliberately NOT interpreted using their
    # drawn up/down direction. Meter mounting alone does not locate a drain.
    vertical = (detail.assembly_orientation in ('vertical_up','vertical_down')
                and detail.meter_mounting == detail.assembly_orientation
                and not detail.flexible_connections
                and all(v == detail.assembly_orientation for v in detail.component_orientations.values()))
    serviceable = detail.maintenance_layout == 'serviceable'
    nodes = []
    for n in chain.nodes:
        kind = ('source' if n.id in SOURCE_IDS else 'isolation' if n.id in ISOLATORS else
                'check' if n.id == 'check_valve' else 'component')
        nodes.append(ServiceNode(n.id,n.title,kind,
            wet=kind != 'source', forward_to=forward.get(n.id,'') if kind == 'check' else ''))
    links, seen = [], set()
    for path in chain.paths:
        for a,b in zip(path.nodes,path.nodes[1:]):
            key = frozenset((a,b))
            if key in seen:
                continue
            seen.add(key)
            gravity, basis, air = 'unknown','',None
            if vertical and path.id == 'main':
                gravity = 'b_to_a' if detail.assembly_orientation == 'vertical_up' else 'a_to_b'
                basis = 'Заданная прямая вертикальная ось ВУ; не координаты рисунка'
            if serviceable and vertical and path.id in ('control_1','control_2','maintenance_in','maintenance_out'):
                gravity, basis = 'level', 'Проектный сервисный отбор на уровне присоединения; без восходящего кармана'
            if serviceable and vertical and path.id in ('main','control_1','control_2','maintenance_in','maintenance_out'):
                air = True
            links.append(ServiceLink(a,b,gravity,air_passable=air,basis=basis))
    ids = {n.id for n in nodes}
    ports = tuple(ServicePort(f'control_{i}',f'control_cap_{i}',relief=True,drain=True,
                             air=serviceable and vertical)
                  for i in (1,2) if f'control_cap_{i}' in ids)
    if serviceable:
        ports += tuple(ServicePort(f'maintenance_{side}',f'maintenance_cap_{side}',
                                  relief=True,drain=True,air=vertical)
                       for side in ('in','out') if f'maintenance_cap_{side}' in ids)
    return ServiceNetwork(tuple(nodes),tuple(links),ports)


def audit_metering_maintenance(project, state=None, *, selection=None, chain=None):
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    state = state or drawing_state(project)
    selection = selection or resolve_metering_products(project,state.meter,
        bypass=state.bypass,electric_bypass=state.electric_bypass)
    chain = chain or build_metering_chain(project.metering_detail,state,selection)
    network = network_from_chain(project.metering_detail,chain)
    from app.pz.metering_supply import extend_service_network, inlet_feeds
    network = extend_service_network(network, state)
    titles = {n.id:n.title for n in network.nodes}
    order = ('meter','filter','check_valve','valve_before','valve_after','inlet_valve','bypass_valve','outlet_valve')
    order += tuple(feed.valve_id for feed in inlet_feeds(state))
    if state.switching_bridge:
        order += tuple(n.id for n in network.nodes if n.id.startswith('g1_') and n.kind in ('isolation', 'check'))
    if state.fire_branch:
        order += tuple(feed.fire_ids[1] for feed in inlet_feeds(state))
    switching_check = None
    operating_modes = None
    if state.switching_bridge:
        from app.pz.metering_switching import operating_path_check
        from app.pz.metering_modes import build_modes
        switching_check = operating_path_check(network)
        operating_modes = build_modes(project, state, network)
    operating_tags = {v['id']: v['mark'] for v in operating_modes['valves']} if operating_modes else {}
    scenarios = []
    support_scenarios = {}
    if project.metering_detail.mounting.supports:
        from app.pz.metering_supports import support_report
        support_scenarios = {r['target']: r for r in support_report(project, state, chain=chain)['scenarios']}
    for target in order:
        if target not in titles:
            continue
        result = assess_removal(network,target)
        row = result.to_dict()
        row['title'] = titles[target]
        row['status_label'] = LABELS[result.status]
        row['close_titles'] = [(operating_tags[n]+' - ' if n in operating_tags else '')+titles[n]
                               for n in result.close_valves]
        row['operating_mark'] = operating_tags.get(target, '')
        messages = []
        if result.isolation == 'blocked':
            boundaries = ', '.join(dict.fromkeys(titles[path[-1]] for path in result.source_paths))
            messages.append('Нет отсечки от границ: '+boundaries+'. Нужно определить отключение за пределами этого участка.')
        if result.pressure_relief != 'checked':
            messages.append('Сброс давления: '+('контрольный отбор найден, отвод воды/полости не подтверждены.'
                if result.relief_ports else 'в отключаемом участке не найден отдельный доступ.'))
        if target == 'check_valve' and project.metering_detail.maintenance_layout == 'serviceable':
            messages.append('Отборы предусмотрены с обеих сторон обратного клапана. Открытие затвора остаточным напором '
                            'и полное опорожнение его корпуса без паспорта не считаются подтверждёнными.')
        if result.drainage != 'checked':
            messages.append('Слив: '+('контрольный кран выше удерживаемой воды; нужен нижний слив внутри отсечек.'
                if target in result.trapped_nodes and project.metering_detail.assembly_orientation == 'vertical_up'
                and target in ('meter','filter') else
                'опорожнение не подтверждено: проверить нижние точки, карманы корпусов и приём воды.'))
        if result.air_admission != 'checked':
            messages.append('Впуск воздуха в опорожняемый участок не подтверждён; разборка прибора его не заменяет.')
        if state.electric_bypass and any(n == 'bypass_valve' or n.startswith('g1_bypass_') for n in (*result.close_valves, target)):
            messages.append('Затрагивается пожарная обводная: нужен согласованный режим автоматики и обслуживания; '
                            'самопроизвольное открытие должно быть исключено.')
        row['messages'] = messages
        if target in support_scenarios:
            row['support_coverage'] = support_scenarios[target]
            missing = support_scenarios[target]['uncovered']
            messages.append('Опоры: ' + (f'после снятия остаются группы без заданных точек опирания: {len(missing)}.'
                if missing else 'в каждой оставшейся связной группе есть заданная точка опирания; устойчивость не подтверждена.'))
        scenarios.append(row)
    return dict(version='2026-10-14-service-g1-modes', switching_check=switching_check,
        operating_modes=operating_modes, scope=getattr(project,'node_title',
        'Общий ВУ: все вводы и подпор здания' if state.common_inlets else 'ВУ: основной узел одной линии ввода'),
        layout=project.metering_detail.maintenance_layout,
        instances=chain.instances, scenarios=scenarios, notice=NOTICE,
        all_design_checks_passed=bool(scenarios) and all(r['status']=='checked' for r in scenarios),
        safe_to_remove=False, hydraulic_calculation_changed=False,
        normative_basis='СП 30.13330.2020, пп. 11.7–11.9, 11.17, 12.8–12.9, 12.13; паспорта выбранных изделий',
        limitations=['Границы ввода и здания считаются возможными источниками воды, а не подтверждёнными отключениями.',
                    'Контрольные краны — кандидаты для сервисного отбора, не подтверждённые нижние сливы.',
                    'Полости корпусов, безопасный приём воды и впуск воздуха требуют проектного решения.',
                    'Проверка не вычисляет объём/время слива и не подтверждает разъёмы, опоры и выемку изделия.'])


def maintenance_contents(project, state=None):
    """Plain text blocks, not disconnected table rules; reusable SVG appendix."""
    from app.pz.metering_detail import _text, _lines
    report = audit_metering_maintenance(project,state)
    heading = ('ВУ-Г. Обслуживание узла учёта' if getattr(project,'metering_node','') == 'hot'
               else 'Обслуживание водомерного узла')
    pages, content, y = [], [], 0
    for row in report['scenarios']:
        title = (row['operating_mark']+' - ' if row['operating_mark'] else '')+f"{row['title']} - {row['status_label']}"
        body = ['Границы отсечения по модели: '+(', '.join(row['close_titles']) or 'не найдены')+'.',
                *row['messages']]
        lines = [line for paragraph in body for line in _lines(paragraph,375,3.5)]
        title_lines = _lines(title,375,3.5)
        height = (len(title_lines)+len(lines))*5.5 + 7
        if not content or y+height > 222:
            if content:
                pages.append(''.join(content))
            content = [_text(28,17,heading,5),
                _text(28,26,report['scope'],3.5),
                _text(28,34,'Проектная проверка связей. Не является разрешением на разборку.',3.5)]
            y = 47
        content.append(f'<g data-maintenance-target="{row["target"]}" data-status="{row["status"]}">')
        for line in title_lines+lines:
            content.append(_text(28,y,line,3.5)); y += 5.5
        content.append('</g>'); y += 7
    if content:
        pages.append(''.join(content))
    return pages

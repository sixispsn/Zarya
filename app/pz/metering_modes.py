"""Design-state checks for the approved G.1 graph, NOT switching instructions.

No pressure, capacity, actuation time or fail position is inferred. A proven
path is not an approved operating mode. Unknown valves are closed for proving
supply and open for finding possible hazards. Boundaries are never transit
nodes: an unmodelled building/external network must not repair a broken graph.
"""
from dataclasses import asdict, dataclass

from app.pz.maintenance_engine import assess_removal


@dataclass(frozen=True)
class Valve:
    id: str
    mark: str
    title: str
    group: str
    normal: str = 'open'


# Equipment position and operating tag are distinct: two identical valves
# may share a specification position, but can NEVER share an operating tag.
VALVES = (
    Valve('supply_valve_1', 'З1', 'Отсечка ввода 1', 'main'),
    Valve('supply_valve_2', 'З2', 'Отсечка ввода 2', 'main'),
    Valve('g1_switch_in_1', 'З3', 'К вставке от магистрали 1', 'main'),
    Valve('g1_switch_in_2', 'З4', 'К вставке от магистрали 2', 'main'),
    Valve('g1_switch_out_1', 'З5', 'От вставки к магистрали 1', 'main'),
    Valve('g1_switch_out_2', 'З6', 'От вставки к магистрали 2', 'main'),
    Valve('g1_bypass_1', 'З7', 'Обвод магистрали 1', 'bypass', 'closed'),
    Valve('g1_bypass_2', 'З8', 'Обвод магистрали 2', 'bypass', 'closed'),
    Valve('g1_out_valve_1', 'З9', 'Выходная отсечка 1', 'main'),
    Valve('g1_out_valve_2', 'З10', 'Выходная отсечка 2', 'main'),
    Valve('valve_before', 'З11', 'Перед фильтром и счётчиком', 'main'),
    Valve('valve_after', 'З12', 'После счётчика', 'main'),
    Valve('outlet_valve', 'З13', 'За обратным клапаном вставки', 'main'),
    Valve('supply_fire_valve_1', 'З14', 'Ответвление В2 от ввода 1', 'fire', 'unknown'),
    Valve('supply_fire_valve_2', 'З15', 'Ответвление В2 от ввода 2', 'fire', 'unknown'),
    Valve('control_cock_1', 'КК1', 'Контрольный кран до З12', 'service', 'closed'),
    Valve('control_cock_2', 'КК2', 'Контрольный кран после З12', 'service', 'closed'),
    Valve('maintenance_cock_in', 'КС1', 'Сервисный кран перед фильтром', 'service', 'closed'),
    Valve('maintenance_cock_out', 'КС2', 'Сервисный кран за обратным клапаном', 'service', 'closed'),
    Valve('gauge_cock', 'КМ1', 'Кран манометра', 'instrument', 'measurement'),
)
POSITION_LABELS = {'open': 'О', 'closed': 'З', 'unknown': '?',
                   'measurement': 'М', 'removed': 'С'}
STATUS_LABELS = {'checked': 'Пути проверены', 'needs_data': 'Требует уточнения',
                 'blocked': 'Не обеспечено', 'not_applicable': 'Не применяется'}
NOTICE = ('Проектные состояния, не последовательность переключений и не разрешение на работы. '
          'Связность не подтверждает расход, напор, герметичность или работу автоматики.')


def valves_for(network):
    ids = {n.id for n in network.nodes}
    result = tuple(v for v in VALVES if v.id in ids)
    missing = {n.id for n in network.nodes if n.kind == 'isolation'} - {v.id for v in result}
    if missing:
        raise ValueError('В таблице режимов нет арматуры: ' + ', '.join(sorted(missing)))
    return result


def operating_paths(network, start, blocked=()):
    """Return actual directed paths, stopping at every external boundary."""
    network.validate()
    nodes = {n.id: n for n in network.nodes}
    if start not in nodes:
        raise ValueError('Неизвестная граница режима: ' + start)
    blocked = set(blocked)
    adjacency = {n: set() for n in nodes}
    for e in network.links:
        adjacency[e.a].add(e.b)
        adjacency[e.b].add(e.a)
    for n in network.nodes:
        if n.kind == 'check' and not n.forward_to:
            raise ValueError('Не задано направление обратного клапана: ' + n.id)
    if start in blocked:
        return {}
    paths, queue = {start: (start,)}, [start]
    for current in queue:
        node = nodes[current]
        if current != start and node.kind == 'source':
            continue
        neighbours = {node.forward_to} if node.kind == 'check' else adjacency[current]
        for nxt in sorted(neighbours):
            if nxt in blocked or nxt in paths:
                continue
            if nodes[nxt].kind == 'check' and current == nodes[nxt].forward_to:
                continue
            paths[nxt] = (*paths[current], nxt)
            queue.append(nxt)
    return paths


def check_positions(network, positions, *, active_sources=('supply_source_1', 'supply_source_2'),
                    unavailable_sources=(), target=None, metered=True, require_supply=True,
                    outputs=('g1_building_1', 'g1_building_2')):
    """Check one explicitly specified state; never choose a valve sequence."""
    valves = valves_for(network)
    if set(positions) != {v.id for v in valves}:
        raise ValueError('Положения должны охватывать всю арматуру, без лишних ID')
    if any(p not in POSITION_LABELS for p in positions.values()):
        raise ValueError('Неизвестное положение арматуры')
    if any(p == 'removed' and n != target for n, p in positions.items()):
        raise ValueError('Снятое положение допускается только для обслуживаемого элемента')
    closed = {n for n, p in positions.items() if p in ('closed', 'removed')}
    unknown = {n for n, p in positions.items() if p == 'unknown'}
    removed = {target} if target else set()
    certain = {s: operating_paths(network, s, closed | unknown | removed) for s in active_sources}
    possible = {s: operating_paths(network, s, closed | removed) for s in active_sources}
    failures, pending = [], []
    supplied = all(any(o in paths for paths in certain.values()) for o in outputs)
    if require_supply and not supplied:
        possible_supply = all(any(o in paths for paths in possible.values()) for o in outputs)
        (pending if possible_supply else failures).append('SUPPLY_NOT_PROVEN' if possible_supply else 'NO_SUPPLY')
    bypass_paths = []
    possible_bypass = []
    for s in active_sources:
        for uncertainty, result in ((unknown, bypass_paths), (set(), possible_bypass)):
            paths = operating_paths(network, s, closed | removed | uncertainty | {'meter'})
            result.extend(paths[o] for o in outputs if o in paths)
    if metered and possible_bypass:
        (failures if bypass_paths else pending).append('UNMETERED_PATH')
    crossfeed = [p[t] for s, p in possible.items() for t in active_sources if t != s and t in p]
    if crossfeed:
        pending.append('INLET_CROSSFEED_POSSIBLE')
    # A disconnected inlet may be pressurised from the building/В2 as well.
    backfeed, certain_backfeed = [], []
    for n in network.nodes:
        if n.kind != 'source' or n.id in unavailable_sources:
            continue
        paths = operating_paths(network, n.id, closed | removed)
        backfeed.extend(paths[s] for s in unavailable_sources if s in paths)
        paths = operating_paths(network, n.id, closed | removed | unknown)
        certain_backfeed.extend(paths[s] for s in unavailable_sources if s in paths)
    if backfeed:
        (failures if certain_backfeed else pending).append('UNAVAILABLE_INLET_CONNECTED')
    # A service cock open to a live network is not a service-ready state,
    # even when a cap currently masks discharge. Caps are not valve isolation.
    live_service, certain_live_service = [], []
    for n in network.nodes:
        if n.kind != 'source':
            continue
        paths = operating_paths(network, n.id, closed | removed)
        live_service += [v.id for v in valves if v.group == 'service'
                         and positions[v.id] != 'closed' and v.id in paths]
        paths = operating_paths(network, n.id, closed | removed | unknown)
        certain_live_service += [v.id for v in valves if v.group == 'service'
                                 and positions[v.id] == 'open' and v.id in paths]
    if live_service:
        (failures if certain_live_service else pending).append('LIVE_SERVICE_PORT')
    maintenance = None
    if target:
        isolation_ids = {n.id for n in network.nodes if n.kind == 'isolation'}
        maintenance = assess_removal(network, target, closed_valves=(closed & isolation_ids) - {target}).to_dict()
        if maintenance['isolation'] != 'checked':
            failures.append('TARGET_NOT_ISOLATED')
        if maintenance['status'] != 'checked':
            pending.append('SERVICE_NOT_CONFIRMED')
    if unknown:
        pending.append('UNKNOWN_POSITIONS')
    status = 'blocked' if failures else 'needs_data' if pending else 'checked'
    return dict(topology_status=status, supplied=supplied, paths=certain,
                unmetered_paths=bypass_paths, crossfeed_paths=crossfeed,
                backfeed_paths=backfeed, live_service_ports=sorted(set(live_service)),
                failures=sorted(set(failures)), pending=sorted(set(pending)), maintenance=maintenance)


def build_modes(project, state, network):
    if not state.switching_bridge:
        return None
    valves = valves_for(network)
    normal = {v.id: v.normal for v in valves}
    rows = []

    def add(ident, title, positions, *, notes=(), applicable=True, **checks):
        result = check_positions(network, positions, **checks) if applicable else None
        row = dict(id=ident, title=title, positions=dict(positions), notes=list(notes),
                   checks=result, target=checks.get('target'),
                   status=('blocked' if result and result['failures'] else
                           'needs_data' if applicable else 'not_applicable'),
                   operation_approved=False, hydraulic_capacity_confirmed=False)
        requested = checks.get('outputs', ('g1_building_1','g1_building_2'))
        row['output_scope'] = ('В1 и В2' if any(n.startswith('supply_fire') for n in requested)
                               and any(n.startswith('g1_building') for n in requested) else
                               'В2' if any(n.startswith('supply_fire') for n in requested) else
                               'В1+В2' if state.combined else 'В1')
        row['status_label'] = STATUS_LABELS[row['status']]
        row['position_text'] = ', '.join(v.mark + '=' + POSITION_LABELS[positions[v.id]] for v in valves)
        rows.append(row)

    add('normal', 'Нормальная работа', normal,
        notes=('З7 и З8 закрыты и опломбированы; рабочий путь через счётчик открыт (СП 30, п. 12.11).',
               'Связь вводов до счётчика требует проверки давлений наружной сети и ТУ; это не доказанный переток.'))
    for i in (1, 2):
        positions = {**normal, f'supply_valve_{i}': 'closed'}
        add(f'inlet_{i}_off', f'Отключён ввод {i}', positions,
            active_sources=(f'supply_source_{3-i}',), unavailable_sources=(f'supply_source_{i}',),
            notes=(f'Подача от ввода {3-i}. Отсечение ввода {i} проверяется и от подпора здания.',
                   'Пропуск полного расчётного расхода оставшимся вводом подтвердить гидравлически (СП 30, п. 8.23).'))
    # Outward common-insert boundaries isolate the complete insert for repair;
    # checking the actual removed target prevents it from isolating itself.
    for target in ('meter', 'filter'):
        positions = {**normal, **{f'g1_switch_{side}_{i}': 'closed'
                                 for side in ('in', 'out') for i in (1, 2)},
                     'g1_bypass_1': 'open', 'g1_bypass_2': 'open'}
        add('service_' + target, 'Снятие ' + ('счётчика' if target == 'meter' else 'фильтра'),
            positions, target=target, metered=False,
            notes=('Проектный вариант подачи по обводам; не разрешение на безучётное потребление.',
                   'Распломбирование/временный учёт согласовать. Слив, впуск воздуха и отсутствие давления подтвердить до разборки.'))
    # No assumed fail-open/fail-closed characteristic for an unspecified drive.
    fire = dict(normal)
    if state.fire_branch:
        fire.update({f'supply_fire_valve_{i}': 'open' for i in (1, 2)})
        fire_note = ('В2 отбирается до счётчика; пожар не является командой открыть З7/З8.',
                     'З14/З15=О - требуемый путь при пожаре, не назначение дежурного положения/последовательности команд. Алгоритм АППЗ уточнить.')
        fire_outputs = ('supply_fire_outlet_1', 'supply_fire_outlet_2')
    elif state.combined:
        if state.electric_bypass:
            fire.update(g1_bypass_1='open', g1_bypass_2='open')
        elif not state.meter or state.meter.ok_b is not True:
            fire.update(g1_bypass_1='unknown', g1_bypass_2='unknown')
        fire_note = ('Положение обводов зависит от проверки п. 12.16; автоматика по п. 12.11 СП 30, СП 10 и СП 484.',
                     'Пропуск пожарного расхода и алгоритм открытия не подтверждаются одной связностью.')
        fire_outputs = ('g1_building_1', 'g1_building_2')
    else:
        fire_note = ('Пожарный путь через данный ВУ не задан; режим В2 здесь не назначается.',)
        fire_outputs = ()
    add('fire', 'Пожар', fire, metered=False, outputs=fire_outputs,
        applicable=bool(state.fire_branch or state.combined), notes=fire_note)
    electric = ({'g1_bypass_1', 'g1_bypass_2'} if state.electric_bypass else set())
    if state.fire_branch and project.fire.branch_electric_valves:
        electric.update(('supply_fire_valve_1', 'supply_fire_valve_2'))
    for ident, title in (('power_failure', 'Потеря питания'), ('drive_failure', 'Отказ привода / сигнала положения')):
        add(ident, title, {**normal, **{n: 'unknown' for n in electric}}, applicable=bool(electric),
            outputs=('g1_building_1','g1_building_2') + (
                ('supply_fire_outlet_1','supply_fire_outlet_2') if state.fire_branch else ()),
            notes=(('Положение без питания/при отказе неизвестно до выбора привода и схемы управления.',
                    'Нужны контроль положения, сигнал неисправности и задание автоматике; автоматический возврат не назначен.')
                   if electric else ('В данной обвязке не заданы электроприводы; этот режим к ней не применяется.',)))
    add('restore', 'Возврат после обслуживания', normal,
        notes=('Это конечное состояние, не порядок действий. Проверить заполнение/удаление воздуха, герметичность, закрытие отборов, пломбы и восстановление автоматики.',))
    # All other removable operating valves/checks retain their own real cuts.
    service_rows = []
    for node in network.nodes:
        if node.kind not in ('isolation', 'check'):
            continue
        audit = assess_removal(network, node.id).to_dict()
        positions = {**normal, **{n: 'closed' for n in audit['close_valves']}}
        if node.id in positions:
            positions[node.id] = 'removed'
        checks = check_positions(network, positions, target=node.id, metered=False, require_supply=False)
        service_rows.append(dict(target=node.id, title=node.title, positions=positions,
                                 close_marks=[next(v.mark for v in valves if v.id == n) for n in audit['close_valves']],
                                 checks=checks, maintenance=audit, operation_approved=False))
    return dict(version='2026-10-14-g1-modes', valves=[asdict(v) for v in valves], modes=rows,
                service_modes=service_rows, notice=NOTICE, hydraulic_calculation_changed=False,
                operation_approved=False, normative_basis='СП 30: 8.23, 12.11 (изм. 3), 12.12, 12.16; ГОСТ Р 21.619-2023: 5.2.2.6, Г.1',
                forbidden=['Открытый обвод в штатном режиме учёта.',
                           'Снятие элемента, связанного с источником или подпором здания.',
                           'Использование снимаемой задвижки или обратного клапана как ремонтной отсечки.',
                           'Открытие сервисного отбора на неотсечённом участке как состояние готовности к разборке.',
                           'Признание неизвестного положения привода открытым, закрытым или безопасным.',
                           'Перенос команды пожарного обвода на В1 при самостоятельном отборе В2 до счётчика.'])


def modes_for_project(project, state=None):
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_maintenance import network_from_chain
    from app.pz.metering_switching import extend_network
    state = state or drawing_state(project)
    if not state.switching_bridge:
        return None
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    chain = build_metering_chain(project.metering_detail, state, selection)
    return build_modes(project, state, extend_network(network_from_chain(project.metering_detail, chain), state))

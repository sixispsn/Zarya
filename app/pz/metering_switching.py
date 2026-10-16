"""Explicit two-line/common-insert topology of GOST R 21.619-2023, G.1.

Paper coordinates, catalogue lengths and hydraulic calculations are not graph
inputs. Two bypasses belong to the through mains, not to the common insert.
The reference's DN200 and motor drives are NOT defaults for a real project.
"""
from dataclasses import replace
from app.pz.maintenance_engine import ServiceNode, ServiceLink
from app.pz.metering_chain import ChainPath


def external_graph(state):
    if not state.switching_bridge:
        return (), ()
    nodes, paths = [], []
    for i in (1, 2):
        source, feed = f"supply_source_{i}", f"supply_valve_{i}"
        left, right = f"g1_left_{i}", f"g1_right_{i}"
        bypass, check = f"g1_bypass_{i}", f"g1_check_{i}"
        out, building = f"g1_out_valve_{i}", f"g1_building_{i}"
        si, so = f"g1_switch_in_{i}", f"g1_switch_out_{i}"
        nodes += [ServiceNode(source, f"Ввод {i}: наружная сеть", "source", wet=False),
            ServiceNode(feed, f"Отсечка ввода {i}", "isolation"),
            ServiceNode(left, f"Отбор к общей вставке, магистраль {i}"),
            ServiceNode(bypass, f"Обводная арматура магистрали {i}", "isolation"),
            ServiceNode(check, f"Обратный клапан магистрали {i}", "check", forward_to=right),
            ServiceNode(right, f"Возврат общей вставки, магистраль {i}"),
            ServiceNode(out, f"Выходная отсечка магистрали {i}", "isolation"),
            ServiceNode(building, f"Выход {i}: возможный подпор здания", "source", wet=False),
            ServiceNode(si, f"Входная переключающая арматура {i}", "isolation"),
            ServiceNode(so, f"Выходная переключающая арматура {i}", "isolation")]
        prefix = [source, feed]
        if state.fire_branch:
            tee, valve, outlet = (f"supply_fire_{r}_{i}" for r in ("takeoff", "valve", "outlet"))
            nodes += [ServiceNode(tee, f"Отбор В2 ввода {i}"),
                ServiceNode(valve, f"Отсечка В2 ввода {i}", "isolation"),
                ServiceNode(outlet, f"В2 ввода {i}: возможный подпор", "source", wet=False)]
            prefix.append(tee)
            paths.append(ChainPath(f"g1_fire_{i}", f"В2 до учёта, ввод {i}", (tee, valve, outlet)))
        paths += [ChainPath(f"g1_main_{i}", f"Проходная магистраль {i}",
                            (*prefix, left, bypass, check, right, out, building)),
                  ChainPath(f"g1_feed_{i}", f"К общей вставке от ввода {i}", (left, si, "inlet")),
                  ChainPath(f"g1_return_{i}", f"От общей вставки к выходу {i}", ("outlet", so, right))]
    return tuple(nodes), tuple(paths)


def component_ids(state):
    nodes, _ = external_graph(state)
    # Building/external network boundaries are not purchased components.
    return {n.id for n in nodes if n.kind != "source" or n.id.startswith("supply_fire_outlet_")}


def extend_network(network, state):
    nodes, paths = external_graph(state)
    core = tuple(replace(n, kind="component", wet=True) if n.id in ("inlet", "outlet") else n
                 for n in network.nodes)
    links = tuple(ServiceLink(a, b) for p in paths for a, b in zip(p.nodes, p.nodes[1:]))
    return replace(network, nodes=(*core, *nodes), links=(*network.links, *links))


def operating_path_check(network):
    """Topology-only audit of two alternative metered feed scenarios.

    Not an operator's switching instruction, nor proof of pressures/capacity.
    Check valves are directional here, but never isolation in service audits.
    """
    from app.pz.metering_modes import operating_paths

    scenarios = []
    for i in (1, 2):
        closed = {"g1_bypass_1", "g1_bypass_2", f"supply_valve_{3-i}"}
        source = f"supply_source_{i}"
        outputs = [f"g1_building_{j}" for j in (1, 2)]
        paths = operating_paths(network, source, closed)
        without_meter = operating_paths(network, source, closed | {'meter'})
        scenarios.append(dict(inlet=i, closed=sorted(closed),
            outlets_reachable=all(out in paths for out in outputs),
            no_unmetered_path=not any(out in without_meter for out in outputs)))
    return dict(scenarios=scenarios,
        passed=all(s["outlets_reachable"] and s["no_unmetered_path"] for s in scenarios),
        hydraulic_capacity_confirmed=False, operation_approved=False,
        scope='two_alternative_metered_paths_only')


def spec_rows(project, state, selection):
    from app.pz.spec import SpecRow
    d = project.metering_detail
    rows = []

    def add(title, ids, mark, dn, *, known=True, note=""):
        ids = tuple(ids)
        rows.append(SpecRow(1, title + (f", DN{dn}" if dn else ", DN уточнить"),
            unit="шт." if known else "компл.", qty=len(ids) if known else None,
            diagram_pos=mark, component_ids=ids,
            quantity_basis="metering_scheme" if known else "",
            quantity_source="Топология общего ВУ по рисунку Г.1" if known else "",
            note=note or "Модель, P/T, присоединения, ориентацию и строительную длину подтвердить. Размеры из примера ГОСТ не перенесены."))

    add("Запорная арматура вводов", (f"supply_valve_{i}" for i in (1,2)), "ВВ", d.inlet_dn)
    add("Выходная запорная арматура магистралей", (f"g1_out_valve_{i}" for i in (1,2)), "ВВых", d.inlet_dn)
    add("Переключающая арматура общей измерительной вставки",
        (f"g1_switch_{side}_{i}" for side in ("in","out") for i in (1,2)), "ВПк", d.inlet_dn)
    add("Обводная арматура проходных магистралей" + (" с электроприводом" if state.electric_bypass else ""),
        (f"g1_bypass_{i}" for i in (1,2)), "ОБ", d.bypass_dn,
        note="Две отдельные обводные ветви; в режиме учёта закрыты и опломбированы. DN и привод по расчёту/ТУ; электропривод рисунка Г.1 не назначается автоматически.")
    add("Обратные клапаны проходных магистралей", (f"g1_check_{i}" for i in (1,2)), "КО", d.inlet_dn)
    add("Трубы и соединительные фасонные части переключающей обвязки",
        (f"g1_{side}_{i}" for side in ("left","right") for i in (1,2)), "—", d.inlet_dn,
        known=False, note="Четыре узла присоединения к магистралям; трубные длины и состав деталей по привязке. При разных DN магистрали и обводной нужны отдельные переходы; не выводить количество по рисунку.")
    if state.fire_branch:
        add("Арматура ответвлений В2 до учёта", (f"supply_fire_valve_{i}" for i in (1,2)), "ВП", d.fire_branch_dn,
            note=("С электроприводом. " if project.fire.branch_electric_valves else "") + "Два самостоятельных ответвления В2, до общего счётчика.")
        add("Ответвления В2: трубы и фасонные части",
            (f"supply_fire_{side}_{i}" for side in ("takeoff","outlet") for i in (1,2)), "—", d.fire_branch_dn,
            known=False, note="Трубы, фасонные части и проходки по проектной привязке; длина рисунка не является метражом.")
    assert {i for r in rows for i in r.component_ids} == component_ids(state)
    return rows

"""Composition of the existing VU schematic, not an inferred installation BOM.

Each service branch and every reducer survives product selection failures.
Logical junctions do NOT assign a tee model, gender, length or pipe cut length.
The graph documents connection coverage, not hydraulic suitability.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChainNode:
    id: str
    title: str
    catalogue_id: str | None = None
    # None means unspecified fitting/pipe/port, not "no fitting needed".
    role: str | None = None
    required_thread: str = ""
    required_standard: str = ""
    minimum_length_mm: float | None = None
    dimension_source: str = ""


@dataclass(frozen=True)
class ChainPath:
    id: str
    title: str
    nodes: tuple[str, ...]


@dataclass(frozen=True)
class MeteringChain:
    nodes: tuple[ChainNode, ...]
    paths: tuple[ChainPath, ...]
    instances: int

    def node(self, ident):
        return next(n for n in self.nodes if n.id == ident)

    @property
    def links(self):
        return tuple((a, b) for path in self.paths for a, b in zip(path.nodes, path.nodes[1:]))

    @property
    def installation_complete(self):
        # Joint seal, engagement, pipe cuts, dismantling and support geometry
        # are not part of this version. Even all product IDs would not suffice.
        return False


def build_metering_chain(detail, state, selection):
    """One core per assembly. Common inlet feeds are a separate graph boundary."""
    nodes, paths, main = [], [], []
    switching = getattr(state, "switching_bridge", False)
    core_bypass = state.bypass and not switching
    kit_check = next((c for c in selection.accessories if c.role == "meter_connections"), None)
    kit_id = kit_check.catalogue_id if kit_check and not kit_check.errors else None
    meter_product = selection.selected("meter")
    straight = meter_product.straight_sections if meter_product else None

    def meter_end(ident, before):
        if straight:
            nodes.append(ChainNode(ident,
                "Прямой участок до счётчика" if before else "Прямой участок после счётчика",
                role="meter_straight",
                minimum_length_mm=meter_product.dn * (straight.before_dn if before else straight.after_dn),
                dimension_source=f"{straight.source_id}: {straight.reference}"))
            return ident
        return add(ident, "Входная часть штатного комплекта" if before else "Выходная часть штатного комплекта",
                   catalogue_id=kit_id)

    def add(ident, title, role=None, catalogue_id=None):
        from app.pz.metering_service import SERVICE_ROLES
        service = next((s for s in selection.services if ident in SERVICE_ROLES[s.role][2]), None)
        if service:
            catalogue_id = service.part.id if service.part else None
        if role:
            part = selection.selected(role)
            catalogue_id = part.id if part else None
            if part and part.valve_type == "gate":
                title = title.replace("Кран", "Задвижка")
        elif ident in ("reducer_in", "reducer_out"):
            check = next((c for c in selection.reducers if c.role == ident), None)
            catalogue_id = check.part.id if check and check.part else None
        fitting = next((c for c in selection.fittings if c.role == ident), None)
        if fitting:
            catalogue_id = fitting.part.id if fitting.part else None
            if fitting.part:
                title = fitting.part.name
        nodes.append(ChainNode(ident, title, catalogue_id, role))
        return ident

    def flow(ident, title, role=None):
        main.append(add(ident, title, role))

    def flexible(role):
        if role not in detail.flexible_connections:
            return
        check = next((c for c in selection.flexible_connections if c['role'] == role), None)
        ident = 'flex_' + role
        nodes.append(ChainNode(ident, 'Гибкая вставка ' + ('на вводе' if role == 'inlet' else 'перед узлом учёта'),
            check['catalogue_id'] if check and not check['errors'] else None, 'flexible_connection'))
        main.append(ident)

    def connection(role, *, upstream=False):
        """Named joints C1-C6 occur once, in actual flow order.

        Geometry/port failure clears the part ID, never the logical node.
        An unknown saved intermediate ID must also remain visible as missing.
        """
        check = next((c for c in selection.connections if c.role == role), None)
        if check is None:
            return ()
        from app.pz.metering_connections import CONNECTION_ROLES
        mark = CONNECTION_ROLES[role][0]
        prefix = "outlet" if role == "check_valve_out" else f"connection_{role}"
        ids = []
        if role in detail.connection_thread_items:
            ids.append(add(f"{prefix}_thread", f"Резьбовой соединитель {mark}", catalogue_id=(
                check.thread_adapter.id if check.connector and check.thread_adapter else None)))
        ids.append(add(f"{prefix}_connector", f"Соединитель трубы {mark}", catalogue_id=(
            check.connector.id if check.connector else None)))
        return tuple(reversed(ids)) if upstream else tuple(ids)

    common = getattr(state, "common_inlets", False)
    flow("inlet", "Соединительный участок вводов" if common else "Труба ввода")
    flexible('inlet')
    if state.fire_branch and not getattr(state, "common_inlets", False):
        flow("fire_takeoff", "Ответвление В2 до учёта")
    if getattr(state, "node_key", "") != "hot" and not switching:
        main.extend(connection("inlet_valve_in", upstream=True))
        flow("inlet_valve", "Кран общего ВУ" if common else "Кран ввода", "inlet_valve")
    if core_bypass:
        flow("bypass_start", "Начало обводной")
    reduction = bool(state.meter and detail.inlet_dn and state.meter.dn != detail.inlet_dn)
    if reduction:
        flow("reducer_in", "Переход к DN счётчика")
    flow("valve_before", "Кран до счётчика", "meter_valves")
    if detail.maintenance_layout == "serviceable":
        flow("maintenance_in", "Сервисный отбор внутри отсечек перед фильтром")
    from app.pz.metering_orientation import horizontal_filter_offset
    mixed_filter = horizontal_filter_offset(detail)
    if mixed_filter:
        flow("filter_turn_in", "Поворот 90° перед горизонтальным фильтром")
    main.extend(connection("filter_in", upstream=True))
    flow("filter", "Фильтр", "filter")
    if mixed_filter:
        flow("filter_turn_out", "Поворот 90° после горизонтального фильтра")
    flexible('before_meter')
    main.append(meter_end("kit_in", True))
    flow("meter", "Счётчик", "meter")
    main.append(meter_end("kit_out", False))
    flow("service_before", "Контроль давления / контрольный кран до запорного")
    flow("valve_after", "Кран после счётчика", "meter_valves")
    main.extend(connection("meter_valve_out"))
    if reduction:
        flow("reducer_out", "Переход к DN основной линии")
    low_control = detail.maintenance_layout == "serviceable" and detail.assembly_orientation == "vertical_up"
    if low_control:
        # The return of an upward bypass must not sit below its drain tap.
        # Keep the second normative control downstream of valve_after, but
        # BEFORE the upward bypass return; no new drain is needed here.
        flow("service_after", "Контрольный кран после запорного")
    if core_bypass:
        flow("bypass_end", "Возврат обводной")
    if not low_control:
        flow("service_after", "Контрольный кран после запорного")
    flow("check_valve", "Обратный клапан", "check_valve")
    main.extend(connection("check_valve_out"))
    if detail.maintenance_layout == "serviceable":
        flow("maintenance_out", "Сервисный отбор за обратным клапаном")
        flow("outlet_valve", "Отсечка со стороны здания", "outlet_valve")
    flow("outlet", "Труба после узла")
    paths.append(ChainPath("main", "Основной поток", tuple(main)))

    if core_bypass:
        route_in = add("bypass_route_in", "Трубы и повороты обводной до арматуры")
        valve = add("bypass_valve", "Арматура обводной", "bypass_valve")
        route_out = add("bypass_route_out", "Трубы и повороты обводной после арматуры")
        paths.append(ChainPath("bypass", "Обводная", ("bypass_start", route_in,
            *connection("bypass_valve_in", upstream=True), valve,
            *connection("bypass_valve_out"), route_out, "bypass_end")))
    for number, anchor in ((1, "service_before"), (2, "service_after")):
        cock = add(f"control_cock_{number}", f"Контрольный кран {number}")
        cap = add(f"control_cap_{number}", f"Заглушка контрольного крана {number}")
        paths.append(ChainPath(f"control_{number}", f"Контрольный отбор {number}", (anchor, cock, cap)))
    gauge_cock = add("gauge_cock", "Кран манометра")
    gauge = add("gauge", "Манометр")
    paths.append(ChainPath("gauge", "Манометр", ("service_before", gauge_cock, gauge)))
    if detail.maintenance_layout == "serviceable":
        for suffix in ("in", "out"):
            anchor = f"maintenance_{suffix}"
            cock = add(f"maintenance_cock_{suffix}", "Сервисный кран " + ("перед фильтром" if suffix == "in" else "после обратного клапана"))
            cap = add(f"maintenance_cap_{suffix}", "Заглушка сервисного крана")
            paths.append(ChainPath(anchor, "Обслуживание " + ("фильтра и счётчика" if suffix == "in" else "выходной полости"),
                                   (anchor, cock, cap)))
    if state.fire_branch and not getattr(state, "common_inlets", False):
        valve = add("fire_valve", "Арматура ответвления В2")
        outlet = add("fire_outlet", "Граница ответвления В2")
        paths.append(ChainPath("fire", "В2 до учёта", ("fire_takeoff", valve, outlet)))
    chain = MeteringChain(tuple(nodes), tuple(paths), getattr(state, "assemblies_count", state.inputs_count))
    # A direct straight connection between two selected female ports needs a
    # male/male part. This is a topology-derived generic nipple, not an
    # automatically approved manufacturer model or inferred body length.
    from app.pz.metering_joint_audit import complete_female_joints
    return complete_female_joints(chain, detail, selection.inline_joints)


def chain_contents(project, state):
    """Readable coverage sheet; no fabricated purchase quantities or dimensions."""
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_detail import _text, _line, _lines
    from app.pz.metering_table_grid import table_grid_sides
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    chain = build_metering_chain(project.metering_detail, state, selection)
    has_c4 = "check_valve_out" in project.metering_detail.connection_items
    g = [_text(28,17,"Цепочка соединений водомерного узла",5),
         _text(28,26,f"Состав одного узла; узлов: {chain.instances}; вводов: {state.inputs_count}. Монтажная комплектация.",3.5)]
    rows = [
        ("Ввод", "Труба - вводной кран", "Соединение трубы с краном; крепление и проходка."),
        ("До фильтра", "Кран до счётчика - фильтр", "Для выбранных изделий проверить оба конца. Две ВР напрямую не соединяются."),
        ("Учёт", "Фильтр - штатный комплект - счётчик - штатный комплект", "Комплект учитывается один раз. Прямые участки и монтаж по паспорту счётчика."),
        ("После счётчика", "Узел контроля - кран после счётчика - узел контрольного отбора - обратный клапан",
         "Присоединения, тройники/крестовина, контрольные краны и заглушки требуют отдельных изделий."),
        ("С4 / выход", "Обратный клапан - соединительные детали - труба",
         "Проверка выбранных портов и деталей приведена на карточке С4; монтажная длина не определена."
         if has_c4 else "Соединительные детали выхода не выбраны; монтажная совместимость не подтверждена."),
    ]
    if project.metering_detail.maintenance_layout == "serviceable":
        rows.append(("Ремонтная компоновка", "Отбор перед фильтром; отбор за обратным клапаном; отсечка со стороны здания",
                     "Два нормативных контрольных крана и обводная сохранены. Сервисные отборы не врезаются в прямые участки счётчика. "
                     "Низ/верх определяются профилем, не координатами рисунка; приём воды и полости уточнить."))
    if any(n.id == "reducer_in" for n in chain.nodes):
        descriptions = []
        for role in ("reducer_in", "reducer_out"):
            check = next((c for c in selection.reducers if c.role == role), None)
            mark = "П1" if role == "reducer_in" else "П2"
            descriptions.append(f"{mark}: {check.part.article}; проверено стыков {sum(check.joints_confirmed)}/2."
                                if check and check.part else f"{mark}: изделие не подтверждено.")
        rows.insert(1,("Смена DN", "До крана счётчика / после крана счётчика",
                       "Два перехода вне штатного комплекта счётчика. " + " ".join(descriptions)))
    for path in chain.paths[1:]:
        route = " - ".join(chain.node(n).title for n in path.nodes)
        rows.append((path.title, route,
                     "Размеры соединений, арматура и монтажная компоновка требуют уточнения."))
    # Two-column table avoids compressing the normal 3.5 mm text.
    pages, y, table_top = [], 38, 38
    for label, route, pending in rows:
        body = _lines(route,276,3.5) + _lines(pending,276,3.5)
        label_lines = _lines(label,83,3.5)
        height = max(len(body),len(label_lines))*5.5 + 7
        if y+height > 222:
            g.append(table_grid_sides((27,122,407), table_top, y, kind='chain'))
            pages.append(''.join(g))
            g = [_text(28,17,"Цепочка соединений ВУ - продолжение",5)]
            y = table_top = 29
        g.append(_line(27,y,407,y,.25))
        for i,line in enumerate(label_lines):
            g.append(_text(29,y+6+i*5.5,line,3.5))
        for i,line in enumerate(body):
            g.append(_text(126,y+6+i*5.5,line,3.5))
        y += height
    g.append(table_grid_sides((27,122,407), table_top, y, kind='chain'))
    note = ("Это состав принципиальной схемы, не закупочная спецификация и не монтажный чертёж. "
            "Узлы ответвлений не превращаются автоматически в конкретные тройники. "
            "Расходы, потери и результаты подбора водомеров не изменены.")
    for i,line in enumerate(_lines(note,376,3.5)):
        g.append(_text(28,y+9+i*5.5,line,3.5))
    pages.append(''.join(g))
    return pages

"""Audit *direct* catalogue-to-catalogue joints without inventing adapters.

The logical graph includes unresolved assemblies (tees, meter union halves).
Such a node has no known port until its actual execution is selected. A manual
engagement dimension cannot make two female ports connect to each other.
"""
from dataclasses import dataclass
from app.data.metering_products import ThreadConnector, FlangeConnection


@dataclass(frozen=True)
class Port:
    standard: str
    thread: str
    sex: str
    seal: str = "thread"
    # Exact catalogue meter, not a generic permission for all G union faces.
    mating_meter_ids: tuple[str, ...] = ()
    flange: FlangeConnection | None = None
    dn: int | None = None
    pn_bar: float | None = None

    @property
    def label(self):
        if self.flange:
            return f"Фланец DN{self.dn} PN{self.pn_bar:g}; {self.flange.standard}"
        return (f"{self.standard}{self.thread} " + {"male": "НР", "female": "ВР"}.get(self.sex, "?")
                + (" / плоская прокладка" if self.seal == "flat_gasket" else ""))


@dataclass(frozen=True)
class JointCheck:
    id: str
    before: str
    after: str
    left: Port | None
    right: Port | None
    status: str
    reason: str


def _port(node, catalogue, end, inlet_dn, peer=""):
    from app.data.metering_products import MeteringProduct, MeteringConnector, ThreadConnector, ThreadReducer
    if node.role == 'flexible_connection' and node.catalogue_id:
        from app.data.engineering_catalogue import get_engineering_catalogue
        item = get_engineering_catalogue().require(node.catalogue_id, kind='flexible_connection')
        p = item.ports[0 if end == 'in' else 1]
        flange = FlangeConnection(p.standard, bolt_circle_mm=p.bolt_circle_mm,
                                  bolt_count=p.bolt_count, bolt_hole_mm=p.bolt_hole_mm)
        return Port(p.standard, '', 'flanged', 'rubber_lip', flange=flange, dn=p.dn, pn_bar=item.pn_bar)
    fitting = getattr(catalogue, "fittings", {}).get(node.catalogue_id)
    if fitting:
        index = 0 if end == "in" else 1
        if fitting.kind == "reducer":
            towards_inlet = (node.id == "reducer_in") == (end == "in")
            index = 0 if towards_inlet == (inlet_dn == fitting.large_dn) else 1
        elif len(fitting.ports) > 2:
            if node.id == "service_before":
                if "gauge" in peer:
                    index = 2
                elif "control_cock_1" in peer:
                    index = 3
            elif ((node.id in ("bypass_start", "bypass_end") and "bypass_route" in peer)
                    or (node.id == "service_after" and "control_cock_2" in peer)
                    or (node.id in ("maintenance_in", "maintenance_out") and "maintenance_cock_" in peer)
                    or (node.id == "fire_takeoff" and "fire_valve" in peer)):
                index = 2
        p = fitting.ports[index]
        if p.connection == "threaded":
            return Port("G", p.thread, p.sex, dn=p.dn, pn_bar=fitting.pn_bar)
        circle, count, hole = p.drilling
        flange = FlangeConnection("Каталог изготовителя", bolt_circle_mm=circle,
                                  bolt_count=count, bolt_hole_mm=hole)
        return Port(flange.standard, "", "flanged", "flange_gasket", flange=flange,
                    dn=p.dn, pn_bar=fitting.pn_bar)
    service = getattr(catalogue, "service_products", {}).get(node.catalogue_id)
    if service:
        # Verified connections survive a quarantined body-dimension conflict.
        # A plug/gauge has one port and can never be a through-flow fitting.
        if end == "out" and len(service.ports) == 1:
            return None
        return Port(*service.ports[0 if end == "in" else 1])
    if node.role == "inline_nipple" and not node.catalogue_id and node.required_standard and node.required_thread:
        return Port(node.required_standard, node.required_thread, "male")
    kit = catalogue.connection_kits.get(node.catalogue_id)
    if kit and node.id in ("kit_in", "kit_out"):
        meter_end = (node.id == "kit_in") == (end == "out")
        if meter_end:
            return (Port("G", kit.meter_thread, "female", kit.meter_seal, kit.meter_ids)
                    if kit.meter_seal == "flat_gasket" else None)
        return (Port("G", kit.pipe_thread, kit.pipe_connection_sex)
                if kit.pipe_connection_sex in ("male", "female") else None)
    product = next((items[node.catalogue_id] for items in (
        catalogue.products, catalogue.connectors, catalogue.thread_connectors, catalogue.reducers
    ) if node.catalogue_id in items), None)
    if product is None or product.dimension_status != "verified":
        return None
    if isinstance(product, MeteringProduct):
        if product.flange:
            return Port(product.connection_standard, "", "flanged", "flange_gasket",
                        flange=product.flange, dn=product.dn, pn_bar=product.pn_bar)
        # A meter's union nut seals on its end face, not as an ordinary
        # male-thread fitting. Its separate kit nodes must remain in the graph.
        if product.kind == "meter":
            kits = [k for k in catalogue.connection_kits.values()
                    if product.id in k.meter_ids and k.meter_seal == "flat_gasket"]
            return (Port(product.connection_standard, product.thread, product.connection_sex,
                         "flat_gasket", (product.id,)) if kits else None)
        return Port(product.connection_standard, product.thread, product.connection_sex)
    upstream = "inlet_valve_in" in node.id or "filter_in" in node.id or "bypass_valve_in" in node.id
    if isinstance(product, MeteringConnector):
        equipment_end = "out" if upstream else "in"
        return Port(product.connection_standard, product.thread, product.connection_sex) if end == equipment_end else None
    if isinstance(product, ThreadConnector):
        equipment_end = "out" if upstream else "in"
        if end == equipment_end:
            return Port(product.connection_standard, product.equipment_thread, product.equipment_sex)
        return Port(product.connection_standard, product.pipe_connector_thread, product.pipe_connector_sex)
    if isinstance(product, ThreadReducer):
        # reducer_in goes from the inlet DN to the smaller metering line;
        # reducer_out is the same product oriented in the opposite direction.
        if inlet_dn not in (product.large_dn, product.small_dn):
            return None
        towards_inlet_size = (node.id == "reducer_in") == (end == "in")
        large = towards_inlet_size == (inlet_dn == product.large_dn)
        return Port(product.connection_standard,
                    product.large_thread if large else product.small_thread,
                    product.large_sex if large else product.small_sex)
    return None


def audit_direct_joints(chain, catalogue, *, inlet_dn=None):
    checks = []
    for a, b in chain.links:
        left, right = _port(chain.node(a), catalogue, "out", inlet_dn, b), _port(chain.node(b), catalogue, "in", inlet_dn, a)
        if left is None or right is None:
            status, reason = "unresolved", "Исполнение соединительного узла не определено"
        elif left.flange or right.flange:
            if not left.flange or not right.flange or left.dn != right.dn:
                status, reason = "incompatible", "Нужен переход между разными типами/DN присоединений"
            elif any(a is not None and b is not None and a != b for a, b in (
                (left.flange.bolt_circle_mm, right.flange.bolt_circle_mm),
                (left.flange.bolt_count, right.flange.bolt_count))):
                status, reason = "incompatible", "Присоединительные размеры фланцев различаются"
            else:
                status, reason = "unresolved", "Проверить исполнение уплотнительных поверхностей, сверловку, прокладку и крепёж фланцев; совпадения DN недостаточно"
        elif (left.standard, left.thread) != (right.standard, right.thread):
            status, reason = "incompatible", "Различаются присоединения; прямое соединение не подтверждено"
        elif left.seal != right.seal:
            status, reason = "incompatible", "Резьбовое уплотнение и накидная гайка с плоской прокладкой не взаимозаменяемы"
        elif {left.sex, right.sex} != {"male", "female"}:
            status, reason = "incompatible", "Нужна соединительная деталь: два одинаковых окончания напрямую не соединяются"
        elif left.seal == "flat_gasket" and not left.mating_meter_ids and not right.mating_meter_ids:
            status, reason = "unresolved", "Резьба совпадает; торцевое уплотнение манометра и крана не подтверждено"
        elif left.seal == "flat_gasket" and not set(left.mating_meter_ids).intersection(right.mating_meter_ids):
            status, reason = "incompatible", "Комплект не относится к данному исполнению счётчика"
        elif left.seal == "flat_gasket":
            status, reason = "ports_match", "Штатное торцевое соединение; толщина сжатой прокладки и монтажные размеры не заданы"
        else:
            status, reason = "ports_match", "Размер и тип резьбы согласованы; посадка и уплотнение проверяются отдельно"
        checks.append(JointCheck(f"{a}>{b}", a, b, left, right, status, reason))
    return tuple(checks)


def complete_female_joints(chain, detail, assignments=()):
    """Minimal straight connection, only when BOTH actual ports are known.

    No action on unknown tees, kits, pipe ends, thread mismatch or two male
    ends. A generic nipple enters the SO once but has no fabricated model/L.
    Existing assigned connectors already interrupt the direct edge.
    """
    from app.data.metering_products import get_metering_catalogue
    from app.pz.metering_chain import ChainNode, ChainPath, MeteringChain
    required = {}
    for c in audit_direct_joints(chain, get_metering_catalogue(), inlet_dn=detail.inlet_dn):
        if (c.left and c.right and c.left.sex == c.right.sex == "female"
            and c.left.seal == c.right.seal == "thread"
            and c.left.standard == c.right.standard == "G" and c.left.thread == c.right.thread):
            ident=f"joint_{c.before}__{c.after}"
            check = next((c for c in assignments if c.id == ident), None)
            required[(c.before,c.after)] = ChainNode(ident, f"Ниппель G{c.left.thread} НР/НР",
                catalogue_id=check.part.id if check and check.part else None,
                role="inline_nipple", required_thread=c.left.thread, required_standard="G")
    if not required:
        return chain
    paths=[]
    for path in chain.paths:
        ids=[]
        for a,b in zip(path.nodes,path.nodes[1:]):
            ids.append(a)
            if (a,b) in required:
                ids.append(required[(a,b)].id)
        ids.append(path.nodes[-1])
        paths.append(ChainPath(path.id,path.title,tuple(ids)))
    return MeteringChain(chain.nodes+tuple(required.values()),tuple(paths),chain.instances)


@dataclass(frozen=True)
class InlineJointCheck:
    id: str
    part: ThreadConnector | None
    candidates: tuple[ThreadConnector, ...]
    proposed: bool
    errors: tuple[str, ...]
    pending: tuple[str, ...]


def check_inline_joints(chain, detail, catalogue, *, revision_ok):
    """No DN guesses, hidden brand substitution or fabricated thread overlap.

    The unbound chain already contains only necessary F/F connectors. Bind a
    body to those exact current ports. Stale/invalid manual choices never fall
    back to a proposal. A proposal is geometry only, not acceptance of P/T.
    """
    from app.pz.equipment_origin import origin_error
    nodes = {n.id: n for n in chain.nodes if n.role == "inline_nipple"}
    checks = []
    for ident in sorted(nodes.keys() | detail.inline_joint_items.keys()):
        node, requested = nodes.get(ident), detail.inline_joint_items.get(ident)
        errors, pending = [], []
        pressure, temperature = detail.design_pressure_bar, detail.water_temperature_c

        def incompatibilities(part):
            problems = []
            if part.dimension_status != "verified":
                problems.append("Осевые размеры изделия не подтверждены")
            if node and (part.connection_standard != node.required_standard
                or part.equipment_thread != node.required_thread
                or part.pipe_connector_thread != node.required_thread
                or part.equipment_sex != "male" or part.pipe_connector_sex != "male"):
                problems.append("Ниппель не соответствует обоим текущим резьбовым портам")
            if pressure is not None and pressure > part.pn_bar:
                problems.append("Давление выше PN ниппеля")
            if temperature is not None and not part.temperature_c[0] <= temperature <= part.temperature_c[1]:
                problems.append("Температура вне паспортного диапазона ниппеля")
            table = dict(part.pressure_temperature)
            if pressure is not None and temperature in table and pressure > table[temperature]:
                problems.append("Давление выше паспортного предела ниппеля при заданной температуре")
            if error := origin_error(detail, part.id):
                problems.append(error)
            return problems

        candidates = tuple(p for p in catalogue.thread_connectors.values()
                           if node and not incompatibilities(p))
        part, proposed = None, False
        if requested:
            part = catalogue.thread_connectors.get(requested)
            if part is None:
                errors.append("Неизвестный ниппель; автоматической замены нет")
            else:
                errors.extend(incompatibilities(part))
        if not node:
            errors.append("Стык отсутствует в текущей цепочке; перепроверьте сохранённое назначение")
        if not revision_ok:
            errors.append("Редакция каталога не подтверждена; ниппель необходимо перепроверить")
        if not requested and node and not errors:
            if (detail.inline_joint_selection_mode == "catalogue_proposal"
                and pressure is not None and temperature is not None and len(candidates) == 1):
                part, proposed = candidates[0], True
            else:
                pending.append("Каталожный ниппель не выбран" if candidates else "Нет проверенного ниппеля для текущих портов/условий")
        if pressure is None or temperature is None:
            pending.append("Нужны расчётное максимальное давление и температура")
        if errors:
            part = None
        if part:
            if proposed:
                pending.append("Предварительное каталожное предложение; не согласованное закупочное назначение")
            pending += ["Допустимость сочетания P/T проверить по паспорту исполнения; PN не является кривой P/T",
                        "Уплотнение и посадки двух резьб уточнить; L корпуса не равна монтажной длине"]
        checks.append(InlineJointCheck(ident, part, candidates, proposed, tuple(errors), tuple(pending)))
    return tuple(checks)


def meter_kit_topology_issues(chain, catalogue):
    """A factory straight-section assembly must survive routing/branch edits.

    This checks the drawn solution, not installed straight lengths or field
    conditions. No fixed 3DN/1DN rule is extrapolated to other products.
    """
    nodes = {n.id: n for n in chain.nodes}
    kit_in, kit_out = nodes.get("kit_in"), nodes.get("kit_out")
    kit = catalogue.connection_kits.get(kit_in.catalogue_id) if kit_in else None
    meter = nodes.get("meter")
    product = catalogue.products.get(meter.catalogue_id) if meter else None
    straight = product.straight_sections if product else None
    if not straight and (not kit or not kit.protects_straight_sections):
        return ()
    issues = []
    if straight:
        for node, multiplier in ((kit_in, straight.before_dn), (kit_out, straight.after_dn)):
            if not node or node.role != "meter_straight" or node.minimum_length_mm != product.dn * multiplier:
                issues.append("Потеряно паспортное требование к прямому участку фланцевого счётчика")
    elif not kit_out or kit_out.catalogue_id != kit.id or not meter or meter.catalogue_id not in kit.meter_ids:
        issues.append("Обе присоединительные части должны относиться к штатному комплекту выбранного счётчика")
    main = next((p.nodes for p in chain.paths if p.id == "main"), ())
    if (not all(n in main for n in ("kit_in", "meter", "kit_out"))
        or main[main.index("kit_in"):main.index("kit_out")+1] != ("kit_in", "meter", "kit_out")):
        issues.append("В зону штатного комплекта счётчика попала посторонняя деталь; переходы и арматура должны быть вне прямых участков")
    for path in chain.paths:
        if path.id != "main" and set(path.nodes).intersection(("kit_in", "meter", "kit_out")):
            issues.append(f"{path.title}: отбор из зоны прямых участков штатного комплекта не допускается компоновкой")
    return tuple(issues)

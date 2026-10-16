"""Design-time isolation/drainage audit, NOT an instruction to operate valves.

Pressure reachability is conservative and bidirectional: a check valve is not
a maintenance isolation boundary. Gravity and air paths are separate graphs.
Unknown geometry can never yield a successful drainage check. No drawing
coordinates, flow rates, guessed volumes or hydraulic formulae are used.
"""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ServiceNode:
    id: str
    title: str = ''
    kind: str = 'component'  # component / isolation / check / source
    wet: bool = True
    body_drainable: bool | None = None
    # A passive check needs explicit low-head evidence before gravity passage.
    forward_to: str = ''
    gravity_passage_verified: bool = False
    air_passage_verified: bool = False


@dataclass(frozen=True)
class ServiceLink:
    a: str
    b: str
    gravity: str = 'unknown'  # a_to_b / b_to_a / level / blocked / unknown
    air_passable: bool | None = None
    basis: str = ''


@dataclass(frozen=True)
class ServicePort:
    id: str
    node: str
    relief: bool = False
    drain: bool = False
    air: bool = False
    discharge_basis: str = ''  # Explicit safe receiver/air-gap arrangement.


@dataclass(frozen=True)
class ServiceNetwork:
    nodes: tuple[ServiceNode, ...]
    links: tuple[ServiceLink, ...]
    ports: tuple[ServicePort, ...] = ()

    def validate(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes) or any(not n.id for n in self.nodes):
            raise ValueError('Сеть обслуживания: пустые/повторные ID')
        for n in self.nodes:
            if n.kind not in ('component','isolation','check','source'):
                raise ValueError('Сеть обслуживания: неизвестный тип элемента')
            if n.body_drainable is not None and type(n.body_drainable) is not bool:
                raise ValueError('Сеть обслуживания: неверное подтверждение опорожнения корпуса')
            if any(type(v) is not bool for v in (n.wet, n.gravity_passage_verified, n.air_passage_verified)):
                raise ValueError('Сеть обслуживания: неверный логический признак')
            if n.kind == 'check' and n.forward_to and n.forward_to not in ids:
                raise ValueError('Сеть обслуживания: неизвестное направление обратного клапана')
        seen = set()
        for e in self.links:
            if e.a not in ids or e.b not in ids or e.a == e.b:
                raise ValueError('Сеть обслуживания: неверная связь')
            key = frozenset((e.a,e.b))
            if key in seen:
                raise ValueError('Сеть обслуживания: повторная связь')
            seen.add(key)
            if e.gravity not in ('a_to_b','b_to_a','level','blocked','unknown'):
                raise ValueError('Сеть обслуживания: неизвестный профиль участка')
            if e.air_passable is not None and type(e.air_passable) is not bool:
                raise ValueError('Сеть обслуживания: неверный признак прохода воздуха')
            if (e.gravity != 'unknown' or e.air_passable is not None) and not e.basis.strip():
                raise ValueError('Сеть обслуживания: нет основания геометрии/прохода воздуха')
        for n in self.nodes:
            if n.kind == 'check' and n.forward_to and frozenset((n.id,n.forward_to)) not in seen:
                raise ValueError('Сеть обслуживания: направление клапана не соответствует связи')
        if len({p.id for p in self.ports}) != len(self.ports) or any(not p.id or p.node not in ids for p in self.ports):
            raise ValueError('Сеть обслуживания: неизвестный/повторный сервисный порт')
        for p in self.ports:
            if any(type(v) is not bool for v in (p.relief,p.drain,p.air)):
                raise ValueError('Сеть обслуживания: неверное назначение порта')


@dataclass(frozen=True)
class MaintenanceResult:
    target: str
    close_valves: tuple[str, ...]
    compartment: tuple[str, ...]
    source_paths: tuple[tuple[str, ...], ...]
    isolation: str
    pressure_relief: str
    drainage: str
    air_admission: str
    trapped_nodes: tuple[str, ...]
    unknown_drain_nodes: tuple[str, ...]
    relief_ports: tuple[str, ...]
    drain_ports: tuple[str, ...]
    air_ports: tuple[str, ...]
    findings: tuple[dict, ...]
    status: str
    # A graph never certifies valve tightness, zero pressure or a dry body.
    safe_to_remove: bool = False

    def to_dict(self):
        return asdict(self)


def assess_removal(network, target, *, closed_valves=None):
    """Propose the nearest valve cut, or verify an explicitly supplied cut.

    The removable valve itself is NEVER an isolator. All source boundaries,
    including building-side backfeed, are checked. Port opening is a design
    scenario only; this function neither commands hardware nor authorises work.
    """
    network.validate()
    nodes = {n.id:n for n in network.nodes}
    if target not in nodes or nodes[target].kind == 'source':
        raise ValueError('Неизвестный/необслуживаемый элемент')
    adj = {n:[] for n in nodes}
    for e in network.links:
        adj[e.a].append((e.b,e)); adj[e.b].append((e.a,e))
    sources = {n.id for n in network.nodes if n.kind == 'source'}

    def reachable(start, closed, *, mode='pressure', possible=False):
        paths = {start:(start,)}; queue = [start]
        for a in queue:
            for b,e in adj[a]:
                if b in closed or b in paths:
                    continue
                if mode != 'pressure':
                    check = nodes[a] if nodes[a].kind == 'check' else None
                    passage = check and (check.air_passage_verified if mode == 'air'
                                         else check.gravity_passage_verified)
                    if check and (not passage or b != check.forward_to):
                        # No guaranteed opening under residual gravity head;
                        # a check valve is not assumed to admit air either.
                        continue
                    if mode == 'air':
                        if e.air_passable is False or (e.air_passable is None and not possible):
                            continue
                    elif not (e.gravity == 'level' or
                              e.gravity == ('a_to_b' if a == e.a else 'b_to_a') or
                              (possible and e.gravity == 'unknown')):
                        continue
                paths[b] = (*paths[a],b); queue.append(b)
        return paths

    if closed_valves is None:
        # Frontier of the target component: every branch is visited, so rings
        # and bypasses cannot be hidden by a two-valve linear-path heuristic.
        closed, visited, queue = set(), {target}, [target]
        for a in queue:
            for b,_ in adj[a]:
                if b in visited:
                    continue
                visited.add(b)
                if nodes[b].kind == 'isolation':
                    closed.add(b)
                elif nodes[b].kind != 'source':
                    queue.append(b)
    else:
        closed = set(closed_valves)
        if target in closed or any(n not in nodes or nodes[n].kind != 'isolation' for n in closed):
            raise ValueError('Нельзя отключать снимаемой арматурой или обратным клапаном')
    paths = reachable(target,closed)
    compartment = set(paths)
    pressure_paths = tuple(paths[n] for n in sorted(sources & compartment))
    findings = []

    def finding(code,status,message):
        findings.append(dict(code=code,status=status,message=message))

    isolation = 'blocked' if pressure_paths else ('checked' if sources else 'needs_data')
    if pressure_paths:
        finding('LIVE_SOURCE','blocked','Остаётся связь с источником воды: '+
                '; '.join(' → '.join(path) for path in pressure_paths))
    elif not sources:
        finding('SOURCES_UNKNOWN','needs_data','Не заданы все границы возможной подачи и обратного подпора.')
    ports = [p for p in network.ports if p.node in compartment and p.node != target]
    wet = {n for n in compartment if nodes[n].wet and nodes[n].kind != 'source'}
    # Each pocket separated by a passive check needs its own relief path.
    # In particular, removing the check must not magically open its obturator.
    passive = {n.id for n in network.nodes if n.kind == 'check'}
    relief = [p for p in ports if p.relief]
    relieved, possible_relief = set(), set()
    for p in relief:
        reach = set(reachable(p.node,closed | passive))
        possible_relief.update(reach)
        if p.discharge_basis.strip():
            relieved.update(reach)
    pressure_wet = wet - passive
    pressure_relief = ('blocked' if not relief or not pressure_wet <= possible_relief else
                       'needs_data' if not pressure_wet <= relieved or wet & passive else 'checked')
    if pressure_relief != 'checked':
        finding('PRESSURE_RELIEF',pressure_relief,
                'Нужен контролируемый сброс давления отключённого участка с безопасным отводом воды; разборка соединения его не заменяет.')
    drains = [p for p in ports if p.drain]
    air_ports = [p for p in ports if p.air]
    trapped, unknown = [], []
    for n in sorted(wet):
        if nodes[n].body_drainable is False:
            trapped.append(n)
            continue
        certain = reachable(n,closed,mode='gravity')
        possible = reachable(n,closed,mode='gravity',possible=True)
        valid = [p for p in drains if p.node in certain and p.discharge_basis.strip()]
        if valid:
            if nodes[n].body_drainable is not True:
                unknown.append(n)
        elif any(p.node in possible for p in drains):
            unknown.append(n)
        else:
            trapped.append(n)
    drainage = 'blocked' if trapped or not drains else ('needs_data' if unknown else 'checked')
    if drainage != 'checked':
        finding('DRAIN_PATH',drainage,
                ('Нет пути самотёчного слива: '+', '.join(trapped)+'. ' if trapped else '')+
                'Проверить нижний слив, отсутствие карманов, полости корпусов и место приёма воды. Отсутствующие отметки не берутся с рисунка.')
    # Air must reach the complete wet compartment, not just the tap nearest
    # the target. Edges here describe a VERIFIED vent route, not pipe openness.
    certain_air, possible_air = set(), set()
    for p in air_ports:
        certain_air.update(reachable(p.node,closed,mode='air'))
        possible_air.update(reachable(p.node,closed,mode='air',possible=True))
    air = 'checked' if air_ports and wet <= certain_air else (
        'needs_data' if air_ports and wet <= possible_air else 'blocked')
    if air != 'checked':
        finding('AIR_ADMISSION',air,'Не подтверждён впуск воздуха во весь опорожняемый участок. Открытие соединения снимаемого прибора не считается воздушным устройством.')
    status = 'blocked' if any(f['status']=='blocked' for f in findings) else (
        'needs_data' if findings else 'checked')
    return MaintenanceResult(target,tuple(sorted(closed)),tuple(sorted(compartment)),
        pressure_paths,isolation,pressure_relief,drainage,air,tuple(trapped),tuple(unknown),
        tuple(p.id for p in relief),tuple(p.id for p in drains),tuple(p.id for p in air_ports),
        tuple(findings),status)

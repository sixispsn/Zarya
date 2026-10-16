"""L06 repair extension: explicit closed edges/ports, unchanged A*L_eff*q².

Scope after isolation: a tree or one hydraulic cycle, fed by equal-head ports
of ONE pump header. A virtual root imposes the common boundary; its zero-loss
edges are constraints, not invented pipes. Continuity is exact on a spanning
tree; the remaining cycle is balanced by a monotone scalar bisection.

The intact two-port solver and working legacy are deliberately not modified.
Disconnected active cabinets are an error, never silently removed from demand.
"""
from dataclasses import dataclass
from math import isfinite, sqrt

from app.calc.fire_diaphragm_graph import flow_domain, read_pressure_drop
from app.calc.fire_hydraulics import MPA_TO_M, SourceKind, ValveKind
from app.calc.fire_pressure_flow import CabinetFlow, PressureFlowResult, PumpFlowCheck, _linear_solve
from app.calc.pump_curve import interpolate_head, valid_curve


@dataclass(frozen=True)
class RepairHydraulics:
    cabinet_heads_m: dict
    segment_flows_lps: dict
    port_flows_lps: dict
    energy_residual_m: float
    balance_residual_lps: float


class RepairNetwork:
    """Prepared residual topology, with explicit isolation and no input mutation."""

    def __init__(self, network, *, closed_segment_ids=(), closed_port_ids=()):
        self.network = network
        ports = [network.source] + ([network.second_source] if network.second_source else [])
        nodes = network.nodes
        self.ids = [c.cabinet_id for c in network.cabinets]
        segments = {s.segment_id: s for s in network.segments}
        port_ids = [p.node_id for p in ports]
        closed_segments, closed_ports = set(closed_segment_ids), set(closed_port_ids)
        if (not self.ids or len(set(self.ids)) != len(self.ids)
                or len(segments) != len(network.segments) or len(set(port_ids)) != len(port_ids)):
            raise ValueError('Unique pipes, ports and active cabinets required')
        if closed_segments-set(segments) or closed_ports-set(port_ids):
            raise ValueError('Unknown isolated pipe or header port')
        if not closed_segments and not closed_ports:
            raise ValueError('Repair calculation requires explicit isolation')
        if any(not isfinite(n.elevation_m) for n in nodes.values()):
            raise ValueError('Invalid elevation')
        if any(p.node_id not in nodes or p.kind != SourceKind.CITY_MAIN for p in ports):
            raise ValueError('Explicit common discharge-header ports required')
        self.datum = nodes[ports[0].node_id].elevation_m
        if any(abs(nodes[p.node_id].elevation_m-self.datum) > 1e-9 for p in ports):
            raise ValueError('Header ports must have the same elevation')
        if any(c.node_id not in nodes for c in network.cabinets):
            raise ValueError('Unknown cabinet node')
        self.edges = []
        for s in network.segments:
            if (s.from_node not in nodes or s.to_node not in nodes or s.from_node == s.to_node
                    or any(not isfinite(v) for v in (s.A, s.length_m, s.equiv_length_m, s.valves_equiv_length_m))
                    or s.A <= 0 or s.length_m <= 0 or s.equiv_length_m < 0
                    or any(not isfinite(v.equiv_length_m) or v.equiv_length_m < 0 for v in s.valves)):
                raise ValueError('Invalid explicit pipe resistance or endpoints')
            if s.segment_id not in closed_segments:
                resistance = s.A*s.effective_length_m
                if not isfinite(resistance):
                    raise ValueError('Nonfinite pipe resistance')
                if any(v.kind == ValveKind.CHECK for v in s.valves):
                    raise ValueError('Internal check-valve direction is outside this repair model')
                self.edges.append((s.from_node, s.to_node, resistance, s.segment_id))
        self.physical_count = len(self.edges)
        self.root = object()
        self.active_ports = [p.node_id for p in ports if p.node_id not in closed_ports]
        if not self.active_ports:
            raise ValueError('All discharge-header ports are closed')
        for p in self.active_ports:
            self.edges.append((self.root, p, 0., None))
        adjacency = {}
        for i, (a, b, _, _) in enumerate(self.edges):
            adjacency.setdefault(a, []).append((b, i, 1))
            adjacency.setdefault(b, []).append((a, i, -1))
        self.parent = {self.root: None}
        self.order = [self.root]
        tree_edges = set()
        for node in self.order:
            for other, idx, sign in adjacency.get(node, []):
                if other not in self.parent:
                    self.parent[other] = (node, idx, sign)
                    self.order.append(other)
                    tree_edges.add(idx)
        unreachable = [c.cabinet_id for c in network.cabinets if c.node_id not in self.parent]
        if unreachable:
            raise ValueError('Disconnected active cabinets: '+', '.join(unreachable))
        self.used = [i for i, (a, b, _, _) in enumerate(self.edges) if a in self.parent and b in self.parent]
        chords = [i for i in self.used if i not in tree_edges]
        if len(chords) > 1:
            raise ValueError('Residual topology exceeds one hydraulic cycle')
        self.cycle = None
        if chords:
            idx = chords[0]
            a, b, _, _ = self.edges[idx]
            self.cycle = self._tree_flows({a: 1., b: -1.})
            self.cycle[idx] = 1.
            if not any(c and self.edges[i][2] > 0 for i, c in enumerate(self.cycle)):
                raise ValueError('Degenerate zero-resistance cycle')

    def _tree_flows(self, demands):
        accumulated = dict(demands)
        flows = [0.]*len(self.edges)
        for node in reversed(self.order[1:]):
            parent, idx, sign = self.parent[node]
            q = accumulated.get(node, 0.)
            flows[idx] = sign*q
            accumulated[parent] = accumulated.get(parent, 0.)+q
        return flows

    def solve(self, flows_by_cabinet, header_head_m):
        if (set(flows_by_cabinet) != set(self.ids) or not isfinite(header_head_m)
                or any(not isfinite(q) or q < 0 for q in flows_by_cabinet.values())):
            raise ValueError('Finite header pressure and one nonnegative flow per active cabinet required')
        demands = {}
        for cab in self.network.cabinets:
            demands[cab.node_id] = demands.get(cab.node_id, 0.)+flows_by_cabinet[cab.cabinet_id]
        flows = self._tree_flows(demands)
        if self.cycle is not None:
            def residual(x):
                return sum(c*self.edges[i][2]*(flows[i]+c*x)*abs(flows[i]+c*x)
                           for i, c in enumerate(self.cycle) if c)
            low, high = -1., 1.
            for _ in range(60):
                if residual(low) <= 0 <= residual(high):
                    break
                low *= 2; high *= 2
            else:
                raise ValueError('Cannot bracket cycle flow')
            for _ in range(100):
                x = (low+high)/2
                error = residual(x)
                if abs(error) <= 1e-10:
                    break
                if error > 0: high = x
                else: low = x
            else:
                raise ValueError('Cycle energy did not converge')
            flows = [q+c*x for q, c in zip(flows, self.cycle)]
        potential = {self.root: header_head_m+self.datum}
        for node in self.order[1:]:
            parent, idx, sign = self.parent[node]
            potential[node] = potential[parent]-sign*self.edges[idx][2]*flows[idx]*abs(flows[idx])
        if any(not isfinite(v) for v in potential.values()):
            raise ValueError('Nonfinite network head')
        energy = max(abs(potential[a]-potential[b]-r*flows[i]*abs(flows[i]))
                     for i in self.used for a, b, r, _ in [self.edges[i]])
        net_out = {node: 0. for node in self.order}
        for i in self.used:
            a, b, _, _ = self.edges[i]
            net_out[a] += flows[i]; net_out[b] -= flows[i]
        balance = max(abs(net_out[n]+demands.get(n, 0.)) for n in self.order[1:])
        if energy > 1e-7 or balance > 1e-8:
            raise ValueError('Residual network conservation failure')
        return RepairHydraulics(
            {c.cabinet_id: potential[c.node_id]-self.network.nodes[c.node_id].elevation_m
             for c in self.network.cabinets},
            {sid: flows[i] for i, (_, _, _, sid) in enumerate(self.edges[:self.physical_count])},
            {p: flows[self.physical_count+i] for i, p in enumerate(self.active_ports)}, energy, balance)


def check_repair_operating_point(network, characteristics, curve, *,
        closed_segment_ids=(), closed_port_ids=(), suction_static_head_m,
        supply_resistance, apertures_mm, station_suction_resistance=0.,
        station_discharge_resistance=0., axis_offset_px=0., max_iterations=60):
    """Same bounded pump/nomogram equations as intact L06; repaired graph only.

    Apertures stay fixed. This is a steady state AFTER isolation, not a leak,
    valve-closing transient, pump switching transient or proof of room coverage.
    """
    net = RepairNetwork(network, closed_segment_ids=closed_segment_ids, closed_port_ids=closed_port_ids)
    chars = tuple(characteristics)
    ids = [c.cabinet_id for c in chars]
    if len(set(ids)) != len(ids) or set(ids) != set(net.ids):
        raise ValueError('Exactly one characteristic per cabinet required')
    for c in chars: c.validate()
    if (not valid_curve(curve) or any(b[1] > a[1] for a, b in zip(curve, curve[1:]))
            or not isfinite(suction_static_head_m) or max_iterations < 1
            or any(not isfinite(r) or r < 0 for r in (supply_resistance,
                station_suction_resistance, station_discharge_resistance))):
        raise ValueError('Invalid pump curve, source, resistance or iteration count')
    if set(apertures_mm)-set(ids):
        raise ValueError('Unknown cabinet in diaphragm layout')
    cabs = {c.cabinet_id: c for c in network.cabinets}
    domains = {i: flow_domain(valve_dn=cabs[i].dn, aperture_mm=d, axis_offset_px=axis_offset_px)
               for i, d in apertures_mm.items()}
    q = [max(c.minimum_flow_lps, sqrt(c.minimum_head_m/c.resistance_head)) for c in chars]
    for j, i in enumerate(ids):
        if i in domains:
            low, high = domains[i]
            q[j] = min(max(q[j], low+1e-5), high-1e-5)

    def evaluate(flows):
        if any(not isfinite(q) or q < 0 for q in flows): raise ValueError('Invalid flow trial')
        losses = [MPA_TO_M*read_pressure_drop(valve_dn=cabs[i].dn, flow_lps=q,
                    aperture_mm=apertures_mm[i], axis_offset_px=axis_offset_px)
                  if i in domains else 0. for i, q in zip(ids, flows)]
        total = sum(flows)
        pump = interpolate_head(curve, total*3.6)
        if pump is None: raise ValueError('Outside published pump range')
        suction = suction_static_head_m-(supply_resistance+station_suction_resistance)*total**2
        header = suction+pump-station_discharge_resistance*total**2
        hydraulics = net.solve(dict(zip(ids, flows)), header)
        residual = [hydraulics.cabinet_heads_m[c.cabinet_id]-c.resistance_head*q*q-loss
                    for c, q, loss in zip(chars, flows, losses)]
        return residual, losses, hydraulics, pump, suction, header

    norm = lambda v: max(abs(x) for x in v)
    converged = False
    for iteration in range(1, max_iterations+1):
        try: values = evaluate(q)
        except ValueError: break
        residual = values[0]
        if norm(residual) <= 1e-5:
            converged = True
            break
        jac = [[0.]*len(q) for _ in q]
        valid = True
        for j, value in enumerate(q):
            shift = max(1e-4, value*1e-4)
            for step in (shift, -shift):
                trial = q.copy(); trial[j] += step
                try:
                    r = evaluate(trial)[0]
                    for i in range(len(q)): jac[i][j] = (r[i]-residual[i])/step
                    break
                except ValueError: pass
            else:
                valid = False
                break
        if not valid: break
        try: delta = _linear_solve(jac, [-x for x in residual])
        except ValueError: break
        damping = 1.
        for _ in range(28):
            trial = [x+damping*d for x, d in zip(q, delta)]
            try:
                if norm(evaluate(trial)[0]) < norm(residual):
                    q = trial
                    break
            except ValueError: pass
            damping /= 2
        else: break
    if not converged:
        return PumpFlowCheck('unresolved_within_nomogram_domain', None, None, None, None, None,
            'No bounded repair solution; never extrapolated or accepted as a pass')
    residual, losses, hydraulic, pump, suction, header = values
    rows = []
    for c, flow, loss in zip(chars, q, losses):
        h = hydraulic.cabinet_heads_m[c.cabinet_id]; outlet = h-loss
        rows.append(CabinetFlow(c.cabinet_id, flow, h, outlet, loss, c.minimum_flow_lps, c.minimum_head_m,
            flow+1e-6 >= c.minimum_flow_lps and outlet+1e-5 >= c.minimum_head_m,
            outlet <= c.maximum_head_m if c.maximum_head_m is not None else None,
            True if c.cabinet_id in domains else None))
    balance = max(hydraulic.balance_residual_lps, abs(sum(hydraulic.port_flows_lps.values())-sum(q)))
    op = PressureFlowResult(header, sum(q), tuple(rows), iteration, 0.,
        max(norm(residual), hydraulic.energy_residual_m), balance,
        ideal_controls=False, product_verified=False, fixed_controls=bool(apertures_mm))
    status = ('suction_unverified' if suction <= 0 else
              'outside_characteristic_range' if any(c.within_characteristic_range is False for c in rows) else
              'meets_minimum' if all(c.meets_minimum for c in rows) else 'insufficient_at_cabinet')
    return PumpFlowCheck(status, op, sum(q)*3.6, pump, suction, 0.,
        'L06 isolated-network study; unchanged apertures and one active pump; no coverage or release approval')

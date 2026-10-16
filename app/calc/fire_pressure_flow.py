"""L06: explicit pressure-driven extension, NOT a replacement of legacy T73.

Scope: one intact ring, two ports of one discharge header, independent terminal
cabinet branches. Existing ring losses are reused without new pipe coefficients.
The caller supplies an outlet characteristic and an explicit source. Handbook
characteristics and ideal pressure controls are study models, not product proof.
"""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite, sqrt

from app.calc.fire_hydraulics import MPA_TO_M, SourceKind
from app.calc.pump_curve import interpolate_head, valid_curve
from app.calc.ring_hydraulics import decompose_ring_network, solve_two_source_scenario
from app.data.fire_tables import get_nozzle_data


@dataclass(frozen=True)
class CabinetCharacteristic:
    """p(MPa) = resistance_mpa_per_lps2 * q(l/s)^2, at cabinet outlet.

    minimum_head_m / minimum_flow_lps are independent acceptance requirements.
    They need not lie exactly on an approximate handbook characteristic.
    """
    cabinet_id: str
    resistance_mpa_per_lps2: float
    minimum_flow_lps: float
    minimum_head_m: float
    source: str
    evidence: str  # 'handbook_study' or 'technical_documentation'
    maximum_head_m: float | None = None  # explicitly documented model range

    def validate(self):
        if (not self.cabinet_id or not self.source.strip() or
                self.evidence not in {"handbook_study", "technical_documentation"}):
            raise ValueError("Cabinet characteristic needs an identified source and evidence type")
        if any(not isfinite(v) or v <= 0 for v in (
                self.resistance_mpa_per_lps2, self.minimum_flow_lps, self.minimum_head_m)):
            raise ValueError("Invalid cabinet characteristic")
        if self.maximum_head_m is not None and (
                not isfinite(self.maximum_head_m) or self.maximum_head_m < self.minimum_head_m):
            raise ValueError("Invalid characteristic range")
        if self.evidence == "technical_documentation" and self.maximum_head_m is None:
            raise ValueError("Technical documentation must specify its pressure range")

    @property
    def resistance_head(self):
        return self.resistance_mpa_per_lps2 * MPA_TO_M


@dataclass(frozen=True)
class FixedLossCharacteristic:
    """Explicit passive resistance: delta_h(m)=R*q(l/s)^2, NOT a pressure cap.

    A required_characteristic_study is a design target, not a manufactured
    aperture. Neither the diameter nor a discharge coefficient is guessed.
    """
    resistance_head_per_lps2: float
    source: str
    evidence: str
    maximum_flow_lps: float | None = None

    def validate(self):
        if (not isfinite(self.resistance_head_per_lps2)
                or self.resistance_head_per_lps2 <= 0 or not self.source.strip()
                or self.evidence not in {'required_characteristic_study', 'technical_documentation'}):
            raise ValueError('An explicit sourced positive fixed resistance is required')
        if self.maximum_flow_lps is not None and (
                not isfinite(self.maximum_flow_lps) or self.maximum_flow_lps <= 0):
            raise ValueError('Invalid fixed-device flow range')
        if self.evidence == 'technical_documentation' and self.maximum_flow_lps is None:
            raise ValueError('Technical fixed-device data must specify a flow range')

    def head_loss(self, flow_lps):
        self.validate()
        if not isfinite(flow_lps) or flow_lps < 0:
            raise ValueError('Nonnegative finite discharge required')
        return self.resistance_head_per_lps2 * flow_lps * flow_lps


def handbook_characteristic(cabinet, *, hose_material, nozzle_kind):
    """Explicit opt-in study composition of two published physical relations.

    VNIIPO 2010, p.385: q=10*K*sqrt(p); p.109: dp=A*q²*L/100.
    Adding hose loss to nozzle pressure gives R=(1/K²+A*L)/100.
    Not interpolation of T73; not a certified characteristic of a modern nozzle.
    No extra valve loss or hose elevation is guessed. Boundary is after valve,
    nozzle at cabinet elevation. The study must disclose these restrictions.
    """
    if nozzle_kind != "non_shutoff":
        raise ValueError("Shutoff nozzle requires its own technical documentation (SP10 7.14)")
    k = {13: .588, 16: .891, 19: 1.260}.get(cabinet.nozzle_mm)
    a = {("rubber_lined", 50): .0065, ("rubber_lined", 65): .0017,
         ("unlined", 50): .012, ("unlined", 65): .00385}.get((hose_material, cabinet.dn))
    row = get_nozzle_data(cabinet.dn, cabinet.nozzle_mm, cabinet.hose_m, cabinet.jet_m)
    if k is None or a is None or row is None:
        raise ValueError("No published handbook coefficient or exact T73 requirement for this kit")
    return CabinetCharacteristic(cabinet.cabinet_id, (1/k**2+a*cabinet.hose_m)/100,
        row.q, row.p*MPA_TO_M,
        "ВНИИПО, Мешман и др., 2010: с.109, табл.3.3.3.7 и с.385; "
        f"K={k}; A={a}; L={cabinet.hose_m}. Минимумы: СП10, табл.7.3.",
        "handbook_study")


@dataclass(frozen=True)
class CabinetFlow:
    cabinet_id: str
    flow_lps: float
    inlet_head_m: float
    outlet_head_m: float
    control_drop_m: float
    minimum_flow_lps: float
    minimum_head_m: float
    meets_minimum: bool
    within_characteristic_range: bool | None
    within_device_range: bool | None = None


@dataclass(frozen=True)
class PressureFlowResult:
    header_head_m: float
    total_flow_lps: float
    cabinets: tuple[CabinetFlow, ...]
    iterations: int
    flow_residual_lps: float
    energy_residual_m: float
    supply_balance_residual_lps: float
    ideal_controls: bool
    product_verified: bool
    fixed_controls: bool = False


def _linear_solve(matrix, rhs):
    """Small dense Newton system; no optional numerical runtime dependency."""
    n = len(rhs)
    a = [list(row)+[rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(a[i][col]))
        if abs(a[pivot][col]) < 1e-12:
            raise ValueError("Singular pressure-flow Jacobian")
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [v/scale for v in a[col]]
        for i in range(n):
            if i != col:
                scale = a[i][col]
                a[i] = [v-scale*w for v,w in zip(a[i],a[col])]
    return [row[-1] for row in a]


def solve_pressure_flows(network, characteristics, header_head_m, *,
                         ideal_outlet_heads=None, fixed_losses=None,
                         tolerance_lps=1e-6, max_iterations=60):
    """Solve actual outlet flows at a fixed common-header pressure.

    ideal_outlet_heads is an explicit design experiment, NOT a selected regulator.
    A valve can reduce pressure, never increase it. Unsupported geometry, invalid
    data or non-convergence raise; no last iterate is returned as a valid result.
    """
    if not isfinite(header_head_m) or not isfinite(tolerance_lps) or tolerance_lps <= 0 or max_iterations < 1:
        raise ValueError("Invalid solver boundary/tolerance")
    net = deepcopy(network)
    if net.validate() or net.second_source is None or not net.cabinets:
        raise ValueError("A valid two-port network is required")
    ports = (net.source, net.second_source)
    z0 = net.nodes[ports[0].node_id].elevation_m
    if any(p.kind != SourceKind.CITY_MAIN or
           abs(net.nodes[p.node_id].elevation_m-z0) > 1e-9 for p in ports):
        raise ValueError("Two ports must belong to one discharge header at the same elevation")
    if any(not isfinite(n.elevation_m) for n in net.nodes.values()):
        raise ValueError("Invalid elevation")
    ids = [c.cabinet_id for c in net.cabinets]
    chars = list(characteristics)
    by_id = {c.cabinet_id:c for c in chars}
    if len(ids) != len(set(ids)) or len(chars) != len(by_id) or set(by_id) != set(ids):
        raise ValueError("Exactly one explicit characteristic per cabinet is required")
    for c in chars:
        c.validate()
    for s in net.segments:
        if (not all(isfinite(v) for v in (s.A, s.length_m, s.equiv_length_m, s.valves_equiv_length_m))
                or s.A <= 0 or s.length_m <= 0 or s.equiv_length_m < 0 or s.valves_equiv_length_m < 0):
            raise ValueError("Invalid explicit pipe resistance")
    controls = dict(ideal_outlet_heads or {})
    if set(controls)-set(ids) or any(not isfinite(v) or v <= 0 for v in controls.values()):
        raise ValueError("Invalid ideal pressure control")
    devices = dict(fixed_losses or {})
    if set(devices)-set(ids) or set(devices) & set(controls):
        raise ValueError('Unknown cabinet or ambiguous fixed/ideal control on one cabinet')
    for device in devices.values():
        if not isinstance(device, FixedLossCharacteristic):
            raise ValueError('Fixed device must carry explicit source and evidence')
        device.validate()
    for p in ports:
        p.available_head_m = header_head_m
    chars = [by_id[i] for i in ids]
    total_resistance = [c.resistance_head + (devices[i].resistance_head_per_lps2
                         if i in devices else 0.0) for i,c in zip(ids,chars)]
    heads = {c.cabinet_id:c.minimum_head_m for c in chars}
    deco = decompose_ring_network(net, net.cabinets, {i:1.0 for i in ids}, heads)
    if deco.problems:
        raise ValueError("Unsupported L06 topology: "+"; ".join(deco.problems))
    # The old decomposition does not support two active outlets sharing a riser.
    branch_ids = [s.segment_id for b in deco.branches for s in b.segments]
    if len(branch_ids) != len(set(branch_ids)):
        raise ValueError("Shared active cabinet branches require a multi-outlet solver")

    def evaluate(q):
        # Exact zero-demand static state; no artificial demand is introduced.
        if sum(q) <= 1e-14:
            actual = [header_head_m+z0-net.nodes[c.node_id].elevation_m for c in net.cabinets]
            inner = None
        else:
            inner = solve_two_source_scenario(net, net.cabinets, dict(zip(ids,q)), heads)
            if inner is None or not inner.solve.converged:
                raise ValueError("Inner ring solve failed")
            actual_by_id = {c.cabinet_id:c.actual_head_at_pk_m for c in inner.per_pk}
            actual = [actual_by_id[i] for i in ids]
        # Both passive losses scale with q². Pressure division is used only for
        # the open-outlet equation; a closed cabinet has no such pressure drop.
        available = [min(h,controls[i]) if i in controls else h for i,h in zip(ids,actual)]
        outlet = [h*c.resistance_head/r if h > 0 and i in devices else h
                  for i,h,c,r in zip(ids,available,chars,total_resistance)]
        residual = [v-sqrt(max(0,h)/r) for v,h,r in zip(q,available,total_resistance)]
        return residual, actual, outlet, inner

    q = [sqrt(max(0, min(header_head_m+z0-net.nodes[cab.node_id].elevation_m,
                        controls.get(cab.cabinet_id, float("inf"))))/r)
         for cab,r in zip(net.cabinets,total_resistance)]
    norm = lambda r: max(abs(v) for v in r)
    for iteration in range(1,max_iterations+1):
        residual, actual, outlet, inner = evaluate(q)
        if norm(residual) <= tolerance_lps:
            break
        jac = [[0.0]*len(q) for _ in q]
        for j in range(len(q)):
            step = max(1e-3, abs(q[j])*1e-3)
            shifted = q.copy()
            shifted[j] += step
            r2, *_ = evaluate(shifted)
            for i in range(len(q)):
                jac[i][j] = (r2[i]-residual[i])/step
        change = _linear_solve(jac, [-r for r in residual])
        damping = 1.0
        for _ in range(24):
            trial = [max(0.0,v+damping*d) for v,d in zip(q,change)]
            r2, *_ = evaluate(trial)
            if norm(r2) < norm(residual):
                q = trial
                break
            damping /= 2
        else:
            raise ValueError("Pressure-flow Newton step did not reduce residual")
    else:
        raise ValueError("Pressure-flow solve did not converge")
    energy = max((abs(h-c.resistance_head*v*v) if h > 0 else 0.0)
                 for h,c,v in zip(outlet,chars,q))
    energy = max(energy, max((abs(actual[j]-total_resistance[j]*q[j]**2)
                 if actual[j] > 0 and ids[j] in devices else 0.0) for j in range(len(ids))))
    balance = 0.0
    if inner:
        energy = max(energy,inner.solve.residual_loop_m,inner.solve.residual_pseudo_m)
        balance = abs(inner.supply1_lps+inner.supply2_lps-sum(q))
    if energy > 1e-3 or balance > 1e-5:
        raise ValueError("Pressure-flow conservation check failed")
    rows = tuple(CabinetFlow(c.cabinet_id,v,h,out,max(0,h-out),c.minimum_flow_lps,c.minimum_head_m,
        v+1e-6 >= c.minimum_flow_lps and out+1e-5 >= c.minimum_head_m,
        out <= c.maximum_head_m if c.maximum_head_m is not None else None,
        (v <= devices[c.cabinet_id].maximum_flow_lps
         if c.cabinet_id in devices and devices[c.cabinet_id].maximum_flow_lps is not None else None))
        for c,v,h,out in zip(chars,q,actual,outlet))
    return PressureFlowResult(header_head_m,sum(q),rows,iteration,norm(residual),energy,balance,
        bool(controls),not controls and all(c.evidence == "technical_documentation" and
            r.within_characteristic_range is True for c,r in zip(chars,rows)) and
            all(d.evidence == 'technical_documentation' for d in devices.values()) and
            all(r.within_device_range is True for r in rows if r.cabinet_id in devices), bool(devices))


@dataclass(frozen=True)
class PumpFlowCheck:
    status: str
    operating: PressureFlowResult | None
    pump_flow_m3h: float | None
    pump_head_m: float | None
    suction_head_m: float | None
    boundary_residual_lps: float | None
    reason: str


def required_common_header(network, characteristics, *, ceiling_head_m):
    """Minimum header pressure meeting BOTH independent T73 criteria.

    The caller supplies a design ceiling; no unbounded head growth is hidden.
    This is an unregulated calculation. A regulator's necessary differential
    pressure must subsequently be added from its technical documentation.
    """
    if not isfinite(ceiling_head_m) or ceiling_head_m <= 0:
        raise ValueError("Explicit positive header ceiling required")
    chars = tuple(characteristics)
    hi = ceiling_head_m
    upper = solve_pressure_flows(network, chars, hi)
    if not all(c.meets_minimum for c in upper.cabinets):
        raise ValueError("Cannot meet all cabinet minima within the specified header ceiling")
    lo = 0.0
    zero = solve_pressure_flows(network, chars, lo)
    if all(c.meets_minimum for c in zero.cabinets):
        return zero
    for _ in range(45):
        mid = (hi+lo)/2
        result = solve_pressure_flows(network, chars, mid)
        if all(c.meets_minimum for c in result.cabinets):
            hi, upper = mid, result
        else:
            lo = mid
        if hi-lo < 1e-5:
            return upper
    raise ValueError("Minimum header search did not converge")


def check_pump_operating_point(network, characteristics, curve, *,
                               suction_static_head_m, supply_resistance, ideal_outlet_heads=None,
                               fixed_losses=None, station_suction_resistance=0.,
                               station_discharge_resistance=0.):
    """Unique intersection for a NON-INCREASING published pump curve only.

    One explicit supply carries all flow: suction=Hstatic-Rsupply*Q².
    Optional preliminary station Rs/Rd (m per (l/s)^2) are separate from
    the external supply. Rs reduces pump-suction pressure; Rd reduces the
    downstream header. Their zero defaults retain the bare-pump study API,
    not a claim that any manufactured station has zero loss.
    No curve extension, no L02 parabola and no sum of working+reserve pumps.
    Empty/ambiguous data raise; absent in-range intersection is an explicit status.
    """
    if not valid_curve(curve) or any(b[1] > a[1] for a,b in zip(curve,curve[1:])):
        raise ValueError("L06 requires a non-increasing published pump curve")
    if (not isfinite(suction_static_head_m) or
            any(not isfinite(r) or r < 0 for r in (supply_resistance,
                station_suction_resistance, station_discharge_resistance))):
        raise ValueError("Explicit suction boundary and resistance are required")
    characteristics = tuple(characteristics)

    def evaluate(q):
        hp = interpolate_head(curve,q*3.6)
        if hp is None:
            raise ValueError("Outside pump curve")
        suction = suction_static_head_m-(supply_resistance+station_suction_resistance)*q*q
        header = suction+hp-station_discharge_resistance*q*q
        out = solve_pressure_flows(network,characteristics,header,
                                   ideal_outlet_heads=ideal_outlet_heads, fixed_losses=fixed_losses)
        return out.total_flow_lps-q,out,hp,suction

    lo,hi = curve[0][0]/3.6,curve[-1][0]/3.6
    low, high = evaluate(lo),evaluate(hi)
    if low[0] < -1e-6 or high[0] > 1e-6:
        return PumpFlowCheck("outside_published_curve",None,None,None,None,None,
            "Пересечение вне опубликованного диапазона Q-H; экстраполяция запрещена")
    for _ in range(70):
        q = (lo+hi)/2
        residual,out,hp,suction = evaluate(q)
        if abs(residual) <= 1e-6:
            if suction <= 0:
                return PumpFlowCheck("suction_unverified",out,q*3.6,hp,suction,residual,
                    "Положительное давление на всасывании не подтверждено; нужен отдельный расчёт")
            status = ("outside_characteristic_range" if any(c.within_characteristic_range is False
                or c.within_device_range is False
                for c in out.cabinets) else "meets_minimum" if all(c.meets_minimum for c in out.cabinets)
                else "insufficient_at_cabinet")
            return PumpFlowCheck(status,out,q*3.6,hp,suction,residual,
                "Расчёт характеристики; паспорта, NPSH, статика и покрытие помещений проверяются отдельно")
        if residual > 0:
            lo = q
        else:
            hi = q
    raise ValueError("Pump/network boundary did not converge")

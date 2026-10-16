"""Explicit common fire-pump boundary, composed from existing V2 calculations.

The two downstream source nodes are ports of ONE discharge header, at the same
elevation and pressure. They are not two independent city connections. Each
external supply is checked at the full design flow (SP 10, 12.27, amendment 1).
No parallel-suction flow split, system curve or manufacturer data is invented.
"""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite

from app.calc.fire_hydraulics import (
    FireNetwork, NetworkMode, PipeSegment, PumpDutyPoint, ScenarioResult,
    SourceKind, SpecificResistanceBackend, solve_fire_hydraulics_scenario,
)


@dataclass(frozen=True)
class StationSupply:
    name: str
    source_elevation_m: float
    guaranteed_head_m: float
    maximum_head_m: float | None
    segments: tuple[PipeSegment, ...]


@dataclass(frozen=True)
class CommonFireStation:
    pump_axis_m: float
    supplies: tuple[StationSupply, ...]
    basis: str
    review_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SupplyCheck:
    name: str
    flow_lps: float
    source_elevation_m: float
    guaranteed_head_m: float
    loss_m: float
    suction_head_m: float


@dataclass
class StationCalculation:
    network: FireNetwork
    hydraulic: ScenarioResult
    supplies: list[SupplyCheck]
    minimum_suction_head_m: float
    maximum_static_suction_head_m: float | None
    pump_axis_m: float
    basis: str
    pipework_audit: dict | None = None


def calculate_common_fire_station(
    downstream: FireNetwork, station: CommonFireStation, required_jets: int,
    *, mode=NetworkMode.PURE_FIRE, scenario_filter=None, pipework=None,
) -> StationCalculation:
    """Return the actual suction datum and a duty of the COMMON pump.

    Missing/invalid inputs fail closed; supplied objects are never mutated.
    The full-flow supply check is conservative, not a prediction of the split
    between simultaneously open external connections. Without ``pipework``,
    header/connection losses belong to supplied effective lengths. With explicit
    pipework, those lengths must EXCLUDE it: suction and discharge losses are
    added once, on their respective sides of the pump.
    """
    if len(station.supplies) < 2 or not station.basis.strip():
        raise ValueError("Common station requires two explicit supplies and a design basis")
    if not isfinite(station.pump_axis_m):
        raise ValueError("Pump elevation must be finite")
    if len({s.name for s in station.supplies}) != len(station.supplies):
        raise ValueError("Supply names must be unique")
    net = deepcopy(downstream)
    ports = [net.source] + ([net.second_source] if net.second_source else [])
    for port in ports:
        if (port.kind != SourceKind.CITY_MAIN or
                abs(net.nodes[port.node_id].elevation_m-station.pump_axis_m) > 1e-9):
            raise ValueError("All discharge-header ports must share the explicit pump datum")
        port.available_head_m = 0.0
    preliminary = solve_fire_hydraulics_scenario(
        net, required_jets, mode=mode, scenario_filter=scenario_filter)
    if preliminary.dictating_scenario is None:
        raise ValueError("Station downstream network has no solved design scenario")
    flow = preliminary.dictating_scenario.total_flow_lps
    internal = pipework.audit(flow*3.6) if pipework is not None else None
    internal_losses = internal['losses_m'] if internal else dict(suction=0., discharge=0.)
    backend = SpecificResistanceBackend()
    checks, maxima = [], []
    for supply in station.supplies:
        if not supply.segments or not supply.name.strip():
            raise ValueError("Each supply requires an explicit pipe path")
        if (not isfinite(supply.source_elevation_m) or
                not isfinite(supply.guaranteed_head_m) or supply.guaranteed_head_m < 0):
            raise ValueError("Invalid supply pressure/elevation")
        if supply.maximum_head_m is not None and (
                not isfinite(supply.maximum_head_m) or
                supply.maximum_head_m < supply.guaranteed_head_m):
            raise ValueError("Maximum supply head cannot be below guaranteed head")
        for index, segment in enumerate(supply.segments):
            if (not all(isfinite(x) for x in (
                    segment.length_m, segment.A, segment.equiv_length_m,
                    segment.valves_equiv_length_m)) or
                    segment.length_m <= 0 or segment.A <= 0 or
                    segment.equiv_length_m < 0 or segment.valves_equiv_length_m < 0):
                raise ValueError("Invalid supply resistance/length")
            if index and supply.segments[index-1].to_node != segment.from_node:
                raise ValueError("Supply segments must be a continuous ordered path")
        loss = sum(backend.segment_loss(s, flow) for s in supply.segments) + internal_losses['suction']
        suction = supply.guaranteed_head_m + supply.source_elevation_m - station.pump_axis_m - loss
        checks.append(SupplyCheck(supply.name, flow, supply.source_elevation_m,
                                  supply.guaranteed_head_m, loss, suction))
        if supply.maximum_head_m is not None:
            maxima.append(supply.maximum_head_m + supply.source_elevation_m - station.pump_axis_m)
    minimum = min(row.suction_head_m for row in checks)
    if minimum <= 0:
        raise ValueError("Positive suction pressure not established; separate suction/NPSH design required")
    for port in ports:
        port.available_head_m = minimum - internal_losses['discharge']
    hydraulic = solve_fire_hydraulics_scenario(
        net, required_jets, mode=mode, scenario_filter=scenario_filter)
    deficit = hydraulic.required_head_at_source_m + internal_losses['discharge'] - minimum
    notes = [
        "Общая насосная: границы расчётной сети — выходы одного напорного коллектора.",
        "Каждый наружный ввод проверен на полный пожарный расход; разделение расходов между вводами не моделируется.",
        f"Напор до насоса на отметке {station.pump_axis_m:.3f}: не менее {minimum:.3f} м; "
        + ("на выходе станции" if internal else "после насоса")
        + f" требуется {hydraulic.required_head_at_source_m:.3f} м.",
    ]
    if internal:
        notes.append(f"Отдельная обвязка: всасывание {internal_losses['suction']:.3f} м, "
                     f"напор {internal_losses['discharge']:.3f} м при {flow:.3f} л/с. "
                     "Вводы и сеть исключают эти потери; резервная ветвь не добавляется.")
    hydraulic.pump_duty = (PumpDutyPoint(deficit, flow, SourceKind.CITY_MAIN, notes=notes)
                           if deficit > 1e-9 else None)
    hydraulic.needs_pump = deficit > 1e-9
    hydraulic.available_head_m = minimum - internal_losses['discharge']
    hydraulic.available_head_ok = deficit <= 1e-9
    hydraulic.warnings.extend(notes)
    return StationCalculation(net, hydraulic, checks, minimum,
        max(maxima) if len(maxima) == len(checks) else None,
        station.pump_axis_m, station.basis, internal)

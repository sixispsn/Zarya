"""Explicit, opt-in engineering inputs for a residential section regression case.

No study value becomes a production default. Pipe grades/lengths are proposed
inputs; water and rain demand use existing legacy ports and executable parity.
The installation graph is independent of sheet coordinates and room packing.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isclose, isfinite
from pathlib import Path
import subprocess
from typing import Any

from app.calc.storm import StormInput, StormResult, calculate_storm
from app.calc.water_demand import ConsumerGroup, WaterDemandResult, calculate_water_demand
from app.data.sewer_pipe_catalog import DUEKER_SML, SewerPipeGeometry, sewer_pipe_geometry
from app.pz.wastewater_diagnostics import service_limit_m
from app.pz.wastewater_drafting import (
    WastewaterDraftAssembly, build_lower_turn_cleanout_assembly, build_lower_turn_through_junction_assembly,
)
from app.pz.wastewater_fan_drafting import FanDetailEdge, FanDetailGraph, FanDetailNode
from app.pz.wastewater_floor_drafting import FloorFixtureInput, WastewaterFloorAssembly, build_typical_floor_assembly
from app.pz.wastewater_suspended_profile import SuspendedCollectorProfile
from app.pz.wastewater_ventilation import (
    FanRiser, FanTerminal, FanVentilationAudit, FanVentilationInput, audit_fan_ventilation,
)


@dataclass(frozen=True)
class CaseCollector:
    profile: SuspendedCollectorProfile
    pipe: SewerPipeGeometry
    stations: tuple[float, ...]
    revisions: tuple[float, ...]

    def invert(self, station: float) -> float:
        p = self.profile
        if p.length_m is None or p.slope is None or p.start_invert_m is None or not 0 <= station <= p.length_m:
            raise ValueError("station outside explicit collector profile")
        return p.start_invert_m-station*p.slope

    def axis(self, station: float) -> float:
        return self.invert(station)+self.pipe.inner_diameter_mm/2000

    def nodes(self) -> tuple[WastewaterDraftAssembly, ...]:
        return tuple((build_lower_turn_cleanout_assembly if i == 0 else build_lower_turn_through_junction_assembly)(
            system=self.profile.system, dn_mm=100, assembly_id=f"{self.profile.system}-base-{i+1}")
            for i in range(len(self.stations)))

    def validate(self, ceiling: float, floor: float, outlet: float) -> None:
        p = self.profile
        if (p.outer_diameter_mm, p.wall_thickness_mm) != (self.pipe.outer_diameter_mm, self.pipe.wall_thickness_mm):
            raise ValueError("collector profile must use the selected pipe's actual bore")
        if self.pipe.outer_diameter_mm != 110:
            raise ValueError("this study's DN100 fittings need a separate composition for another pipe size")
        if not self.stations or self.stations[0] != 0 or any(a >= b for a, b in zip(self.stations, self.stations[1:])):
            raise ValueError("collector stations must start at zero and increase")
        for station in (*self.stations, *self.revisions):
            self.invert(station)
        if tuple(sorted(set(self.revisions))) != self.revisions:
            raise ValueError("invalid maintenance order")
        # Geometric envelope only. Zero required passage DOES NOT claim a safe
        # personnel walkway in a 1.5 m unheated technical underfloor space.
        p.validate_envelope(ceiling_m=ceiling, floor_m=floor, required_ceiling_gap_m=.05, required_passage_m=0)
        p.drop_height_m(outlet)
        if p.length_m is None:
            raise ValueError("missing collector length")
        accesses = (0., *self.revisions, p.length_m)
        for index, (a, b) in enumerate(zip(accesses, accesses[1:])):
            kind = "cleanout" if index == 0 else "revision"
            limit = service_limit_m(p.system, 100, kind)
            if limit is None or b-a > limit:
                raise ValueError("maintenance interval exceeds SP30 table 18.1")
        for i, node in enumerate(self.nodes()):
            if node.validate() or (node.service_path is not None) != (i == 0):
                raise ValueError("initial cleanout lost or throughflow capped")


@dataclass(frozen=True)
class ResidentialSectionCase:
    case_id: str
    source_image: str
    authority: str
    floors: int
    floor_to_floor_m: float
    slab_m: float
    subfloor_clear_m: float
    first_floor_m: float
    roof_m: float
    outlet_invert_m: float
    apartments_per_floor: int
    residents: int
    storm_input: StormInput
    catchments: tuple[float, ...]
    grades: tuple[float, float]
    k1: CaseCollector
    k2: CaseCollector
    fan_stations: tuple[float, ...]
    fan_start_m: float
    fan_slope: float
    fan_terminal_riser: str
    fan_height_m: float
    fan_placement: str
    assumptions: tuple[str, ...]

    @property
    def floor_levels(self) -> dict[int, float]:
        return {f: self.first_floor_m+(f-1)*self.floor_to_floor_m for f in range(1, self.floors+1)}

    @property
    def ceiling_m(self) -> float:
        return self.first_floor_m-self.slab_m

    @property
    def subfloor_m(self) -> float:
        return self.ceiling_m-self.subfloor_clear_m

    @property
    def release_ready(self) -> bool:
        return False

    def floors_graph(self) -> dict[tuple[str, int], WastewaterFloorAssembly]:
        return {(f"K1-{i+1}", f): build_typical_floor_assembly(
            assembly_id=f"K1-{i+1}:F{f}", riser_id=f"K1-{i+1}", floor_no=f, floor_elevation_m=z,
            slope_dn50=self.grades[0], slope_dn100=self.grades[1],
            fixtures=tuple(FloorFixtureInput(k, k, "Кухня-гостиная" if k == "sink" else "Санузел")
                           for k in ("sink", "bath", "washbasin", "toilet")),
        ) for i in range(self.apartments_per_floor) for f, z in self.floor_levels.items()}

    def drainage_paths(self) -> dict[str, tuple[str, ...]]:
        graph: dict[str, str] = {}
        sources: list[str] = []
        for (rid, floor), assembly in self.floors_graph().items():
            if assembly.validate():
                raise ValueError("invalid floor installation graph")
            prefix = f"{rid}:F{floor}:"
            pairs = [(s.start_port_id, s.end_port_id) for s in assembly.segments if s.carries_flow]
            pairs += [(j.start_port_id, j.end_port_id) for j in assembly.direct_fitting_joints]
            pairs += [(f.trap_inlet_port_id, f.trap_outlet_port_id) for f in assembly.fixtures if f.trap_mode == "external"]
            graph.update((prefix+a, prefix+b) for a, b in pairs)
            graph[prefix+"riser_join"] = f"{rid}:F{floor-1}:riser_join" if floor > 1 else f"{rid}:base:riser_in"
            sources.extend(prefix+f.fixture_outlet_port_id for f in assembly.fixtures)
        for collector in (self.k1, self.k2):
            system = collector.profile.system
            for i, node in enumerate(collector.nodes()):
                prefix = f"{system}-{i+1}:base:"
                graph.update((prefix+s.start_port_id, prefix+s.end_port_id) for s in node.segments if s.carries_flow)
                graph[prefix+"main_out"] = f"{system}-{i+2}:base:main_in" if i+1 < len(collector.stations) else f"{system}:drop"
                if system == "K2":
                    source = f"K2:funnel-{i+1}"
                    graph[source] = prefix+"riser_in"
                    sources.append(source)
            graph[f"{system}:drop"] = f"{system}:outlet"
        paths = {}
        for source in sources:
            system, current, path = source[:2], source, []
            while current != f"{system}:outlet":
                if current in path or current not in graph or not current.startswith(system):
                    raise ValueError("disconnected/cyclic/mixed K1/K2 path")
                path.append(current)
                current = graph[current]
            paths[source] = tuple((*path, current))
        return paths

    def fan_graph(self) -> FanDetailGraph:
        nodes, edges = [], []
        for i, station in enumerate(self.fan_stations):
            rid = f"K1-{i+1}"
            level = self.fan_start_m+station*self.fan_slope
            nodes += [FanDetailNode(rid, station, self.roof_m, "riser_port", rid),
                      FanDetailNode("join:"+rid, station, level, "collector_join", rid)]
            edges.append(FanDetailEdge("vent:"+rid, rid, "join:"+rid, 100., "riser_vent"))
            if i:
                edges.append(FanDetailEdge(f"collector:{i}", f"join:K1-{i}", "join:"+rid, 100., "vent_collector"))
        station = self.fan_stations[int(self.fan_terminal_riser.split('-')[-1])-1]
        nodes.append(FanDetailNode("K1-FAN", station, self.roof_m+self.fan_height_m, "open_end", "K1-FAN"))
        edges.append(FanDetailEdge("common-vent", "join:"+self.fan_terminal_riser, "K1-FAN", 100., "common_vent"))
        result = FanDetailGraph("K1-FAN", tuple(nodes), tuple(edges))
        result.validate()
        return result

    def fan_audit(self) -> FanVentilationAudit:
        ids = tuple(f"K1-{i+1}" for i in range(self.apartments_per_floor))
        # Proposed geometric conditions are explicit. Missing opening/UV
        # evidence remains pending; no fabricated "all checks passed" badge.
        evidence = FanVentilationInput((FanTerminal(
            "K1-FAN", ids, "roof", self.authority, self.fan_height_m, 100., 100.,
            open_end_confirmed=True, separate_from_other_systems=True,
            condensate_drains_to_risers=True, cold_attic=False, plastic_exposed=True,
        ),))
        return audit_fan_ventilation(roof_kind="flat_accessible", residential=True, evidence=evidence,
                                    risers=tuple(FanRiser(rid, 100., "ventilated", "K1:outlet") for rid in ids))

    def calculate(self) -> tuple[WaterDemandResult, StormResult]:
        return (calculate_water_demand([ConsumerGroup("residential_full_bath", self.residents)]),
                calculate_storm(self.storm_input))

    def verify_legacy(self, node: str, root: Path) -> None:
        water, storm = self.calculate()
        request = {"residents": [self.residents], "cases": [dict(city=storm.city.name,
                   roof=self.storm_input.roof_area_m2, walls=self.storm_input.walls_area_m2,
                   period=self.storm_input.period_years)]}
        raw = subprocess.run([node, str(root/'scripts/legacy_rainwater_reference.mjs')], input=json.dumps(request),
                             text=True, capture_output=True, check=True)
        reference = json.loads(raw.stdout)
        r, w = reference['cases'][0], reference['residents'][0]
        if ((storm.q_total_l_per_s, storm.q5, storm.f_calculated_m2) != (r['flow_lps'], r['q5'], r['area'])
                or (water.total.q_sec, water.total.q_hr, water.sewage_flow) !=
                (w['total_lps'], w['hourly_m3'], w['sewage_lps'])):
            raise ValueError("legacy mismatch: stop export; do not change reference")

    def validate(self) -> None:
        if not self.authority or not self.assumptions or not self.source_image:
            raise ValueError("explicit source/assumptions required")
        if self.floors < 1 or self.apartments_per_floor != 4 or len(self.k1.stations) != 4:
            raise ValueError("this residential composition needs four apartment groups per floor")
        values = (self.floor_to_floor_m, self.slab_m, self.subfloor_clear_m, self.roof_m,
                  self.first_floor_m, self.outlet_invert_m, self.fan_start_m, self.fan_slope, self.fan_height_m, *self.grades)
        if not all(isfinite(v) for v in values) or not 0 < self.slab_m < self.floor_to_floor_m or self.subfloor_clear_m <= 0:
            raise ValueError("invalid levels/dimensions")
        if self.roof_m <= max(self.floor_levels.values()) or not isclose(self.outlet_invert_m, self.subfloor_m):
            raise ValueError("roof or user-specified outlet at underfloor floor conflicts")
        if min(self.grades) <= 0 or self.residents < 1:
            raise ValueError("invalid demand/grades")
        if (not self.catchments or len(self.catchments) != len(self.k2.stations)
                or not all(isfinite(v) and v > 0 for v in self.catchments)
                or not isclose(sum(self.catchments), self.storm_input.roof_area_m2) or self.storm_input.walls_area_m2 != 0):
            raise ValueError("roof catchment conservation failed")
        for collector in (self.k1, self.k2):
            collector.validate(self.ceiling_m, self.subfloor_m, self.outlet_invert_m)
        if self.k1.profile.system != 'K1' or self.k2.profile.system != 'K2':
            raise ValueError("collector systems cannot be mixed")
        if (self.k1.pipe != sewer_pipe_geometry('ostendorf_ht_pp', 110)
                or self.k2.pipe != SewerPipeGeometry(DUEKER_SML, 110, 3.5)):
            raise ValueError("this study requires the explicitly proposed HT / SML pipe series")
        if (self.fan_placement != 'guarded_roof_technical_strip' or len(self.fan_stations) != 4
                or not all(isfinite(v) and v >= 0 for v in self.fan_stations)
                or self.fan_start_m <= self.roof_m or self.fan_slope <= 0 or self.fan_height_m < 3
                or self.fan_terminal_riser not in {f'K1-{i}' for i in range(1, 5)}
                or any(b <= a for a, b in zip(self.fan_stations, self.fan_stations[1:]))):
            raise ValueError("common fan collector must be above roof, drain to risers, and end 3 m above roof")
        if self.fan_start_m+max(self.fan_stations)*self.fan_slope >= self.roof_m+self.fan_height_m:
            raise ValueError("collector above open terminal")
        self.fan_graph()
        if self.fan_audit().status == 'fail':
            raise ValueError("fan normative check failed")
        self.drainage_paths()


def load_residential_section_case(path: Path) -> ResidentialSectionCase:
    return residential_section_case_from_mapping(json.loads(path.read_text()))


def residential_section_case_from_mapping(d: dict[str, Any]) -> ResidentialSectionCase:
    """One conversion path for the CLI fixture and a versioned Studio snapshot."""
    def collector(system: str) -> CaseCollector:
        row = d[system.lower()]
        pipe = sewer_pipe_geometry(row['series_id'], row['outer_mm']) if system == 'K1' else SewerPipeGeometry(DUEKER_SML, 110., 3.5)
        if system == 'K2' and (row['series_id'] != DUEKER_SML.series_id or row['outer_mm'] != 110):
            raise ValueError("K2 requires a separate explicit pipe series")
        profile = SuspendedCollectorProfile(system, row['start_invert_m'], row['length_m'], row['slope'],
                                             pipe.outer_diameter_mm, pipe.wall_thickness_mm, 30., 30.)
        return CaseCollector(profile, pipe, tuple(row['stations_m']), tuple(row['revision_stations_m']))
    f = d['fan']
    model = ResidentialSectionCase(
        d['case_id'], d['source_image'], d['authority'], d['floors'], d['floor_to_floor_m'], d['slab_m'],
        d['subfloor_clear_m'], d['first_floor_m'], d['roof_m'], d['outlet_invert_m'], d['apartments_per_floor'], d['residents'],
        StormInput(d['city'], d['roof_area_m2'], d['adjacent_walls_m2'], d['rain_period_years']),
        tuple(d['roof_catchments_m2']), tuple(d['branch_grades']), collector('K1'), collector('K2'),
        tuple(f['stations_m']), f['collector_start_m'], f['collector_slope'], f['terminal_riser'],
        f['height_above_roof_m'], f['placement'], tuple(d['assumptions']))
    model.validate()
    return model

"""Opt-in calculation of the agreed educational house; not production defaults.

Rain/water demand use the unchanged legacy ports. Partial-flow hydraulics are
the EXISTING Chezy–Manning implementation, not a claimed Shevelev table port.
Lengths, catchments and roughness below are explicit study assumptions, never
measurements inferred from the representative paper-space section.
"""
from dataclasses import dataclass
from math import isfinite

from app.calc.sewer_hydraulics import SewerHydraulicInput, SewerHydraulicResult, calculate_sewer_hydraulics
from app.calc.storm import STORM_RISER_CAPACITY_LPS, StormInput, StormResult, calculate_storm
from app.calc.water_demand import ConsumerGroup, WaterDemandResult, calculate_water_demand
from app.calc.sewage_horizontal import HorizontalSewageResult, calculate_horizontal_sewage
from app.data.sewer_pipe_catalog import DUEKER_SML, SewerPipeGeometry
from app.pz.small_residential_basement_proposal import BasementRoutingProposal, educational_basement_proposal
from app.pz.small_residential_preview import ResidentialPreview
from app.pz.wastewater_diagnostics import service_limit_m
from app.pz.wastewater_suspended_profile import SuspendedCollectorProfile

FUNNEL_URL = "https://www.hutterer-lechner.com/en/products/catalog/roof-drains/products/gravity-drainage/vertical/hl62/hl62.1/1.aspx"
FUNNEL_MODEL = "HL62.1/1"
FUNNEL_CAPACITY_LPS = 10.7  # Manufacturer catalogue, conditions/roof build-up to be approved.
ROUGHNESS_BASIS = "Учебное значение, не измерение: n=0,011 для PP; n=0,013 для SML; проверка чувствительности до 0,015."


@dataclass(frozen=True)
class ServiceRouteCheck:
    system: str
    access_port_id: str
    target_port_id: str
    length_m: float
    limit_m: float
    graph_ok: bool
    distance_ok: bool
    # Physical access under the ceiling is not established by graph reachability.
    accessibility_confirmed: bool = False


@dataclass(frozen=True)
class ResidentialCalculation:
    basement: BasementRoutingProposal
    rain_profile: SuspendedCollectorProfile
    rain_pipe: SewerPipeGeometry
    rain_chainages_m: tuple[float, ...]
    storm: StormResult
    water: WaterDemandResult
    k1: SewerHydraulicResult | None
    k2: SewerHydraulicResult
    sensitivities: tuple[SewerHydraulicResult, ...]
    catchments_m2: tuple[float, ...]
    catchment_flows_lps: tuple[float, ...]
    services: tuple[ServiceRouteCheck, ...]
    provisional_k2_outlet_m: float
    residents: int
    input_residents: int = 20
    k1_flow: HorizontalSewageResult | None = None

    def rain_invert_at(self, station: float) -> float:
        p = self.rain_profile
        if (p.start_invert_m is None or p.length_m is None or p.slope is None
                or not isfinite(station) or not 0 <= station <= p.length_m):
            raise ValueError("K2 station outside explicit study profile")
        return p.start_invert_m-station*p.slope

    def rain_axis_at(self, station: float) -> float:
        return self.rain_invert_at(station)+self.rain_pipe.inner_diameter_mm/2000

    @property
    def hydrostatic_head_m(self) -> float:
        # Scenario only: no unprovided roof ponding or external backwater added.
        return 6.6-self.provisional_k2_outlet_m

    @property
    def hydrostatic_bar(self) -> float:
        return self.hydrostatic_head_m*1000*9.80665/100000

    @property
    def riser_capacity_lps(self) -> float:
        return STORM_RISER_CAPACITY_LPS[100]

    def validate(self, model: ResidentialPreview) -> None:
        self.basement.validate(model)
        if model.roof is None or model.roof.elevation_m != 6.6 or len(model.apartments) != 8:
            raise ValueError("calculation is bound to the agreed house, not arbitrary defaults")
        if self.residents != self.input_residents or len(self.catchments_m2) != len(model.roof.lower_nodes):
            raise ValueError("study occupancy/catchments no longer match agreed input")
        if self.water != calculate_water_demand([ConsumerGroup("residential_full_bath", self.input_residents)]):
            raise ValueError("study water demand differs from its inputs")
        p = self.rain_profile
        if (p.system != "K2" or p.outer_diameter_mm != self.rain_pipe.outer_diameter_mm
                or p.wall_thickness_mm != self.rain_pipe.wall_thickness_mm
                or len(self.rain_chainages_m) != len(model.roof.lower_nodes)
                or any(a >= z for a, z in zip(self.rain_chainages_m, self.rain_chainages_m[1:]))):
            raise ValueError("inconsistent K2 pipe/profile/chainages")
        for station in self.rain_chainages_m:
            self.rain_axis_at(station)
        p.validate_envelope(ceiling_m=model.basement.ceiling_m, floor_m=model.basement.basement_floor_m,
                            required_ceiling_gap_m=.05, required_passage_m=1.8)
        p.drop_height_m(self.provisional_k2_outlet_m)
        if sum(self.catchments_m2) != self.storm.f_calculated_m2:
            raise ValueError("proposed catchment areas do not conserve roof area")
        if self.k1_flow is not None:
            expected = calculate_horizontal_sewage(self.water.total.q_hr, self.k1_flow.fixtures_count,
                self.k1_flow.receiving_length_m, self.k1_flow.fixture_max_lps)
            if expected != self.k1_flow or self.k1 is None or self.k1.design_flow_lps != round(expected.q_sewage_lps, 3):
                raise ValueError("horizontal K1 flow differs from formula 5.7/current inputs")
        elif self.k1 is not None:
            raise ValueError("horizontal K1 hydraulic result lacks formula 5.7 inputs")
        if self.k2.design_flow_lps != self.storm.q_total_l_per_s:
            raise ValueError("schematic calculations use different demand results")
        for r, profile in ((self.k1, self.basement.k1), (self.k2, p)):
            if r is None:
                continue
            assert profile.slope is not None and profile.outer_diameter_mm and profile.wall_thickness_mm
            if (abs(r.inner_diameter_mm-(profile.outer_diameter_mm-2*profile.wall_thickness_mm)) > 1e-8
                    or r.slope_per_mille != profile.slope*1000):
                raise ValueError("hydraulic diameter/grade differs from the drawn profile")
        if not all(s.graph_ok and s.distance_ok for s in self.services):
            raise ValueError("service graph or maximum service interval failed")


def _service_routes(model: ResidentialPreview, proposal: BasementRoutingProposal,
                    rain: SuspendedCollectorProfile) -> tuple[ServiceRouteCheck, ...]:
    """Walk the real ordered installation ports, including off-plane wyes.

    A graph route does not prove cable bend radius, removable closures, access
    hatches or the SP30 18.26 servicing arrangement. These remain unresolved.
    """
    assert model.roof is not None
    checks = []
    for system, nodes, profile in (("K1", model.lower_nodes, proposal.k1),
                                    ("K2", model.roof.lower_nodes, rain)):
        graph: dict[str, str] = {}
        for i, node in enumerate(nodes):
            if node.validate():
                raise ValueError("invalid lower assembly")
            for seg in node.segments:
                if seg.carries_flow:
                    graph[f"{i}:{seg.start_port_id}"] = f"{i}:{seg.end_port_id}"
            graph[f"{i}:main_out"] = f"{i+1}:main_in" if i+1 < len(nodes) else "drop:in"
        access = nodes[0].service_path
        if access is None:
            raise ValueError("initial coaxial cleanout is missing")
        for a, b in zip(access.point_ids, access.point_ids[1:]):
            graph[f"0:{a}"] = f"0:{b}"
        current, seen = f"0:{access.access_port_id}", set()
        while current != "drop:in" and current in graph and current not in seen:
            seen.add(current)
            current = graph[current]
        limit = service_limit_m(system, 100, "cleanout")
        assert limit is not None and profile.length_m is not None
        checks.append(ServiceRouteCheck(system, f"0:{access.access_port_id}", "drop:in",
                                        profile.length_m, limit, current == "drop:in", profile.length_m <= limit))
    return tuple(checks)


def calculate_residential_study(model: ResidentialPreview, *, residents: int = 20,
                                storm_input: StormInput | None = None,
                                k1_receiving_length_m: float | None = None) -> ResidentialCalculation:
    model.validate()
    proposal = educational_basement_proposal(model)
    pipe = SewerPipeGeometry(DUEKER_SML, 110., 3.5)
    rain = SuspendedCollectorProfile("K2", -1.13, 6., .015, pipe.outer_diameter_mm,
                                     pipe.wall_thickness_mm, 20., 30.)
    storm_input = storm_input or StormInput("moscow", 252., 0., 1)
    if storm_input.walls_area_m2 != 0 or storm_input.period_years != 1:
        raise ValueError("this educational roof has no adjacent walls and uses P=1")
    storm = calculate_storm(storm_input)
    water = calculate_water_demand([ConsumerGroup("residential_full_bath", residents)])
    def hydraulics(system, q, bore, slope, material, n):
        return calculate_sewer_hydraulics(SewerHydraulicInput(system, q, bore, slope, material, n, ROUGHNESS_BASIS))
    # The 9 m basement route is NOT L to the next riser/manhole. No invented
    # receiving length. The fixed study has 8 apartments x 4 fixtures, q0s=1.6.
    k1_flow = (calculate_horizontal_sewage(water.total.q_hr, 32, k1_receiving_length_m, 1.6)
               if k1_receiving_length_m is not None else None)
    k1 = (hydraulics("K1", k1_flow.q_sewage_lps, model.stack_pipe.inner_diameter_mm, 20., "pp", .011)
          if k1_flow else None)
    k2 = hydraulics("K2", storm.q_total_l_per_s, pipe.inner_diameter_mm, 15., "cast_iron", .013)
    cases = [("K2", storm.q_total_l_per_s, pipe.inner_diameter_mm, 15., "cast_iron")]
    if k1_flow:
        cases.insert(0, ("K1", k1_flow.q_sewage_lps, model.stack_pipe.inner_diameter_mm, 20., "pp"))
    sensitivities = tuple(hydraulics(system, q, bore, slope, material, n)
                          for system, q, bore, slope, material in cases
                          for n in (.011, .013, .015))
    areas = (storm_input.roof_area_m2 / 4,)*4  # Explicit equal-area EDUCATIONAL proposal.
    flows = tuple(calculate_storm(StormInput(storm_input.city_code, area)).q_total_l_per_s for area in areas)
    result = ResidentialCalculation(proposal, rain, pipe, (.3, 2., 3.5, 5.), storm, water, k1, k2,
                                    sensitivities, areas, flows, _service_routes(model, proposal, rain), -2.25, residents, residents, k1_flow)
    result.validate(model)
    return result

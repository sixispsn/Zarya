"""Explicit stage-P branch regulation, NOT final valve/zone hydraulics.

Only a separately accepted project assumption enables this presentation.
The envelope screens elevations at the existing required source head, without
deducting flow-dependent losses. It is a requirement for coordination of the
control design, never the real discharge-sensor setpoint or VFD operation.
No pump, demand, Kv, pressure check or procurement quantity is overwritten.
"""
from dataclasses import dataclass
from math import isfinite

from app.data.booster_controls import booster_control
from app.pz.water_control_review import review_water_control


@dataclass(frozen=True)
class BranchRegulationPlan:
    state: str = "not_specified"
    floors: tuple[int, ...] = ()
    systems: tuple[str, ...] = ()
    reference_head_m: float | None = None
    fixture_offset_m: float | None = None
    basis: str = ""
    issue: str = ""

    @property
    def floor_text(self):
        if not self.floors:
            return ""
        if self.floors == tuple(range(self.floors[0], self.floors[-1]+1)):
            return str(self.floors[0]) if len(self.floors) == 1 else f"{self.floors[0]}–{self.floors[-1]}"
        return ", ".join(map(str, self.floors))

    def shows(self, system, floor):
        return self.state == "principle" and system in self.systems and floor in self.floors


def branch_regulation_plan(project):
    decision = project.water_regulation_design
    if not decision:
        return BranchRegulationPlan()
    pending = lambda text: BranchRegulationPlan(state="needs_data", issue=text)
    if (decision.get("kind") != "apartment_branches_required_head_envelope"
            or not decision.get("basis") or project.building.purpose.value != "residential"):
        return pending("Принцип регулирования квартирных ветвей не подтверждён исходными.")
    if not booster_control(project.pumps):
        return pending("Для принятого принципа требуется подтверждённое частотное управление станции.")
    review = review_water_control(project)
    if not review.rows:
        return pending("Решение по РД требует актуального баланса напора: " + " ".join(review.issues))
    levels = project.building.floor_elevations_m
    floors = tuple(range(1, int(project.building.floors_above)+1))
    offset = decision.get("fixture_offset_m")
    z = project.source.elev_header_m
    low = project.source.lowest_fixture_elevation_m
    upper = project.source.elev_fixture_m
    values = [offset, z, low, upper, *(levels.get(f) for f in floors)]
    if (not floors or any(not isinstance(x, (int, float)) or isinstance(x, bool)
                          or not isfinite(x) for x in values) or offset < 0
            or not project.source.lowest_fixture_basis
            or abs(levels[1]+offset-low) > 1e-6
            or abs(levels[floors[-1]]+offset-upper) > 1e-6
            or any(levels[b] <= levels[a] for a,b in zip(floors,floors[1:]))):
        return pending("Для поэтажного решения РД нужны согласованные отметки и высота приборов.")
    # A common-source single-zone envelope: not a new pump-sizing algorithm.
    selected = tuple(f for f in floors
                     if review.reference_head_m - (levels[f]+offset-z) > 45.0+1e-9)
    systems = ("В1", "Т3") if any(r.code == "T3" for r in review.rows) else ("В1",)
    return BranchRegulationPlan("principle", selected, systems,
        review.reference_head_m, offset, decision["basis"])

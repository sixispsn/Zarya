"""Explicit educational K1 profile. Never a recovered basement plan or sizing.

The user has no basement AR. The fixture/riser graph is unchanged; the numbers
below are a separate, opt-in routing study. K2 remains unresolved, not copied
from the K1 pipe catalogue. Paper distances are never used as pipe lengths.
"""
from dataclasses import dataclass
from math import isfinite

from app.pz.small_residential_preview import ResidentialPreview
from app.pz.wastewater_suspended_profile import SuspendedCollectorProfile


@dataclass(frozen=True)
class BasementRoutingProposal:
    k1: SuspendedCollectorProfile
    junction_chainages_m: tuple[float, ...]
    source: str
    required_passage_m: float
    required_ceiling_gap_m: float

    def validate(self, model: ResidentialPreview) -> None:
        p, b = self.k1, model.basement
        if not self.source.strip() or p.system != "K1" or p.end_invert_m is None:
            raise ValueError("explicit complete educational K1 proposal required")
        if (p.outer_diameter_mm != model.stack_pipe.outer_diameter_mm
                or p.wall_thickness_mm != model.stack_pipe.wall_thickness_mm):
            raise ValueError("proposal must use the selected exact K1 pipe")
        stations = self.junction_chainages_m
        if (len(stations) != len(model.lower_nodes) or p.length_m is None
                or any(isinstance(x, bool) or not isfinite(x) for x in stations)
                or not 0 <= stations[0] < stations[-1] < p.length_m
                or any(a >= z for a, z in zip(stations, stations[1:]))):
            raise ValueError("all risers need ordered chainages inside the proposed route")
        p.validate_envelope(ceiling_m=b.ceiling_m, floor_m=b.basement_floor_m,
                            required_ceiling_gap_m=self.required_ceiling_gap_m,
                            required_passage_m=self.required_passage_m)
        p.drop_height_m(b.proposed_invert_m)

    def invert_at(self, chainage_m: float) -> float:
        p = self.k1
        if (p.length_m is None or p.start_invert_m is None or p.slope is None
                or not isfinite(chainage_m) or not 0 <= chainage_m <= p.length_m):
            raise ValueError("chainage must be within the explicit profile")
        return p.start_invert_m - chainage_m*p.slope

    def axis_at(self, chainage_m: float) -> float:
        p = self.k1
        if p.outer_diameter_mm is None or p.wall_thickness_mm is None:
            raise ValueError("exact bore required to distinguish axis from invert")
        return self.invert_at(chainage_m) + (p.outer_diameter_mm/2-p.wall_thickness_mm)/1000


def educational_basement_proposal(model: ResidentialPreview) -> BasementRoutingProposal:
    """Chosen scenario, not project defaults or an inferred plan of a 21x12 house."""
    result = BasementRoutingProposal(
        k1=SuspendedCollectorProfile(
            "K1", start_invert_m=-.80, length_m=9., slope=.020,
            outer_diameter_mm=model.stack_pipe.outer_diameter_mm,
            wall_thickness_mm=model.stack_pipe.wall_thickness_mm,
            extra_top_envelope_mm=20., extra_bottom_envelope_mm=30.,
        ),
        junction_chainages_m=(.5, 3., 5.5, 7.5),
        source="Учебное предложение без плана подвала: 9 м от начальной прочистки до опуска; привязки не подтверждены АР.",
        # Chosen study criteria, not universal normative ceiling/passage limits.
        required_passage_m=2., required_ceiling_gap_m=.05,
    )
    result.validate(model)
    return result

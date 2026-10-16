"""Explicit grade inputs for a suspended collector, not hydraulic pipe sizing.

Drawing coordinates never supply missing engineering elevations or lengths.
Envelope allowances include sockets, insulation and hangers, and must be
specified before a clearance check can be claimed as complete.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class SuspendedCollectorProfile:
    system: str
    start_invert_m: float | None = None
    length_m: float | None = None
    slope: float | None = None
    outer_diameter_mm: float | None = None
    wall_thickness_mm: float | None = None
    extra_top_envelope_mm: float | None = None
    extra_bottom_envelope_mm: float | None = None

    def __post_init__(self) -> None:
        if self.system not in {"K1", "K2"}:
            raise ValueError("separate K1 or K2 profile required")
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name != "system" and value is not None:
                if isinstance(value, bool) or not isfinite(value):
                    raise ValueError(f"{name} must be finite")
                if name != "start_invert_m" and value < 0:
                    raise ValueError(f"{name} cannot be negative")
                if name in {"length_m", "outer_diameter_mm", "wall_thickness_mm", "slope"} and value == 0:
                    raise ValueError(f"{name} must be positive for this gravity profile")
        if (self.outer_diameter_mm is not None and self.wall_thickness_mm is not None
                and 2*self.wall_thickness_mm >= self.outer_diameter_mm):
            raise ValueError("pipe bore must be positive")

    @property
    def end_invert_m(self) -> float | None:
        if self.start_invert_m is None or self.length_m is None or self.slope is None:
            return None
        return self.start_invert_m - self.length_m*self.slope

    def ceiling_clearance_m(self, ceiling_m: float) -> float | None:
        if not isfinite(ceiling_m):
            raise ValueError("ceiling level must be finite")
        if (self.start_invert_m is None or self.outer_diameter_mm is None
                or self.wall_thickness_mm is None or self.extra_top_envelope_mm is None):
            return None
        crown = self.start_invert_m + (
            self.outer_diameter_mm - self.wall_thickness_mm + self.extra_top_envelope_mm
        ) / 1000
        return ceiling_m - crown

    def passage_height_m(self, floor_m: float) -> float | None:
        if not isfinite(floor_m):
            raise ValueError("floor level must be finite")
        end = self.end_invert_m
        if end is None or self.wall_thickness_mm is None or self.extra_bottom_envelope_mm is None:
            return None
        return end - (self.wall_thickness_mm + self.extra_bottom_envelope_mm)/1000 - floor_m

    def validate_envelope(self, *, ceiling_m: float, floor_m: float,
                          required_ceiling_gap_m: float, required_passage_m: float) -> None:
        """Limits are explicit project inputs, never invented universal SP gaps."""
        if not all(isfinite(v) for v in (ceiling_m, floor_m, required_ceiling_gap_m, required_passage_m)):
            raise ValueError("envelope bounds must be finite")
        if min(required_ceiling_gap_m, required_passage_m) < 0 or ceiling_m <= floor_m:
            raise ValueError("invalid envelope bounds")
        gap, passage = self.ceiling_clearance_m(ceiling_m), self.passage_height_m(floor_m)
        if gap is None or passage is None:
            raise ValueError("missing grade or pipe envelope inputs")
        if gap < required_ceiling_gap_m:
            raise ValueError("collector envelope conflicts with ceiling clearance")
        if passage < required_passage_m:
            raise ValueError("collector envelope conflicts with passage height")

    def drop_height_m(self, outlet_invert_m: float) -> float | None:
        if not isfinite(outlet_invert_m):
            raise ValueError("outlet invert must be finite")
        if self.end_invert_m is None:
            return None
        drop = self.end_invert_m - outlet_invert_m
        if drop <= 0:
            raise ValueError("outlet does not permit a downward drop")
        return drop

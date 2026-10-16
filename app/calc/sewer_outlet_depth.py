"""A frost-only boundary, never a completed gravity-outlet design.

SP 32.13330.2018, 6.2.4: in the absence of local operating data the invert
of pipes up to 500 mm may be 0.3 m above zero-temperature penetration depth.
The independent 0.7 m minimum crown cover and receiving-network connection
still need checking. This helper neither sizes pipes nor creates outside pipes.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class PreliminaryFrostBound:
    highest_invert_m: float
    zero_temperature_level_m: float
    minimum_crown_cover_m: float = 0.7

    @property
    def release_ready(self) -> bool:
        return False


def preliminary_k1_frost_bound(
    *, ground_elevation_m: float, zero_temperature_depth_m: float,
    diameter_mm: float,
) -> PreliminaryFrostBound:
    """Limited to gravity K1, D <= 500, when local operating data are absent.

    Caller must explicitly establish/assume *zero-temperature penetration*,
    not silently substitute a normative soil freezing depth or an elevation.
    Result is the highest invert permitted by this ONE depth condition only.
    """
    if not all(isfinite(v) for v in
               (ground_elevation_m, zero_temperature_depth_m, diameter_mm)):
        raise ValueError("frost-bound inputs must be finite")
    if zero_temperature_depth_m <= 0:
        raise ValueError("zero-temperature penetration must be a positive depth")
    if not 0 < diameter_mm <= 500:
        raise ValueError("this preliminary K1 rule supports only diameters up to 500 mm")
    level = ground_elevation_m - zero_temperature_depth_m
    return PreliminaryFrostBound(highest_invert_m=level + 0.3, zero_temperature_level_m=level)

"""Necessary nominal duty/static checks for the separately approved L06 study.

No production selection, no reserve summation, no pump-curve extrapolation.
Static margin is NOT a certified allowance for transients or pump tolerances.
"""
from dataclasses import dataclass
from math import isfinite

from app.calc.pump_curve import interpolate_head, valid_curve


@dataclass(frozen=True)
class PumpEnvelopeScreen:
    duty_head_m: float | None
    shutoff_head_m: float | None
    dynamic_margin_m: float | None
    static_margin_m: float | None
    nominal_bounds_met: bool
    failures: tuple[str, ...]
    missing: tuple[str, ...]
    selection_confirmed: bool = False


def screen_pump_envelope(curve, *, required_q_m3h, required_boost_m,
                         maximum_suction_head_m, allowed_header_static_m):
    if not valid_curve(curve) or any(b[1] > a[1] for a, b in zip(curve, curve[1:])):
        raise ValueError("A non-increasing published Q-H curve is required")
    values = (required_q_m3h, required_boost_m, maximum_suction_head_m,
              allowed_header_static_m)
    if any(not isfinite(v) for v in values) or any(v < 0 for v in values):
        raise ValueError("Explicit nonnegative finite boundary data required")
    duty = interpolate_head(curve, required_q_m3h)
    shutoff = interpolate_head(curve, 0)
    dynamic = None if duty is None else duty - required_boost_m
    static = (None if shutoff is None else
              allowed_header_static_m - maximum_suction_head_m - shutoff)
    failures, missing = [], []
    if duty is None:
        missing.append("duty_outside_published_curve")
    elif dynamic < 0:
        failures.append("insufficient_duty_head")
    if shutoff is None:
        missing.append("no_published_shutoff_head")
    elif static < 0:
        failures.append("excessive_nominal_static_head")
    return PumpEnvelopeScreen(duty, shutoff, dynamic, static,
                              not failures and not missing,
                              tuple(failures), tuple(missing))

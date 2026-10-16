"""Fail-closed screening of L06 ideal control against real product evidence.

This is a feasibility check, not a regulator characteristic or a pump selector.
It never changes the pressure-flow network, legacy or a production specification.
"""
from dataclasses import dataclass
from math import isfinite

from app.calc.fire_hydraulics import MPA_TO_M
from app.data.fire_regulators import RegulatorCandidate

BAR_TO_M = MPA_TO_M / 10


def _finite(value: float, *, positive: bool = False) -> None:
    if not isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError("Finite positive/nonnegative engineering inputs required")


def _range(values: tuple[float, float]) -> None:
    if len(values) != 2:
        raise ValueError("Two bounds required")
    for v in values:
        _finite(v)
    if values[0] > values[1]:
        raise ValueError("Reversed bounds")


@dataclass(frozen=True)
class RegulatorScreen:
    candidate_id: str
    status: str
    failures: tuple[str, ...]
    missing: tuple[str, ...]
    selection_confirmed: bool = False


def screen_regulator(candidate: RegulatorCandidate, *, application: str,
                     flow_range_m3h: tuple[float, float], setting_bar: float,
                     minimum_available_drop_bar: float,
                     maximum_inlet_pressure_bar: float) -> RegulatorScreen:
    """Check documented bounds at a supplied duty; unknown is never a pass.

    Zero-flow locking is distinct from the continuous-flow stability range.
    A family range for minimum Δp is not an exact selected configuration.
    """
    if application not in {"standalone_vpv", "automatic_water_foam_fire"}:
        raise ValueError("Unsupported application")
    if not candidate.source_url or not candidate.source_locator:
        raise ValueError("Manufacturer source required")
    _range(flow_range_m3h)
    _finite(setting_bar, positive=True)
    _finite(minimum_available_drop_bar)
    _finite(maximum_inlet_pressure_bar, positive=True)
    failures, missing = [], list(candidate.open_issues)
    if candidate.function != "pressure_reducing":
        failures.append("not_a_downstream_pressure_reducer")
    if application in candidate.excluded_applications:
        failures.append("application_excluded_by_manufacturer")
    if candidate.fire_application_declared is not True:
        missing.append("fire_application_confirmation")
    for name, bounds, demand in (
            ("flow", candidate.flow_range_m3h, flow_range_m3h),
            ("setting", candidate.setting_range_bar, (setting_bar, setting_bar))):
        if bounds is None:
            missing.append(name + "_range")
        else:
            _range(bounds)
            if demand[0] < bounds[0] or demand[1] > bounds[1]:
                failures.append(name + "_outside_documented_range")
    drop = candidate.minimum_drop_bar
    if drop is None:
        missing.append("minimum_control_drop")
    else:
        _range(drop)
        if minimum_available_drop_bar < drop[0] - 1e-10:
            failures.append("insufficient_control_drop")
        if drop[0] != drop[1]:
            missing.append("exact_minimum_drop_for_configuration")
    if candidate.max_inlet_bar is None:
        missing.append("maximum_inlet_at_design_temperature")
    else:
        _finite(candidate.max_inlet_bar, positive=True)
        if maximum_inlet_pressure_bar > candidate.max_inlet_bar:
            failures.append("inlet_above_documented_limit")
    # A water-service PN alone cannot prove the actual pressure/temperature envelope.
    if candidate.nominal_pressure_bar is not None:
        _finite(candidate.nominal_pressure_bar, positive=True)
        if maximum_inlet_pressure_bar > candidate.nominal_pressure_bar:
            failures.append("inlet_above_nominal_pressure")
    missing.extend(("duty_specific_characteristic", "scheme_and_product_acceptance"))
    return RegulatorScreen(candidate.id,
        "outside_documented_limits" if failures else "needs_manufacturer_data",
        tuple(dict.fromkeys(failures)), tuple(dict.fromkeys(missing)))


@dataclass(frozen=True)
class SetpointWindow:
    minimum_setting_head_m: float
    maximum_setting_head_m: float
    dynamic_ceiling_head_m: float
    static_ceiling_head_m: float
    feasible: bool


def setpoint_window(*, required_dynamic_head_m: float, available_inlet_head_m: float,
                    allowed_static_head_m: float, minimum_control_drop_bar: float,
                    no_flow_extra_bar: float, lower_error_bar: float,
                    upper_error_bar: float) -> SetpointWindow:
    """Algebraic necessary conditions at ONE common elevation and ONE duty.

    Errors and no-flow excess must be explicit; zero is allowed only as an
    explicitly labelled ideal sensitivity assumption, not an inferred passport.
    Dynamic/static bounds are not a simulated regulated pump operating point.
    """
    for value in (required_dynamic_head_m, available_inlet_head_m,
                  allowed_static_head_m, minimum_control_drop_bar,
                  no_flow_extra_bar, lower_error_bar, upper_error_bar):
        _finite(value)
    lower = required_dynamic_head_m + lower_error_bar * BAR_TO_M
    dynamic = available_inlet_head_m - (minimum_control_drop_bar + upper_error_bar) * BAR_TO_M
    static = allowed_static_head_m - (no_flow_extra_bar + upper_error_bar) * BAR_TO_M
    upper = min(dynamic, static)
    return SetpointWindow(lower, upper, dynamic, static, lower <= upper + 1e-9)

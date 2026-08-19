from math import cos, pi, radians, sqrt

import pytest

from app.calc.sewer_fixture_safety import (
    BoundaryLevelPoint,
    FirstManholeBoundary,
    FixtureSafetyInput,
    FixtureSafetyStatus,
    TrapSealStatus,
    evaluate_fixture_safety,
)
from app.calc.sewer_stack_pressure import (
    DischargeEvent,
    StackPressureInput,
    StackVentilationMode,
    air_valve_capacity_lps,
    calculate_pressure_timeline,
    calculate_stack_pressure,
    timeline_to_trap_pressure,
    ventilated_capacity_lps,
)


def _stack(mode=StackVentilationMode.VENTILATED, **overrides):
    values = {
        "stack_id": "К1-Ст1",
        "ventilation_mode": mode,
        "inner_diameter_mm": 103.2,
        "branch_inner_diameter_mm": 50.0,
        "branch_angle_deg": 45.0,
        "working_height_m": 3.0,
        "minimum_trap_seal_mm": 70.0,
        "source": "схема К1 и паспорт трубы",
    }
    values.update(overrides)
    return StackPressureInput(**values)


def test_ventilated_pressure_matches_sp30_formula_35_golden_value():
    result = calculate_stack_pressure(_stack(), 3.0)

    assert result.vacuum_mm_water == pytest.approx(6.0587941008716015)
    assert result.sewer_air_pressure_pa == pytest.approx(-59.41647316931249)
    assert result.vacuum_within_limit
    assert result.formula_reference.endswith("формула (35)")


def test_formula_34_capacity_and_formula_35_are_consistent_with_published_rounding():
    data = _stack()
    capacity_lps = ventilated_capacity_lps(data)
    pressure = calculate_stack_pressure(data, capacity_lps)

    assert capacity_lps == pytest.approx(12.13848211326537)
    # Коэффициенты и показатели (34), (35) опубликованы с округлением, поэтому
    # они дают не математически тождественные, а практически близкие значения.
    assert pressure.vacuum_mm_water == pytest.approx(
        data.allowable_vacuum_mm_water,
        rel=0.003,
    )


def test_ventilated_height_is_limited_to_90_d_by_clause_19_5():
    diameter_m = 0.1032
    threshold_m = 90.0 * diameter_m
    at_threshold = _stack(working_height_m=threshold_m)
    taller = _stack(working_height_m=50.0)

    assert calculate_stack_pressure(
        taller,
        3.0,
    ).vacuum_mm_water == pytest.approx(
        calculate_stack_pressure(at_threshold, 3.0).vacuum_mm_water
    )


def test_unventilated_pressure_matches_sp30_formulas_36_to_38():
    data = _stack(StackVentilationMode.UNVENTILATED)
    result = calculate_stack_pressure(data, 3.0)

    assert result.induced_air_flow_m3s == pytest.approx(0.021132675286187588)
    assert result.mixture_velocity_mps == pytest.approx(2.885068927519661)
    assert result.vacuum_mm_water == pytest.approx(29.514356953768896)


def test_unventilated_pressure_exceeding_0_9_seal_is_rejected():
    result = calculate_stack_pressure(
        _stack(StackVentilationMode.UNVENTILATED),
        6.0,
    )

    assert result.allowable_vacuum_mm_water == 63.0
    assert result.vacuum_mm_water == pytest.approx(107.83846215004762)
    assert not result.vacuum_within_limit
    assert any("0,9 hз" in note for note in result.notes)


def test_air_valve_formula_39_uses_declared_free_area_and_is_invertible():
    data = _stack(
        StackVentilationMode.AIR_ADMITTANCE_VALVE,
        air_valve_free_area_mm2=2500.0,
        air_valve_source="паспорт клапана",
    )
    result = calculate_stack_pressure(data, 3.0)

    assert result.equivalent_valve_diameter_mm == pytest.approx(
        sqrt(0.0025 / 0.785) * 1000.0
    )
    assert result.vacuum_mm_water == pytest.approx(8.798906487384695)
    capacity_lps = air_valve_capacity_lps(data)
    assert calculate_stack_pressure(
        data,
        capacity_lps,
    ).vacuum_mm_water == pytest.approx(data.allowable_vacuum_mm_water)


def test_air_valve_requires_area_and_its_source():
    with pytest.raises(ValueError, match="площадь живого сечения"):
        _stack(StackVentilationMode.AIR_ADMITTANCE_VALVE)

    with pytest.raises(ValueError, match="источник"):
        _stack(
            StackVentilationMode.AIR_ADMITTANCE_VALVE,
            air_valve_free_area_mm2=2500.0,
        )


def test_standard_trap_height_keeps_mandatory_appendix_k_check_visible():
    result = calculate_stack_pressure(
        _stack(minimum_trap_seal_mm=50.0),
        3.0,
    )

    assert result.appendix_k_check_required
    assert any("приложения К" in note for note in result.notes)


def test_overlapping_discharge_events_are_summed_without_assumed_coincidence():
    data = _stack()
    timeline = calculate_pressure_timeline(
        data,
        events=(
            DischargeEvent("унитаз", 0.0, 10.0, 1.6, "расход прибора"),
            DischargeEvent("душ", 5.0, 10.0, 0.4, "расход прибора"),
        ),
        times_seconds=(0.0, 5.0, 10.0, 15.0),
    )

    assert [point.wastewater_flow_lps for point in timeline.points] == [
        1.6,
        2.0,
        0.4,
        0.0,
    ]
    assert timeline.points[1].active_event_ids == ("унитаз", "душ")
    assert timeline.points[-1].sewer_air_pressure_pa == 0.0


def test_calculated_timeline_feeds_fixture_trap_safety_check():
    data = _stack(
        StackVentilationMode.UNVENTILATED,
        minimum_trap_seal_mm=50.0,
    )
    timeline = calculate_pressure_timeline(
        data,
        events=(DischargeEvent("сброс", 0.0, 10.0, 6.0, "сценарий"),),
        times_seconds=(0.0, 10.0),
    )
    pressure = timeline_to_trap_pressure(timeline, "К1-Тр1")
    fixture = FixtureSafetyInput(
        fixture_id="К1-Тр1",
        pipe_id="К1-М1",
        name="Трап нижнего этажа",
        connection_elevation_m=100.0,
        overflow_elevation_m=100.15,
        trap_seal_depth_mm=50.0,
        minimum_residual_seal_mm=5.0,
        source="АР и паспорт трапа",
    )
    boundary = FirstManholeBoundary(
        manhole_id="К1-1",
        invert_elevation_m=99.0,
        levels=(BoundaryLevelPoint(0.0, 99.2),),
        source="профиль выпуска",
    )

    result = evaluate_fixture_safety(
        fixture=fixture,
        first_manhole=boundary,
        time_seconds=0.0,
        pressure=pressure,
    )

    assert result.trap_status is TrapSealStatus.SIPHONED
    assert result.status is FixtureSafetyStatus.CRITICAL


def test_published_unventilated_formula_is_not_replaced_by_generic_chezy():
    data = _stack(StackVentilationMode.UNVENTILATED)
    flow_m3s = 0.003
    diameter = data.inner_diameter_m
    induced_air = (
        13.8
        * flow_m3s ** 0.333
        * diameter ** 1.75
        * (diameter / data.branch_inner_diameter_m) ** 0.12
        / (
            (1.0 + cos(radians(data.branch_angle_deg))) ** 0.177
            * (90.0 * diameter / data.working_height_m) ** 0.5
        )
    )
    mixture_velocity = (induced_air + flow_m3s) / (pi * diameter ** 2 / 4.0)
    expected_vacuum = 0.31 * mixture_velocity ** 4.3

    assert calculate_stack_pressure(data, 3.0).vacuum_mm_water == pytest.approx(
        expected_vacuum
    )

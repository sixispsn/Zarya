import pytest

from app.calc.sewer_fixture_safety import (
    AirPressurePoint,
    BackwaterStatus,
    BoundaryLevelPoint,
    FirstManholeBoundary,
    FixtureSafetyInput,
    FixtureSafetyStatus,
    TrapPressureHydrograph,
    TrapSealStatus,
    evaluate_all_fixtures,
    evaluate_fixture_safety,
)
from app.calc.sewer_network_simulation import (
    HydrographPoint,
    InflowHydrograph,
    OutletBoundary,
    OutletBoundaryKind,
    SewerNetworkSimulator,
)
from app.calc.sewer_simulation import (
    PipeSection,
    PipeSectionConfig,
    PipeSectionState,
    PipeStatus,
)


def _fixture(*, fixture_id="К1-Тр1", connection=100.0, overflow=100.15):
    return FixtureSafetyInput(
        fixture_id=fixture_id,
        pipe_id="К1-М1",
        name="Трап нижнего этажа",
        connection_elevation_m=connection,
        overflow_elevation_m=overflow,
        trap_seal_depth_mm=50.0,
        minimum_residual_seal_mm=20.0,
        source="АР и паспорт трапа",
    )


def _manhole(level):
    return FirstManholeBoundary(
        manhole_id="К1-1",
        invert_elevation_m=99.0,
        levels=(BoundaryLevelPoint(0.0, level),),
        source="профиль выпуска и исходный уровень",
    )


def _pressure(value_pa):
    return TrapPressureHydrograph(
        fixture_id="К1-Тр1",
        points=(AirPressurePoint(0.0, value_pa),),
        source="расчёт давления в стояке",
    )


def test_level_between_connection_and_overflow_is_backwater_not_flooding():
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(100.10),
        time_seconds=0.0,
        pressure=_pressure(0.0),
    )
    assert result.backwater_status is BackwaterStatus.BACKWATER
    assert result.status is FixtureSafetyStatus.BACKWATER
    assert result.backwater_head_above_connection_m == pytest.approx(0.10)
    assert result.level_margin_to_overflow_m == pytest.approx(0.05)


def test_level_at_or_above_overflow_means_flooding_through_fixture():
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(100.17),
        time_seconds=0.0,
        pressure=_pressure(0.0),
    )
    assert result.backwater_status is BackwaterStatus.FLOODING
    assert result.status is FixtureSafetyStatus.FLOODING
    assert result.flood_depth_above_overflow_m == pytest.approx(0.02)


def test_negative_pressure_can_siphon_trap_seal():
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(99.5),
        time_seconds=0.0,
        pressure=_pressure(-600.0),
    )
    assert result.backwater_status is BackwaterStatus.CLEAR
    assert result.trap_status is TrapSealStatus.SIPHONED
    assert result.status is FixtureSafetyStatus.CRITICAL
    assert result.equivalent_pressure_head_mm < -50.0
    assert result.remaining_trap_seal_mm == 0.0


def test_positive_pressure_can_blow_trap_seal():
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(99.5),
        time_seconds=0.0,
        pressure=_pressure(600.0),
    )
    assert result.trap_status is TrapSealStatus.BLOWN
    assert result.status is FixtureSafetyStatus.CRITICAL


def test_missing_air_pressure_is_not_silently_declared_safe():
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(99.5),
        time_seconds=0.0,
    )
    assert result.backwater_status is BackwaterStatus.CLEAR
    assert result.trap_status is TrapSealStatus.DATA_REQUIRED
    assert result.status is FixtureSafetyStatus.DATA_REQUIRED


def test_known_hydrostatic_head_can_prove_blowout_without_air_model():
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(100.06),
        time_seconds=0.0,
    )
    assert result.backwater_status is BackwaterStatus.BACKWATER
    assert result.trap_status is TrapSealStatus.BLOWN
    assert result.equivalent_pressure_head_mm == pytest.approx(60.0)


def test_all_fixtures_identifies_lower_fixture_by_its_elevation():
    lower = _fixture(fixture_id="К1-Тр1", connection=100.0, overflow=100.15)
    upper = _fixture(fixture_id="К1-Тр2", connection=101.0, overflow=101.15)
    results = evaluate_all_fixtures(
        fixtures=[lower, upper],
        first_manhole=_manhole(100.20),
        time_seconds=0.0,
    )
    by_id = {row.fixture_id: row for row in results}
    assert by_id["К1-Тр1"].status is FixtureSafetyStatus.FLOODING
    assert by_id["К1-Тр2"].backwater_status is BackwaterStatus.CLEAR


def test_boundary_level_is_piecewise_constant_in_time():
    boundary = FirstManholeBoundary(
        manhole_id="К1-1",
        invert_elevation_m=99.0,
        levels=(
            BoundaryLevelPoint(0.0, 99.2),
            BoundaryLevelPoint(60.0, 100.2),
        ),
        source="сценарий подпора",
    )
    assert boundary.level_at(59.9) == 99.2
    assert boundary.level_at(60.0) == 100.2


def test_internal_network_overload_is_reported_without_claiming_fixture_flood_level():
    pipe = PipeSection(
        PipeSectionConfig(
            section_id="К1-М1",
            length_m=100.0,
            inner_diameter_mm=103.2,
            slope_per_mille=10.0,
            material="ПП",
            manning_n=0.011,
            roughness_source="паспорт трубы",
            critical_velocity_mps=0.6,
            critical_velocity_source="исходное правило пользователя",
            critical_fill_ratio=0.8,
        ),
        PipeSectionState(),
    )
    pipe.state.stored_water_m3 = pipe.available_storage_m3
    simulator = SewerNetworkSimulator(
        pipes=[pipe],
        connections=[],
        inflows=[InflowHydrograph(
            pipe_id="К1-М1",
            points=(HydrographPoint(0.0, 0.1),),
            source="испытательный приток",
        )],
        outlets=[OutletBoundary(
            pipe_id="К1-М1",
            kind=OutletBoundaryKind.FLOW_LIMIT,
            source="закрытая граница",
            maximum_flow_lps=0.0,
        )],
    )
    network_step = simulator.step(1.0)
    result = evaluate_fixture_safety(
        fixture=_fixture(),
        first_manhole=_manhole(99.5),
        time_seconds=network_step.time_seconds,
        pressure=_pressure(0.0),
        network_step=network_step,
    )
    assert result.internal_pipe_status is PipeStatus.FLOODING
    assert result.backwater_status is BackwaterStatus.CLEAR
    assert result.status is FixtureSafetyStatus.CRITICAL
    assert any("точное место выхода воды" in note for note in result.notes)

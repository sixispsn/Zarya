import pytest

from app.calc.sewer_network_simulation import (
    HydrographPoint,
    InflowHydrograph,
    NetworkSedimentModel,
    OutletBoundary,
    OutletBoundaryKind,
    PipeConnection,
    SewerNetworkSimulator,
)
from app.calc.sewer_simulation import (
    PipeSection,
    PipeSectionConfig,
    PipeSectionState,
    PipeStatus,
)


def _pipe(pipe_id, *, length=100.0, slope=10.0, state=None):
    return PipeSection(
        PipeSectionConfig(
            section_id=pipe_id,
            length_m=length,
            inner_diameter_mm=103.2,
            slope_per_mille=slope,
            material="ПП",
            manning_n=0.011,
            roughness_source="паспорт выбранной трубы",
            critical_velocity_mps=0.6,
            critical_velocity_source="исходное правило пользователя",
            critical_fill_ratio=0.8,
        ),
        state=state or PipeSectionState(),
    )


def _free_outlet(pipe_id):
    return OutletBoundary(
        pipe_id=pipe_id,
        kind=OutletBoundaryKind.FREE_OUTFALL,
        source="заданная свободная выходная граница",
    )


def test_flow_moves_from_one_section_to_the_next_on_later_step():
    first = _pipe("К1-1")
    second = _pipe("К1-2")
    simulator = SewerNetworkSimulator(
        pipes=[first, second],
        connections=[PipeConnection("К1-1", "К1-2")],
        inflows=[InflowHydrograph(
            pipe_id="К1-1",
            points=(HydrographPoint(0.0, 1.0),),
            source="испытательный гидрограф",
        )],
        outlets=[_free_outlet("К1-2")],
    )

    first_step = simulator.step(1.0)
    assert first_step.by_pipe("К1-1").stored_water_m3 == pytest.approx(0.001)
    assert first_step.by_pipe("К1-2").inflow_lps == 0

    second_step = simulator.step(1.0)
    assert second_step.by_pipe("К1-2").inflow_lps > 0
    assert second_step.water_balance_error_m3 == pytest.approx(0.0, abs=1e-12)


def test_blocked_outlet_rejects_upstream_flow_and_eventually_floods_upstream():
    downstream = _pipe("К1-2")
    downstream.state.stored_water_m3 = downstream.available_storage_m3
    upstream = _pipe("К1-1")
    upstream.state.stored_water_m3 = upstream.available_storage_m3
    simulator = SewerNetworkSimulator(
        pipes=[upstream, downstream],
        connections=[PipeConnection("К1-1", "К1-2")],
        inflows=[InflowHydrograph(
            pipe_id="К1-1",
            points=(HydrographPoint(0.0, 0.2),),
            source="испытательный гидрограф",
        )],
        outlets=[OutletBoundary(
            pipe_id="К1-2",
            kind=OutletBoundaryKind.FLOW_LIMIT,
            maximum_flow_lps=0.0,
            source="испытательная закрытая граница",
        )],
    )

    snapshot = simulator.step(1.0)
    upper = snapshot.by_pipe("К1-1")
    assert upper.downstream_rejected_lps > 0
    assert upper.flooded_volume_m3 == pytest.approx(0.0002)
    assert upper.status is PipeStatus.FLOODING
    assert snapshot.water_balance_error_m3 == pytest.approx(0.0, abs=1e-12)


def test_suspended_solids_are_conserved_and_low_velocity_builds_sediment():
    pipe = _pipe("К1-1")
    simulator = SewerNetworkSimulator(
        pipes=[pipe],
        connections=[],
        inflows=[InflowHydrograph(
            pipe_id="К1-1",
            points=(HydrographPoint(0.0, 0.1, 300.0),),
            source="испытательный гидрограф со взвесями",
        )],
        outlets=[_free_outlet("К1-1")],
        sediment_models={
            "К1-1": NetworkSedimentModel(
                sediment_bulk_density_kg_m3=1200.0,
                capture_efficiency_at_zero_velocity=0.8,
                velocity_deficit_exponent=1.0,
                source="испытательная калибровка",
            )
        },
    )

    snapshot = simulator.step(1.0)
    row = snapshot.by_pipe("К1-1")
    assert row.deposited_mass_kg > 0
    assert row.sediment_depth_mm > 0
    assert snapshot.solids_balance_error_kg == pytest.approx(0.0, abs=1e-12)


def test_cycle_and_unlisted_terminal_boundary_are_rejected():
    first = _pipe("К1-1")
    second = _pipe("К1-2")
    with pytest.raises(ValueError, match="цикл"):
        SewerNetworkSimulator(
            pipes=[first, second],
            connections=[
                PipeConnection("К1-1", "К1-2"),
                PipeConnection("К1-2", "К1-1"),
            ],
            inflows=[],
            outlets=[],
        )

    with pytest.raises(ValueError, match="выходные границы"):
        SewerNetworkSimulator(
            pipes=[_pipe("К1-3")],
            connections=[],
            inflows=[],
            outlets=[],
        )


def test_courant_violation_stops_instead_of_silently_skipping_pipe_length():
    pipe = _pipe("К1-1", length=0.1)
    pipe.state.stored_water_m3 = pipe.available_storage_m3 * 0.5
    simulator = SewerNetworkSimulator(
        pipes=[pipe],
        connections=[],
        inflows=[],
        outlets=[_free_outlet("К1-1")],
    )
    with pytest.raises(ValueError, match="условие Куранта"):
        simulator.step(10.0)


def test_hydrograph_is_piecewise_constant_by_declared_time():
    hydrograph = InflowHydrograph(
        pipe_id="К1-1",
        points=(
            HydrographPoint(0.0, 0.1, 100.0),
            HydrographPoint(60.0, 0.5, 300.0),
        ),
        source="минутный график",
    )
    assert hydrograph.value_at(59.999).flow_lps == 0.1
    assert hydrograph.value_at(60.0).flow_lps == 0.5


def test_inflow_above_gravity_capacity_is_flagged_before_physical_flooding():
    pipe = _pipe("К1-1")
    simulator = SewerNetworkSimulator(
        pipes=[pipe],
        connections=[],
        inflows=[InflowHydrograph(
            pipe_id="К1-1",
            points=(HydrographPoint(0.0, 50.0),),
            source="испытательная перегрузка",
        )],
        outlets=[_free_outlet("К1-1")],
    )

    snapshot = simulator.step(1.0).by_pipe("К1-1")
    assert snapshot.capacity_exceeded
    assert snapshot.maximum_gravity_capacity_lps < snapshot.inflow_lps
    assert snapshot.status is PipeStatus.CRITICAL_FILL
    assert snapshot.flooded_volume_m3 == 0

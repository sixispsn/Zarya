from copy import deepcopy
from pathlib import Path

import pytest

from app.calc.sewer_fixture_safety import (
    BackwaterStatus,
    FixtureSafetyStatus,
    TrapSealStatus,
)
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import generate_wastewater_calculation_html
from app.pz.ios2_orchestrator import design_ios2
from app.pz.wastewater_transients import assess_wastewater_transients


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _project():
    return build_project(load_request_file(str(DEMO)))


def test_registry_resolves_events_through_branch_riser_and_mains():
    result = assess_wastewater_transients(_project())

    assert result.ready
    assert result.errors == []
    assert len(result.events) == 2
    first = result.events[0]
    assert first.fixture_id == "К1-Ун1"
    assert first.branch_section_id == "К1-Ветв-СУ1"
    assert first.riser_id == "К1-Ст1"
    assert first.route_section_ids == (
        "К1-Ветв-СУ1",
        "К1-Ст1",
        "К1-М1",
        "К1-Вып1",
    )


def test_one_timeline_drives_risers_and_horizontal_network_inflows():
    result = assess_wastewater_transients(_project())

    assert [row.time_seconds for row in result.report_points] == [
        0.0, 3.0, 5.0, 8.0, 240.0,
    ]
    overlap = next(row for row in result.points if row.time_seconds == 3.0)
    assert overlap.total_flow_lps == pytest.approx(3.2)
    assert overlap.riser_flows_lps == {"К1-Ст1": 1.6, "К1-Ст2": 1.6}
    assert overlap.section_flows_lps["К1-Вып1"] == pytest.approx(3.2)

    inflows = {row.pipe_id: row for row in result.network_inflows}
    assert inflows["К1-М1"].value_at(3.0).flow_lps == pytest.approx(1.6)
    assert inflows["К1-Вып1"].value_at(3.0).flow_lps == pytest.approx(1.6)
    assert inflows["К1-М1"].value_at(5.0).flow_lps == 0.0


def test_stack_pressure_is_calculated_from_resolved_simultaneous_events():
    result = assess_wastewater_transients(_project())
    checks = {row.riser_id: row for row in result.stack_checks}

    assert checks["К1-Ст1"].peak_scenario_flow_lps == pytest.approx(1.6)
    assert checks["К1-Ст1"].design_flow_lps == pytest.approx(2.758)
    assert checks["К1-Ст1"].peak_vacuum_mm_water == pytest.approx(
        14.18448020237986
    )
    assert checks["К1-Ст1"].allowable_vacuum_mm_water == pytest.approx(45.0)
    assert checks["К1-Ст1"].status == "verified"
    assert checks["К1-Ст2"].status == "verified"


def test_time_step_network_preserves_balance_and_propagates_flow():
    result = assess_wastewater_transients(_project())

    assert len(result.network_steps) == 240
    assert all(
        abs(step.water_balance_error_m3) < 1e-10
        for step in result.network_steps
    )
    summaries = {row.section_id: row for row in result.network_summaries}
    assert summaries["К1-М1"].peak_inflow_lps == pytest.approx(1.6)
    # Выпуск получает собственный внешний сброс второго стояка и позже поток
    # первого стояка; гидравлическое хранение не даёт мгновенного Q=3,2 л/с.
    assert 1.6 < summaries["К1-Вып1"].peak_inflow_lps < 3.2
    assert summaries["К1-Вып1"].flooded_volume_m3 == 0.0
    assert summaries["К1-Вып1"].final_stored_water_m3 > 0.0
    nodes = {row.node_id: row for row in result.internal_node_summaries}
    assert set(nodes) == {"К1-Ст1", "К1-Ст2"}
    assert nodes["К1-Ст2"].overflow_absolute_elevation_m == 147.27
    assert nodes["К1-Ст2"].flooded_volume_m3 == 0.0


def test_internal_node_reports_location_and_time_of_overflow():
    project = deepcopy(_project())
    for event in project.sewage.discharge_events:
        event.start_seconds = 0.0
        event.duration_seconds = 1.0
        event.flow_lps = 1000.0
    project.sewage.transient_duration_seconds = 2.0

    result = assess_wastewater_transients(project)

    flooded = [
        row for row in result.internal_node_summaries
        if row.flooded_volume_m3 > 0
    ]
    assert flooded
    assert flooded[0].first_overflow_time_seconds == 1.0
    assert "техническое подполье" in flooded[0].overflow_location
    assert all(
        abs(step.water_balance_error_m3) < 1e-10
        for step in result.network_steps
    )


def test_missing_solids_does_not_fake_sediment_prediction():
    result = assess_wastewater_transients(_project())

    assert not result.sediment_data_complete
    assert all(row.final_sediment_depth_mm == 0.0 for row in result.network_summaries)
    assert any("прогноз осадка отключён" in row for row in result.warnings)


def test_stack_pressure_and_first_manhole_level_reach_specific_lower_fixtures():
    result = assess_wastewater_transients(_project())

    assert len(result.fixture_checks) == 2
    checks = {row.fixture_id: row for row in result.fixture_checks}
    first = checks["К1-Ун1"]
    assert first.floor == 1 and first.instance_no == 1
    assert first.riser_id == "К1-Ст1"
    assert first.first_manhole_id == "КК-1"
    assert first.peak_boundary_level_m == pytest.approx(146.60)
    assert first.minimum_level_margin_to_overflow_m == pytest.approx(1.10)
    assert first.maximum_backwater_head_m == 0.0
    assert first.minimum_remaining_trap_seal_mm == pytest.approx(
        50.0 - 14.18448020237986
    )
    assert first.worst_backwater_status is BackwaterStatus.CLEAR
    assert first.worst_trap_status is TrapSealStatus.VERIFIED
    assert first.status is FixtureSafetyStatus.NORMAL


def test_first_manhole_level_can_prove_flooding_and_trap_blowout():
    project = deepcopy(_project())
    project.sewage.first_manholes[0].levels[0].water_level_absolute_elevation_m = (
        147.80
    )

    result = assess_wastewater_transients(project)

    assert result.ready
    first = result.fixture_checks[0]
    assert first.status is FixtureSafetyStatus.FLOODING
    assert first.worst_backwater_status is BackwaterStatus.FLOODING
    assert first.worst_trap_status is TrapSealStatus.BLOWN
    assert first.maximum_backwater_head_m == pytest.approx(0.38)


def test_missing_first_manhole_is_reported_without_inventing_safe_boundary():
    project = deepcopy(_project())
    project.sewage.first_manholes.clear()

    result = assess_wastewater_transients(project)

    assert result.ready
    assert all(
        row.status is FixtureSafetyStatus.DATA_REQUIRED
        for row in result.fixture_checks
    )
    assert all(row.snapshots == () for row in result.fixture_checks)
    assert all("не задан первый колодец" in row.note for row in result.fixture_checks)


def test_unknown_fixture_and_overlapping_same_instance_are_rejected():
    project = deepcopy(_project())
    project.sewage.discharge_events[0].fixture_id = "К1-НЕИЗВЕСТНЫЙ"
    result = assess_wastewater_transients(project)
    assert not result.ready
    assert any("отсутствует в реестре" in row for row in result.errors)

    project = deepcopy(_project())
    second = project.sewage.discharge_events[1]
    second.fixture_id = "К1-Ун1"
    second.floor = 16
    second.instance_no = 1
    result = assess_wastewater_transients(project)
    assert not result.ready
    assert any("перекрывающиеся сбросы" in row for row in result.errors)


def test_fixture_floor_and_instance_are_checked_against_registry_quantity():
    project = deepcopy(_project())
    project.sewage.discharge_events[0].floor = 17
    result = assess_wastewater_transients(project)
    assert any("вне диапазона прибора" in row for row in result.errors)

    project = deepcopy(_project())
    project.sewage.discharge_events[0].instance_no = 3
    result = assess_wastewater_transients(project)
    assert any("превышает количество 2 на этаже" in row for row in result.errors)


def test_missing_dynamic_pipe_inputs_keep_flow_scenario_but_skip_network_solver():
    project = deepcopy(_project())
    main = next(
        row for row in project.sewage.pipes if row.section_id == "К1-М1"
    )
    main.critical_velocity_mps = None
    result = assess_wastewater_transients(project)

    assert result.ready
    assert result.network_steps == ()
    assert any("критическая скорость" in row for row in result.warnings)


def test_event_grid_and_simulation_horizon_are_not_silently_rounded():
    project = deepcopy(_project())
    project.sewage.discharge_events[0].start_seconds = 0.5
    result = assess_wastewater_transients(project)
    assert not result.ready
    assert any("не кратно шагу" in row for row in result.errors)

    project = deepcopy(_project())
    project.sewage.transient_duration_seconds = 7.0
    result = assess_wastewater_transients(project)
    assert not result.ready
    assert any("меньше окончания последнего события" in row for row in result.errors)


def test_invalid_courant_step_is_reported_without_breaking_package():
    project = deepcopy(_project())
    project.sewage.transient_step_seconds = 5.0
    for event in project.sewage.discharge_events:
        event.start_seconds = 0.0
        event.duration_seconds = 5.0
    project.sewage.transient_duration_seconds = 10.0
    main = next(
        row for row in project.sewage.pipes if row.section_id == "К1-М1"
    )
    main.calculation_length_m = 0.1

    result = assess_wastewater_transients(project)

    assert result.ready
    assert result.network_steps == ()
    assert any("условие Куранта" in row for row in result.warnings)


def test_orchestrator_and_calculation_sheet_include_transient_proof(tmp_path):
    bundle = design_ios2(
        _project(),
        output_dir=str(tmp_path),
        render_documents=False,
    )
    assert bundle.project.sewage.transient_assessment.ready
    assert any("sewage_transients" in row for row in bundle.status)

    html = generate_wastewater_calculation_html(bundle.project)
    assert "Временной сценарий сбросов" in html
    assert "СБР-1" in html and "СБР-2" in html
    assert "14,184" in html
    assert "35,816" in html
    assert "КК-1" in html
    assert "Подпор отсутствует" in html
    assert "Внутренний узел / нижний участок" in html
    assert "техническое подполье у основания К1-Ст2" in html
    assert "не заменяет нормативный расход" in html

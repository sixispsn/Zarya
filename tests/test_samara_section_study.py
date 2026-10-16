from dataclasses import replace
import os
from xml.etree import ElementTree as ET

import pytest

from app.intake.studio_intake import accepted_values, build_handoff_request, answer_field
from app.intake.studio_section import section_model
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg
from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station, run_checks


def test_authorised_study_inputs_are_filled_without_faking_passports():
    d = make_draft(load_basis())
    values = accepted_values(d)
    assert values["residents"] == 350 and values["apartments"] == 143
    assert values["fire_height_m"] == 46.35 and values["storm_roof_area_m2"] == 650
    assert values["h_geom_m"] == 48.195 and "h_vvod_m" not in values
    assert values["section_k1_outlet_invert_m"] == -2.4
    assert values["section_k2_outlet_invert_m"] == -2.3
    assert d["control_basis"]["derived_for_study"]["connection_pipe_axis_relative_m"] == -2.195
    assert d["calculation"]["total"]["q_day"] == 63
    assert d["calculation"]["sewage_flow"] == 4.785
    req = make_request(d)
    assert not req.validate()
    assert req.source_data.meter_minimum_checks == {}
    assert req.storm_selected_funnel_capacity_lps is None
    assert req.fire_topology == "separate"
    assert req.source_data.elev_fixture_m-req.source_data.elev_header_m == values["h_geom_m"]
    assert all("учебн" in row.material.lower() for row in req.v1_sections)
    assert req.t3_sections[1].circulation_flow_lps == .5


def test_ordinary_studio_keeps_water_head_without_loading_fire_fixture(tmp_path):
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    from app.intake.yaml_io import dump_request, load_request
    d = make_draft(load_basis())
    d.pop("control_basis")
    answer_field(d, "connection_note", "Hгар=30 м в точке подключения; учебное условие.")
    req = load_request(dump_request(build_handoff_request(d)))
    assert req.fire_topology == "separate"
    assert req.floor_elevations_m[-1] == -3.25
    assert req.floor_elevations_m[16] == 45
    assert req.wastewater_roof_relative_elevation_m == 51
    assert "учебное условие" in req.source_data.basis
    assert req.network is None and not req.rooms
    b = design_ios2(build_project(req), output_dir=str(tmp_path), render_documents=False)
    assert b.project.head_paths.governing.head.h_required_m == 80.25
    assert b.project.head_paths.governing.head.h_pump_m == 50.25
    assert all(path.head.km == .3 for path in b.project.head_paths.paths)
    # The station previously reviewed for one fixture is NOT a general default.
    assert b.fire_station_result is None
    answer_field(d, "floor_height_m", None)
    answer_field(d, "section_fan_roof_level_m", None)
    req = build_handoff_request(d)
    assert req.floor_elevations_m == {-1: -3.25, 1: 0}
    assert req.wastewater_roof_relative_elevation_m is None


def test_reproducible_head_does_not_put_whole_building_flow_in_each_branch(tmp_path):
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    d = make_draft(load_basis())
    req = make_request(d)
    assert req.v1_sections[0].flow_lps == d["calculation"]["total"]["q_sec"]
    assert req.v1_sections[1].flow_lps > req.v1_sections[2].flow_lps > req.v1_sections[3].flow_lps
    b = design_ios2(build_project(req), output_dir=str(tmp_path), render_documents=False,
                   fire_station=make_fire_station(load_basis()))
    p = b.project
    assert p.head_paths.complete
    assert p.head_paths.governing.head.h_required_m == 80.25
    assert p.head_paths.governing.head.h_pump_m == 50.25
    assert all(x.head.km == .3 for x in p.head_paths.paths)
    assert p.pumps.model and p.pumps.pump_head_at_design_m >= p.pumps.h_design_m
    assert p.fire.q_total == 5.2 and p.fire.network_topology == "separate"
    assert p.fire_pumps.model
    assert p.fire_pumps.curve_kind == "duty_only"
    assert p.fire_pumps.working_units == p.fire_pumps.reserve_units == 1
    assert p.fire_pumps.sp10_compliant is None  # No manufactured NPSH / AR evidence.
    assert not any("сценарий не рассчитан" in w for w in b.warnings)
    h = b.fire_hydraulic_result
    assert h.dictating_scenario and h.needs_pump and h.pump_duty
    suction = 30+(-2.195)-(-2.45)-.0023*20*1.1*5.2**2
    assert h.available_head_m == pytest.approx(suction)
    # Common discharge header at -2.450; split flow AFTER the station only.
    expected = .21/.00981 + 48.8 + (.0023*20+.011*47)*1.1*2.6**2
    assert h.required_head_at_source_m == pytest.approx(expected, abs=1e-4)
    assert h.pump_duty.required_head_m == pytest.approx(expected-suction, abs=1e-4)
    assert b.fire_station_result.maximum_static_suction_head_m == pytest.approx(35.255)
    assert all(row.flow_lps == 5.2 for row in b.fire_station_result.supplies)
    sections = {row.segment_id: row for row in h.dictating_scenario.sections}
    assert sections["М1"].flow_lps == pytest.approx(2.6, abs=1e-4)
    assert sections["М1"].effective_length_m == 22
    r = b.resilience_report
    assert r.all_cases_solved
    assert len(r.source_failure_cases) == 2
    assert r.survives_worst_case and r.survives_by_pump
    for case in r.source_failure_cases:
        assert case.available_head_m == pytest.approx(suction) and case.needs_pump
        # 5.2 in one discharge feeder, 1.3 in each half-ring to remote riser.
        required = .21/.00981 + 48.8 + 1.1*(.0023*20*5.2**2 + .0023*46*1.3**2 + .011*47*2.6**2)
        assert case.required_head_at_source_m == pytest.approx(required, abs=1e-4)


@pytest.mark.parametrize("mode", ["unresolved", "individual"])
def test_technical_floor_survives_unresolved_or_individual_fan(mode):
    m = section_model(accepted_values(make_draft(load_basis())))
    m = replace(m, fan=replace(m.fan, mode=mode))
    svg = build_concept_section_svg(m)
    assert not audit_concept_section_svg(m, svg)
    root = ET.fromstring(svg)
    marks = {r.get("data-level-mark"): float(r.get("data-elevation-m"))
             for r in root.iter() if r.get("data-level-mark")}
    assert marks["fan-space"] == 48 and marks["fan-roof"] == 51
    assert marks["floor-16"] == 45 and marks["basement"] == -3.25
    assert len([r for r in root.iter() if r.get("data-section-apartment")]) == 6
    assert len([r for r in root.iter() if r.get("data-section-funnel")]) == 1
    assert "data-common-fan" not in svg
    for node in m.lower_nodes():
        assert not node.validate()
    assert m.lower_nodes()[0].service_path and not m.lower_nodes()[1].service_path
    next(r for r in root.iter() if r.get("data-level-mark") == "fan-roof").set("data-elevation-m", "48")
    assert "invalid elevation symbol: fan-roof" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))


def test_case_matches_executed_working_legacy():
    node = os.environ.get("NODE_BINARY")
    assert node, "Set NODE_BINARY for mandatory parity"
    result = run_checks(make_draft(load_basis()), node)
    assert result["demand_parity"] and result["k1_parity"] and result["meter_parity"]
    assert result["rain_parity"] and result["branch_parity"]
    assert result["studio_preview_available"]

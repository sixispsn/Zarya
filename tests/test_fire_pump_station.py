from copy import deepcopy
from dataclasses import replace

import pytest

from app.calc.fire_pump_station import calculate_common_fire_station
from app.intake.project_builder import build_project
from app.pz.geometry_builder import build_network
from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station


@pytest.fixture
def case():
    b = load_basis()
    return build_network(build_project(make_request(make_draft(b)))), make_fire_station(b)


def test_common_boundary_is_explicit_and_does_not_mutate_graph(case):
    net, station = case
    before = deepcopy(net)
    out = calculate_common_fire_station(net, station, 2)
    assert net == before
    assert out.network.source.available_head_m == out.network.second_source.available_head_m
    assert out.hydraulic.pump_duty.flow_lps == 5.2
    for supply in out.supplies:
        assert supply.loss_m == pytest.approx(.0023*22*5.2**2)
        assert supply.suction_head_m == pytest.approx(30+.255-supply.loss_m)


def test_translation_of_all_elevations_preserves_duty(case):
    net, station = case
    original = calculate_common_fire_station(net, station, 2)
    for n in net.nodes.values():
        n.elevation_m += 123
    station = replace(station, pump_axis_m=station.pump_axis_m+123,
        supplies=tuple(replace(s, source_elevation_m=s.source_elevation_m+123) for s in station.supplies))
    shifted = calculate_common_fire_station(net, station, 2)
    assert shifted.hydraulic.pump_duty.required_head_m == pytest.approx(original.hydraulic.pump_duty.required_head_m)


def test_weaker_supply_sets_full_flow_envelope_and_unknown_max_stays_unknown(case):
    net, station = case
    station = replace(station, supplies=(station.supplies[0],
        replace(station.supplies[1], guaranteed_head_m=25, maximum_head_m=None)))
    out = calculate_common_fire_station(net, station, 2)
    assert out.minimum_suction_head_m == out.supplies[1].suction_head_m
    assert out.supplies[0].suction_head_m-out.supplies[1].suction_head_m == pytest.approx(5)
    assert out.maximum_static_suction_head_m is None


def test_no_booster_when_city_covers_common_header(case):
    net, station = case
    station = replace(station, supplies=tuple(
        replace(s, guaranteed_head_m=100, maximum_head_m=110) for s in station.supplies))
    out = calculate_common_fire_station(net, station, 2)
    assert out.hydraulic.pump_duty is None
    assert out.hydraulic.available_head_ok and not out.hydraulic.needs_pump


@pytest.mark.parametrize("kind", ["single", "no_basis", "wrong_datum", "bad_pressure", "negative_length", "gap", "no_positive_suction"])
def test_incomplete_or_unsupported_station_fails_closed(case, kind):
    net, station = case
    supply = station.supplies[0]
    if kind == "single":
        station = replace(station, supplies=(supply,))
    elif kind == "no_basis":
        station = replace(station, basis="")
    elif kind == "wrong_datum":
        net.nodes[net.second_source.node_id].elevation_m += 1
    elif kind == "bad_pressure":
        supply = replace(supply, maximum_head_m=20)
    elif kind == "negative_length":
        supply = replace(supply, segments=(replace(supply.segments[0], length_m=-1),))
    elif kind == "gap":
        supply = replace(supply, segments=supply.segments+(replace(supply.segments[0], from_node="Disconnected"),))
    elif kind == "no_positive_suction":
        supply = replace(supply, guaranteed_head_m=0)
    if kind not in {"single", "no_basis", "wrong_datum"}:
        station = replace(station, supplies=(supply, station.supplies[1]))
    with pytest.raises(ValueError):
        calculate_common_fire_station(net, station, 2)


def test_pressure_envelope_and_shared_drawing_frame(tmp_path):
    from scripts.build_samara_section_study import check_fire_pressure_scenarios
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.fire_station_study_sheet import build_fire_station_study_sheet
    from xml.etree import ElementTree as ET
    b = load_basis()
    bundle = design_ios2(build_project(make_request(make_draft(b))),
        fire_station=make_fire_station(b), output_dir=str(tmp_path),render_documents=False)
    original = deepcopy(bundle.fire_station_result.network)
    review = check_fire_pressure_scenarios(b, bundle)
    rows = review["floors"]
    assert bundle.fire_station_result.network == original
    assert review["scenario_count"] == 256
    assert not review["free_discharge_verified"] and not review["regulatory_coverage_verified"]
    assert {tuple(s["floors"]) for s in review["scenarios"]} == {
        (a,b) for a in range(1,17) for b in range(1,17)}
    assert all(s["fixed_total_flow_lps"] == 5.2 for s in review["scenarios"])
    assert max(s["required_header_head_m"] for s in review["scenarios"]) == pytest.approx(
        bundle.fire_hydraulic_result.required_head_at_source_m, abs=1e-6)
    assert [r["floor"] for r in rows if r["pressure_control_required"]] == list(range(1,13))
    assert [r["floor"] for r in rows if not r["independent_fire_static_ok"]] == list(range(1,14))
    assert rows[0]["static_envelope_mpa"] == pytest.approx(1.25971322575)
    for row in rows:
        assert row["dynamic_upper_bound_mpa"]-row["dynamic_pressure_mpa"] == pytest.approx(
            .0023*22*5.2**2*.00980665)
    assert rows[-1]["cabinet_elevation_m"] == 46.35
    svg = build_fire_station_study_sheet(bundle.project, bundle.fire_station_result)
    root = ET.fromstring(svg)
    assert root.attrib["width"] == "420mm" and root.attrib["height"] == "297mm"
    assert len([x for x in root.iter() if x.get("data-drawing-frame")]) == 1
    assert "45.51" in svg and "74.393" in svg and "28.887" in svg
    bundle.project.fire.pressure_at_lowest_pk_mpa = rows[0]["static_envelope_mpa"]
    rechecked = design_ios2(bundle.project, fire_station=make_fire_station(b),
                           output_dir=str(tmp_path),render_documents=False)
    assert rechecked.project.fire_pumps.sp10_compliant is False
    check = next(c for c in rechecked.project.fire_pumps.sp10_checks if c.clause.startswith("6.2.20"))
    assert check.status == "fail" and "1.260" in check.decision


def test_pressure_review_rejects_missing_curve(tmp_path):
    from scripts.build_samara_section_study import check_fire_pressure_scenarios
    from app.pz.ios2_orchestrator import design_ios2
    b = load_basis()
    bundle = design_ios2(build_project(make_request(make_draft(b))),
        fire_station=make_fire_station(b), output_dir=str(tmp_path),render_documents=False)
    bundle.project.fire_pumps.curve = []
    with pytest.raises(ValueError, match="published pump curve"):
        check_fire_pressure_scenarios(b,bundle)

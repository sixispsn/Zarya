from math import isclose

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_wastewater_typical_floor_node_pdf
from app.pz.wastewater_floor_drafting import (
    FloorFixtureInput,
    build_typical_floor_assembly,
    build_typical_floor_control_sheet_svg,
    render_typical_floor_assembly_svg,
)


def test_floor_module_is_one_connected_branch_with_toilet_last():
    floor = build_typical_floor_assembly()

    assert floor.validate() == []
    assert [row.kind for row in floor.fixtures] == [
        "sink",
        "bath",
        "washbasin",
        "toilet",
    ]
    assert floor.fixtures[-1].dn_mm == 100
    branch = [floor.segment(row) for row in floor.branch_segment_ids]
    assert [row.dn_mm for row in branch] == [50, 50, 50, 100]
    assert all(
        upstream.end_port_id == downstream.start_port_id
        for upstream, downstream in zip(branch, branch[1:])
    )


def test_each_fixture_starts_a_real_connection_and_reaches_common_branch():
    floor = build_typical_floor_assembly()

    for fixture in floor.fixtures:
        connection = [floor.segment(row) for row in fixture.connection_segment_ids]
        assert connection[0].start_port_id == fixture.fixture_outlet_port_id
        assert connection[-1].end_port_id == fixture.junction_port_id
        assert all(row.carries_flow for row in connection)
        assert all(
            floor.port(row.end_port_id).point.y_mm
            >= floor.port(row.start_port_id).point.y_mm
            for row in connection
        )
        vertical_gap = (
            floor.port(fixture.junction_port_id).point.y_mm
            - floor.port(fixture.fixture_outlet_port_id).point.y_mm
        )
        assert vertical_gap <= 70.0


def test_floor_branch_enters_riser_through_elbow_and_oblique_tee():
    floor = build_typical_floor_assembly()
    elbow = floor.fitting("riser_branch_elbow_45")
    tee = floor.fitting("riser_branch_wye")
    joint = floor.direct_fitting_joint("riser_elbow_to_wye")
    start = floor.port(joint.start_port_id).point
    end = floor.port(joint.end_port_id).point

    assert elbow.kind == "elbow_45"
    assert elbow.connected_segment_ids == ("collector_to_riser",)
    assert tee.kind == "wye_45"
    assert set(tee.connected_segment_ids) == {"riser_upper", "riser_lower"}
    assert joint.start_fitting_id == elbow.fitting_id
    assert joint.end_fitting_id == tee.fitting_id
    assert all(row.segment_id != "riser_branch_diagonal" for row in floor.segments)
    dx, dy = start.vector_to(end)
    assert dx == pytest.approx(dy)
    assert 0 < dx <= 8.0


def test_external_and_integral_traps_are_not_confused():
    floor = build_typical_floor_assembly()
    by_kind = {row.kind: row for row in floor.fixtures}

    for kind in ("sink", "bath", "washbasin"):
        assert by_kind[kind].trap_mode == "external"
        assert by_kind[kind].trap_inlet_port_id
        assert by_kind[kind].trap_outlet_port_id
        assert floor.fitting(f"{by_kind[kind].fixture_id}_trap").kind == "trap"
    assert by_kind["toilet"].trap_mode == "integral"
    assert not by_kind["toilet"].trap_inlet_port_id
    assert not by_kind["toilet"].trap_outlet_port_id
    assert all(row.kind != "trap" or "Ун1" not in row.fitting_id for row in floor.fittings)


def test_cleanout_is_capped_collinear_and_reaches_the_riser():
    floor = build_typical_floor_assembly()
    access = floor.segment("cleanout_access")
    first_branch = floor.segment(floor.branch_segment_ids[0])
    cap = floor.port(access.start_port_id).point
    first = floor.port(access.end_port_id).point
    next_point = floor.port(first_branch.end_port_id).point
    ax, ay = cap.vector_to(first)
    bx, by = first.vector_to(next_point)

    assert isclose(ax * by - ay * bx, 0.0, abs_tol=1e-9)
    assert ax * bx + ay * by > 0
    assert floor.port("cleanout_cap").accessible
    assert floor.fitting("cleanout_cap_fitting").kind == "cap"
    assert floor.service_path.point_ids[0] == "cleanout_cap"
    assert "riser_branch_elbow" in floor.service_path.point_ids
    assert floor.service_path.point_ids[-1] == "riser_join"
    assert floor.service_path.serviced_segment_ids == floor.branch_segment_ids


def test_floor_inputs_are_deterministic_and_reject_unsafe_toilet_dn():
    fixtures = (
        FloorFixtureInput("WC", "toilet", "Санузел"),
        FloorFixtureInput("B", "bath", "Санузел"),
        FloorFixtureInput("S", "sink", "Кухня"),
    )
    floor = build_typical_floor_assembly(fixtures=fixtures)
    assert [row.fixture_id for row in floor.fixtures] == ["S", "B", "WC"]

    bad = (
        FloorFixtureInput("S", "sink", "Кухня"),
        FloorFixtureInput("B", "bath", "Санузел"),
        FloorFixtureInput("WC", "toilet", "Санузел", dn_mm=50),
    )
    with pytest.raises(ValueError, match="toilet connection must be DN100"):
        build_typical_floor_assembly(fixtures=bad)
    with pytest.raises(ValueError, match="at least three fixtures"):
        build_typical_floor_assembly(fixtures=fixtures[:2])


def test_svg_contains_canonical_ugo_fittings_and_no_fake_cleanout_stub():
    floor = build_typical_floor_assembly()
    normative = render_typical_floor_assembly_svg(floor, diagnostics=False)
    diagnostic = render_typical_floor_assembly_svg(floor, diagnostics=True)

    assert normative.count('data-floor-fixture=') == 4
    assert normative.count('data-ugo="trap"') == 3
    assert 'data-trap-mode="integral"' in normative
    assert normative.count('_wye_45">') == 5
    assert normative.count('_elbow_45">') == 5
    assert 'data-floor-fitting="riser_branch_elbow_45"' in normative
    assert 'data-floor-fitting="riser_branch_wye_45"' in normative
    assert 'data-direct-fitting-joint="riser_elbow_to_wye"' in normative
    assert 'data-floor-segment="riser_branch_diagonal"' not in normative
    assert 'data-fitting-label="riser_branch_wye_45"' in normative
    assert 'data-role="cleanout_access"' in normative
    assert 'data-carries-flow="false"' in normative
    assert 'data-service-path="floor_cleanout_cable"' not in normative
    assert 'data-service-path="floor_cleanout_cable"' in diagnostic


def test_control_sheet_is_a4_landscape_vector_pdf(tmp_path):
    floor = build_typical_floor_assembly()
    svg = build_typical_floor_control_sheet_svg(floor)
    assert 'viewBox="0 0 1123 794"' in svg
    assert 'data-floor-assembly="К1-Этаж-02"' in svg
    assert "Контрольный модуль 02" in svg

    output = tmp_path / "typical-floor.pdf"
    generate_wastewater_typical_floor_node_pdf(str(output))
    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(297.0, abs=0.05)
    assert height_mm == pytest.approx(210.0, abs=0.05)

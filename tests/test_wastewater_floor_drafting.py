from dataclasses import replace
from math import isclose
from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_wastewater_typical_floor_node_pdf
from app.pz.wastewater_drafting import DraftPipeSegment
from app.pz.wastewater_floor_drafting import (
    FloorFixtureInput,
    audit_floor_simplification,
    audit_floor_rendering_conventions,
    build_typical_floor_assembly,
    build_typical_floor_control_sheet_svg,
    build_floor_graphic_annotations,
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
        direct_joint = floor.direct_fitting_joint(fixture.connection_joint_id)
        assert connection[0].start_port_id == fixture.fixture_outlet_port_id
        assert connection[-1].end_port_id == direct_joint.start_port_id
        assert direct_joint.end_port_id == fixture.junction_port_id
        assert direct_joint.start_fitting_id.endswith("_elbow_45")
        assert direct_joint.end_fitting_id.endswith("_wye_45")
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


def test_fixture_elbows_are_directly_socketed_into_wyes_without_pipe_spools():
    floor = build_typical_floor_assembly()

    assert audit_floor_simplification(floor) == ()
    assert all("_diagonal" not in row.segment_id for row in floor.segments)
    assert len(floor.direct_fitting_joints) == len(floor.fixtures) + 1
    for fixture in floor.fixtures:
        joint = floor.direct_fitting_joint(fixture.connection_joint_id)
        start = floor.port(joint.start_port_id).point
        end = floor.port(joint.end_port_id).point
        dx, dy = start.vector_to(end)
        assert dx == pytest.approx(dy)
        assert 0 < dx <= 8.0


def test_simplification_audit_rejects_old_graphic_elbow_wye_spool():
    floor = build_typical_floor_assembly()
    fixture = floor.fixtures[0]
    joint = floor.direct_fitting_joint(fixture.connection_joint_id)
    obsolete = DraftPipeSegment(
        "obsolete_fixture_diagonal",
        joint.start_port_id,
        joint.end_port_id,
        joint.dn_mm,
        "fixture_connection",
    )
    old_style = replace(
        floor,
        segments=(*floor.segments, obsolete),
        direct_fitting_joints=tuple(
            row for row in floor.direct_fitting_joints if row.joint_id != joint.joint_id
        ),
    )

    findings = audit_floor_simplification(old_style)
    assert [(row.code, row.element_id) for row in findings] == [
        ("avoidable_elbow_wye_spool", "obsolete_fixture_diagonal")
    ]


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


def test_floor_annotations_derive_slopes_and_dn_transition_from_topology():
    floor = build_typical_floor_assembly()
    slopes, transitions = build_floor_graphic_annotations(floor)

    assert [(row.dn_mm, row.slope) for row in slopes] == [
        (50, pytest.approx(0.03)),
        (100, pytest.approx(0.02)),
    ]
    assert len(transitions) == 1
    transition = transitions[0]
    assert transition.port_id == floor.fixtures[-1].junction_port_id
    assert (transition.upstream_dn_mm, transition.downstream_dn_mm) == (50, 100)


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
    assert normative.count('data-direct-fitting-joint=') == 5
    assert 'data-floor-segment="riser_branch_diagonal"' not in normative
    assert 'data-floor-segment="К1-Мой1_diagonal"' not in normative
    assert 'data-fitting-boundary="riser_elbow_outlet_45"' in normative
    assert 'data-fitting-label="riser_branch_wye_45"' in normative
    assert "i=" not in normative
    assert normative.count('data-slope-marker=') == 2
    assert 'data-placement="above"' in normative
    assert 'data-slope-value="0,030"' in normative
    assert 'data-slope-value="0,020"' in normative
    assert normative.count('data-diameter-transition=') == 1
    assert normative.count('data-diameter-transition-mask=') == 1
    assert 'data-upstream-dn="50"' in normative
    assert 'data-downstream-dn="100"' in normative
    assert 'data-role="cleanout_access"' in normative
    assert 'data-carries-flow="false"' in normative
    assert 'data-service-path="floor_cleanout_cable"' not in normative
    assert 'data-service-path="floor_cleanout_cable"' in diagnostic
    assert audit_floor_rendering_conventions(floor, normative) == ()


def test_graphic_convention_audit_rejects_legacy_i_and_missing_open_triangle():
    floor = build_typical_floor_assembly()
    normative = render_typical_floor_assembly_svg(floor, diagnostics=False)
    broken = normative.replace(
        "</g>", '<text>i=0,030</text></g>', 1
    ).replace(
        'data-diameter-transition="transition_3"',
        'data-removed-transition="transition_3"',
        1,
    )

    findings = audit_floor_rendering_conventions(floor, broken)
    assert {row.code for row in findings} == {
        "legacy_slope_notation",
        "missing_diameter_transition",
    }


def test_riser_fitting_ticks_and_label_do_not_collide_with_direct_joint():
    floor = build_typical_floor_assembly()
    root = ElementTree.fromstring(
        render_typical_floor_assembly_svg(floor, diagnostics=False)
    )

    def line_with(attribute: str, value: str):
        return next(row for row in root.iter("line") if row.get(attribute) == value)

    def endpoints(row):
        return tuple(float(row.get(key)) for key in ("x1", "y1", "x2", "y2"))

    def intersects(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b

        def orient(px, py, qx, qy, rx, ry):
            return (qx - px) * (ry - py) - (qy - py) * (rx - px)

        return (
            orient(ax1, ay1, ax2, ay2, bx1, by1)
            * orient(ax1, ay1, ax2, ay2, bx2, by2)
            <= 0
            and orient(bx1, by1, bx2, by2, ax1, ay1)
            * orient(bx1, by1, bx2, by2, ax2, ay2)
            <= 0
        )

    direct_joint = endpoints(
        line_with("data-direct-fitting-joint", "riser_elbow_to_wye")
    )
    upper_tick = endpoints(
        line_with("data-fitting-boundary", "riser_wye_upper")
    )
    outlet_tick = endpoints(
        line_with("data-fitting-boundary", "riser_elbow_outlet_45")
    )

    assert not intersects(upper_tick, direct_joint)
    assert intersects(outlet_tick, direct_joint)

    label = next(
        row
        for row in root.iter("text")
        if row.get("data-fitting-label") == "riser_branch_wye_45"
    )
    assert float(label.get("y")) < direct_joint[3]


def test_fixture_fitting_ticks_do_not_create_false_pipe_spools():
    floor = build_typical_floor_assembly()
    root = ElementTree.fromstring(
        render_typical_floor_assembly_svg(floor, diagnostics=False)
    )

    def line_with(attribute: str, value: str):
        return next(row for row in root.iter("line") if row.get(attribute) == value)

    def endpoints(row):
        return tuple(float(row.get(key)) for key in ("x1", "y1", "x2", "y2"))

    def intersects(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b

        def orient(px, py, qx, qy, rx, ry):
            return (qx - px) * (ry - py) - (qy - py) * (rx - px)

        return (
            orient(ax1, ay1, ax2, ay2, bx1, by1)
            * orient(ax1, ay1, ax2, ay2, bx2, by2)
            <= 0
            and orient(bx1, by1, bx2, by2, ax1, ay1)
            * orient(bx1, by1, bx2, by2, ax2, ay2)
            <= 0
        )

    for fixture in floor.fixtures:
        direct_joint = endpoints(
            line_with("data-direct-fitting-joint", fixture.connection_joint_id)
        )
        upstream_tick = endpoints(
            line_with(
                "data-fitting-boundary", f"{fixture.fixture_id}_wye_upstream"
            )
        )
        outlet_tick = endpoints(
            line_with(
                "data-fitting-boundary", f"{fixture.fixture_id}_elbow_outlet_45"
            )
        )
        assert not intersects(upstream_tick, direct_joint)
        assert intersects(outlet_tick, direct_joint)


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

from math import isclose

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_wastewater_lower_turn_node_pdf
from app.pz.wastewater_drafting import (
    build_lower_turn_cleanout_assembly,
    build_lower_turn_control_sheet_svg,
    render_lower_turn_assembly_svg,
)


def test_lower_turn_is_a_connected_gravity_assembly():
    node = build_lower_turn_cleanout_assembly(system="K1", dn_mm=100)

    assert node.validate() == []
    assert node.flow_segment_ids == ("riser", "diagonal", "main")
    assert [node.segment(row).role for row in node.flow_segment_ids] == [
        "riser",
        "diagonal",
        "main",
    ]
    for upstream, downstream in zip(
        node.flow_segment_ids, node.flow_segment_ids[1:]
    ):
        assert (
            node.segment(upstream).end_port_id
            == node.segment(downstream).start_port_id
        )


def test_service_wye_replaces_second_elbow_and_has_a_capped_end():
    node = build_lower_turn_cleanout_assembly()
    wye = node.fitting("service_wye_45")
    cap = node.port("cleanout_cap")

    assert wye.kind == "wye_45_cleanout"
    assert wye.replaces_kind == "elbow_45"
    assert set(wye.connected_segment_ids) == {
        "diagonal",
        "main",
        "cleanout_access",
    }
    assert node.fitting("cleanout_cap_fitting").kind == "cap"
    assert cap.accessible


def test_cleanout_axis_looks_straight_into_downstream_main():
    node = build_lower_turn_cleanout_assembly()
    access = node.segment("cleanout_access")
    main = node.segment("main")
    a0 = node.port(access.start_port_id).point
    a1 = node.port(access.end_port_id).point
    m0 = node.port(main.start_port_id).point
    m1 = node.port(main.end_port_id).point
    ax, ay = a0.vector_to(a1)
    mx, my = m0.vector_to(m1)

    assert isclose(ax * my - ay * mx, 0.0, abs_tol=1e-9)
    assert ax * mx + ay * my > 0
    assert node.service_path.point_ids == (
        "cleanout_cap",
        "wye_45",
        "main_out",
    )
    assert node.service_path.serviced_segment_ids == ("main",)


def test_builder_rejects_unknown_system_and_bad_dn():
    with pytest.raises(ValueError, match="system must be"):
        build_lower_turn_cleanout_assembly(system="X")
    with pytest.raises(ValueError, match="dn_mm must be positive"):
        build_lower_turn_cleanout_assembly(dn_mm=0)


def test_vector_fragment_contains_physical_parts_and_optional_cable_path():
    node = build_lower_turn_cleanout_assembly()
    normative = render_lower_turn_assembly_svg(node, diagnostics=False)
    diagnostic = render_lower_turn_assembly_svg(node, diagnostics=True)

    for marker in (
        'data-draft-segment="riser"',
        'data-draft-segment="diagonal"',
        'data-draft-segment="main"',
        'data-draft-segment="cleanout_access"',
        'data-fitting="lower_elbow_45"',
        'data-fitting="service_wye_45"',
        'data-fitting="cleanout_cap_fitting"',
        ">Прочистка</text>",
    ):
        assert marker in normative
    assert 'data-service-path="cleanout_cable"' not in normative
    assert 'data-service-path="cleanout_cable"' in diagnostic
    assert "маршрут троса:" in diagnostic
    assert "доступ - тройник - магистраль" in diagnostic


def test_control_sheet_is_a4_landscape_vector_pdf(tmp_path):
    node = build_lower_turn_cleanout_assembly()
    svg = build_lower_turn_control_sheet_svg(node)
    assert 'viewBox="0 0 1123 794"' in svg
    assert svg.count('data-draft-assembly="К1-Узел-НП1"') == 2

    output = tmp_path / "lower-turn.pdf"
    generate_wastewater_lower_turn_node_pdf(str(output))
    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(297.0, abs=0.05)
    assert height_mm == pytest.approx(210.0, abs=0.05)

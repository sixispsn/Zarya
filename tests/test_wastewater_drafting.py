from math import acos, degrees, hypot, isclose

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_wastewater_lower_turn_node_pdf
from app.pz.wastewater_drafting import (
    build_lower_turn_cleanout_assembly,
    build_lower_turn_control_sheet_svg,
    plan_repeated_inline_pipe_label_positions,
    render_inline_pipe_label,
    render_lower_turn_assembly_svg,
    render_repeated_inline_pipe_labels,
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


def test_service_wye_replaces_second_half_elbow_and_has_a_capped_end():
    node = build_lower_turn_cleanout_assembly()
    wye = node.fitting("service_wye_45")
    cap = node.port("cleanout_cap")

    assert wye.kind == "wye_45_cleanout"
    assert wye.replaces_kind == "elbow_45"
    assert len([row for row in node.fittings if row.kind == "elbow_45"]) == 1
    assert set(wye.connected_segment_ids) == {
        "diagonal",
        "main",
        "cleanout_access",
    }
    assert node.fitting("cleanout_cap_fitting").kind == "cap"
    assert cap.accessible


def test_cleanout_axis_is_collinear_with_downstream_main():
    node = build_lower_turn_cleanout_assembly()
    access = node.segment("cleanout_access")
    main = node.segment("main")
    a0 = node.port(access.start_port_id).point
    a1 = node.port(access.end_port_id).point
    m0 = node.port(main.start_port_id).point
    m1 = node.port(main.end_port_id).point
    ax, ay = a0.vector_to(a1)
    mx, my = m0.vector_to(m1)

    dot = ax * mx + ay * my
    angle = degrees(acos(dot / (hypot(ax, ay) * hypot(mx, my))))
    assert isclose(angle, 0.0, abs_tol=1e-9)
    assert dot > 0
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


def test_repeated_line_marks_keep_clear_of_fittings_and_support_k1_k2_k3():
    positions = plan_repeated_inline_pipe_label_positions(
        label="К1 ⌀100",
        start=(0.0, 0.0),
        end=(1000.0, 0.0),
        max_spacing=240.0,
        fitting_points=((500.0, 0.0),),
        fitting_clearance=20.0,
    )

    assert len(positions) == 4
    assert all(abs(position - 0.5) > 0.06 for position in positions)
    assert positions == tuple(sorted(positions))

    for system in ("К1", "К2", "К3"):
        svg = render_repeated_inline_pipe_labels(
            line_id=f"{system}-М1",
            label=f"{system} ⌀100",
            start=(0.0, 0.0),
            end=(1000.0, 0.0),
            max_spacing=240.0,
            fitting_points=((500.0, 0.0),),
            fitting_clearance=20.0,
        )
        assert f'data-repeated-pipe-labels="{system}-М1"' in svg
        assert f'data-inline-pipe-label="{system} ⌀100"' in svg
        assert svg.count('data-pipe-label-mask=') == 4


def test_inline_diameter_mark_is_vector_and_does_not_depend_on_font_glyph():
    svg = render_inline_pipe_label(
        line_id="К1-М1",
        label="К1 ⌀100",
        start=(0.0, 0.0),
        end=(200.0, 0.0),
    )

    assert 'data-inline-pipe-label="К1 ⌀100"' in svg
    assert svg.count('data-vector-diameter-sign="true"') == 1
    assert '<circle ' in svg
    assert '<line ' in svg
    # The symbol remains in metadata for auditing, but is not emitted as a
    # font-dependent text node that macOS Preview can replace with a square.
    assert '>⌀' not in svg


def test_repeated_line_mark_is_omitted_when_clear_run_is_too_short():
    assert render_repeated_inline_pipe_labels(
        line_id="К1-Короткий",
        label="К1 ⌀100",
        start=(0.0, 0.0),
        end=(35.0, 0.0),
    ) == ""


def test_one_fitting_does_not_multiply_marks_on_a_short_line():
    positions = plan_repeated_inline_pipe_label_positions(
        label="К1 ⌀100",
        start=(0.0, 0.0),
        end=(135.0, 0.0),
        max_spacing=240.0,
        font_size=6.2,
        padding=2.0,
        end_clearance=4.0,
        fitting_points=((65.0, 0.0),),
        fitting_clearance=6.0,
    )

    assert len(positions) <= 1


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
    assert normative.count('data-inline-pipe-label="К1 ⌀100"') == 2
    assert 'data-pipe-line-id="К1-Узел-НП1:riser"' in normative
    assert 'data-pipe-line-id="К1-Узел-НП1:main"' in normative
    assert normative.count('data-pipe-label-mask=') == 2
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

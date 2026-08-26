from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from app.pz.generator import generate_wastewater_basement_node_pdf
from app.pz.wastewater_basement_drafting import (
    build_wastewater_basement_assembly,
    build_wastewater_basement_control_svg,
)


def test_basement_path_is_continuous_from_riser_to_outside_wall():
    basement = build_wastewater_basement_assembly()

    assert basement.validate() == []
    assert basement.draft.flow_segment_ids == (
        "riser_above_revision",
        "riser_to_lower_turn",
        "riser",
        "diagonal",
        "main",
        "collector_main",
        "collector_to_sleeve",
        "sleeve_segment",
        "outlet_segment",
    )
    for upstream_id, downstream_id in zip(
        basement.draft.flow_segment_ids,
        basement.draft.flow_segment_ids[1:],
    ):
        upstream = basement.draft.segment(upstream_id)
        downstream = basement.draft.segment(downstream_id)
        assert upstream.end_port_id == downstream.start_port_id


def test_cleanout_services_the_whole_downstream_internal_path():
    basement = build_wastewater_basement_assembly()

    assert basement.draft.service_path.point_ids[-1] == "outlet_end"
    assert basement.draft.service_path.serviced_segment_ids == (
        "main",
        "collector_main",
        "collector_to_sleeve",
        "sleeve_segment",
        "outlet_segment",
    )
    assert basement.lower_turn.fitting("service_wye_45").replaces_kind == "elbow_45"


def test_sleeve_crosses_wall_and_outlet_finishes_outside():
    basement = build_wastewater_basement_assembly()
    sleeve_in = basement.draft.port("sleeve_in").point
    sleeve_out = basement.draft.port("sleeve_out").point
    outlet = basement.draft.port("outlet_end").point

    assert sleeve_in.x_mm == basement.wall_inner_x_mm
    assert sleeve_out.x_mm == basement.wall_outer_x_mm
    assert outlet.x_mm > basement.wall_outer_x_mm
    assert basement.draft.segment("outlet_segment").role == "building_outlet"
    assert not any(
        row.role in {"external_network", "external_manhole"}
        for row in basement.draft.segments
    )


def test_project_elevations_are_blank_until_explicitly_supplied():
    basement = build_wastewater_basement_assembly()
    svg = build_wastewater_basement_control_svg(basement)

    assert basement.basement_floor_elevation_m is None
    assert basement.outlet_invert_elevation_m is None
    assert basement.collector_slope_per_mille is None
    assert basement.missing_project_inputs == (
        "basement_floor_elevation_m",
        "outlet_invert_elevation_m",
        "collector_slope_per_mille",
    )
    assert not basement.project_inputs_complete
    assert "отм. пола ________" in svg
    assert "отм. лотка ________" in svg
    assert 'data-slope-status="required"' in svg
    assert "уклон не задан" in svg

    explicit = build_wastewater_basement_assembly(
        basement_floor_elevation_m=-3.2,
        outlet_invert_elevation_m=-1.75,
        collector_slope_per_mille=20.0,
        outlet_id="К1-7",
    )
    explicit_svg = build_wastewater_basement_control_svg(explicit)
    assert explicit.project_inputs_complete
    assert explicit.missing_project_inputs == ()
    assert "отм. пола -3,200" in explicit_svg
    assert "отм. лотка -1,750" in explicit_svg
    assert 'data-slope-status="confirmed"' in explicit_svg
    assert ">0,020</text>" in explicit_svg
    assert "Выпуск К1-7 DN100" in explicit_svg


def test_basement_builder_rejects_false_geometry_and_small_outlet():
    with pytest.raises(ValueError, match="at least DN100"):
        build_wastewater_basement_assembly(dn_mm=50)
    with pytest.raises(ValueError, match="below the first floor"):
        build_wastewater_basement_assembly(basement_floor_elevation_m=0.0)
    with pytest.raises(ValueError, match="must be positive"):
        build_wastewater_basement_assembly(collector_slope_per_mille=0.0)
    with pytest.raises(ValueError, match="must not be blank"):
        build_wastewater_basement_assembly(outlet_id=" ")


def test_control_svg_contains_architecture_revision_sleeve_and_outlet():
    basement = build_wastewater_basement_assembly()
    svg = build_wastewater_basement_control_svg(basement)
    ElementTree.fromstring(svg)

    for marker in (
        'data-basement-slab="hatched"',
        'data-foundation-wall="true"',
        'data-basement-revision="first-floor"',
        'data-wall-sleeve="true"',
        'data-basement-segment="outlet_segment"',
        'data-basement-slope="collector"',
        'data-label-underline="false"',
        'data-outlet-direction="true"',
        "Выпуск К1-1 DN100",
        "наружная сеть не выдуманы",
    ):
        assert marker in svg


def test_basement_pdf_is_a3_landscape(tmp_path):
    output = tmp_path / "basement.pdf"
    generate_wastewater_basement_node_pdf(str(output))

    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(420.0, abs=0.05)
    assert height_mm == pytest.approx(297.0, abs=0.05)

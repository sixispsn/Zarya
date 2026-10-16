from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.pz.wastewater_fan_drafting import (
    audit_fan_detail_svg, build_fan_detail_svgs, build_roof_detail_graph,
    build_valve_detail_graph, generate_fan_details_pdf,
)
from scripts.build_fan_details import control_fan_details


def test_group_is_one_connected_graph_with_four_real_riser_ports():
    data = control_fan_details()
    data.validate()
    graph = build_roof_detail_graph(data, data.roofs[0])
    graph.validate()
    assert {n.source_id for n in graph.nodes if n.role == "riser_port"} == set(data.evidence.terminals[0].riser_ids)
    assert len([n for n in graph.nodes if n.role == "open_end"]) == 1
    assert len([e for e in graph.edges if e.role == "vent_collector"]) == 3
    assert len(graph.edges) == len(graph.nodes)-1
    assert all("К2" not in n.source_id for n in graph.nodes)


def test_missing_collector_link_cannot_pass_graph_check():
    data = control_fan_details()
    graph = build_roof_detail_graph(data, data.roofs[0])
    broken = replace(graph, edges=tuple(e for e in graph.edges if e.edge_id != "collector:1"))
    with pytest.raises(ValueError, match="disconnected"):
        broken.validate()


@pytest.mark.parametrize("bad_ids", [("К1-Ст1",), ("К1-Ст1", "К2-Ст1", "К1-Ст3", "К1-Ст4")])
def test_incomplete_or_foreign_membership_is_not_drawn(bad_ids):
    data = control_fan_details()
    roof = replace(data.roofs[0], risers=tuple(
        replace(data.roofs[0].risers[i], riser_id=rid) for i, rid in enumerate(bad_ids)
    ))
    with pytest.raises(ValueError, match="membership"):
        build_fan_detail_svgs(replace(data, roofs=(roof,)))


def test_five_risers_are_actually_drawn_not_labelled_as_four():
    data = control_fan_details()
    old = data.evidence.terminals[0]
    new = replace(old, riser_ids=old.riser_ids+("К1-Ст6",))
    extra_riser = replace(data.risers[0], riser_id="К1-Ст6")
    extra_position = replace(data.roofs[0].risers[-1], riser_id="К1-Ст6", x_m=8.5, collector_m=5.02)
    data = replace(data, risers=data.risers+(extra_riser,),
                   evidence=replace(data.evidence, terminals=(new, data.evidence.terminals[1])),
                   roofs=(replace(data.roofs[0], risers=data.roofs[0].risers+(extra_position,)),))
    svg = build_fan_detail_svgs(data)[0]
    assert '5 стояка' in svg
    assert svg.count('data-role="riser_vent"') == 5


def test_unknown_normative_inputs_do_not_create_pdf(tmp_path):
    data = control_fan_details()
    data = replace(data, evidence=replace(data.evidence, terminals=(
        replace(data.evidence.terminals[0], opening_distance_m=None), data.evidence.terminals[1],
    )))
    output = tmp_path / "fan.pdf"
    with pytest.raises(ValueError, match="validation not complete"):
        generate_fan_details_pdf(data, str(output))
    assert not output.exists()


def test_condensate_pocket_and_unspecified_geometry_are_rejected():
    data = control_fan_details()
    d = data.roofs[0]
    low = replace(d.risers[2], collector_m=4.8)
    for bad in (replace(d, source_ref=""), replace(d, risers=d.risers[:2]+(low,)+d.risers[3:])):
        with pytest.raises(ValueError):
            build_fan_detail_svgs(replace(data, roofs=(bad,)))


def test_vent_dimension_changes_with_height_and_has_real_roof_reference():
    data = control_fan_details()
    original = ET.fromstring(build_fan_detail_svgs(data)[0])
    changed = replace(data, evidence=replace(data.evidence, terminals=(
        replace(data.evidence.terminals[0], height_m=3.5), data.evidence.terminals[1],
    )))
    dim1 = next(r for r in original.iter() if r.get("data-dimension") == "vent-above-roof")
    dim2 = next(r for r in ET.fromstring(build_fan_detail_svgs(changed)[0]).iter()
                if r.get("data-dimension") == "vent-above-roof")
    assert dim1.get("data-value-mm") == "3000"
    assert dim2.get("data-value-mm") == "3500"
    assert dim1.get("data-end-y") == dim2.get("data-end-y") == "112"
    assert float(dim1.get("data-start-y"))-float(dim2.get("data-start-y")) == pytest.approx(10)


def test_valve_ends_its_pipe_inside_building_without_open_roof_stub():
    data = control_fan_details()
    graph = build_valve_detail_graph(data, data.valves[0])
    assert {n.role for n in graph.nodes} == {"riser_port", "valve"}
    assert len(graph.edges) == 1
    svg = build_fan_detail_svgs(data)[1]
    assert 'data-normative-ugo="false"' in svg
    assert 'data-ugo="check_valve"' not in svg
    assert 'common_vent' not in svg
    assert 'data-value-mm="350"' in svg
    assert '350 мм - разница' in svg
    changed = replace(data, valves=(replace(data.valves[0], connection_level_m=4.65),))
    assert 'data-value-mm="500"' in build_fan_detail_svgs(changed)[1]
    assert '500 мм - разница' in build_fan_detail_svgs(changed)[1]


@pytest.mark.parametrize("level", [4., 4.15, 6.6, float("nan")])
def test_valve_cannot_be_below_rim_or_through_ceiling(level):
    data = control_fan_details()
    with pytest.raises(ValueError, match="valve must be above"):
        build_fan_detail_svgs(replace(data, valves=(replace(data.valves[0], connection_level_m=level),)))


def test_unavailable_valve_contour_and_missing_detail_fail_explicitly():
    data = control_fan_details()
    with pytest.raises(ValueError, match="unsupported valve contour"):
        build_fan_detail_svgs(replace(data, valves=(replace(data.valves[0], outline_ref="invented"),)))
    with pytest.raises(ValueError, match="exactly one"):
        build_fan_detail_svgs(replace(data, valves=()))


def test_valve_outline_cannot_silently_add_a_reducer_for_another_connection():
    data = control_fan_details()
    with pytest.raises(ValueError, match="110 mm"):
        build_fan_detail_svgs(replace(data, valves=(
            replace(data.valves[0], connection_outer_diameter_mm=50),
        )))


def test_unreadable_scale_is_rejected_instead_of_shrinking_the_text():
    data = control_fan_details()
    with pytest.raises(ValueError, match="fit A3"):
        build_fan_detail_svgs(replace(data, roofs=(replace(data.roofs[0], scale=1),)))


def test_leaders_do_not_overwrite_pipe_or_dimension_lines():
    for svg in build_fan_detail_svgs(control_fan_details()):
        assert audit_fan_detail_svg(svg) == ()
        root = ET.fromstring(svg)
        leader = next(n for n in root.iter() if n.get("data-leader-id"))
        x = float(leader.get("data-text-box-x1")) + 1
        a, b = float(leader.get("data-text-box-y1")), float(leader.get("data-text-box-y2"))
        ET.SubElement(root, "{http://www.w3.org/2000/svg}line", {
            "data-fan-edge": "collision", "x1": str(x), "x2": str(x), "y1": str(a), "y2": str(b),
        })
        assert audit_fan_detail_svg(ET.tostring(root, encoding="unicode"))


def test_pdf_is_two_readable_control_sheets_not_a_building_release(tmp_path):
    path = generate_fan_details_pdf(control_fan_details(), str(tmp_path / "fan.pdf"))
    pages = PdfReader(path).pages
    assert len(pages) == 2
    for page in pages:
        assert float(page.mediabox.width)*25.4/72 == pytest.approx(420, abs=.01)
        assert float(page.mediabox.height)*25.4/72 == pytest.approx(297, abs=.01)
        text = page.extract_text()
        assert "Контроль" in text
        assert "Не является готовым листом ПД" in text
    assert "3000" in pages[0].extract_text()
    assert "350" in pages[1].extract_text()


def test_slope_labels_cannot_be_hidden_under_a_leader():
    root = ET.fromstring(build_fan_detail_svgs(control_fan_details())[0])
    leader = next(r for r in root.iter() if r.get("data-leader-id") == "collector")
    group = next(r for r in root.iter() if r.get("data-condensate-slope"))
    label = next(r for r in group if r.tag.endswith("text"))
    label.set("x", str(float(leader.get("data-text-box-x1"))+10))
    label.set("y", str(float(leader.get("data-text-box-y1"))+5))
    errors = audit_fan_detail_svg(ET.tostring(root, encoding="unicode"))
    assert any("slope label" in error for error in errors)

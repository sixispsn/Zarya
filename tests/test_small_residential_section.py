"""Representative cutaway is a view, not a smaller engineering model."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfReader
import pytest

from app.intake.yaml_io import load_request_file
from app.pz.small_residential_preview import build_small_residential_preview
from app.pz.small_residential_section import (
    audit_individual_fan_section, build_section_projection, build_small_residential_section_svg,
    generate_small_residential_section_pdf,
)
from app.pz.wastewater_basement_profile import basement_profile_from_request


@pytest.fixture
def model():
    req = load_request_file(str(Path(__file__).parents[1]/"demo/residential_2floors_8apartments.yaml"))
    basement = basement_profile_from_request(req, proposed_invert_m=-2.2,
                                             proposed_invert_basis="Предварительный предел по морозу", preview_dn_mm=100)
    return build_small_residential_preview(req, basement=basement, source_ref="Исходные планы", proposed_shafts=4,
                                          branch_outer_mm=50, stack_outer_mm=110, include_roof=True)


def rows(root, attr):
    return [r for r in root.iter() if r.get(attr) is not None]


def test_projection_accounts_for_all_eight_apartments_without_eight_drawings(model):
    projection = build_section_projection(model)
    visible = {a.apartment_id for a in projection.visible_apartments}
    omitted = {source for source, _ in projection.apartment_repeats}
    assert len(visible) == len(omitted) == 4
    assert visible.isdisjoint(omitted)
    assert visible | omitted == {a.apartment_id for a in model.apartments}
    assert {peer for _, peer in projection.apartment_repeats} <= visible
    assert projection.visible_lanes == (0, 3)
    assert projection.lower_repeats == ((1, 3), (2, 3))


def test_different_off_plane_apartment_cannot_be_hidden(model):
    apt = model.apartments[1]
    changed = replace(apt, assembly=replace(apt.assembly,
                      fixtures=(replace(apt.assembly.fixtures[0], quantity=2), *apt.assembly.fixtures[1:])))
    with pytest.raises(ValueError, match="different apartment"):
        build_section_projection(replace(model, apartments=(model.apartments[0], changed, *model.apartments[2:])))


def test_unique_lower_component_cannot_be_hidden_as_identical_repeat(model):
    node = model.lower_nodes[1]
    changed = replace(node, fittings=(replace(node.fittings[0], dn_mm=150), *node.fittings[1:]))
    with pytest.raises(ValueError):
        build_section_projection(replace(model, lower_nodes=(model.lower_nodes[0], changed, *model.lower_nodes[2:])))


def test_fixtures_are_in_rooms_not_a_remote_detail_box(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    assert not rows(root, "data-detail-reference")
    assert not rows(root, "data-typical-apartment-detail")
    assert len(rows(root, "data-section-storey")) == 2
    apartments = rows(root, "data-section-apartment")
    assert len(apartments) == 4
    for apt in apartments:
        assert {r.get("data-kind") for r in rows(apt, "data-floor-fixture")} == {
            "sink", "bath", "washbasin", "toilet",
        }
        assert len(rows(apt, "data-floor-fixture")) == 4
        assert len(rows(apt, "data-diameter-transition-group")) == 1
        assert len(rows(apt, "data-riser-revision")) == 1
    assert len(rows(root, "data-section-room")) == 10


def test_k2_inside_common_zone_and_both_networks_share_the_floor_frame(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    k1 = {r.get("data-k1-stack"): float(r.get("x1")) for r in rows(root, "data-k1-stack")}
    k2 = {r.get("data-k2-stack"): float(r.get("x1")) for r in rows(root, "data-k2-stack")}
    assert k1 == {"1": 219, "4": 371}
    assert min(k1.values()) < min(k2.values()) < max(k2.values()) < max(k1.values())
    for floor in rows(root, "data-section-storey"):
        for x in k2.values():
            assert any(float(z.get("x")) < x < float(z.get("x"))+float(z.get("width"))
                       for z in rows(floor, "data-common-shaft-zone"))
        assert len(rows(floor, "data-floor-boundary")) == 1
    for group in rows(root, "data-lower-system"):
        number = str(int(group.get("data-source-lane"))+1)
        assert float(group.get("data-axis-x")) == (k1 if group.get("data-lower-system") == "K1" else k2)[number]


def test_free_and_passing_maintenance_nodes_and_outlets_survive(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    for system in ("K1", "K2"):
        nodes = [r for r in rows(root, "data-lower-system") if r.get("data-lower-system") == system]
        assert len(nodes) == 2
        assert [rows(n, "data-lower-connection")[0].get("data-accessible-capped-end") for n in nodes] == ["true", "false"]
    crossings = rows(root, "data-nonconnecting-crossing")
    assert {float(c.get("data-crossing-x")) for c in crossings} == {251, 339}
    assert len(rows(root, "data-outlet-sleeve")) == 2
    outlets = {r.get("data-outlet"): float(r.get("x2")) for r in rows(root, "data-outlet")}
    assert outlets["K1"] > 485 and outlets["K2"] < 105


def test_all_maintenance_leaders_point_to_actual_ports(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    leaders = {r.get("data-leader-id"): r for r in rows(root, "data-leader-id")}
    for apt in build_section_projection(model).visible_apartments:
        axis, sign = (219., 1) if apt.lane == 0 else (371., -1)
        fy = 290+(model.basement.basement_floor_m-apt.assembly.floor_elevation_m)*20
        cap = apt.assembly.port("cleanout_cap").point
        expected = axis+sign*(cap.x_mm-313)*.34
        leader = leaders[f"{apt.apartment_id}-cleanout"]
        assert float(leader.get("data-target-x")) == pytest.approx(expected, abs=.001)
        assert float(leader.get("data-target-y")) == pytest.approx(fy+(cap.y_mm-212)*.34, abs=.001)
    for system, axis, sign, node in (("K1", 219., 1, model.lower_nodes[0]),
                                    ("K2", 339., -1, model.roof.lower_nodes[0])):
        leader = leaders[f"{system}-cleanout"]
        placement = next(r for r in rows(root, "data-lower-system")
                         if r.get("data-lower-system") == system and r.get("data-source-lane") == "0")
        scale = float(placement.get("data-node-scale"))
        assert float(leader.get("data-target-x")) == pytest.approx(axis+sign*node.port("cleanout_cap").point.x_mm*scale)
        assert float(leader.get("data-target-y")) == float(placement.get("data-main-y"))
        lo, hi = float(leader.get("data-text-box-x1")), float(leader.get("data-text-box-x2"))
        assert not any(lo <= x <= hi for x in (219, 251, 339, 371))


def test_level_dimensions_and_font_independent_diameters(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    assert len(rows(root, "data-fan-vent")) == 2
    for vent in rows(root, "data-fan-vent"):
        assert float(vent.get("data-roof-y"))-float(vent.get("data-tip-y")) == 4
        assert vent.get("data-height-mm") == "200"
    for rev in rows(root, "data-riser-revision"):
        assert float(rev.get("data-floor-y"))-float(rev.get("data-centre-y")) == 20
    assert not any("⌀" in (r.text or "") for r in root.iter() if r.tag.endswith("text"))
    assert len(rows(root, "data-vector-diameter-sign")) >= 10
    for leader in rows(root, "data-leader-id"):
        assert not rows(leader, "data-pipe-label-mask"), "a diameter label must not erase the leader shelf"
        assert leader.get("data-text-height-mm") == "3.5"


def test_four_independent_vents_are_accounted_for_on_the_same_sheet(model, tmp_path):
    svg = build_small_residential_section_svg(model)
    root = ET.fromstring(svg)
    assert audit_individual_fan_section(model, svg) == ()
    coverage = rows(root, "data-independent-fan-riser")
    assert len(coverage) == 4
    assert all(r.get("data-own-open-end") == "true" for r in coverage)
    assert all(r.get("data-tip-level-m") == "6.8" for r in coverage)
    assert {r.get("data-independent-fan-riser") for r in coverage if r.get("data-visible") == "false"} == {"К1-2", "К1-3"}
    assert not rows(root, "data-section-fan-port")
    assert "сборного трубопровода нет" in svg
    output = generate_small_residential_section_pdf(str(tmp_path / "one-sheet.pdf"), model)
    pages = PdfReader(output).pages
    assert len(pages) == 1
    text = "".join(pages[0].extract_text().split())
    assert "четыресамостоятельныхфановыхвывода" in text
    assert "клисту2" not in text


@pytest.mark.parametrize("change", ["hidden_missing", "hidden_merged", "visible_missing", "wrong_height", "cut_pipe", "shared", "reference"])
def test_one_sheet_fan_guard_catches_lost_endings_or_automatic_group(model, change):
    root = ET.fromstring(build_small_residential_section_svg(model))
    if change == "hidden_missing":
        rows(root, "data-independent-fan-riser")[1].attrib.pop("data-independent-fan-riser")
    elif change == "hidden_merged":
        rows(root, "data-independent-fan-riser")[1].set("data-own-open-end", "false")
    elif change == "visible_missing":
        rows(root, "data-fan-vent")[0].attrib.pop("data-fan-vent")
    elif change == "wrong_height":
        rows(root, "data-fan-vent")[0].set("data-height-mm", "3000")
    elif change == "cut_pipe":
        rows(root, "data-k1-stack")[0].set("y1", "120")
    elif change == "shared":
        ET.SubElement(root, "line", {"data-role": "vent_collector"})
    else:
        ET.SubElement(root, "g", {"data-section-fan-port": "К1-1"})
    assert audit_individual_fan_section(model, ET.tostring(root, encoding="unicode"))


def test_projected_crossing_avoids_revision_and_bend(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    # Derive the collision envelope from this view rather than retaining old
    # low-level collector pixel positions after moving the pipes overhead.
    main1 = float(next(r for r in rows(root, "data-lower-system")
                       if r.get("data-lower-system") == "K1").get("data-main-y"))
    for group in rows(root, "data-lower-system"):
        if group.get("data-lower-system") == "K2":
            riser = rows(group, "data-draft-segment")[0]
            assert float(next(iter(riser)).get("y2")) > main1+2.25+.3


def test_suspended_mains_are_separate_from_outlet_elevations(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    ceiling = next(r for r in rows(root, "data-basement-slab") if r.get("data-basement-slab") == "ceiling")
    underside = float(ceiling.get("y"))+float(ceiling.get("height"))
    for group in rows(root, "data-lower-system"):
        assert underside < float(group.get("data-main-y")) <= underside+20
    for main in rows(root, "data-projected-main"):
        assert main.get("data-placement") == "suspended"
        assert main.get("data-invert-status") == "requires_confirmation"
        assert main.get("data-grade-status") == "requires_inputs"
    profiles = rows(root, "data-collector-profile")
    assert len(profiles) == 2
    assert all(p.get("data-end-invert") == "unknown" for p in profiles)
    assert all(p.get("data-clearance-status") == "requires_inputs" for p in profiles)
    changed = replace(model, basement=replace(model.basement, proposed_invert_m=-2.4))
    other = ET.fromstring(build_small_residential_section_svg(changed))
    assert [n.get("data-main-y") for n in rows(root, "data-lower-system")] == [
        n.get("data-main-y") for n in rows(other, "data-lower-system")]
    outlet = next(r for r in rows(root, "data-outlet") if r.get("data-outlet") == "K1")
    shifted = next(r for r in rows(other, "data-outlet") if r.get("data-outlet") == "K1")
    assert float(shifted.get("y2"))-float(outlet.get("y2")) == pytest.approx(4)


def test_drops_are_continuous_downward_and_revisions_cannot_float(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    assert len(rows(root, "data-outlet-drop")) == 2
    for drop in rows(root, "data-outlet-drop"):
        segments = rows(drop, "data-drop-segment")
        assert len(segments) == 5
        for a, b in zip(segments, segments[1:]):
            assert a.get("x2") == b.get("x1") and a.get("y2") == b.get("y1")
        assert all(float(s.get("y2")) >= float(s.get("y1")) for s in segments)
        assert len(rows(drop, "data-fitting")) == 6  # two pairs of directly joined 45° elbows
        assert not rows(drop, "data-accessible-capped-end")
        revision = rows(drop, "data-drop-revision")[0]
        assert float(drop.get("data-top-y"))+5 < float(revision.get("data-centre-y"))
        assert float(revision.get("data-centre-y")) < float(drop.get("data-bottom-y"))-5
        assert revision.get("data-mounting-height-status") == "requires_confirmation"
    # Revisions on K2 risers now stand above their offset, on the first floor.
    floor_revisions = rows(root, "data-riser-revision")
    assert len(floor_revisions) == 6
    assert all(float(r.get("data-floor-y")) <= 228 for r in floor_revisions)


def test_drop_too_short_for_revision_fails_instead_of_drawing_an_orphan(model):
    shallow = replace(model, basement=replace(model.basement, proposed_invert_m=-1.6))
    with pytest.raises(ValueError, match="room for the elbows"):
        build_small_residential_section_svg(shallow)


def test_projection_never_changes_counts_flows_or_release_status(model):
    before = deepcopy(model)
    edges1, edges2 = model.flow_edges(), model.roof.flow_edges()
    build_small_residential_section_svg(model)
    assert model == before
    assert model.flow_edges() == edges1 and model.roof.flow_edges() == edges2
    assert len(model.apartments) == 8
    assert sum(len(a.assembly.fixtures) for a in model.apartments) == 32
    assert {n for e in edges1 for n in e}.isdisjoint({n for e in edges2 for n in e})
    assert not model.release_ready


def test_a2_pdf_declares_omissions_and_is_not_a_release_claim(model, tmp_path):
    target = tmp_path/"section.pdf"
    generate_small_residential_section_pdf(str(target), model)
    pdf = PdfReader(target)
    assert len(pdf.pages) == 1
    page = pdf.pages[0]
    assert float(page.mediabox.width) == pytest.approx(594*72/25.4)
    assert float(page.mediabox.height) == pytest.approx(420*72/25.4)
    text = "".join(page.extract_text().split())
    for value in ("условномразрезе", "Кухня", "Санузел", "ВыпускК1", "ВыпускК2", "32прибора", "внеплоскостиразреза", "не готовый ИОС3"):
        assert "".join(value.split()) in text
    assert "ФрагментА" not in text

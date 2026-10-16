"""Proposed lengths must not become measured AR or a hydraulic pass."""
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.intake.yaml_io import load_request_file
from app.pz.small_residential_basement_proposal import educational_basement_proposal
from app.pz.small_residential_preview import build_small_residential_preview
from app.pz.small_residential_section import (
    audit_basement_proposal_section, build_small_residential_section_svg, generate_small_residential_section_pdf,
)
from app.pz.wastewater_basement_profile import basement_profile_from_request


@pytest.fixture
def model():
    req = load_request_file(str(Path(__file__).parents[1]/"demo/residential_2floors_8apartments.yaml"))
    basement = basement_profile_from_request(req, proposed_invert_m=-2.2,
                                            proposed_invert_basis="Предварительная граница", preview_dn_mm=100)
    return build_small_residential_preview(req, basement=basement, source_ref="Планы этажей, не подвала",
                                          proposed_shafts=4, branch_outer_mm=50, stack_outer_mm=110, include_roof=True)


def rows(root, attr):
    return [r for r in root.iter() if r.get(attr) is not None]


def test_proposed_geometry_uses_exact_bore_and_finite_envelopes(model):
    p = educational_basement_proposal(model)
    assert p.k1.end_invert_m == pytest.approx(-.98)
    assert p.k1.passage_height_m(-3.1) == pytest.approx(2.0873)
    assert p.k1.ceiling_clearance_m(-.3) == pytest.approx(.3727)
    assert p.k1.drop_height_m(-2.2) == pytest.approx(1.22)
    assert p.axis_at(0)-p.invert_at(0) == pytest.approx(.0523)
    assert all(p.invert_at(a) > p.invert_at(b) for a, b in zip(p.junction_chainages_m, p.junction_chainages_m[1:]))


@pytest.mark.parametrize("stations", [(0, 1), (0, 3, 2, 7), (0, 3, 5, 10), (0, 3, 5, float("nan"))])
def test_invalid_or_missing_off_plane_stations_rejected(model, stations):
    with pytest.raises(ValueError, match="chainages"):
        replace(educational_basement_proposal(model), junction_chainages_m=stations).validate(model)


@pytest.mark.parametrize("change", ["long", "ceiling", "catalogue", "source", "reversed_drop"])
def test_bad_proposal_cannot_generate_an_apparently_valid_scheme(model, change):
    p = educational_basement_proposal(model)
    if change == "long":
        p = replace(p, k1=replace(p.k1, length_m=30))
    elif change == "ceiling":
        p = replace(p, k1=replace(p.k1, start_invert_m=-.4))
    elif change == "catalogue":
        p = replace(p, k1=replace(p.k1, outer_diameter_mm=160))
    elif change == "source":
        p = replace(p, source="")
    else:
        model = replace(model, basement=replace(model.basement, proposed_invert_m=-.9))
    with pytest.raises(ValueError):
        build_small_residential_section_svg(model, basement_proposal=p)


def test_drawn_nodes_and_outlet_axis_are_bound_to_proposal_not_page_defaults(model):
    p = educational_basement_proposal(model)
    root = ET.fromstring(build_small_residential_section_svg(model, basement_proposal=p))
    assert len(rows(root, "data-proposed-k1-station")) == 4
    assert root.get("data-release-ready") == "false"
    for node in rows(root, "data-lower-system"):
        if node.get("data-lower-system") != "K1":
            continue
        lane = int(node.get("data-source-lane"))
        axis = p.axis_at(p.junction_chainages_m[lane])
        assert float(node.get("data-main-y")) == pytest.approx(290+(-3.1-axis)*20)
        lower = rows(node, "data-lower-connection")[0]
        assert lower.get("data-accessible-capped-end") == ("true" if lane == 0 else "false")
    end = next(r for r in rows(root, "data-outlet") if r.get("data-outlet") == "K1")
    assert float(end.get("y2")) == pytest.approx(290+(-3.1-(-2.2+.0523))*20)
    profile = rows(root, "data-collector-profile")[0]
    assert float(profile.get("data-min-passage-m")) == pytest.approx(2.0873)
    assert profile.get("data-clearance-status") == "proposal_only"
    k2 = rows(root, "data-collector-profile")[1]
    assert k2.get("data-end-invert") == "unknown"
    assert k2.get("data-clearance-status") == "requires_inputs"
    assert rows(root, "data-proposal-slope")[0].get("data-sign-shape") == "acute-angle"


def test_proposed_export_keeps_one_sheet_and_explicit_missing_inputs(model, tmp_path):
    target = tmp_path / "basement.pdf"
    original = build_small_residential_section_svg(model)
    generate_small_residential_section_pdf(str(target), model, basement_proposal=educational_basement_proposal(model))
    reader = PdfReader(target)
    assert len(reader.pages) == 1
    text = "".join(reader.pages[0].extract_text().split())
    assert "проход2,09м" in text and "безпланаАР" in text
    assert "гидравликойнеподтверждены" in text and "К1/К2раздельны" in text
    assert original == build_small_residential_section_svg(model)


def test_cap_leader_targets_follow_rescaled_lower_fittings(model):
    root = ET.fromstring(build_small_residential_section_svg(model, basement_proposal=educational_basement_proposal(model)))
    node = next(n for n in rows(root, "data-lower-system") if n.get("data-lower-system") == "K1")
    leader = next(n for n in rows(root, "data-leader-id") if n.get("data-leader-id") == "K1-cleanout")
    port = model.lower_nodes[0].port("cleanout_cap").point
    assert float(leader.get("data-target-x")) == pytest.approx(219+port.x_mm*float(node.get("data-node-scale")))
    assert float(leader.get("data-target-y")) == float(node.get("data-main-y"))


@pytest.mark.parametrize("change", ["missing_cap", "passing_cap", "leader", "level", "hidden", "release"])
def test_export_guard_catches_regressions_in_composed_basement(model, change):
    p = educational_basement_proposal(model)
    svg = build_small_residential_section_svg(model, basement_proposal=p)
    assert not audit_basement_proposal_section(model, p, svg)
    root = ET.fromstring(svg)
    if change == "missing_cap":
        node = rows(root, "data-lower-system")[0]
        next(r for r in node.iter() if r.get("data-fitting") == "cleanout_cap_fitting").attrib.pop("data-fitting")
    elif change == "passing_cap":
        n = next(r for r in rows(root, "data-lower-system") if r.get("data-source-lane") == "3")
        ET.SubElement(n, "path", {"data-fitting": "cleanout_cap_fitting"})
    elif change == "leader":
        n = next(r for r in rows(root, "data-leader-id") if r.get("data-leader-id") == "K1-cleanout")
        n.set("data-target-y", "290")
    elif change == "level":
        rows(root, "data-lower-system")[0].set("data-main-y", "300")
    elif change == "hidden":
        rows(root, "data-proposed-k1-station")[1].attrib.pop("data-proposed-k1-station")
    else:
        root.set("data-release-ready", "true")
    assert audit_basement_proposal_section(model, p, ET.tostring(root, encoding="unicode"))

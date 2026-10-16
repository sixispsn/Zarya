"""Single-sheet projection must simplify repetition, never network topology."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
from xml.etree import ElementTree as ET

from pypdf import PdfReader
import pytest

from app.intake.yaml_io import load_request_file
from app.pz.small_residential_preview import build_small_residential_preview
from app.pz.small_residential_combined import (
    apartment_references, build_small_residential_combined_svg, generate_small_residential_combined_pdf,
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


def test_references_cover_every_apartment_and_all_32_fixture_ids(model):
    refs = apartment_references(model)
    assert len(refs) == 8
    assert {r.apartment_id for r in refs} == {a.apartment_id for a in model.apartments}
    ids = [fid for r in refs for fid in r.fixture_ids]
    assert len(set(ids)) == len(ids) == 32
    assert {r.detail_id for r in refs} == {"A"}
    for r, a in zip(refs, model.apartments):
        assert r.stack_id == a.stack_id
        assert r.floor_number == a.floor_number


def test_different_apartment_configuration_cannot_be_collapsed_into_a(model):
    apt = model.apartments[-1]
    fixtures = (replace(apt.assembly.fixtures[0], quantity=2), *apt.assembly.fixtures[1:])
    changed = replace(apt, assembly=replace(apt.assembly, fixtures=fixtures))
    m = replace(model, apartments=(*model.apartments[:-1], changed))
    with pytest.raises(ValueError, match="non-identical branch"):
        apartment_references(m)


def test_missing_roof_does_not_silently_create_combined_k2(model):
    with pytest.raises(ValueError, match="confirmed roof"):
        build_small_residential_combined_svg(replace(model, roof=None))


def test_main_view_references_do_not_leak_complete_fixture_geometry(model):
    root = ET.fromstring(build_small_residential_combined_svg(model))
    assert len(rows(root, "data-apartment-reference")) == 8
    assert len(rows(root, "data-detail-reference")) == 8
    assert len(rows(root, "data-typical-apartment-detail")) == 1
    assert len(rows(root, "data-floor-fixture")) == 4
    assert len(rows(root, "data-diameter-transition-group")) == 1
    for apt in rows(root, "data-apartment-reference"):
        assert not rows(apt, "data-floor-fixture")
        assert {r.get("data-floor-segment") for r in rows(apt, "data-floor-segment")} == {"collector_to_riser"}
        assert {r.get("data-direct-fitting-joint") for r in rows(apt, "data-direct-fitting-joint")} == {"riser_elbow_to_wye"}
        assert {r.get("data-floor-fitting") for r in rows(apt, "data-floor-fitting")} == {
            "riser_branch_elbow_45", "riser_branch_wye_45",
        }


def test_all_networks_and_maintenance_nodes_survive_on_one_sheet(model):
    root = ET.fromstring(build_small_residential_combined_svg(model))
    assert len(rows(root, "data-k1-stack")) == len(rows(root, "data-k2-stack")) == 4
    assert len([r for r in rows(root, "data-ugo") if r.get("data-ugo") == "roof_funnel"]) == 4
    assert len(rows(root, "data-riser-revision")) == 8
    assert len(rows(root, "data-k2-revision")) == 4
    assert len(rows(root, "data-fan-vent")) == 4
    for v in rows(root, "data-fan-vent"):
        assert float(v.get("data-roof-y"))-float(v.get("data-tip-y")) == 4
    lower = rows(root, "data-lower-system")
    assert len(lower) == 8
    for system in ("K1", "K2"):
        nodes = [g for g in lower if g.get("data-lower-system") == system]
        assert [rows(g, "data-lower-connection")[0].get("data-accessible-capped-end") for g in nodes] == [
            "true", "false", "false", "false",
        ]


def test_axes_match_lower_nodes_and_outlets_are_separate_outside_walls(model):
    root = ET.fromstring(build_small_residential_combined_svg(model))
    k1 = {r.get("data-k1-stack"): float(r.get("x1")) for r in rows(root, "data-k1-stack")}
    k2 = {r.get("data-k2-stack"): float(r.get("x1")) for r in rows(root, "data-k2-stack")}
    for g in rows(root, "data-lower-system"):
        axes = k1 if g.get("data-lower-system") == "K1" else k2
        axis = axes[str(int(g.get("data-lane"))+1)]
        assert float(g.get("data-axis-x")) == axis
        riser = next(r for r in g.iter() if r.get("data-draft-segment") == "riser")
        assert float(next(iter(riser)).get("x1")) == axis
        if g.get("data-lower-system") == "K1":
            assert g.get("transform") == f"translate({2*axis:g} 0) scale(-1 1)"
    for apt in rows(root, "data-apartment-connection"):
        assert float(apt.get("data-stack-x")) in k1.values()
    # Entire K1 route goes left of the K2 route, without any crossing masks.
    assert max(k1.values()) < min(k2.values())
    left, right = sorted(float(w.get("x")) for w in rows(root, "data-building-wall"))
    assert float(rows(root, "data-k1-outlet")[0].get("x2")) < left
    assert float(rows(root, "data-k2-outlet")[0].get("x2")) > right+4


def test_compaction_is_presentation_only_and_does_not_change_graphs(model):
    before = deepcopy(model)
    k1, k2 = model.flow_edges(), model.roof.flow_edges()
    build_small_residential_combined_svg(model)
    assert model == before
    assert model.flow_edges() == k1
    assert model.roof.flow_edges() == k2
    assert {n for e in k1 for n in e}.isdisjoint({n for e in k2 for n in e})
    assert not model.release_ready


def test_cleanout_leaders_point_to_actual_caps_after_paper_mirroring(model):
    root = ET.fromstring(build_small_residential_combined_svg(model))
    leaders = {r.get("data-leader-id"): r for r in rows(root, "data-leader-id")}
    first = {g.get("data-lower-system"): g for g in rows(root, "data-lower-system") if g.get("data-lane") == "0"}
    for system, node, direction in (("K1", model.lower_nodes[0], -1), ("K2", model.roof.lower_nodes[0], 1)):
        axis = float(first[system].get("data-axis-x"))
        expected = axis+direction*node.port("cleanout_cap").point.x_mm*.22
        leader = leaders[f"{system}-cleanout"]
        assert float(leader.get("data-target-x")) == pytest.approx(expected)
        assert leader.get("data-arrow-kind") == "closed-filled"
        assert leader.get("data-line-width-mm") == "0.25"
        # Leader title/detail must stay off every vertical riser in the basement.
        lo, hi = float(leader.get("data-text-box-x1")), float(leader.get("data-text-box-x2"))
        axes = [float(g.get("data-axis-x")) for g in rows(root, "data-lower-system")]
        assert not any(lo <= x <= hi for x in axes)


def test_single_a2_pdf_and_vector_diameters(model, tmp_path):
    root = ET.fromstring(build_small_residential_combined_svg(model))
    assert not any("⌀" in (r.text or "") for r in root.iter() if r.tag.endswith("text"))
    assert len(rows(root, "data-vector-diameter-sign")) >= 16
    target = tmp_path/"combined.pdf"
    generate_small_residential_combined_pdf(str(target), model)
    reader = PdfReader(target)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(594*72/25.4)
    assert float(page.mediabox.height) == pytest.approx(420*72/25.4)
    text = re.sub(r"\s+", "", page.extract_text())
    for expected in ("Фрагмент А", "Выпуск К1", "Выпуск К2", "Квартира 8", "Квартира 1", "Фановый стояк", "200"):
        assert re.sub(r"\s+", "", expected) in text

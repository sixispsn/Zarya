"""Coverage and continuity of the two-floor composition, without release bypass."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.intake.project_builder import RequestValidationError, build_project
from app.intake.yaml_io import load_request_file
from app.pz.small_residential_preview import (
    build_small_residential_preview, build_small_residential_svg, generate_small_residential_pdf,
)
from app.pz.wastewater_basement_profile import basement_profile_from_request
from app.pz.wastewater_drafting import build_lower_turn_cleanout_assembly
from app.pz.small_residential_rainwater import build_small_residential_k2_svg, FUNNEL_OUTLET_ANCHOR


EXAMPLE = Path(__file__).parents[1] / "demo/residential_2floors_8apartments.yaml"


def request():
    return load_request_file(str(EXAMPLE))


def model(req=None, **kwargs):
    req = req or request()
    basement = basement_profile_from_request(
        req, proposed_invert_m=-2.2, proposed_invert_basis="Предварительный предел по морозу.", preview_dn_mm=100,
    )
    values = dict(basement=basement, source_ref="Планы двух этажей, ручное чтение, разводка предлагается.",
                  proposed_shafts=4, branch_outer_mm=50, stack_outer_mm=110)
    return build_small_residential_preview(req, **(values | kwargs))


def elements(root, attribute):
    return [row for row in root.iter() if row.get(attribute) is not None]


def test_all_eight_apartments_and_32_fixtures_come_from_room_programme():
    m = model()
    assert len(m.apartments) == len(m.programme.apartments) == 8
    assert len(m.programme.fixtures_for_system("K1")) == 32
    assert len(m.lower_nodes) == 4
    assert {a.floor_number for a in m.apartments} == {1, 2}
    for lane in range(4):
        pair = [a for a in m.apartments if a.lane == lane]
        assert len(pair) == 2
        assert len({a.stack_id for a in pair}) == 1
        assert {a.assembly.floor_elevation_m for a in pair} == {0, 3.3}
        for apt in pair:
            f = apt.assembly
            assert not f.validate()
            assert [row.kind for row in f.fixtures] == ["sink", "bath", "washbasin", "toilet"]
            assert [row.dn_mm for row in f.fixtures] == [50, 50, 50, 100]
            assert all(row.quantity == 1 for row in f.fixtures)
    assert m.programme.requires_confirmation


def test_each_fixture_reaches_the_single_outlet_without_cycles_or_dead_ends():
    m = model()
    graph = {}
    for source, target in m.flow_edges():
        graph.setdefault(source, []).append(target)
    starts = [a.apartment_id + ":" + f.fixture_outlet_port_id
              for a in m.apartments for f in a.assembly.fixtures]
    assert len(set(starts)) == 32
    for source in starts:
        node, seen = source, set()
        while node != "outlet":
            assert node not in seen
            seen.add(node)
            assert len(graph[node]) == 1
            node = graph[node][0]
        assert any(n.startswith("base-") for n in seen)


def test_only_first_basement_node_has_a_capped_free_end():
    m = model()
    assert [n.service_path is not None for n in m.lower_nodes] == [True, False, False, False]
    invalid = replace(m, lower_nodes=(m.lower_nodes[0], build_lower_turn_cleanout_assembly(), *m.lower_nodes[2:]))
    with pytest.raises(ValueError, match="only the first free"):
        invalid.validate()
    for n in m.lower_nodes[1:]:
        assert n.port("main_in")
        assert not any(s.role == "cleanout_access" for s in n.segments)


def test_preview_does_not_invent_confirmed_project_data_or_change_request():
    req = request()
    before = deepcopy(req)
    m = model(req)
    build_small_residential_svg(m)
    assert req == before
    assert req.sewer_pipes == req.sewer_first_manholes == []
    assert not m.release_ready
    assert m.branch_pipe.inner_diameter_mm == 46.4
    assert m.stack_pipe.inner_diameter_mm == 104.6
    with pytest.raises(RequestValidationError):
        build_project(req)


@pytest.mark.parametrize("change,kwargs", [
    ({"apartments_by_floor": {1: 3, 2: 5}}, {}),
    ({"floors": 3}, {}),
    ({"floor_elevations_m": {-1: -3.1, 1: 0}}, {}),
    ({}, {"stack_outer_mm": 100}),
    ({}, {"proposed_shafts": 2}),
])
def test_unknown_levels_or_different_plan_cannot_silently_use_this_layout(change, kwargs):
    with pytest.raises(ValueError):
        model(replace(request(), **change), **kwargs)


def test_complete_graphic_coverage_including_reducers_and_traps():
    root = ET.fromstring(build_small_residential_svg(model()))
    assert root.get("data-release-ready") == "false"
    assert len(elements(root, "data-apartment")) == 8
    assert len(elements(root, "data-preview-room")) == 16
    assert len(elements(root, "data-floor-fixture")) == 32
    ugos = elements(root, "data-ugo")
    assert sum(r.get("data-ugo") == "trap" for r in ugos) == 24
    assert sum(r.get("data-ugo") == "toilet" for r in ugos) == 8
    assert len(elements(root, "data-riser-revision")) == 8
    transitions = elements(root, "data-diameter-transition-group")
    assert len(transitions) == 8  # Presentation filtering must never drop reducers.
    assert all(r.get("data-flat-side") == "downstream" for r in transitions)
    assert all("toilet" in r.get("data-adjacent-fitting") for r in transitions)
    assert all(r.get("fill") == "none" for r in elements(root, "data-diameter-transition"))
    lower = elements(root, "data-lower-connection")
    assert [r.get("data-accessible-capped-end") for r in lower] == ["true", "false", "false", "false"]
    assert len(elements(root, "data-floor-cleanout-leader")) == 8
    assert len(elements(root, "data-building-outlet")) == 1
    assert not elements(root, "data-slope-marker")  # Layout slopes are not design results.
    assert "не определены" in "".join(root.itertext())


def test_pipes_meet_the_same_stack_axis_on_floors_and_in_basement():
    m = model()
    root = ET.fromstring(build_small_residential_svg(m))
    axes = {r.get("data-stack-axis"): float(r.get("x1")) for r in elements(root, "data-stack-axis")}
    placements = {r.get("data-apartment-pipework"): r for r in elements(root, "data-apartment-pipework")}
    for apt in m.apartments:
        g = placements[apt.apartment_id]
        tx, ty, scale = map(float, re.findall(r"[-+]?\d+(?:\.\d+)?", g.get("transform")))
        assert tx + apt.assembly.port("riser_join").point.x_mm * scale == pytest.approx(axes[apt.stack_id])
        assert float(g.get("data-stack-x")) == axes[apt.stack_id]
    for g, axis in zip(elements(root, "data-draft-assembly"), axes.values()):
        riser = next(r for r in g.iter() if r.get("data-draft-segment") == "riser")
        line = next(iter(riser))
        assert float(line.get("x1")) == axis
    outlet = elements(root, "data-building-outlet")[0]
    wall = elements(root, "data-preview-wall")[0]
    assert float(outlet.get("x2")) > float(wall.get("x")) + float(wall.get("width"))


def test_levels_and_revision_dimensions_are_not_fixed_pixel_labels():
    req = request()
    changed = replace(req, floor_elevations_m={-1: -3.1, 1: 0, 2: 3.6})
    root = ET.fromstring(build_small_residential_svg(model(changed)))
    boundaries = {int(r.get("data-floor-boundary")): float(r.get("y1"))
                  for r in elements(root, "data-floor-boundary")}
    assert boundaries[1] - boundaries[2] == pytest.approx(3.6 * 20)
    for r in elements(root, "data-riser-revision"):
        assert float(r.get("data-floor-y")) - float(r.get("data-centre-y")) == 20
        numbers = [t for t in r.iter() if t.text == "1000"]
        assert numbers[0].get("data-paper-text-height-mm") == "3.5"
        assert numbers[0].get("transform").startswith("rotate(-90 ")


def test_diameter_signs_are_vector_not_font_dependent_and_pdf_is_a2(tmp_path):
    m = model()
    root = ET.fromstring(build_small_residential_svg(m))
    assert len(elements(root, "data-vector-diameter-sign")) == 27  # three/apartment + three mains
    assert not any("⌀" in (r.text or "") for r in root.iter() if r.tag.endswith("text"))
    path = tmp_path / "residential.pdf"
    generate_small_residential_pdf(str(path), m)
    reader = PdfReader(path)
    assert len(reader.pages) == 1
    p = reader.pages[0]
    assert float(p.mediabox.width) == pytest.approx(594*72/25.4)
    assert float(p.mediabox.height) == pytest.approx(420*72/25.4)
    text = p.extract_text()
    for value in ("Квартира 1", "Квартира 8", "Подвал", "Прочистка", "+3,30", "-3,10", "-2,20"):
        # Cairo embeds individual positioned glyphs; PDF extraction can omit spaces.
        assert re.sub(r"\s+", "", value) in re.sub(r"\s+", "", text)


def test_roof_has_four_funnels_outside_apartments_and_separate_k2_outlet():
    m = model(include_roof=True)
    roof = m.roof
    assert roof.elevation_m == 6.6
    assert roof.vent_height_m == .2
    k1_nodes = {n for e in m.flow_edges() for n in e}
    k2_nodes = {n for e in roof.flow_edges() for n in e}
    assert k1_nodes.isdisjoint(k2_nodes)
    assert [n.service_path is not None for n in roof.lower_nodes] == [True, False, False, False]
    graph = dict(roof.flow_edges())
    for n in range(1, 5):
        current, seen = f"K2:funnel-{n}", set()
        while current != "K2:outlet":
            assert current not in seen
            seen.add(current)
            current = graph[current]
    assert all(9 < x < 12 and 3 < y < 6 for x, y in roof.funnel_positions_m)
    # Four proposed locations do not imply four calculated catchment areas.
    assert request().storm_roof_area_m2 == 0
    assert request().sewer_pipes == []


@pytest.mark.parametrize("changes", [
    {"wastewater_roof_kind": "unknown"},
    {"wastewater_roof_kind": "flat_accessible"},
    {"wastewater_roof_relative_elevation_m": None},
    {"wastewater_roof_relative_elevation_m": 3.3},
    {"storm_funnels_count": 3},
])
def test_roof_preview_never_guesses_missing_or_different_roof_inputs(changes):
    with pytest.raises(ValueError):
        model(replace(request(), **changes), include_roof=True)


def test_k2_rejects_apartment_positions_and_blocked_through_junctions():
    m = model(include_roof=True)
    for roof in (
        replace(m.roof, placement_zone="apartment"),
        replace(m.roof, funnel_positions_m=((4, 4), *m.roof.funnel_positions_m[1:])),
        replace(m.roof, lower_nodes=(m.roof.lower_nodes[0], m.roof.lower_nodes[0], *m.roof.lower_nodes[2:])),
        replace(m.roof, lower_nodes=(m.lower_nodes[0], *m.roof.lower_nodes[1:])),
    ):
        with pytest.raises(ValueError):
            replace(m, roof=roof).validate()


def test_each_fan_vent_has_connected_leader_and_actual_200_mm_dimension():
    root = ET.fromstring(build_small_residential_svg(model(include_roof=True)))
    vents = elements(root, "data-fan-vent")
    axes = {r.get("data-stack-axis"): r for r in elements(root, "data-stack-axis")}
    assert len(vents) == 4
    for vent in vents:
        roof_y, tip_y = float(vent.get("data-roof-y")), float(vent.get("data-tip-y"))
        assert roof_y-tip_y == pytest.approx(.2*20)
        assert float(axes[vent.get("data-fan-vent")].get("y1")) == tip_y
        assert len(elements(vent, "data-vent-dimension-line")) == 1
        assert any(t.text == "Фановый стояк" for t in vent.iter())
        assert any(t.text == "200" and t.get("data-paper-text-height-mm") == "3.5" for t in vent.iter())
    assert not any("⌀" in (r.text or "") for r in root.iter() if r.tag.endswith("text"))


def test_k2_drawing_has_all_funnels_revisions_and_only_one_free_end_cleanout():
    m = model(include_roof=True)
    root = ET.fromstring(build_small_residential_k2_svg(m))
    assert len([r for r in elements(root, "data-ugo") if r.get("data-ugo") == "roof_funnel"]) == 4
    assert len(elements(root, "data-k2-riser")) == len(elements(root, "data-k2-revision")) == 4
    assert len(elements(root, "data-funnel-plan-position")) == 4
    assert len(elements(root, "data-k2-building-outlet")) == 1
    assert root.get("data-route-elevations") == "unknown"
    assert not elements(root, "data-slope-marker")
    assert not elements(root, "data-diameter-transition")
    lower = elements(root, "data-lower-connection")
    assert [r.get("data-accessible-capped-end") for r in lower] == ["true", "false", "false", "false"]
    assert FUNNEL_OUTLET_ANCHOR[0] == pytest.approx(4662*.008192524322-38.197644649258)
    assert FUNNEL_OUTLET_ANCHOR[1] == pytest.approx(-3045*.008192524322+47.725550435228)
    for revision in elements(root, "data-k2-revision"):
        assert float(revision.get("data-floor-y"))-float(revision.get("data-centre-y")) == 20


def test_roof_variant_outputs_two_separate_a2_sheets_and_preserves_k1(tmp_path):
    m = model(include_roof=True)
    path = tmp_path / "K1_K2.pdf"
    generate_small_residential_pdf(str(path), m)
    reader = PdfReader(path)
    assert len(reader.pages) == 2
    for p in reader.pages:
        assert float(p.mediabox.width) == pytest.approx(594*72/25.4)
        assert float(p.mediabox.height) == pytest.approx(420*72/25.4)
    first, second = (re.sub(r"\s+", "", p.extract_text()) for p in reader.pages)
    assert "Квартира8" in first and "Фановыйстояк" in first
    assert "ВоронкаК2-Вр4" in second and "ВыпускК2" in second
    assert "Лотокуточнить" in second
    assert "Квартира" not in second

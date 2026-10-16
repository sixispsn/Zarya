"""The new plan is a proposal, not a copy of the first house's calculations."""
from dataclasses import replace
import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
import pytest

import app.architecture.residential_plan_study as module
from app.architecture.residential_plan_study import load_plan_study
from app.pz.residential_plan_study_pdf import StudySheet, generate_plan_study_pdf

DATA = Path(__file__).parents[1]/"demo/residential_second_layout.study.json"


@pytest.fixture
def study():
    return load_plan_study(DATA)


@pytest.fixture
def source(tmp_path):
    path = tmp_path/"1677505735_list-1.jpg"
    Image.new("RGB", (1500, 1123), "white").save(path)
    return path


def test_zone_paths_reach_only_their_own_section_outlets(study):
    paths = study.paths()
    assert len(paths) == 16
    for g in study.groups:
        expected = "K1-Out1" if g.section == "S1" else "K1-Out2"
        for floor in (1, 2):
            for kind in ("kitchen", "sanitary"):
                p = paths[f"{g.group_id}:F{floor}:{kind}"]
                assert p[-1] == expected
                assert g.stack+":base:riser_in" in p
                assert len(p) == len(set(p))
                if floor == 2:
                    assert p.index(g.stack+":F2") < p.index(g.stack+":F1")
    assert not study.release_ready


def test_cleanout_is_at_hydraulic_start_not_lowest_stack_number(study):
    first, second = study.routes
    assert first.ordered_stacks == ("K1-2", "K1-1")
    assert second.ordered_stacks == ("K1-3", "K1-4")
    for route in study.routes:
        nodes = study.lower_assemblies(route)
        assert nodes[0].service_path is not None and nodes[1].service_path is None
        cap, join = study.cap(route), study.join(route, route.ordered_stacks[0])
        assert cap[1] == join[1]  # coaxial, never an arbitrary 45-degree stub
        assert (join[0]-cap[0])*route.direction > 0
        assert route.outlet_x < 0 or route.outlet_x > 1


@pytest.mark.parametrize("damage", ["duplicate", "missing", "reverse", "cross_section", "inside_outlet", "shared_outlet", "invalid_point", "floor", "crop"])
def test_invalid_proposed_network_cannot_be_exported(study, damage):
    r = study.routes[0]
    if damage == "duplicate":
        changed = replace(study, groups=(study.groups[0], study.groups[0], *study.groups[2:]))
    elif damage == "missing":
        changed = replace(study, routes=(replace(r, ordered_stacks=("K1-2",)), study.routes[1]))
    elif damage == "reverse":
        changed = replace(study, routes=(replace(r, ordered_stacks=tuple(reversed(r.ordered_stacks))), study.routes[1]))
    elif damage == "cross_section":
        changed = replace(study, groups=(replace(study.groups[0], section="S2"), *study.groups[1:]))
    elif damage == "inside_outlet":
        changed = replace(study, routes=(replace(r, outlet_x=.1), study.routes[1]))
    elif damage == "shared_outlet":
        changed = replace(study, routes=(replace(r, outlet=study.routes[1].outlet), study.routes[1]))
    elif damage == "invalid_point":
        changed = replace(study, groups=(replace(study.groups[0], position=(float("nan"), .7)), *study.groups[1:]))
    elif damage == "floor":
        changed = replace(study, floors=(1, 1))
    else:
        changed = replace(study, basement_crop_px=(300, 200, 100, 50))
    with pytest.raises(ValueError):
        changed.validate()


def test_capped_passing_node_is_rejected(study, monkeypatch):
    monkeypatch.setattr(module, "build_lower_turn_through_junction_assembly", module.build_lower_turn_cleanout_assembly)
    with pytest.raises(ValueError, match="capped throughflow"):
        study.validate()


@pytest.mark.parametrize("field,value", [("residents", 20), ("floor_elevations_m", {"1": 0, "2": 3.3}),
                                          ("basement_clear_height_m", 2.8), ("basement_elevation_m", -3.1),
                                          ("coordinate_basis", "metres"), ("interpretation_status", "confirmed"),
                                          ("k2_status", "four_roof_drains")])
def test_first_house_parameters_cannot_be_silently_imported(tmp_path, field, value):
    data = json.loads(DATA.read_text())
    data[field] = value
    target = tmp_path/"study.json"
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_plan_study(target)


def test_pdf_uses_same_stack_axes_for_floor_and_basement(study, source, tmp_path, monkeypatch):
    points = []
    original = StudySheet.circle
    def record(self, p, radius=2.4):
        points.append(p)
        original(self, p, radius)
    monkeypatch.setattr(StudySheet, "circle", record)
    pdf = generate_plan_study_pdf(tmp_path/"review.pdf", study, source)
    assert len(points) == 8
    floor_x = [p[0] for p in points[:4]]
    basement_x = [p[0] for p in points[4:]]
    assert sorted(floor_x) == sorted(basement_x)
    # Basement rendering follows flow order, not the sorted graphical IDs.
    assert basement_x == [floor_x[1], floor_x[0], floor_x[2], floor_x[3]]
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width)*25.4/72 == pytest.approx(594)
    assert float(page.mediabox.height)*25.4/72 == pytest.approx(420)
    text = " ".join(page.extract_text().split())
    for fragment in ("условный", "К1-М1", "К1-М2", "16", "Пр.", "Выпуск 1", "Выпуск 2", "не назначены"):
        assert fragment.lower() in text.lower()
    for forbidden in ("20 жителей", "0,020", "0,015", "DN100", "+6,60", "5,395", "\ufffd"):
        assert forbidden not in text


def test_changed_source_resolution_requires_anchor_review(study, source, tmp_path):
    Image.new("RGB", (750, 560), "white").save(source)
    target = tmp_path/"review.pdf"
    with pytest.raises(ValueError, match="1500x1123"):
        generate_plan_study_pdf(target, study, source)
    assert not target.exists()


def test_stack_coordinates_come_from_data_not_fixed_renderer_positions(study, source, tmp_path, monkeypatch):
    group = replace(study.groups[0], position=(.15, .76))
    revised = replace(study, groups=(group, *study.groups[1:]))
    points = []
    monkeypatch.setattr(StudySheet, "circle", lambda self, p, radius=2.4: points.append(p))
    generate_plan_study_pdf(tmp_path/"revised.pdf", revised, source)
    expected_x = 40+390*.15
    assert points[0][0] == points[5][0] == expected_x


def test_markup_has_plain_notes_and_stays_nonproject(study, source, tmp_path, monkeypatch):
    from copy import deepcopy
    from hashlib import sha256

    before = deepcopy(study)
    source_hash = sha256(source.read_bytes()).hexdigest()
    lines = []
    original = StudySheet.line

    def record(self, a, b, *args, **kwargs):
        lines.append((a, b))
        return original(self, a, b, *args, **kwargs)

    monkeypatch.setattr(StudySheet, "line", record)
    path = generate_plan_study_pdf(tmp_path / "plain-notes.pdf", study, source)
    assert not any(a[0] == 458 and b[0] == 580 and a[1] == b[1] for a, b in lines)
    # Keep the graphic panel boundary and the complete identification strip;
    # neither is a decorative separator between paragraphs.
    assert ((449, 38), (449, 387)) in lines
    assert ((20, 395), (589, 395)) in lines
    assert study == before and sha256(source.read_bytes()).hexdigest() == source_hash
    page = PdfReader(path).pages[0]
    assert len(page.images) == 1
    text = page.extract_text()
    assert "Не расчётная аксонометрия и не готовый ИОС3" in text
    assert all(label in text for label in ("Что предложено", "Как читать разметку", "Границы этого шага"))
    assert "Стадия" not in text and "Листов" not in text

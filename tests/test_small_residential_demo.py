"""Paper annotations survive composition without changing the network/legacy."""
from copy import deepcopy
from dataclasses import replace
from xml.etree import ElementTree as ET

from pypdf import PdfReader
import pytest

from app.pz.small_residential_calculation import calculate_residential_study
from app.pz.small_residential_section import (
    audit_basement_proposal_section, audit_calculated_section, audit_individual_fan_section,
    audit_section_slopes, build_section_projection, build_small_residential_section_svg,
    generate_small_residential_section_pdf,
)
from app.pz.leader_layout import _segments_cross
from tests.test_small_residential_section import model as model_fixture, rows


@pytest.fixture
def model():
    return model_fixture.__wrapped__()


def test_all_visible_floor_grades_survive_even_without_calculation_mode(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    assert len(rows(root, "data-section-slope")) == 8
    for apt in rows(root, "data-section-apartment"):
        marks = rows(apt, "data-section-slope")
        assert [(m.get("data-dn"), m.get("data-slope")) for m in marks] == [("50", "0.03"), ("100", "0.02")]
        assert {m.get("data-direction") for m in marks} == ({"1"} if apt.get("data-source-lane") == "0" else {"-1"})
    assert not audit_section_slopes(model, ET.tostring(root, encoding="unicode"))


def test_ink_boxes_clear_fixture_pipes_and_diameter_leaders(model):
    root = ET.fromstring(build_small_residential_section_svg(model))
    for apt in build_section_projection(model).visible_apartments:
        group = next(r for r in rows(root, "data-section-apartment") if r.get("data-section-apartment") == apt.apartment_id)
        sign, axis = (-1, 371) if apt.lane == 3 else (1, 219)
        fy = 290+(model.basement.basement_floor_m-apt.assembly.floor_elevation_m)*20
        def xy(port):
            p = apt.assembly.port(port).point
            return (axis+sign*(p.x_mm-313)*.34, fy+(p.y_mm-212)*.34)
        segments = [(xy(s.start_port_id), xy(s.end_port_id)) for s in apt.assembly.segments]
        for leader in rows(group, "data-leader-id"):
            if not leader.get("data-leader-id").endswith("-110"):
                continue
            # Explicit callout geometry: target to the shelf knee.
            target = float(leader.get("data-target-x")), float(leader.get("data-target-y"))
            segments.append((target, (float(leader.get("data-knee-x")), float(leader.get("data-knee-y")))))
        for mark in rows(group, "data-section-slope"):
            x1, x2, y1, y2 = [float(mark.get("data-ink-"+k)) for k in ("x1", "x2", "y1", "y2")]
            # 0.6-mm pipe + 0.25-mm auxiliary line, and extra white clearance.
            x1, x2, y1, y2 = x1-.7, x2+.7, y1-.7, y2+.7
            edges = (((x1,y1),(x2,y1)), ((x2,y1),(x2,y2)), ((x2,y2),(x1,y2)), ((x1,y2),(x1,y1)))
            for segment in segments:
                assert not any(_segments_cross(segment, edge) for edge in edges), (apt.apartment_id, mark.attrib, segment)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "value", "text", "direction", "size", "chevron", "invisible"])
def test_export_guard_catches_slope_regressions(model, damage):
    r = calculate_residential_study(model)
    root = ET.fromstring(build_small_residential_section_svg(model, calculation=r, compact_demo=True))
    mark = rows(root, "data-section-slope")[0]
    parent = next(p for p in root.iter() if mark in list(p))
    text = next(c for c in mark if c.tag.endswith("text"))
    if damage == "missing":
        parent.remove(mark)
    elif damage == "duplicate":
        parent.append(deepcopy(mark))
    elif damage == "value":
        mark.set("data-slope", "0.01")
    elif damage == "text":
        text.text = "0,100"
    elif damage == "direction":
        mark.set("data-direction", "-1")
    elif damage == "size":
        text.set("font-size", "1")
    elif damage == "chevron":
        rows(mark, "data-slope-angle")[0].set("d", "M1,1 L2,2 L1,3")
    else:
        mark.set("display", "none")
    assert audit_section_slopes(model, ET.tostring(root, encoding="unicode"), calculation=r)


def test_demo_still_checks_connections_cleanouts_levels_and_separation(model):
    before = deepcopy(model)
    r = calculate_residential_study(model)
    svg = build_small_residential_section_svg(model, calculation=r, compact_demo=True)
    assert not audit_individual_fan_section(model, svg)
    assert not audit_basement_proposal_section(model, r.basement, svg)
    assert not audit_calculated_section(model, r, svg)
    assert not audit_section_slopes(model, svg, calculation=r)
    root = ET.fromstring(svg)
    assert len(rows(root, "data-section-slope")) == 10
    assert len(rows(root, "data-legend-kind")) == 12
    assert len(rows(root, "data-outlet-grade")) == 2
    assert model == before


@pytest.mark.parametrize("receiving_length", [None, 10.0])
def test_self_cleaning_result_does_not_gate_illustrative_drawing(model, receiving_length):
    # Missing receiving length must stay unknown. An explicit synthetic length
    # exercises a failed self-cleaning result; neither case assigns project data.
    r = calculate_residential_study(model, k1_receiving_length_m=receiving_length)
    if receiving_length is None:
        assert r.k1 is None
    else:
        assert r.k1 is not None
        r = replace(r, k1=replace(r.k1, self_cleaning_ok=False))
    svg = build_small_residential_section_svg(model, calculation=r, compact_demo=True)
    assert not audit_section_slopes(model, svg, calculation=r)
    visible = " ".join(ET.fromstring(svg).itertext()).lower()
    assert "самоочищ" not in visible and "заилив" not in visible
    assert "уклон уточнить*" in visible and "учебная схема" in visible


def test_final_demo_is_one_a2_sheet_with_embedded_font_and_readable_grades(model, tmp_path):
    r = calculate_residential_study(model)
    pdf = generate_small_residential_section_pdf(str(tmp_path/"demo.pdf"), model, calculation=r, compact_demo=True)
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width)*25.4/72 == pytest.approx(594)
    assert float(page.mediabox.height)*25.4/72 == pytest.approx(420)
    text = page.extract_text()
    assert text.count("0,030") == 4 and text.count("0,020") == 5 and text.count("0,015") == 1
    assert "Условные обозначения" in text and "\ufffd" not in text
    fonts = [v.get_object() for v in page["/Resources"]["/Font"].values()]
    assert any("OpenGOST" in f["/BaseFont"] for f in fonts)


def test_compact_demo_requires_explicit_study_not_silent_defaults(model):
    with pytest.raises(ValueError, match="explicit"):
        build_small_residential_section_svg(model, compact_demo=True)


def test_lost_outlet_unknown_is_not_replaced_by_a_made_up_grade(model):
    r = calculate_residential_study(model)
    root = ET.fromstring(build_small_residential_section_svg(model, calculation=r, compact_demo=True))
    group = rows(root, "data-outlet-grade")[0]
    root.remove(group)
    assert audit_section_slopes(model, ET.tostring(root, encoding="unicode"), calculation=r)


def test_missing_caption_stops_actual_pdf_export(model, tmp_path, monkeypatch):
    import app.pz.small_residential_section as section
    r = calculate_residential_study(model)
    root = ET.fromstring(build_small_residential_section_svg(model, calculation=r, compact_demo=True))
    group = rows(root, "data-section-slope")[0]
    next(p for p in root.iter() if group in list(p)).remove(group)
    monkeypatch.setattr(section, "build_small_residential_section_svg", lambda *a, **kw: ET.tostring(root, encoding="unicode"))
    target = tmp_path/"must_not_exist.pdf"
    with pytest.raises(ValueError, match="уклон отсутствует"):
        section.generate_small_residential_section_pdf(str(target), model, calculation=r, compact_demo=True)
    assert not target.exists()

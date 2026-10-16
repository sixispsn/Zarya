"""Paper presentation regressions; no changes to the hydraulic model."""
from dataclasses import replace
from xml.etree import ElementTree as ET

import pymupdf
import pytest

from app.intake.project_builder import build_project
from app.intake.studio_intake import accepted_values, answer_field, build_handoff_request
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request
from app.pz.project import DocumentInfo
from app.pz.residential_concept_section import (
    audit_concept_section_svg, build_concept_section_svg, generate_concept_section_pdf,
)
from app.pz.wastewater_building_drafting import _title_block_svg
from app.pz.wastewater_graphic_exports import representative_section_model
from app.pz.wastewater_presentation import RepresentativeSectionInput
from tests.test_section_fan_integration import fan_draft
from tests.test_studio_concept_section import ready_draft


def elements(root, key):
    return [r for r in root.iter() if r.get(key) is not None]


def model():
    return section_model(accepted_values(fan_draft()))


def test_shared_frame_has_full_paper_dimensions_and_real_document_data(tmp_path):
    m = replace(model(), document=DocumentInfo(cipher="26-001-ИОС3", object_name="Жилой дом",
        organization="Заря", developer_name="Иванов"))
    svg = build_concept_section_svg(m)
    root = ET.fromstring(svg)
    border = elements(root, "data-sheet-border")[0]
    assert tuple(float(border.get(k)) for k in ("x", "y", "width", "height")) == (20, 5, 272, 410)
    stamp = elements(root, "data-title-block")[0]
    rect = next(r for r in stamp if r.tag.endswith("rect"))
    assert tuple(float(rect.get(k)) for k in ("x", "y", "width", "height")) == (107, 360, 185, 55)
    assert audit_concept_section_svg(m, svg) == ()
    path = tmp_path / "framed.pdf"
    generate_concept_section_pdf(path, m)
    with pymupdf.open(path) as pdf:
        assert len(pdf) == 1
        assert pdf[0].rect.width * 25.4 / 72 == pytest.approx(297, abs=.01)
        assert pdf[0].rect.height * 25.4 / 72 == pytest.approx(420, abs=.01)
        text = pdf[0].get_text()
        for label in ("26-001-ИОС3", "Жилой дом", "Заря", "Иванов", "Стадия", "Листов", "0,030", "0,020"):
            assert label in text


def test_old_a1_frame_retains_its_geometry():
    root = ET.fromstring(_title_block_svg(DocumentInfo(), sheet_no=1, sheet_total=1, title=""))
    rect = next(r for r in root if r.tag == "rect")
    scale = 10 / 3
    for key, mm in (("x", 651), ("y", 534), ("width", 185), ("height", 55)):
        assert float(rect.get(key)) == pytest.approx(mm * scale, abs=.051)


@pytest.mark.parametrize("mutation", ["short_stamp", "lost_grid", "missing_frame", "note_in_stamp"])
def test_frame_and_reserved_notes_band_are_enforced(mutation):
    m = model()
    root = ET.fromstring(build_concept_section_svg(m))
    frame = elements(root, "data-drawing-frame")[0]
    stamp = elements(root, "data-title-block")[0]
    if mutation == "short_stamp":
        next(r for r in stamp if r.tag.endswith("rect")).set("height", "28")
    elif mutation == "lost_grid":
        stamp.remove(next(r for r in stamp if r.tag.endswith("line")))
    elif mutation == "missing_frame":
        root.remove(frame)
    else:
        elements(root, "data-section-note")[0].set("y", "364")
    errors = audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))
    assert ("notes overlap drawing or title block" if mutation == "note_in_stamp" else
            "missing or nonstandard shared drawing frame") in errors


@pytest.mark.parametrize("mutation", ["missing", "wrong_value", "wrong_basis"])
def test_floor_slope_labels_cannot_disappear_or_be_replaced_by_one_over_d(mutation):
    m = model()
    root = ET.fromstring(build_concept_section_svg(m))
    row = next(r for r in elements(root, "data-section-slope") if r.get("data-section-slope").endswith("grade50"))
    if mutation == "missing":
        row.attrib.pop("data-section-slope")
    elif mutation == "wrong_value":
        row.set("data-slope", ".02")
    else:
        row.set("data-grade-basis", "1/d")
    assert "missing or untraceable floor-branch slope" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))


def test_missing_main_slopes_are_not_replaced_with_apartment_slopes():
    m = section_model(accepted_values(ready_draft()))
    svg = build_concept_section_svg(m)
    assert m.k1.slope is None and m.k2.slope is None
    root = ET.fromstring(svg)
    assert len([r for r in elements(root, "data-section-slope") if "grade" in r.get("data-section-slope")]) == 4 * len(m.shown_floors)
    assert audit_concept_section_svg(m, svg) == ()
    assert "н/д" in svg


@pytest.mark.parametrize("choice,heated,symbol", [("yes", True, "roof_funnel_heated"),
    ("no", False, "roof_funnel"), ("unknown", None, "roof_funnel")])
def test_funnel_choice_survives_studio_yaml_project_and_uses_canonical_vector(choice, heated, symbol):
    draft = fan_draft()
    answer_field(draft, "section_funnel_heated", choice)
    direct = section_model(accepted_values(draft))
    project = build_project(load_request(dump_request(build_handoff_request(draft))))
    restored = representative_section_model(project)
    assert direct.funnel_heated is heated and restored.funnel_heated is heated
    svg = build_concept_section_svg(restored)
    root = ET.fromstring(svg)
    funnel = elements(root, "data-section-funnel")[0]
    assert funnel.get("data-section-funnel") == symbol
    assert funnel.get("data-heating-known") == str(heated is not None).lower()
    assert any(r.get("data-ugo") == symbol for r in funnel.iter())
    assert audit_concept_section_svg(restored, svg) == ()
    riser = next(r for r in elements(root, "data-section-riser") if r.get("data-section-riser") == "К2")
    riser.set("y1", str(float(riser.get("y1")) + 3))
    assert "storm riser disconnected from funnel" in audit_concept_section_svg(restored, ET.tostring(root, encoding="unicode"))


def test_old_saved_input_does_not_invent_heating():
    assert RepresentativeSectionInput.from_mapping({"mode": "representative"}).funnel_heated is None
    with pytest.raises(ValueError):
        RepresentativeSectionInput(funnel_heated="yes")


@pytest.mark.parametrize("count", [4, 6, 8])
def test_common_fan_keeps_declared_group_without_dangling_extra_pipes(count):
    m = model()
    m = replace(m, fan=replace(m.fan, member_ids=tuple(f"К1-{i}" for i in range(1, count+1))))
    svg = build_concept_section_svg(m)
    root = ET.fromstring(svg)
    assert len(elements(root, "data-fan-member")) == 2
    assert len(elements(root, "data-fan-open-terminal")) == 1
    assert elements(root, "data-common-fan")[0].get("data-fan-group-size") == str(count)
    assert f"Стояков в группе: {count} (условно)" in svg
    assert all(rid in svg for rid in m.fan.member_ids)
    assert audit_concept_section_svg(m, svg) == ()


def test_two_long_sources_stay_outside_stamp():
    m = model()
    m = replace(m, k1=replace(m.k1, source_ref="А" * 200), k2=replace(m.k2, source_ref="Б" * 200))
    svg = build_concept_section_svg(m)
    root = ET.fromstring(svg)
    assert len(elements(root, "data-section-note")) == 9
    assert audit_concept_section_svg(m, svg) == ()
    assert "А" * 200 in svg and "Б" * 200 in svg

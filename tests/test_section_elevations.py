"""Declared levels must reach Studio/YAML/PDF without paper-derived geometry."""
from dataclasses import replace
from xml.etree import ElementTree as ET

import pymupdf
import pytest

from app.intake.project_builder import build_project
from app.intake.studio_intake import accepted_values, answer_field, build_handoff_request, validate_value
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg, generate_concept_section_pdf
from app.pz.wastewater_graphic_exports import representative_section_model
from app.pz.wastewater_presentation import RepresentativeSectionInput, SectionMainInput
from tests.test_studio_concept_section import ready_draft


def annotated_draft():
    d = ready_draft()
    for key, value in dict(section_zero_absolute_m=100, section_zero_source_ref="Учебное допущение; не геодезия",
        section_k1_start_invert_m=-.6, section_k1_outlet_invert_m=-2.4, section_k1_source_ref="Учебная компоновка К1",
        section_k2_start_invert_m=-.8, section_k2_outlet_invert_m=-2.3, section_k2_source_ref="Учебная компоновка К2").items():
        answer_field(d, key, value)
    return d


def test_current_values_survive_yaml_and_both_rendering_adapters():
    d = annotated_draft()
    direct = section_model(accepted_values(d))
    req = load_request(dump_request(build_handoff_request(d)))
    model = representative_section_model(build_project(req))
    assert model.zero_absolute_m == direct.zero_absolute_m == 100
    assert model.zero_source_ref == direct.zero_source_ref
    assert model.k1.start_invert_m == direct.k1.start_invert_m == -.6
    assert model.k2.start_invert_m == -.8
    assert req.sewer_pipes == [] and req.sewer_elements == []
    svg = build_concept_section_svg(model)
    assert audit_concept_section_svg(model, svg) == ()
    assert 'Абс. +97,60' in svg and 'Абс. +97,70' in svg
    assert 'data-main-start="К1"' in svg and 'data-main-start="К2"' in svg
    answer_field(d, "section_zero_absolute_m", 120)
    changed = representative_section_model(build_project(build_handoff_request(d)))
    assert changed.datum.absolute_level(changed.k1.outlet_invert_m) == 117.6


@pytest.mark.parametrize("datum,source,outlet,expected", [(0, "АР", -2, -2), (-10,"АР",-2,-12),
    (100,"",-2,None), (None,"АР",-2,None), (100,"АР",None,None)])
def test_no_implicit_datum_or_outlet(datum,source,outlet,expected):
    assert RepresentativeSectionInput(zero_absolute_m=datum,zero_source_ref=source).absolute_level(outlet) == expected


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 10001, -10001, "bad"])
def test_invalid_studio_datum(value):
    with pytest.raises(ValueError):
        validate_value("section_zero_absolute_m", value)


@pytest.mark.parametrize("start,end", [(-2,-1), (-2,-2)])
def test_counter_slope_is_not_accepted_as_gravity(start,end):
    with pytest.raises(ValueError, match="выше"):
        SectionMainInput(start_invert_m=start, outlet_invert_m=end)


def test_counter_slope_does_not_corrupt_saved_draft():
    d = annotated_draft()
    before = dict(d["answers"])
    with pytest.raises(ValueError, match="выше"):
        answer_field(d, "section_k1_start_invert_m", -3)
    assert d["answers"] == before
    answer_field(d,"section_k1_start_invert_m",None)
    answer_field(d,"section_k1_outlet_invert_m",-1)
    assert section_model(accepted_values(d)).k1.start_invert_m is None


def test_old_yaml_remains_relative_and_no_extra_project_values():
    old = RepresentativeSectionInput.from_mapping({"mode":"representative"})
    assert old.zero_absolute_m is None and old.k1.start_invert_m is None
    m = section_model(accepted_values(ready_draft()))
    svg = build_concept_section_svg(m)
    assert 'Абс. отм. не задана' in svg and 'data-main-start=' not in svg
    assert audit_concept_section_svg(m,svg) == ()


@pytest.mark.parametrize("system", ["К1", "К2"])
@pytest.mark.parametrize("mutation", ["missing_absolute", "wrong_absolute", "missing_start", "wrong_start"])
def test_annotation_regression_guard(system,mutation):
    m = section_model(accepted_values(annotated_draft()))
    root = ET.fromstring(build_concept_section_svg(m))
    if "absolute" in mutation:
        row = next(r for r in root.iter() if r.get("data-outlet-annotation") == system)
        row.set("data-absolute-m", "123" if mutation == "wrong_absolute" else "None")
    else:
        row = next(r for r in root.iter() if r.get("data-level-mark") == "main-start-"+system)
        if mutation == "missing_start":
            row.attrib.pop("data-level-mark")
        else:
            row.set("data-elevation-m", "123")
    assert audit_concept_section_svg(m,ET.tostring(root,encoding="unicode"))


def test_pdf_has_real_text_and_current_levels(tmp_path):
    m = section_model(accepted_values(annotated_draft()))
    path = tmp_path / "levels.pdf"
    generate_concept_section_pdf(path,m)
    with pymupdf.open(path) as pdf:
        assert len(pdf) == 1
        text = pdf[0].get_text()
        for value in ("Абс. +97,60", "Абс. +97,70", "−0,60", "−0,80", "Учебное допущение"):
            assert value.replace("−", "-") in text.replace("−", "-")
    external = replace(m, drainage="external")
    svg = build_concept_section_svg(external)
    assert 'data-outlet-annotation="К2"' not in svg
    assert audit_concept_section_svg(external,svg) == ()

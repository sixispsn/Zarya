"""An assigned final segment can be checked without inventing a whole network."""
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from app.calc.sewer_hydraulics import SewerHydraulicInput, calculate_sewer_hydraulics
from app.intake.project_builder import build_project
from app.intake.studio_intake import accepted_values, answer_field, build_handoff_request, validate_value
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request
from app.pz.generator import generate_wastewater_pz_html
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg
from app.pz.section_main_hydraulics import assess_section_main, current_k1_total
from app.pz.spec import build_wastewater_specification
from app.pz.wastewater_graphic_exports import representative_section_model, wastewater_graphic_export
from app.pz.wastewater_presentation import SectionMainInput
from tests.test_section_design_inputs import designed_draft
from tests import test_studio as studio_tests

client = studio_tests.client


def main_input(**overrides):
    base = SectionMainInput(100, .01, -1.8, "КК-1", "Синтетический контроль, не паспорт",
        design_flow_lps=2.758, outer_diameter_mm=110, wall_thickness_mm=3.4,
        material="pp", manning_n=.011, roughness_source="Учебное n=0,011",
        flow_source="Синтетический расход горизонтального участка для проверки решателя")
    return replace(base, **overrides)


def draft():
    d = designed_draft()
    for key, value in main_input().to_mapping().items():
        answer_field(d, "section_k1_"+key, value)
    return d


def project(d):
    return build_project(load_request(dump_request(build_handoff_request(d))))


def test_exact_existing_solver_no_new_formula_dn_not_inner_diameter():
    data = main_input()
    check = assess_section_main("К1", data)
    assert check.result == calculate_sewer_hydraulics(SewerHydraulicInput(
        "К1-конечный участок", 2.758, 103.2, 10, "pp", .011, "Учебное n=0,011"))
    assert check.result.velocity_mps == .757 and check.result.fill_ratio == .4493
    assert check.status == "verified"
    assert check.result.inner_diameter_mm != data.dn_mm


def test_consistency_roundtrip_pdf_model_pz_spec_no_pipe_registry_no_release():
    d = draft()
    p = project(d)
    m = representative_section_model(p)
    assert m == section_model(accepted_values(d))
    check = m.main_checks[0]
    assert check.status == "verified"
    html = generate_wastewater_pz_html(p)
    assert check.note in html and "0,757" in html and "0,45" in html
    assert 'data-section-main-hydraulics="К1"' in html and "Уклон, ‰" in html
    svg = build_concept_section_svg(m)
    assert 'data-main-hydraulics="К1" data-status="verified"' in svg
    assert audit_concept_section_svg(m, svg) == ()
    rows = [r for s in build_wastewater_specification(p).sections for r in s.rows
            if r.name == "Магистраль и выпуск системы К1"]
    assert len(rows) == 1 and rows[0].qty is None
    assert "103,2" in rows[0].type_mark and "110" in rows[0].type_mark
    assert not p.sewage.pipes and not p.sewage.risers and not p.sewage.elements
    assert not wastewater_graphic_export(p, "k1-k2").ready


@pytest.mark.parametrize("key,empty", [("slope",None), ("dn_mm",None), ("design_flow_lps",None),
    ("outer_diameter_mm",None), ("wall_thickness_mm",None), ("material",""),
    ("manning_n",None), ("roughness_source",""), ("source_ref","")])
def test_partial_input_never_falls_back_to_dn_or_default_n(key, empty):
    data = main_input(**{key:empty})
    check = assess_section_main("К1", data, total_flow_lps=8)
    assert check.status == "pending" and check.result is None
    assert getattr(data, key) == empty


def test_low_flow_is_review_not_invented_1_over_d_or_extra_cleanout():
    data = main_input(design_flow_lps=.2)
    check = assess_section_main("К1", data)
    assert check.status == "review" and check.result.fill_ratio < .3
    assert data.slope == .01 and data.dn_mm == 100
    d = draft()
    before = section_model(accepted_values(d))
    answer_field(d, "section_k1_design_flow_lps", .2)
    after = section_model(accepted_values(d))
    assert before.lower_nodes() == after.lower_nodes()
    assert before.flow_paths() == after.flow_paths()


def test_overload_no_false_velocity_or_fill_and_no_automatic_diameter_change():
    data = main_input(design_flow_lps=100)
    check = assess_section_main("К1", data)
    assert check.status == "fail" and check.result.fill_ratio is None
    assert check.result.velocity_mps is None and data.dn_mm == 100


def test_k2_never_borrows_household_self_cleaning_or_riser_table():
    check = assess_section_main("К2", main_input())
    assert check.status == "pending" and check.result is None
    assert "Таблица 21.1" in check.note


def test_whole_building_flow_is_explicit_recomputed_after_residents_and_fixture_change():
    d = draft()
    answer_field(d, "section_k1_flow_basis", "whole_building")
    assert section_model(accepted_values(d)).main_checks[0].status == "pending"  # conflicting manual input
    answer_field(d, "section_k1_design_flow_lps", None)
    answer_field(d, "section_k1_fixtures_count", 32)
    answer_field(d, "section_k1_receiving_length_m", 10)
    values = accepted_values(d)
    first = section_model(values)
    assert first.main_checks[0].result.design_flow_lps == round(first.k1_hour_max_m3h/3.6 + .47*1.6, 3)
    for key, value in (("residents", 80), ("sewage_max_fixture_lps", 2)):
        answer_field(d, key, value)
        v = accepted_values(d)
        p = project(d)
        # Poisoned cached results cannot become the current segment's flow.
        p.flows.sewage_l_per_s = 999
        m = representative_section_model(p)
        assert m == section_model(v)
        assert m.k1_total_flow_lps == current_k1_total([(v["consumer_code"],v["residents"])], v["sewage_max_fixture_lps"])
        assert m.k1_total_flow_lps != first.k1_total_flow_lps
        assert m.main_checks[0].result.design_flow_lps == round(m.k1_hour_max_m3h/3.6 + .47*m.k1_fixture_max_lps, 3)
        assert m.main_checks[0].result.design_flow_lps != m.k1_total_flow_lps
    assert "только после сбора всех стоков" in m.main_checks[0].note


def test_manual_flow_does_not_become_building_flow():
    assert assess_section_main("К1", main_input(), total_flow_lps=500).result.design_flow_lps == 2.758
    assert assess_section_main("К1", main_input(flow_basis="whole_building", design_flow_lps=None)).status == "pending"


@pytest.mark.parametrize("key,value", [("outer_diameter_mm",0), ("wall_thickness_mm",-1),
    ("manning_n",0), ("manning_n",float('nan')), ("design_flow_lps",True),
    ("flow_basis","guess"), ("material","unknown")])
def test_invalid_inputs_rejected(key, value):
    with pytest.raises(ValueError):
        validate_value("section_k1_"+key, value)
    with pytest.raises(ValueError):
        main_input(**{key:value})


def test_bad_wall_geometry_rejected():
    with pytest.raises(ValueError, match="сечения"):
        main_input(wall_thickness_mm=55)


@pytest.mark.parametrize("data", [main_input(manning_n=1e-323), main_input(outer_diameter_mm=1e250)])
def test_finite_but_extreme_input_cannot_produce_infinite_certification(data):
    check = assess_section_main("К1", data)
    assert check.status == "pending" and check.result is None


def test_changes_to_inputs_invalidate_status_and_audit_catches_tampering():
    d = draft()
    before = section_model(accepted_values(d))
    svg = build_concept_section_svg(before)
    answer_field(d, "section_k1_design_flow_lps", 100)
    after = section_model(accepted_values(d))
    assert "main hydraulics differs from current inputs: К1" in audit_concept_section_svg(after, svg)
    root = ET.fromstring(svg)
    next(r for r in root.iter() if r.get("data-section-slope") == "k1-main").set("data-slope", ".02")
    assert "main slope differs from current inputs: К1" in audit_concept_section_svg(before, ET.tostring(root, encoding="unicode"))


def test_new_fields_are_optional_and_edits_revoke_old_artifacts():
    from app.intake.studio_intake import FIELDS
    keys = {"section_k1_"+k for k in ("flow_basis","design_flow_lps","outer_diameter_mm","wall_thickness_mm","material","manning_n","roughness_source")}
    assert all(not f.required for f in FIELDS if f.key in keys)
    d = draft()
    d.update(preview={"run_id":"old"}, package={"run_id":"old"}, project_calculation={"old":True})
    answer_field(d, "section_k1_manning_n", .015)
    assert not d.get("preview") and not d.get("package") and not d.get("project_calculation")


def test_http_invalid_geometry_does_not_poison_saved_draft(client):
    state = studio_tests.residential_project(client)
    for key, value in main_input().to_mapping().items():
        state = studio_tests.answer(client, state, "section_k1_"+key, value)
    bad = client.patch("/studio/api/answer", json={"revision":state["revision"],
        "field":"section_k1_wall_thickness_mm", "value":55})
    assert bad.status_code == 422
    restored = client.get("/studio/api/draft").json()
    assert restored["revision"] == state["revision"]
    assert studio_tests.values(restored)["section_k1_wall_thickness_mm"]["value"] == 3.4
    result = client.post("/studio/api/calculate", json={"revision":state["revision"]})
    assert result.status_code == 200
    assert result.json()["calculation"]["sewage_flow"] == 2.293

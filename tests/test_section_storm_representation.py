"""A characteristic K2 branch is not the roof plan or a quantity takeoff."""
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from app.intake.studio_intake import (
    FIELD_MAP, accepted_values, answer_field, extract_candidates, field_state,
    next_steps, validate_value,
)
from app.intake.studio_section import section_model, section_readiness
from app.intake.studio_project import calculate_project
from app.pz.project import SewerElementSpec
from app.pz.generator import generate_wastewater_pz_html
from app.pz.residential_concept_section import audit_concept_section_svg, build_concept_section_svg
from app.pz.section_storm import SectionStormInput
from app.pz.spec import build_wastewater_specification
from app.pz.wastewater_graphic_exports import representative_section_model, wastewater_graphic_export
from tests.test_section_calculation_binding import bound_draft, project
from tests import test_studio as studio_tests

client = studio_tests.client


@pytest.mark.parametrize("count", [0, 4, 48, 500])
def test_actual_funnel_quantity_does_not_multiply_drawing_or_block_preview(count):
    d = bound_draft()
    answer_field(d, "storm_risers_count", None)
    if count:
        answer_field(d, "storm_funnels_count", count)
    values = accepted_values(d)
    assert section_readiness(values)["ready"]
    assert not any("storm_funnels_count" in row["fields"] or "storm_risers_count" in row["fields"]
                   for row in next_steps(d))
    p = project(d)  # Includes request -> YAML -> project round trip.
    m = representative_section_model(p)
    assert m == section_model(values)
    assert m.storm.funnels_count == p.storm.funnels_count == count
    assert m.storm.risers_count == 0  # Funnel count is never used as riser count.
    assert m.storm.riser_status == "verified"
    assert m.storm.aggregate_riser_status == "pending"
    svg = build_concept_section_svg(m)
    root = ET.fromstring(svg)
    assert len([r for r in root.iter() if r.get("data-section-funnel")]) == 1
    assert len([r for r in root.iter() if r.get("data-storm-riser-dn")]) == 1
    assert root.get("data-takeoff-eligible") == "false"
    assert audit_concept_section_svg(m, svg) == ()
    assert not wastewater_graphic_export(p, "k1-k2").ready
    rows = [r for s in build_wastewater_specification(p).sections for r in s.rows
            if r.name.startswith("Воронка водосточная для внутреннего водостока")]
    assert len(rows) == 1 and rows[0].qty == (count or None)
    if count:
        assert rows[0].quantity_basis == "project_input"
        assert "не по символам" in rows[0].quantity_note
    html = generate_wastewater_pz_html(p)
    assert m.storm.quantity_notice in html
    assert "задайте нагрузку, число стояков" not in html
    assert m.storm.result == replace(m.storm, funnels_count=0, risers_count=0).result


def test_no_load_no_count_still_draws_branch_without_claiming_a_calculation():
    d = bound_draft()
    for key in ("storm_risers_count", "storm_max_riser_flow_lps", "storm_selected_riser_dn_mm"):
        answer_field(d, key, None)
    m = section_model(accepted_values(d))
    svg = build_concept_section_svg(m)
    assert m.storm.riser_status == m.storm.aggregate_riser_status == "pending"
    assert "характерная ветвь; DN не задан" in svg
    assert 'data-section-funnel="roof_funnel' in svg
    assert not audit_concept_section_svg(m, svg)


def test_aggregate_failure_is_not_hidden_by_valid_individual_riser():
    m = representative_section_model(project())
    m = replace(m, storm=replace(m.storm, roof_area_m2=4000, risers_count=1))
    assert m.storm.riser_status == "verified"
    assert m.storm.aggregate_riser_status == "fail"
    assert "Суммарная способность заданных стояков НЕДОСТАТОЧНА" in m.storm.notice
    svg = build_concept_section_svg(m)
    assert "суммарная способность стояков НЕДОСТАТОЧНА" in svg
    assert not audit_concept_section_svg(m, svg)


def test_pdf_total_is_only_a_candidate_with_page_evidence():
    d = bound_draft()
    rows = extract_candidates("Общее количество водосточных воронок К2: 8 шт.", "roof-ar", 3)
    assert len(rows) == 1
    assert rows[0]["field"] == "storm_funnels_count" and rows[0]["value"] == 8
    assert rows[0]["document_id"] == "roof-ar" and rows[0]["page"] == 3
    d["documents"].append({"id":"roof-ar", "name":"АР.pdf", "candidates":rows})
    assert field_state(d, FIELD_MAP["storm_funnels_count"])["status"] == "review"
    assert "storm_funnels_count" not in accepted_values(d)
    assert project(d).storm.funnels_count == 0
    answer_field(d, "storm_funnels_count", 8)
    state = field_state(d, FIELD_MAP["storm_funnels_count"])
    assert state["source"]["kind"] == "document_confirmed"
    assert state["source"]["evidence"][0]["page"] == 3
    assert project(d).storm.funnels_count == 8


@pytest.mark.parametrize("text", ["Воронка Вр1", "Водосточные воронки: 2 шт.",
    "Общее количество водосточных воронок на участке 1: 2 шт.",
    "Общее количество водосточных воронок: 4–8 шт.",
    "Общее количество водосточных воронок: 4 шт. + 2 шт.",
    "Общее количество водосточных воронок: 1,5 шт."])
def test_local_labels_ranges_and_fractions_never_become_building_total(text):
    assert extract_candidates(text, "ar", 1) == []


@pytest.mark.parametrize("count", [True, -1, 2.5, "nan"])
def test_invalid_counts_rejected(count):
    with pytest.raises(ValueError):
        SectionStormInput(funnels_count=count)
    with pytest.raises(ValueError):
        validate_value("storm_funnels_count", count)


def test_changing_count_invalidates_preview_and_stale_drawing_metadata():
    d = bound_draft()
    d["preview"] = {"id":"old"}
    answer_field(d, "storm_funnels_count", 8)
    assert d["preview"] is None
    m = section_model(accepted_values(d))
    svg = build_concept_section_svg(m)
    changed = replace(m, storm=replace(m.storm, funnels_count=12))
    assert "storm quantity/aggregate status differs from project inputs" in audit_concept_section_svg(changed, svg)
    assert not audit_concept_section_svg(changed, build_concept_section_svg(changed))


def test_confirmed_element_rows_keep_priority_over_general_quantity():
    p = project()
    p.storm.funnels_count = 8
    p.sewage.elements = [SewerElementSpec(element_id="Вр1", system="K2", kind="roof_funnel",
        name="Воронка по ведомости АР", quantity=6, dn_mm=100)]
    rows = [r for s in build_wastewater_specification(p).sections if s.title.startswith("К2") for r in s.rows]
    assert not any(r.name.startswith("Воронка водосточная для внутреннего водостока") for r in rows)
    assert next(r for r in rows if r.name == "Воронка по ведомости АР").qty == 6


def test_conflicting_optional_count_does_not_block_preview_or_silently_pick_one():
    d = bound_draft()
    for count in (8, 12):
        doc_id = f"ar-{count}"
        rows = extract_candidates(f"Общее количество кровельных воронок: {count} шт.", doc_id, 1)
        d["documents"].append({"id":doc_id, "name":doc_id+".pdf", "candidates":rows})
    assert field_state(d, FIELD_MAP["storm_funnels_count"])["status"] == "conflict"
    result = calculate_project(d)
    assert result["can_preview"] and not result["can_release"]
    assert any("Количество воронок из документа не подтверждено" in n for n in result["preview_notes"])
    assert project(d).storm.funnels_count == 0


def test_real_pdf_upload_allows_scheme_preview_before_count_confirmation(client):
    state, d = studio_tests.new(client), bound_draft()
    response = client.post("/studio/api/calculate", json={"revision":state["revision"],
        "answers":{k:row["value"] for k,row in d["answers"].items()}})
    assert response.status_code == 200, response.text
    state = studio_tests.upload(client, response.json(), "Общее количество водосточных воронок: 8 шт.", "План кровли.pdf")
    response = client.post("/studio/api/preview", json={"revision":state["revision"]})
    assert response.status_code == 200, response.text
    state = response.json()
    assert "wastewater_scheme_pdf" in {row["kind"] for row in state["preview"]["documents"]}
    assert any("Количество воронок из документа не подтверждено" in note for note in state["preview"]["notes"])
    assert state["package"] is None
    assert studio_tests.values(state)["storm_funnels_count"]["status"] == "review"

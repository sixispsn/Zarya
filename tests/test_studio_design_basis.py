"""Real input paths for stage-P references; no blanket project approval."""
from copy import deepcopy
import pytest

from app.intake.studio_intake import (answer_field, build_handoff_request, public_draft,
    accepted_values, validate_value, IntakeError, extract_candidates)
from app.intake.studio_project import calculate_project
from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request
from app.pz.generator import generate_pz_html, generate_wastewater_pz_html
from tests.test_studio_apartment_meters import draft
from tests.test_studio_preview_readiness import findings
from tests import test_studio as studio_tests

client = studio_tests.client


def basis_answers():
    # Synthetic test documents, NOT evidence for Samara or any real building.
    return dict(project_assignment_ref="ТЕСТ-ПЗ, раздел 1, приложение А",
        project_survey_ref="ТЕСТ-ИИ, том 1, ревизия 2",
        project_service_life_years=100, project_overhaul_period_years=30,
        water_source_description="Тестовая существующая водопроводная сеть",
        water_connection_point="ВК-7, точка врезки по учебным ТУ",
        water_tu_org="Учебный водоканал В1", water_tu_number="УЧ-В-001",
        water_tu_date="01.10.2026", wastewater_disposal_mode="centralized",
        wastewater_tu_org="Учебный водоканал К1", wastewater_tu_number="УЧ-К-002",
        wastewater_tu_date="02.10.2026")


def filled_draft():
    return draft(**basis_answers())


def test_references_are_optional_for_calculation_and_never_defaulted():
    d = draft();state = public_draft(d)
    assert state["design_basis"]["filled"] == 0
    assert not any(key in accepted_values(d) for key in basis_answers())
    assert not any(key in row["fields"] for row in state["next_steps"] for key in basis_answers())
    assert calculate_project(d)["can_preview"]
    assert not {"ready", "can_release", "confirmed"} & state["design_basis"].keys()


def test_accepted_references_reach_yaml_model_and_both_pz():
    req = build_handoff_request(filled_draft())
    req = load_request(dump_request(req))
    p = build_project(req)
    assert p.source.tu_number == "УЧ-В-001" and p.sewage.connection_tu_number == "УЧ-К-002"
    assert p.source.tu_org == "Учебный водоканал В1"
    assert p.source.description == "Тестовая существующая водопроводная сеть"
    assert p.source.connection_point == basis_answers()["water_connection_point"]
    assert p.source.guaranteed_head_m == 5  # no changed pressure coordinate/number
    for html in (generate_pz_html(p), generate_wastewater_pz_html(p)):
        assert basis_answers()["project_assignment_ref"] in html
        assert basis_answers()["project_survey_ref"] in html
        assert "100 лет" in html and "30 лет" in html
    assert "УЧ-В-001" in generate_pz_html(p) and "УЧ-К-002" not in generate_pz_html(p)
    assert "В1. Проектируемые" in generate_pz_html(p)
    assert "УЧ-К-002" in generate_wastewater_pz_html(p) and "УЧ-В-001" not in generate_wastewater_pz_html(p)
    state = public_draft(filled_draft())["design_basis"]
    assert state["filled"] == state["total"] == 7


def test_only_supplied_document_checks_close_not_engineering_release():
    old = calculate_project(draft());new = calculate_project(filled_draft())
    for key in ("flows", "meters", "head", "pumps", "fire", "storm"):
        assert new[key] == old[key], key
    before, after = findings(old), findings(new)
    for code in ("V-GOST-01", "V-GOST-02", "K-GOST-01", "K-GOST-02", "K-GOST-03"):
        assert before[code]["state"] == "blocked" and after[code]["state"] == "ready", code
    assert after["K-GOST-04"]["state"] == "blocked"  # network properties still absent
    assert not new["can_release"] and not new["sewer_scheme"]["ready"]
    assert after["CALC-03"]["state"] == before["CALC-03"]["state"]


def test_no_cross_copy_no_stale_tu_and_removal_reopens_check():
    d = filled_draft();answer_field(d, "water_tu_number", None)
    assert build_handoff_request(d).source_data.tu_number == ""
    assert build_handoff_request(d).wastewater_tu_number == "УЧ-К-002"
    assert findings(calculate_project(d))["V-GOST-02"]["state"] == "blocked"
    answer_field(d, "wastewater_disposal_mode", "local")
    p = build_project(build_handoff_request(d))
    assert p.sewage.disposal_mode == "local" and not p.sewage.connection_tu_number
    assert "УЧ-К-002" not in generate_wastewater_pz_html(p)
    answer_field(d, "wastewater_disposal_mode", "centralized")
    assert build_handoff_request(d).wastewater_tu_number == "УЧ-К-002"


@pytest.mark.parametrize("key,value", [("water_tu_date","31.02.2026"), ("water_tu_date",123),
    ("wastewater_tu_date","1.1.26"), ("water_tu_date","2026-02-29"),
    ("project_service_life_years",0), ("project_service_life_years",1.5),
    ("project_overhaul_period_years",True), ("project_service_life_years",1001)])
def test_bad_references_rejected_without_mutating_draft(key, value):
    d = filled_draft();before = deepcopy(d)
    with pytest.raises(IntakeError): answer_field(d, key, value)
    assert d == before


def test_date_normalization_and_escaped_text():
    assert validate_value("water_tu_date", "2024-02-29") == "29.02.2024"
    d = filled_draft();answer_field(d, "project_assignment_ref", '<img src=x onerror="alert(1)">')
    p = build_project(build_handoff_request(d))
    for html in (generate_pz_html(p), generate_wastewater_pz_html(p)):
        assert '<img src=x onerror=' not in html and '&lt;img' in html


def test_explicit_document_years_still_require_confirmation():
    text = "Расчётный срок службы здания: 100 лет. Период до капитального ремонта: 30 лет."
    rows = extract_candidates(text, "a"*24, 1)
    assert {r["field"]:r["value"] for r in rows} == {"project_service_life_years":100,"project_overhaul_period_years":30}
    assert not extract_candidates("Срок службы трубы 50 лет. ТУ № 23 от 01.10.2026.", "b"*24, 1)
    d = draft();d["documents"] = [dict(id="a"*24,name="Тест.pdf",candidates=rows)]
    assert "project_service_life_years" not in accepted_values(d)
    answer_field(d,"project_service_life_years",100)
    assert accepted_values(d)["project_service_life_years"] == 100
    assert d["answers"]["project_service_life_years"]["source"]["kind"] == "document_confirmed"


def test_http_persistence_and_preview_invalidation(client):
    state = studio_tests.new(client)
    response = client.post('/studio/api/calculate', json={'revision':state['revision'],
        'answers':{k:r['value'] for k,r in filled_draft()['answers'].items()}})
    assert response.status_code == 200,response.text
    state = response.json()
    assert state['design_basis']['filled'] == 7
    assert client.get('/studio/api/draft').json()['design_basis'] == state['design_basis']
    state = studio_tests.answer(client,state,'project_assignment_ref',None)
    assert state['design_basis']['filled'] == 6 and state['project_calculation'] is None
    assert state['preview'] is None and state['package'] is None

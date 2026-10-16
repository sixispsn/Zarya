"""Representative diagrams cannot fabricate a production pipe registry."""
from dataclasses import replace
from io import BytesIO
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, accepted_values, build_handoff_request, extract_candidates, public_draft, validate_value
from app.intake.studio_project import calculate_project
from app.intake.studio_section import section_model, section_readiness
from app.pz.residential_concept_section import ResidentialConceptSection, build_concept_section_svg, audit_concept_section_svg
from app.pz.wastewater_scheme_service import assess_wastewater_scheme_readiness
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft

client = studio_tests.client


def ready_draft(**overrides):
    return draft(floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                 roof_type="flat_non_accessible", section_drainage="internal", **overrides)


def test_no_basement_means_no_basement_elevation_question_or_stale_handoff():
    d = ready_draft()
    answer_field(d, "basement_kind", "none")
    v = accepted_values(d)
    assert "basement_floor_m" not in section_readiness(v)["missing"]
    assert section_model(v).basement_floor_m is None
    req = build_handoff_request(d)
    assert req.floors_below == 0 and req.wastewater_basement_floor_elevation_m is None
    assert req.sewer_pipes == [] and req.sewer_elements == []


def test_only_conditional_geometry_questions_no_registry():
    d = draft()
    group = next(s for s in public_draft(d)["next_steps"] if s["id"] == "section")
    assert "floor_height_m" in group["fields"] and "basement_kind" in group["fields"]
    assert "basement_floor_m" not in group["fields"]
    answer_field(d, "basement_kind", "subfloor")
    group = next(s for s in public_draft(d)["next_steps"] if s["id"] == "section")
    assert "basement_floor_m" in group["fields"]
    assert calculate_project(d)["can_preview"]  # Still not a gate on water/PZ.
    assert all("sewer_pipe" not in k for k in group["fields"])


@pytest.mark.parametrize("value", [0, 2, "nan", "inf", True])
def test_invalid_basement_level(value):
    with pytest.raises(ValueError):
        validate_value("basement_floor_m", value)


def test_labelled_pdf_text_is_candidate_not_silently_accepted():
    rows = extract_candidates("Высота этажа (от пола до пола): 3,3 м. Отметка пола подвала: −3,100 м.", "ar", 2)
    assert {r["field"]: r["value"] for r in rows} == {"floor_height_m": 3.3, "basement_floor_m": -3.1}
    assert extract_candidates("Высота помещения 2,8 м; 16 этажей", "ar", 1) == []


@pytest.mark.parametrize("floors", [1, 2, 3, 4, 16, 100, 200])
@pytest.mark.parametrize("consumer", ["residential_full_bath", "residential_no_bath", "residential_central_hw"])
def test_connected_topology_and_characteristic_storeys(floors, consumer):
    m = ResidentialConceptSection(floors, 3.3, "basement", -3.1, "flat_non_accessible", "internal", consumer)
    paths = m.flow_paths()
    assert paths and all(p[-1] == ("К2:outlet" if k.startswith("К2:") else "К1:outlet") for k, p in paths.items())
    svg = build_concept_section_svg(m)
    assert audit_concept_section_svg(m, svg) == ()
    root = ET.fromstring(svg)
    boundaries = {int(r.get("data-floor-boundary")) for r in root.iter() if r.get("data-floor-boundary")}
    assert boundaries == set(m.shown_floors)
    assert len([r for r in root.iter() if r.get("data-building-section-break")]) == (floors > 3)
    assert "data-takeoff-eligible=\"false\"" in svg


def test_accessible_roof_never_invents_four_stack_collector_or_vacuum_valve():
    m = section_model(accepted_values(ready_draft()))
    svg = build_concept_section_svg(replace(m, roof_kind="flat_accessible"))
    assert "Трасса объединения не задана" in svg
    assert "data-common-fan" not in svg and "Открытое устье" not in svg
    assert "Решение уточнить" in svg


def test_external_drainage_does_not_create_k2_or_basement():
    m = section_model(accepted_values(ready_draft()))
    m = replace(m, drainage="external", basement_kind="none", basement_floor_m=None, roof_kind="gable")
    svg = build_concept_section_svg(m)
    assert not any(k.startswith("К2:") for k in m.flow_paths())
    assert 'data-section-riser="К2"' not in svg and 'data-basement-floor="true"' not in svg
    assert audit_concept_section_svg(m, svg) == ()


def test_complex_roof_is_not_silently_flattened():
    v = accepted_values(ready_draft())
    v["roof_type"] = "complex"
    status = section_readiness(v)
    assert not status["ready"] and status["limitations"]
    with pytest.raises(ValueError):
        section_model(v)


def test_template_does_not_change_flows_head_quantities_or_strict_release_gate():
    d, before = draft(), calculate_project(draft())
    for k, v in {"floor_height_m": 3.3, "basement_kind": "basement", "basement_floor_m": -3.1,
                 "roof_type": "flat_non_accessible", "section_drainage": "internal"}.items():
        answer_field(d, k, v)
    after = calculate_project(d)
    assert after["sewer_scheme"]["representative"]["ready"]
    assert not after["sewer_scheme"]["ready"] and not after["can_release"]
    assert after["flows"] == before["flows"] and after["head"] == before["head"]
    project = build_project(build_handoff_request(d))
    assert not assess_wastewater_scheme_readiness(project).ready
    req = build_handoff_request(d)
    assert not req.sewer_pipes and not req.sewer_elements


def test_editing_geometry_invalidates_previous_preview():
    d = ready_draft()
    d["preview"] = {"id": "old"}
    answer_field(d, "floor_height_m", 3.5)
    assert d["preview"] is None


def test_missing_geometry_never_serves_old_registry_status_as_scheme(client):
    state = studio_tests.residential_project(client)
    r = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert r.status_code == 200, r.text
    state = r.json()
    kinds = {d["kind"] for d in state["preview"]["documents"]}
    assert "wastewater_pz_pdf" in kinds and "scheme_pdf" in kinds
    assert "wastewater_scheme_pdf" not in kinds and "wastewater_package_pdf" not in kinds
    assert state["project_calculation"]["sewer_scheme"]["representative"]["missing"]


def test_actual_studio_pdf_without_pipe_registry_is_private_and_preliminary(client):
    state, d = studio_tests.new(client), ready_draft()
    r = client.post("/studio/api/calculate", json={"revision": state["revision"],
                   "answers": {k: row["value"] for k, row in d["answers"].items()}})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["project_calculation"]["sewer_scheme"]["representative"]["ready"]
    r = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert r.status_code == 200, r.text
    state = r.json()
    doc = next(d for d in state["preview"]["documents"] if d["kind"] == "wastewater_scheme_pdf")
    assert doc["state"] == "preliminary" and state["package"] is None
    url = f'/studio/api/preview/{state["preview"]["id"]}/files/{doc["name"]}'
    r = client.get(url)
    assert r.status_code == 200 and r.headers["x-zarya-preview"] == "true"
    pdf = PdfReader(BytesIO(r.content))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    assert "Принципиальныйразрез" in text.replace(" ", "") and "К1,К2" in text.replace(" ", "")
    assert "не документ к выпуску" in text and "Каркас:" not in text
    combined = next(d for d in state["preview"]["documents"] if d["kind"] == "wastewater_package_pdf")
    assert combined["state"] == "preliminary"
    combined_url = f'/studio/api/preview/{state["preview"]["id"]}/files/{combined["name"]}'
    package = PdfReader(BytesIO(client.get(combined_url).content))
    assert any("Принципиальныйразрез" in page.extract_text().replace(" ", "") for page in package.pages)
    old = url
    state = studio_tests.answer(client, state, "floor_height_m", 3.5)
    assert client.get(old).status_code == 404

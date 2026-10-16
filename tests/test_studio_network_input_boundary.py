"""Executable audit of the ordinary Studio boundary, not a positive release.

No substituted handoff/Project/calculation. These expectations describe the
current unsupported registry input and must evolve with its explicit editor.
"""
from dataclasses import asdict

import pytest

from app.intake.studio_intake import FIELD_MAP, build_handoff_request
from app.intake.studio_store import StudioStore
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_scheme_service import assess_wastewater_scheme_readiness
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft
from tests.test_wastewater_scheme_service import _project

client = studio_tests.client


def ordinary_answers():
    data = draft(floor_height_m=3.3, basement_kind="basement", basement_floor_m=-3.1,
                 roof_type="flat_non_accessible", storm_city="moscow",
                 storm_roof_area_m2=252, section_drainage="internal",
                 section_fan_mode="individual", section_fan_height_m=.2,
                 section_fan_working_diameter_mm=100, section_fan_opening_distance_m=4,
                 section_fan_plastic_exposed="yes", section_fan_uv_protected="yes",
                 section_fan_source_ref="Синтетические исходные проверки границы ввода")
    return {key: row["value"] for key, row in data["answers"].items()}


def test_real_questionnaire_preserves_section_but_cannot_produce_registry(client, tmp_path):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": ordinary_answers(),
    })
    assert response.status_code == 200, response.text
    public = response.json()
    scheme = public["project_calculation"]["sewer_scheme"]
    assert scheme["presentation"] == "representative" and scheme["available"]
    assert scheme["representative"]["ready"]
    assert not scheme["ready"] and not scheme["representative"]["release_ready"]
    assert not scheme["representative"]["takeoff_eligible"]
    assert not public["project_calculation"]["can_release"]
    saved = StudioStore(tmp_path / "studio").load(public["project_id"])
    request = build_handoff_request(saved)
    assert not request.sewer_pipes and not request.sewer_elements
    assert request.wastewater_fan_ventilation is None
    assert request.wastewater_fan_geometry is None
    # These supported inputs are preserved in their proper scope, not lost.
    assert request.wastewater_floor_height_m == 3.3
    assert request.wastewater_basement_floor_elevation_m == -3.1
    assert request.wastewater_roof_kind == "flat_non_accessible"
    fan = request.wastewater_presentation.fan
    assert fan.mode == "individual" and fan.height_m == .2
    assert fan.working_diameter_mm == 100 and fan.opening_distance_m == 4
    assert fan.plastic_exposed is True and fan.uv_protected is True
    assert fan.source_ref == ordinary_answers()["section_fan_source_ref"]
    before = saved
    assert client.get("/studio/api/draft").json()["project_calculation"] == public["project_calculation"]
    assert StudioStore(tmp_path / "studio").load(public["project_id"]) == before


def test_positive_reference_needs_explicit_registries_and_terminal_confirmations():
    reference = load_request_file("demo/demo_project.yaml")
    confirmed = _project()  # existing test-only terminals, never written to demo
    assert len(reference.sewer_pipes) == 12
    assert len(reference.sewer_elements) == 40
    assert len(confirmed.sewage.fan_ventilation.terminals) == 2
    assert assess_wastewater_scheme_readiness(confirmed).ready
    assert "sewer_pipes" in FIELD_MAP  # Explicit registry editor added after the audit.
    assert "sewer_elements" in FIELD_MAP
    assert "wastewater_fan_ventilation" in FIELD_MAP
    assert "sewage_risers" in FIELD_MAP
    for key in ("wastewater_fan_geometry",
                "sewer_first_manholes", "sewer_internal_nodes", "sewer_fixture_safety_inputs",
                "sewer_discharge_events"):
        assert key not in FIELD_MAP
    assert len(reference.sewer_first_manholes) == 1
    assert len(reference.sewer_internal_nodes) == 2
    assert len(reference.sewer_fixture_safety_inputs) == 2
    assert len(reference.sewer_discharge_events) == 2


@pytest.mark.parametrize("part", ["pipes", "elements", "fan_ventilation"])
def test_each_core_registry_group_is_needed_for_reference_graphic(part):
    project = _project()
    setattr(project.sewage, part, None if part == "fan_ventilation" else [])
    status = assess_wastewater_scheme_readiness(project)
    assert not status.ready and status.reasons


def test_additional_safety_inputs_are_not_required_for_this_graphic_readiness():
    reference = load_request_file("demo/demo_project.yaml")
    reference.wastewater_fan_ventilation = _project().sewage.fan_ventilation
    for key in ("sewer_first_manholes", "sewer_internal_nodes",
                "sewer_fixture_safety_inputs", "sewer_discharge_events"):
        setattr(reference, key, [])
    # Graphic-only readiness, NOT hydraulics, backflow safety or release approval.
    assert assess_wastewater_scheme_readiness(build_project(reference)).ready


@pytest.mark.parametrize("key", ["sewer_first_manholes"])
@pytest.mark.parametrize("route", ["answer", "calculate"])
def test_hidden_registry_payload_is_rejected_atomically(client, tmp_path, key, route):
    state = studio_tests.new(client)
    storage = StudioStore(tmp_path / "studio")
    before = (storage.folder(state["project_id"]) / "draft.json").read_bytes()
    reference = load_request_file("demo/demo_project.yaml")
    if key == "wastewater_fan_ventilation":
        value = _project().sewage.fan_ventilation.to_mapping()
    else:
        value = [asdict(row) for row in getattr(reference, key)]
    if route == "answer":
        response = client.patch("/studio/api/answer", json={
            "revision": state["revision"], "field": key, "value": value,
        })
    else:
        response = client.post("/studio/api/calculate", json={
            "revision": state["revision"], "answers": {**ordinary_answers(), key: value},
        })
    assert response.status_code == 422, response.text
    assert "Неизвестное поле" in response.text
    assert (storage.folder(state["project_id"]) / "draft.json").read_bytes() == before

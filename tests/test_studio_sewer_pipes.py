"""Real user-input registry roundtrip. No handoff or readiness substitutions."""
from copy import deepcopy
from dataclasses import asdict, fields

import pytest

from app.intake.request_dto import SewerPipeRequest, validate_sewer_pipes
from app.intake.studio_intake import build_handoff_request, answer_field
from app.intake.studio_sewer_pipes import validate_registry, editor_columns, MAX_ROWS
from app.intake.studio_store import StudioStore
from app.intake.yaml_io import load_request_file
from tests import test_studio as studio_tests
from tests.test_studio_network_input_boundary import ordinary_answers

client = studio_tests.client


def rows():
    # Existing explicit synthetic geometry, never written back to the demo.
    return [asdict(p) for p in load_request_file("demo/demo_project.yaml").sewer_pipes]


@pytest.mark.parametrize("count", [1, 12])
def test_http_roundtrip_keeps_real_pipes_and_incomplete_network(client, tmp_path, count):
    initial = studio_tests.new(client)
    data = rows()[:count]
    response = client.post("/studio/api/calculate", json={
        "revision": initial["revision"], "answers": {**ordinary_answers(), "sewer_pipes": data},
    })
    assert response.status_code == 200, response.text
    state = response.json()
    row = next(r for r in state["fields"] if r["key"] == "sewer_pipes")
    assert row["value"] == data and row["source"]["kind"] == "user"
    calculation = state["project_calculation"]
    assert not calculation["can_release"]
    assert not calculation["sewer_scheme"]["ready"]
    assert calculation["sewer_scheme"]["presentation"] != "representative"
    assert calculation["sewer_scheme"]["reasons"]
    store = StudioStore(tmp_path / "studio")
    saved = store.load(state["project_id"])
    request = build_handoff_request(saved)
    assert [asdict(p) for p in request.sewer_pipes] == data
    assert request.sewer_elements == [] and request.wastewater_fan_ventilation is None
    assert client.get("/studio/api/draft").json()["project_calculation"] == calculation
    # Editing revokes old computed documents/results; invalid edits below do not.
    changed = deepcopy(data)
    changed[0]["length_m"] += .5
    update = client.patch("/studio/api/answer", json={
        "revision": state["revision"], "field": "sewer_pipes", "value": changed,
    })
    assert update.status_code == 200, update.text
    assert update.json()["project_calculation"] is None
    assert [asdict(p) for p in build_handoff_request(store.load(state["project_id"])).sewer_pipes] == changed
    assert client.patch("/studio/api/answer", json={
        "revision": state["revision"], "field": "sewer_pipes", "value": data,
    }).status_code == 409
    response = client.patch("/studio/api/answer", json={
        "revision": update.json()["revision"], "field": "sewer_pipes", "value": [],
    })
    assert response.status_code == 200
    assert build_handoff_request(store.load(state["project_id"])).sewer_pipes == []


@pytest.mark.parametrize("route", ["answer", "calculate"])
def test_invalid_edit_is_atomic(client, tmp_path, route):
    state = studio_tests.new(client)
    state = studio_tests.answer(client, state, "sewer_pipes", rows())
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    broken = rows()
    broken[0]["length_m"] = ""
    payload = {"revision": state["revision"]}
    if route == "answer":
        response = client.patch("/studio/api/answer", json={**payload, "field": "sewer_pipes", "value": broken})
    else:
        response = client.post("/studio/api/calculate", json={**payload, "answers": {
            **ordinary_answers(), "sewer_pipes": broken}})
    assert response.status_code == 422
    assert file.read_bytes() == before


@pytest.mark.parametrize("patch", [
    {"system":"K3"}, {"section_id":""}, {"purpose":""}, {"length_m":None},
    {"length_m":True}, {"length_m":"nan"}, {"length_m":"inf"}, {"length_m":0},
    {"outer_diameter_mm":0}, {"wall_thickness_mm":60}, {"nominal_diameter_mm":2.5},
    {"material":{}}, {"standard":""}, {"unknown_field":1}, {"insulated":None},
    {"insulated":"no"}, {"pressure_rated":"false"}, {"pressure_rated":False,"pressure_class_bar":10},
    {"slope_per_mille":-1}, {"fill_ratio":1.1}, {"fixtures_count":True}, {"fixtures_count":1.5},
    {"elevation_start_m":1,"elevation_end_m":None},
    {"absolute_elevation_start_m":1,"absolute_elevation_end_m":None},
    {"manning_n":.01,"hydraulic_source":""}, {"catalog_series_id":"unknown"},
])
def test_bad_rows_rejected_without_inventing_values(patch):
    row = {**rows()[0], **patch}
    with pytest.raises(ValueError):
        validate_registry([row])


def test_empty_unknowns_and_zero_elevations_survive():
    row = dict(system="K1", section_id="test", purpose="стояк К1", material="ПП",
               standard="Явный тестовый стандарт", outer_diameter_mm="110,0",
               wall_thickness_mm="3,4", length_m="3,3", insulated=False,
               elevation_start_m="0", elevation_end_m="-3,3")
    saved = validate_registry([row])[0]
    assert saved["length_m"] == 3.3 and saved["wall_thickness_mm"] == 3.4
    assert saved["elevation_start_m"] == 0 and saved["elevation_end_m"] == -3.3
    assert saved["insulated"] is False and saved["pressure_rated"] is None
    for key in ("design_flow_lps", "nominal_diameter_mm", "slope_per_mille", "fill_ratio"):
        assert saved[key] is None
    assert saved["from_node"] == "" and saved["to_node"] == ""
    assert validate_registry([saved]) == [saved]
    assert validate_registry([]) is None


def test_schema_all_fields_limits_and_duplicate_ids():
    assert {c["key"] for c in editor_columns()} == {f.name for f in fields(SewerPipeRequest)}
    for value in ({}, "[]", [None], [rows()[0]] * (MAX_ROWS+1), [rows()[0], rows()[0]]):
        with pytest.raises(ValueError):
            validate_registry(value)


def test_shared_validator_keeps_request_errors():
    request = load_request_file("demo/demo_project.yaml")
    request.sewer_pipes[0].length_m = -1
    request.sewer_pipes[1].section_id = request.sewer_pipes[0].section_id
    shared = validate_sewer_pipes(request.sewer_pipes)
    assert shared
    assert [e for e in request.validate() if e.startswith("sewer_pipes[")] == shared


def test_valid_registry_edit_revokes_project_results_but_keeps_unaffected_demand():
    draft = dict(answers={}, documents=[], calculation={"old": True},
                 project_calculation={"old": True}, preview={"old": True}, package={"old": True})
    answer_field(draft, "sewer_pipes", rows()[:1])
    assert draft["calculation"] == {"old": True}  # Consumer inputs did not change.
    for key in ("project_calculation", "preview", "package"):
        assert not draft.get(key)

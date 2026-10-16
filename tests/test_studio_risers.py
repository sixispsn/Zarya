"""Explicit K1 calculation records through the real Studio input pipeline."""
from copy import deepcopy
from dataclasses import asdict, fields

import pytest

from app.intake.request_dto import SewageRiserRequest, validate_sewage_risers
from app.intake.studio_intake import answer_field, answer_visible_form, build_handoff_request, IntakeError
from app.intake.studio_risers import validate_value, editor_columns, MAX_ROWS
from app.intake.studio_store import StudioStore
from app.intake.yaml_io import load_request_file
from app.intake.project_builder import build_project
from app.pz.wastewater_ventilation import audit_project_fan_ventilation
from tests import test_studio as studio_tests
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_sewer_elements import rows as elements
from tests.test_studio_fans import evidence
from tests.test_studio_network_input_boundary import ordinary_answers

client = studio_tests.client


def rows():
    return [asdict(row) for row in load_request_file("demo/demo_project.yaml").sewage_risers]


def minimal():
    return dict(riser_id=pipes()[0]["section_id"], design_flow_lps="1,2", material="pp",
                ventilation="ventilated", riser_dn_mm=110, branch_dn_mm=110,
                branch_angle_deg="87,5", has_toilet=False)


def building_answers():
    # Match the explicit 16-storey synthetic registry, not the 2-storey
    # questionnaire-boundary fixture. The demo file itself stays unchanged.
    request = load_request_file("demo/demo_project.yaml")
    return {**ordinary_answers(), "floors":request.floors,
            "building_height_m":request.building_height_m,
            "fire_corridor_length_m":20,  # Explicit synthetic test input, never a product default.
            "fire_height_m":request.fire_height_m, "fire_topology":"separate",
            "floor_height_m":request.wastewater_floor_height_m,
            "basement_floor_m":request.wastewater_basement_floor_elevation_m}


@pytest.mark.parametrize("reverse", [False, True])
def test_real_complete_registry_input_roundtrip(client, tmp_path, reverse):
    state = studio_tests.new(client)
    registries = {"sewer_pipes":pipes(), "sewer_elements":elements(),
                  "wastewater_fan_ventilation":evidence(), "sewage_risers":rows()}
    if reverse:
        registries = dict(reversed(list(registries.items())))
    response = client.post("/studio/api/calculate", json={"revision":state["revision"],
                           "answers":{**building_answers(), **registries}})
    assert response.status_code == 200, response.text
    state = response.json()
    store = StudioStore(tmp_path / "studio")
    request = build_handoff_request(store.load(state["project_id"]))
    assert [asdict(r) for r in request.sewage_risers] == rows()
    assert next(r for r in state["fields"] if r["key"] == "sewage_risers")["source"]["kind"] == "user"
    assert audit_project_fan_ventilation(build_project(request)).ready
    assert state["project_calculation"]["sewer_scheme"]["ready"], state["project_calculation"]["sewer_scheme"]["reasons"]
    assert not state["project_calculation"]["can_release"]  # Graphic readiness is not overall release.
    assert client.get("/studio/api/draft").json()["project_calculation"] == state["project_calculation"]
    old = registries["sewage_risers"][0]["riser_id"]
    for row in registries["sewer_pipes"]:
        for key in ("section_id", "from_node", "to_node"):
            if row[key] == old:
                row[key] = "К1-Новый"
    for row in registries["sewer_elements"]:
        for key in ("section_id", "connects_to"):
            if row[key] == old:
                row[key] = "К1-Новый"
    for row in registries["wastewater_fan_ventilation"]["terminals"]:
        row["riser_ids"] = ["К1-Новый" if rid == old else rid for rid in row["riser_ids"]]
    registries["sewage_risers"][0]["riser_id"] = "К1-Новый"
    response = client.patch("/studio/api/answers", json={"revision":state["revision"], "answers":registries})
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["project_calculation"] is None
    assert [asdict(r) for r in build_handoff_request(store.load(state["project_id"])).sewage_risers] == registries["sewage_risers"]
    assert client.patch("/studio/api/answers", json={"revision":state["revision"], "answers":registries}).status_code == 409
    response = client.post("/studio/api/calculate", json={"revision":changed["revision"], "answers":{"sewage_risers":[]}})
    assert response.status_code == 200, response.text
    assert not response.json()["project_calculation"]["sewer_scheme"]["ready"]
    assert any("Режим стояка" in r for r in response.json()["project_calculation"]["sewer_scheme"]["reasons"])
    assert not build_handoff_request(store.load(state["project_id"])).sewage_risers


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("change", ["delete_pipe", "k2", "main", "unknown_id", "missing_flow"])
def test_invalid_edits_are_atomic(client, tmp_path, route, change):
    state = studio_tests.new(client)
    response = client.patch("/studio/api/answers", json={"revision":state["revision"], "answers":{
        "sewage_risers":[minimal()], "sewer_pipes":pipes()}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    key, value = "sewage_risers", [minimal()]
    if change in {"delete_pipe", "k2", "main"}:
        key, value = "sewer_pipes", pipes()
        if change == "delete_pipe":
            value = value[1:]
        elif change == "k2":
            value[0]["system"] = "K2"
        else:
            value[0]["purpose"] = "магистраль"
    elif change == "unknown_id":
        value[0]["riser_id"] = "missing"
    else:
        value[0]["design_flow_lps"] = None
    payload = {"revision":state["revision"]}
    if route == "answer":
        response = client.patch("/studio/api/answer", json={**payload, "field":key, "value":value})
    else:
        response = (client.post if route == "calculate" else client.patch)("/studio/api/"+route,
                        json={**payload, "answers":{key:value}})
    assert response.status_code == 422, response.text
    assert file.read_bytes() == before


@pytest.mark.parametrize("patch", [
    {"riser_id":""}, {"design_flow_lps":None}, {"design_flow_lps":0},
    {"design_flow_lps":True}, {"design_flow_lps":"nan"}, {"working_height_m":"inf"},
    {"riser_dn_mm":110.5}, {"branch_dn_mm":0}, {"branch_dn_mm":None},
    {"material":"steel"}, {"ventilation":"unknown"}, {"ventilation":None},
    {"branch_angle_deg":90}, {"branch_angle_deg":None}, {"has_toilet":None},
    {"has_toilet":"false"}, {"inner_diameter_mm":0}, {"minimum_trap_seal_mm":-1},
    {"inner_diameter_mm":100,"branch_inner_diameter_mm":101},
    {"air_valve_free_area_mm2":100},
    {"ventilation":"vacuum_valve", "air_valve_free_area_mm2":100,"air_valve_source":""},
    {"pressure_input_source":{}}, {"pressure_input_source":"x"*201}, {"unknown":1},
])
def test_required_and_canonical_checks(patch):
    with pytest.raises(ValueError):
        validate_value([{**minimal(), **patch}])


def test_optional_unknowns_false_and_decimals_preserved():
    row = validate_value([minimal()])[0]
    assert row["design_flow_lps"] == 1.2 and row["branch_angle_deg"] == 87.5
    assert row["has_toilet"] is False
    assert all(row[k] is None for k in ("working_height_m", "inner_diameter_mm",
        "branch_inner_diameter_mm", "minimum_trap_seal_mm", "air_valve_free_area_mm2"))
    assert row["pressure_input_source"] == row["air_valve_source"] == ""
    assert validate_value([row]) == [row]
    assert {r["key"] for r in editor_columns()} == {f.name for f in fields(SewageRiserRequest)}
    assert validate_value([]) is None
    for bad in ({}, "[]", [None], [minimal()]*2, [minimal()]*(MAX_ROWS+1)):
        with pytest.raises(ValueError):
            validate_value(bad)


def test_shared_validator_preserves_full_dto_errors():
    request = load_request_file("demo/demo_project.yaml")
    request.sewage_risers[0].design_flow_lps = 0
    request.sewage_risers[1].riser_id = request.sewage_risers[0].riser_id
    request.sewage_risers[1].branch_angle_deg = 90
    assert validate_sewage_risers(request.sewage_risers) == [e for e in request.validate() if e.startswith("sewage_risers[")]


def test_cache_invalidation_and_memory_atomicity():
    draft = dict(answers={}, documents=[], calculation={"keep":True}, project_calculation={"old":True},
                 preview={"old":True}, package={"old":True})
    before = deepcopy(draft)
    with pytest.raises(IntakeError):
        answer_field(draft, "sewage_risers", [minimal()])
    assert draft == before
    answer_visible_form(draft, {"sewage_risers":[minimal()], "sewer_pipes":pipes()}, [])
    assert draft["calculation"] == {"keep":True}
    assert all(draft[k] is None for k in ("project_calculation", "preview", "package"))


def test_conflicting_mode_is_not_silently_changed_or_approved(client, tmp_path):
    state = studio_tests.new(client)
    data = rows()
    data[0]["ventilation"] = "unventilated"
    response = client.post("/studio/api/calculate", json={"revision":state["revision"], "answers":{
        **ordinary_answers(), "sewer_pipes":pipes(), "sewer_elements":elements(),
        "wastewater_fan_ventilation":evidence(), "sewage_risers":data}})
    assert response.status_code == 200, response.text
    state = response.json()
    request = build_handoff_request(StudioStore(tmp_path / "studio").load(state["project_id"]))
    assert request.sewage_risers[0].ventilation == "unventilated"
    assert any(c.code == "FAN-MODE" and c.status == "fail" for c in audit_project_fan_ventilation(build_project(request)).checks)
    assert not state["project_calculation"]["sewer_scheme"]["ready"]

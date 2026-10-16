"""Real explicit element input, including atomic cross-registry changes."""
from copy import deepcopy
from dataclasses import asdict, fields

import pytest

from app.intake.request_dto import SewerElementRequest, validate_sewer_elements
from app.intake.studio_intake import answer_field, answer_visible_form, build_handoff_request, IntakeError
from app.intake.studio_sewer_elements import validate_registry, validate_network, editor_columns, MAX_ROWS
from app.intake.studio_store import StudioStore
from app.intake.yaml_io import load_request_file
from tests import test_studio as studio_tests
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_network_input_boundary import ordinary_answers

client = studio_tests.client


def rows():
    return [asdict(row) for row in load_request_file("demo/demo_project.yaml").sewer_elements]


def minimal():
    return dict(element_id="Э1", system="K1", kind="revision", name="Явная ревизия",
                quantity=2, floor_from=0, accessible=False, include_in_spec=False)


@pytest.mark.parametrize("reverse", [False, True])
def test_real_http_roundtrip_and_atomic_joint_rename(client, tmp_path, reverse):
    state = studio_tests.new(client)
    registries = {"sewer_pipes": pipes(), "sewer_elements": rows()}
    if reverse:
        registries = dict(reversed(list(registries.items())))
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": {**ordinary_answers(), **registries}})
    assert response.status_code == 200, response.text
    state = response.json()
    assert not state["project_calculation"]["can_release"]
    assert not state["project_calculation"]["sewer_scheme"]["ready"]
    store = StudioStore(tmp_path / "studio")
    request = build_handoff_request(store.load(state["project_id"]))
    assert [asdict(row) for row in request.sewer_elements] == rows()
    assert request.wastewater_fan_ventilation is None
    assert next(r for r in state["fields"] if r["key"] == "sewer_elements")["source"]["kind"] == "user"
    assert client.get("/studio/api/draft").json()["project_calculation"] == state["project_calculation"]
    old = registries["sewer_pipes"][0]["section_id"]
    registries["sewer_pipes"][0]["section_id"] = "Переименован"
    for row in registries["sewer_elements"]:
        for key in ("section_id", "connects_to"):
            if row[key] == old:
                row[key] = "Переименован"
    response = client.patch("/studio/api/answers", json={"revision": state["revision"], "answers": registries})
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["project_calculation"] is None
    assert [asdict(e) for e in build_handoff_request(store.load(state["project_id"])).sewer_elements] == registries["sewer_elements"]
    assert client.patch("/studio/api/answers", json={"revision": state["revision"], "answers": registries}).status_code == 409
    response = client.patch("/studio/api/answers", json={"revision": changed["revision"], "answers": {key: [] for key in registries}})
    assert response.status_code == 200, response.text
    assert not build_handoff_request(store.load(state["project_id"])).sewer_elements


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("edit", ["delete_pipe", "bad_link", "delete_element", "wrong_system"])
def test_bad_links_never_mutate_disk(client, tmp_path, route, edit):
    state = studio_tests.new(client)
    elements = [minimal(), {**minimal(), "element_id": "Э2", "connects_to": "Э1"}]
    elements[0]["section_id"] = pipes()[0]["section_id"]
    response = client.patch("/studio/api/answers", json={"revision": state["revision"], "answers": {
        "sewer_pipes": pipes(), "sewer_elements": elements}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    key, value = "sewer_elements", deepcopy(elements)
    if edit == "delete_pipe":
        key, value = "sewer_pipes", []
    elif edit == "bad_link":
        value[0]["connects_to"] = "нет такого ID"
    elif edit == "delete_element":
        value = value[1:]
    else:
        value[0]["system"] = "K2"
    payload = {"revision": state["revision"]}
    if route == "answer":
        response = client.patch("/studio/api/answer", json={**payload, "field": key, "value": value})
    else:
        payload["answers"] = {key: value}
        response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422, response.text
    assert file.read_bytes() == before


@pytest.mark.parametrize("patch", [
    {"element_id":""}, {"kind":"made_up"}, {"system":"K3"}, {"name":""},
    {"quantity":None}, {"quantity":0}, {"quantity":1.5}, {"quantity":True},
    {"floor_from":None}, {"floor_from":1.5}, {"floor_to":-1},
    {"accessible":None}, {"accessible":"true"}, {"include_in_spec":None},
    {"include_in_spec":True}, {"dn_mm":0}, {"dn_mm":"inf"}, {"elevation_m":"nan"},
    {"typical_quantity":0}, {"slope_per_mille":-1}, {"layout_column":-1},
    {"service_direction":"wrong"}, {"service_fitting":"wrong"}, {"service_chainage_m":-1},
    {"name":{}}, {"note":"x"*201}, {"unknown":1},
])
def test_invalid_typed_or_canonical_data_rejected(patch):
    with pytest.raises(ValueError):
        validate_network({"sewer_elements": validate_registry([{**minimal(), **patch}])})


def test_no_engineering_defaults_and_all_fields_preserved():
    row = validate_registry([{**minimal(), "elevation_m":"-3,3", "typical_quantity":1}])[0]
    assert row["accessible"] is False and row["include_in_spec"] is False
    assert row["floor_from"] == 0 and row["quantity"] == 2 and row["typical_quantity"] == 1
    assert row["manufacturer"] == row["unit"] == ""
    assert row["elevation_m"] == -3.3 and row["floor_to"] is None
    assert row["dn_mm"] is None and row["service_chainage_m"] is None
    assert validate_registry([row]) == [row]
    assert {c["key"] for c in editor_columns()} == {f.name for f in fields(SewerElementRequest)}
    for bad in ({}, "[]", [None], [minimal()] * (MAX_ROWS+1)):
        with pytest.raises(ValueError):
            validate_registry(bad)
    with pytest.raises(ValueError, match="повторяется"):
        validate_network({"sewer_elements": validate_registry([minimal(), minimal()])})


def test_shared_checks_keep_canonical_error_order():
    request = load_request_file("demo/demo_project.yaml")
    request.sewer_elements[0].quantity = 0
    request.sewer_elements[1].element_id = request.sewer_elements[0].element_id
    request.sewer_elements[2].connects_to = "missing"
    errors = validate_sewer_elements(request.sewer_elements, request.sewer_pipes)
    assert errors == [e for e in request.validate() if e.startswith("sewer_elements[")]


def test_forward_element_node_and_section_references_are_not_order_dependent():
    pipe = pipes()[0]
    elements = [
        {**minimal(), "connects_to":"Э2"},
        {**minimal(), "element_id":"Э2", "connects_to":pipe["from_node"]},
        {**minimal(), "element_id":"Э3", "connects_to":pipe["section_id"]},
    ]
    validate_network({"sewer_pipes":[pipe], "sewer_elements":validate_registry(elements)})
    validate_network({"sewer_pipes":[pipe], "sewer_elements":validate_registry(elements[::-1])})


def test_canonical_k3_remains_supported_outside_this_editor():
    element = SewerElementRequest(**{**minimal(), "system":"K3"})
    assert validate_sewer_elements([element], []) == []


def test_memory_atomicity_and_cache_invalidation():
    draft = dict(answers={}, documents=[], calculation={"keep":True}, project_calculation={"old":True},
                 preview={"old":True}, package={"old":True})
    before = deepcopy(draft)
    with pytest.raises(IntakeError):
        answer_visible_form(draft, {"sewer_elements":[{**minimal(), "connects_to":"missing"}]}, [])
    assert draft == before
    with pytest.raises(IntakeError):
        answer_field(draft, "sewer_elements", [{**minimal(), "quantity":0}])
    assert draft == before
    answer_field(draft, "sewer_elements", [minimal()])
    assert draft["calculation"] == {"keep":True}
    assert all(draft[key] is None for key in ("project_calculation", "preview", "package"))

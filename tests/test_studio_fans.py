"""Fan evidence through real public input, without inferred riser modes."""
from copy import deepcopy
from dataclasses import fields

import pytest

from app.intake import studio_fans
from app.intake.studio_intake import build_handoff_request, answer_field, answer_visible_form, IntakeError
from app.intake.studio_store import StudioStore
from app.intake.project_builder import build_project
from app.pz.wastewater_ventilation import FanTerminal, audit_project_fan_ventilation
from tests import test_studio as studio_tests
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_sewer_elements import rows as elements
from tests.test_studio_network_input_boundary import ordinary_answers
from tests.test_wastewater_scheme_service import _project

client = studio_tests.client
KEY = "wastewater_fan_ventilation"


def evidence():
    return _project().sewage.fan_ventilation.to_mapping()


def partial():
    return {"terminals":[{"terminal_id":"Ф1", "riser_ids":[pipes()[0]["section_id"]]}]}


@pytest.mark.parametrize("reverse", [False, True])
def test_http_save_reopen_rename_clear_and_incomplete_modes(client, tmp_path, reverse):
    state = studio_tests.new(client)
    answers = {"sewer_pipes":pipes(), "sewer_elements":elements(), KEY:evidence()}
    if reverse:
        answers = dict(reversed(list(answers.items())))
    response = client.post("/studio/api/calculate", json={"revision":state["revision"],
                           "answers":{**ordinary_answers(), **answers}})
    assert response.status_code == 200, response.text
    state = response.json()
    store = StudioStore(tmp_path / "studio")
    request = build_handoff_request(store.load(state["project_id"]))
    assert request.wastewater_fan_ventilation.to_mapping() == evidence()
    assert request.sewage_risers == []  # A roof terminal must not fabricate a riser mode.
    audit = audit_project_fan_ventilation(build_project(request))
    assert not audit.ready and any(c.code == "FAN-MODE" and c.status == "pending" for c in audit.checks)
    assert not state["project_calculation"]["sewer_scheme"]["ready"]
    assert not state["project_calculation"]["can_release"]
    assert any("Режим стояка" in reason for reason in state["project_calculation"]["sewer_scheme"]["reasons"])
    assert next(r for r in state["fields"] if r["key"] == KEY)["source"]["kind"] == "user"
    assert client.get("/studio/api/draft").json()["project_calculation"] == state["project_calculation"]
    old = answers["sewer_pipes"][0]["section_id"]
    for row in answers["sewer_pipes"]:
        for key in ("section_id", "from_node", "to_node"):
            if row[key] == old:
                row[key] = "К1-Новый"
    for row in answers["sewer_elements"]:
        for key in ("section_id", "connects_to"):
            if row[key] == old:
                row[key] = "К1-Новый"
    for row in answers[KEY]["terminals"]:
        row["riser_ids"] = ["К1-Новый" if rid == old else rid for rid in row["riser_ids"]]
    response = client.patch("/studio/api/answers", json={"revision":state["revision"], "answers":answers})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["project_calculation"] is None
    assert build_handoff_request(store.load(saved["project_id"])).wastewater_fan_ventilation.to_mapping() == answers[KEY]
    assert client.patch("/studio/api/answers", json={"revision":state["revision"], "answers":answers}).status_code == 409
    response = client.patch("/studio/api/answers", json={"revision":saved["revision"], "answers":{
        "sewer_pipes":[], "sewer_elements":[], KEY:None}})
    assert response.status_code == 200, response.text
    assert build_handoff_request(store.load(saved["project_id"])).wastewater_fan_ventilation is None


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("change", ["remove_pipe", "k2_pipe", "main_pipe", "unknown_riser", "duplicate_riser"])
def test_link_failures_atomic_on_all_routes(client, tmp_path, route, change):
    state = studio_tests.new(client)
    response = client.patch("/studio/api/answers", json={"revision":state["revision"], "answers":{
        "sewer_pipes":pipes(), KEY:partial()}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    key, value = KEY, partial()
    if change in {"remove_pipe", "k2_pipe", "main_pipe"}:
        key, value = "sewer_pipes", pipes()
        if change == "remove_pipe":
            value = value[1:]
        elif change == "k2_pipe":
            value[0]["system"] = "K2"
        else:
            value[0]["purpose"] = "магистраль"
    elif change == "unknown_riser":
        value["terminals"][0]["riser_ids"] = ["missing"]
    else:
        value["terminals"].append({**value["terminals"][0], "terminal_id":"Ф2"})
    payload = {"revision":state["revision"]}
    if route == "answer":
        response = client.patch("/studio/api/answer", json={**payload, "field":key, "value":value})
    else:
        response = (client.post if route == "calculate" else client.patch)("/studio/api/"+route,
                         json={**payload, "answers":{key:value}})
    assert response.status_code == 422, response.text
    assert file.read_bytes() == before


@pytest.mark.parametrize("patch", [
    {"terminal_id":""}, {"riser_ids":[]}, {"riser_ids":"К1-Ст1"}, {"riser_ids":[""]},
    {"riser_ids":["x", "x"]}, {"kind":"fake"}, {"height_m":-1}, {"height_m":"nan"},
    {"diameter_mm":"inf"}, {"opening_distance_m":True}, {"open_end_confirmed":"false"},
    {"cold_attic":0}, {"source_ref":{}}, {"source_ref":"x"*201}, {"unknown":1},
])
def test_bad_terminal_types(patch):
    with pytest.raises(ValueError):
        studio_fans.validate_value({"terminals":[{**partial()["terminals"][0], **patch}]})


@pytest.mark.parametrize("value", [[], "{}", {"unknown":1}, {"terminals":{}},
    {"terminals":[None]}, {"external_ventilation_verified":"true"},
    {"external_ventilation_ref":False}, {"external_ventilation_ref":[]},
    {"terminals":partial()["terminals"]*201}, {"terminals":partial()["terminals"]*2}])
def test_bad_envelopes(value):
    with pytest.raises(ValueError):
        studio_fans.validate_value(value)


def test_unknowns_false_zero_and_all_columns():
    row = studio_fans.validate_value(partial())["terminals"][0]
    assert row["kind"] == "unknown" and row["source_ref"] == ""
    assert row["height_m"] is None and row["open_end_confirmed"] is None
    value = {"terminals":[{**row, "height_m":"0", "diameter_mm":"100,5", "open_end_confirmed":False}],
             "external_ventilation_verified":False, "external_ventilation_ref":""}
    saved = studio_fans.validate_value(value)
    assert saved["external_ventilation_verified"] is False
    assert saved["terminals"][0]["height_m"] == 0
    assert saved["terminals"][0]["diameter_mm"] == 100.5
    assert saved["terminals"][0]["open_end_confirmed"] is False
    assert studio_fans.validate_value(saved) == saved
    assert studio_fans.validate_value({"terminals":[]}) is None
    assert {r["key"] for r in studio_fans.editor_columns()} == {f.name for f in fields(FanTerminal)}


def test_partial_and_negative_evidence_saved_without_success_or_defaults():
    draft = dict(answers={}, documents=[], calculation={"keep":True}, project_calculation={"old":True},
                 preview={"old":True}, package={"old":True})
    before = deepcopy(draft)
    with pytest.raises(IntakeError):
        answer_field(draft, KEY, partial())
    assert draft == before
    answer_visible_form(draft, {KEY:partial(), "sewer_pipes":pipes()}, [])
    assert draft["calculation"] == {"keep":True}
    assert all(draft[k] is None for k in ("project_calculation", "preview", "package"))
    model = studio_fans.from_values({KEY:draft["answers"][KEY]["value"]})
    assert model.terminals[0].height_m is None
    assert model.terminals[0].open_end_confirmed is None


@pytest.mark.parametrize("kind", ["roof", "valve", "unventilated", "unknown"])
def test_each_declared_kind_roundtrips_without_automatic_confirmations(kind):
    value = partial()
    value["terminals"][0]["kind"] = kind
    saved = studio_fans.validate_value(value)
    studio_fans.validate_links({KEY:saved, "sewer_pipes":pipes()})
    model = studio_fans.from_values({KEY:saved})
    assert model.terminals[0].kind == kind
    assert model.terminals[0].valve_sizing_verified is None
    assert model.terminals[0].separate_from_other_systems is None


def test_external_confirmation_alone_does_not_create_terminal():
    saved = studio_fans.validate_value({"external_ventilation_verified":True})
    assert saved["terminals"] == []
    assert saved["external_ventilation_ref"] == ""

"""Addresses originate in unchanged model branches; globals precede the model."""
from copy import deepcopy

import pytest

from app.intake import studio_fans
from app.intake.registry_input_error import RegistryInputError
from app.intake.studio_store import StudioStore
from app.pz.wastewater_ventilation import FanInputError, FanTerminal, FanVentilationInput
from tests import test_studio as studio_tests
from tests.test_studio_fans import evidence, KEY
from tests.test_studio_risers import building_answers
from tests.test_studio_sewer_pipes import rows as pipes

client = studio_tests.client

CASES = [("terminal_id", "", "fan_model_id", "fan terminal needs an ID"),
         ("riser_ids", ("A", "A"), "fan_model_riser_ids", "fan terminal needs unique explicit riser IDs"),
         ("riser_ids", ("",), "fan_model_riser_ids", "fan terminal needs unique explicit riser IDs"),
         ("kind", "obsolete", "fan_model_kind", "unsupported fan termination kind")]
CASES += [(field, value, "fan_model_number", f"{field} must be a finite non-negative number")
          for field in sorted(studio_fans.NUMBERS) for value in (-1, float("inf"), "1", True)]
CASES += [(field, "true", "fan_model_boolean", f"{field} must be boolean or null")
          for field in sorted(studio_fans.BOOLEANS)]
CASES += [(field, 1, "fan_model_reference", "evidence references must be strings")
          for field in ("source_ref", "valve_sizing_ref")]


@pytest.mark.parametrize("field,value,code,detail", CASES)
def test_direct_model_and_mapping_keep_message_and_precise_source(field, value, code, detail):
    kwargs = dict(terminal_id="T", riser_ids=("A",))
    kwargs[field] = value
    original = deepcopy(kwargs)
    with pytest.raises(FanInputError) as direct:
        FanTerminal(**kwargs)
    assert str(direct.value) == detail
    assert direct.value.args == (detail,)
    assert (direct.value.code, direct.value.field, direct.value.row_index) == (code, field, None)
    mapping = {"terminals": [dict(terminal_id="first", riser_ids=["B"]), kwargs]}
    with pytest.raises(FanInputError) as mapped:
        FanVentilationInput.from_mapping(mapping)
    assert str(mapped.value) == detail
    assert (mapped.value.code, mapped.value.field, mapped.value.row_index) == (code, field, 1)
    assert kwargs == original


def test_duplicate_id_reports_first_repeated_row_without_changing_message():
    data = {"terminals": [dict(terminal_id=t, riser_ids=[str(i)]) for i, t in enumerate(["X", "Y", "X", "Y"])]}
    before = deepcopy(data)
    with pytest.raises(FanInputError) as caught:
        FanVentilationInput.from_mapping(data)
    assert str(caught.value) == "duplicate fan terminal ID"
    assert (caught.value.field, caught.value.code, caught.value.row_index) == ("terminal_id", "fan_model_duplicate_id", 2)
    assert data == before


@pytest.mark.parametrize("field,value,code,detail", [
    ("external_ventilation_verified", "true", "fan_global_boolean", "external ventilation verification must be boolean or null"),
    ("external_ventilation_ref", None, "fan_global_text", "external ventilation reference must be a string")])
def test_global_model_source(field, value, code, detail):
    with pytest.raises(FanInputError) as caught:
        FanVentilationInput(**{field: value})
    assert str(caught.value) == detail
    assert (caught.value.scope, caught.value.field, caught.value.code) == ("global", field, code)


@pytest.mark.parametrize("value", [0, 1, "true", "false", [], {}, "yes"])
def test_global_boolean_parser_rejects_without_coercion(value):
    data = {"external_ventilation_verified": value}
    before = deepcopy(data)
    with pytest.raises(RegistryInputError) as caught:
        studio_fans.validate_value(data)
    assert str(caught.value) == "Вентиляция наружной сети: явно да, нет или неизвестно."
    issue, = caught.value.input_issues
    assert issue["scope"] == "global" and "row_index" not in issue
    assert issue["field"] == "external_ventilation_verified"
    assert data == before


@pytest.mark.parametrize("value", [None, 0, [], {}, "x" * 201])
def test_global_reference_parser_keeps_refusal(value):
    with pytest.raises(RegistryInputError) as caught:
        studio_fans.validate_value({"external_ventilation_ref": value})
    assert str(caught.value) == "Основание вентиляции наружной сети: текст до 200 символов."
    assert caught.value.input_issues[0]["scope"] == "global"


@pytest.mark.parametrize("value", [None, "", False, True])
def test_valid_global_boolean_stays_nullable(value):
    result = studio_fans.validate_value({"external_ventilation_verified": value})
    assert result is None if value is None or value == "" else result["external_ventilation_verified"] is value


def test_original_evaluation_order_parser_globals_terminal_then_duplicates():
    data = evidence()
    data["terminals"][1].update(kind="obsolete", terminal_id=data["terminals"][0]["terminal_id"])
    data.update(external_ventilation_verified="true", external_ventilation_ref=23)
    expected = ["fan_global_boolean", "fan_global_text", "fan_model_kind", "fan_model_duplicate_id"]
    for step, code in enumerate(expected):
        with pytest.raises(RegistryInputError) as caught:
            studio_fans.validate_value(data)
        assert caught.value.input_issues[0]["code"] == code
        if step == 0:
            data["external_ventilation_verified"] = None
        elif step == 1:
            data["external_ventilation_ref"] = ""
        elif step == 2:
            data["terminals"][1]["kind"] = "unknown"


API_CASES = [("kind", "obsolete", "fan_model_kind"),
             ("terminal_id", "duplicate", "fan_model_duplicate_id"),
             ("riser_ids", ["К1-Ст2", "К1-Ст2"], "fan_model_riser_ids")]
API_CASES += [(f, -0.01, "fan_model_number") for f in sorted(studio_fans.NUMBERS)]
API_CASES += [("external_ventilation_verified", "true", "fan_global_boolean"),
              ("external_ventilation_ref", 23, "fan_global_text")]


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("field,value,code", API_CASES)
def test_api_model_and_global_errors_atomic_and_recoverable(client, tmp_path, route, field, value, code):
    initial = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": initial["revision"],
        "answers": {**building_answers(), KEY: evidence(), "sewer_pipes": pipes()}})
    assert response.status_code == 200
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    data = evidence()
    if field.startswith("external_"):
        data[field] = value
    else:
        data["terminals"][1][field] = data["terminals"][0]["terminal_id"] if value == "duplicate" else value
    data["terminals"][1]["source_ref"] = "TEST-ONLY: сохранность соседнего поля"
    def send(value):
        payload = {"revision": state["revision"]}
        payload.update({"field": KEY, "value": value} if route == "answer" else {"answers": {KEY: value}})
        return (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    response = send(data)
    assert response.status_code == 422, response.text
    issue, = response.json()["input_issues"]
    assert (issue["code"], issue["field"]) == (code, field)
    if field.startswith("external_"):
        assert issue["scope"] == "global" and "row_index" not in issue
    else:
        assert issue["row_index"] == 1
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state
    corrected = evidence()
    corrected["terminals"][1]["source_ref"] = data["terminals"][1]["source_ref"]
    response = send(corrected)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert next(f["value"] for f in saved["fields"] if f["key"] == KEY) == corrected
    if route == "calculate":
        assert not saved["project_calculation"]["can_release"]
    else:
        assert saved["project_calculation"] is None

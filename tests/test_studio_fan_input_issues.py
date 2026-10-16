"""Nested fan input addresses preserve existing refusals and atomicity."""
from copy import deepcopy

import pytest

from app.intake import studio_fans
from app.intake.registry_input_error import RegistryInputError
from app.intake.studio_store import StudioStore
from tests import test_studio as studio_tests
from tests.test_studio_fans import evidence, KEY
from tests.test_studio_risers import building_answers
from tests.test_studio_sewer_pipes import rows as pipes

client = studio_tests.client


def broken(field, value):
    data = evidence()
    data["terminals"][1][field] = value
    return data


CASES = (
    [(key, value, "required_value", "Фановое окончание 2: задайте обозначение и ID стояков К1.")
     for key in ("terminal_id", "riser_ids") for value in (None, "", " ")]
    + [(key, value, code, f"{studio_fans.LABELS[key]}: требуется {reason}.")
       for key in sorted(studio_fans.NUMBERS)
       for value, code, reason in [("oops", "invalid_number", "число"),
                                   (True, "invalid_number", "число"),
                                   ("nan", "nonfinite_number", "конечное число"),
                                   ("1e999", "nonfinite_number", "конечное число")]]
    + [(key, value, "boolean_required", f"{studio_fans.LABELS[key]}: явно да, нет или неизвестно.")
       for key in sorted(studio_fans.BOOLEANS) for value in (0, 1, "true", "false", [], {}, "Да")]
    + [(key, value, "fan_text_value", f"{studio_fans.LABELS[key]}: текст до 200 символов.")
       for key in sorted(studio_fans.TEXT) for value in (1, [], {}, "x" * 201)]
    + [("riser_ids", value, "fan_ids_list", "Задайте список ID стояков К1.")
       for value in ([], "К1-Ст1", {}, ["К1-Ст1"] * 201)]
    + [("riser_ids", [value], "fan_ids_list", "ID стояка: текст до 200 символов.")
       for value in (1, None, {}, "x" * 201)]
)


@pytest.mark.parametrize("field,value,code,detail", CASES)
def test_parser_keeps_original_detail_order_and_input(field, value, code, detail):
    data = broken(field, value)
    original = deepcopy(data)
    with pytest.raises(RegistryInputError) as caught:
        studio_fans.validate_value(data)
    assert str(caught.value) == detail
    issue, = caught.value.input_issues
    assert (issue["registry"], issue["row_index"], issue["field"], issue["code"]) == (KEY, 1, field, code)
    assert "строка 2" in caught.value.input_message
    assert data == original


@pytest.mark.parametrize("field", sorted(studio_fans.BOOLEANS))
@pytest.mark.parametrize("value", [False, True, None])
def test_optional_booleans_are_not_defaulted_or_coerced(field, value):
    data = broken(field, value)
    result = studio_fans.validate_value(data)
    assert result["terminals"][1][field] is value


@pytest.mark.parametrize("field", sorted(studio_fans.NUMBERS))
@pytest.mark.parametrize("value", [0, None])
def test_zero_and_missing_numbers_keep_existing_meaning(field, value):
    assert studio_fans.validate_value(broken(field, value))["terminals"][1][field] == value


@pytest.mark.parametrize("field,value,detail", [
    ("kind", "unknown-kind", "unsupported fan termination kind"),
    ("height_m", -1, "height_m must be a finite non-negative number"),
    ("riser_ids", [" "], "fan terminal needs unique explicit riser IDs"),
    ("riser_ids", ["К1-Ст1", "К1-Ст1"], "fan terminal needs unique explicit riser IDs")])
def test_domain_errors_keep_detail_with_source_address(field, value, detail):
    with pytest.raises(ValueError) as caught:
        studio_fans.validate_value(broken(field, value))
    assert str(caught.value) == detail
    assert caught.value.input_issues[0]["field"] == field
    assert caught.value.input_issues[0]["row_index"] == 1


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("field,value,code", [
    ("terminal_id", "", "required_value"), ("riser_ids", [], "fan_ids_list"),
    ("height_m", "oops", "invalid_number"), ("height_m", "nan", "nonfinite_number"),
    ("cold_attic", "true", "boolean_required"), ("source_ref", 23, "fan_text_value"),
    ("riser_ids", ["нет-стояка"], "fan_unlinked_riser"),
    ("riser_ids", ["repeated"], "fan_repeated_riser")])
def test_api_nested_error_is_atomic(client, tmp_path, route, field, value, code):
    initial = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": initial["revision"],
        "answers": {**building_answers(), KEY: evidence(), "sewer_pipes": pipes()}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    if value == ["repeated"]:
        value = evidence()["terminals"][0]["riser_ids"]
    data = broken(field, value)
    data["external_ventilation_ref"] = "TEST-ONLY: соседнее значение"
    payload = {"revision": state["revision"]}
    payload.update({"field": KEY, "value": data} if route == "answer" else {"answers": {KEY: data}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422, response.text
    issue, = response.json()["input_issues"]
    assert (issue["registry"], issue["row_index"], issue["field"], issue["code"]) == (KEY, 1, field, code)
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("change", ["remove", "k2", "main"])
def test_only_pipes_change_points_to_unchanged_fan_row(client, tmp_path, route, change):
    initial = studio_tests.new(client)
    response = client.patch("/studio/api/answers", json={"revision": initial["revision"],
        "answers": {KEY: evidence(), "sewer_pipes": pipes()}})
    assert response.status_code == 200
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    rows = pipes()
    rid = evidence()["terminals"][0]["riser_ids"][0]
    pipe = next(p for p in rows if p["section_id"] == rid)
    if change == "remove":
        rows.remove(pipe)
    elif change == "k2":
        pipe["system"] = "K2"
    else:
        pipe["purpose"] = "магистраль"
    payload = {"revision": state["revision"]}
    payload.update({"field": "sewer_pipes", "value": rows} if route == "answer" else {"answers": {"sewer_pipes": rows}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422, response.text
    issue, = response.json()["input_issues"]
    assert (issue["registry"], issue["row_index"], issue["code"]) == (KEY, 0, "fan_unlinked_riser")
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


def test_required_first_address_does_not_change_combined_message():
    with pytest.raises(RegistryInputError) as caught:
        studio_fans.validate_value({"terminals": [{}]})
    assert str(caught.value) == "Фановое окончание 1: задайте обозначение и ID стояков К1."
    assert caught.value.input_issues[0]["field"] == "terminal_id"

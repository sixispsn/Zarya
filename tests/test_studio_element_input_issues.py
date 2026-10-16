"""Element addresses annotate existing refusals, never relax the registry."""
from copy import deepcopy

import pytest

from app.intake import studio_sewer_elements as elements
from app.intake.registry_input_error import RegistryInputError
from app.intake.request_dto import SewerElementRequest, SewerPipeRequest, validate_sewer_elements
from app.intake.studio_store import StudioStore
from tests import test_studio as studio_tests
from tests.test_studio_sewer_elements import minimal, rows
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_risers import building_answers

client = studio_tests.client


CASES = (
    [(key, value, "required_value", f"укажите «{elements.LABELS[key]}».")
     for key in sorted(elements.REQUIRED) for value in (None, "", " ")]
    + [(key, value, code, f"{elements.LABELS[key]} — {reason}.")
       for key in sorted(elements.INTEGER_KEYS | elements.NUMBER_KEYS)
       for value, code, reason in [("oops", "invalid_number", "число"),
                                   (True, "invalid_number", "число"),
                                   ("nan", "nonfinite_number", "конечное число"),
                                   ("1e999", "nonfinite_number", "конечное число")]]
    + [(key, 1.5, "integer_required", f"{elements.LABELS[key]} — целое число.")
       for key in sorted(elements.INTEGER_KEYS)]
    + [(key, value, "boolean_required", f"{elements.LABELS[key]} — явно да или нет.")
       for key in sorted(elements.BOOLEAN_KEYS) for value in (0, 1, "true", "false", [], {}, "Да")]
)


@pytest.mark.parametrize("field,value,code,detail", CASES)
def test_parser_address_preserves_detail_and_input(field, value, code, detail):
    registry = [minimal(), {**minimal(), "element_id": "Э2", field: value}]
    original = deepcopy(registry)
    with pytest.raises(RegistryInputError) as caught:
        elements.validate_registry(registry)
    assert registry == original
    assert str(caught.value) == "Элемент 2: " + detail
    issue, = caught.value.input_issues
    assert (issue["registry"], issue["row_index"], issue["field"], issue["code"]) == (
        "sewer_elements", 1, field, code)
    assert "строка 2" in caught.value.input_message


LINKS = [("section_id", "unknown", "unknown_element_section"),
         ("section_id", "wrong_system", "element_section_system"),
         ("connects_to", "unknown", "unknown_element_connection")]

RANGES = [("element_id", "duplicate", "duplicate_element_id"),
          ("quantity", 0, "element_quantity_positive"),
          ("typical_quantity", 0, "element_typical_quantity_positive"),
          ("floor_to", 0, "element_floor_order"),
          ("dn_mm", 0, "element_dn_positive"),
          ("slope_per_mille", -0.001, "element_slope_nonnegative"),
          ("layout_column", -1, "element_layout_nonnegative"),
          ("service_chainage_m", -0.001, "element_chainage_nonnegative")]

CHOICES = [("system", "K3", "element_system_choice"),
           ("system", "unknown", "element_system_choice"),
           ("kind", "unknown", "element_kind_choice"),
           ("service_direction", "unknown", "element_direction_choice"),
           ("service_fitting", "unknown", "element_fitting_choice"),
           ("unit", "", "element_spec_unit_required"),
           ("unit", " ", "element_spec_unit_required")]


def broken(field, value):
    registry = rows()
    if value == "wrong_system":
        value = next(p["section_id"] for p in pipes() if p["system"] != registry[1]["system"])
    if value == "duplicate":
        value = registry[0]["element_id"]
    registry[1][field] = value
    return registry


@pytest.mark.parametrize("field,value,code", LINKS)
def test_link_metadata_is_optional_and_does_not_change_validation(field, value, code):
    records = [SewerElementRequest(**row) for row in broken(field, value)]
    sections = [SewerPipeRequest(**row) for row in pipes()]
    original = deepcopy((records, sections))
    issues = []
    assert validate_sewer_elements(records, sections) == validate_sewer_elements(
        records, sections, input_issues=issues)
    assert (records, sections) == original
    assert [(i["code"], i["field"], i["row_index"]) for i in issues] == [(code, field, 1)]
    records[1].quantity = -1
    records[1].name = ""  # Direct DTO bypasses parser; unaddressed error remains visible.
    with pytest.raises(RegistryInputError) as caught:
        elements.validate_network({"sewer_elements": [r.__dict__ for r in records], "sewer_pipes": pipes()})
    assert caught.value.input_message is None
    assert "quantity" in str(caught.value)


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("field,value,code", LINKS + RANGES + CHOICES + [
    ("name", "", "required_value"), ("dn_mm", "oops", "invalid_number"),
    ("elevation_m", "nan", "nonfinite_number"), ("quantity", 1.5, "integer_required"),
    ("accessible", "true", "boolean_required"), ("include_in_spec", "false", "boolean_required")])
def test_api_element_error_is_atomic_and_addressed(client, tmp_path, route, field, value, code):
    initial = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": initial["revision"],
        "answers": {**building_answers(), "sewer_elements": rows(), "sewer_pipes": pipes()}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    registry = broken(field, value)
    registry[1]["room_name"] = "Unsaved TEST-ONLY"
    payload = {"revision": state["revision"]}
    payload.update({"field": "sewer_elements", "value": registry} if route == "answer"
                   else {"answers": {"sewer_elements": registry}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422, response.text
    error = response.json()
    issue, = error["input_issues"]
    assert (issue["code"], issue["field"], issue["row_index"]) == (code, field, 1)
    assert "строка 2" in error["input_message"]
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


@pytest.mark.parametrize("field,value,code", RANGES)
def test_range_metadata_preserves_canonical_detail_and_order(field, value, code):
    records = [SewerElementRequest(**r) for r in broken(field, value)]
    sections = [SewerPipeRequest(**r) for r in pipes()]
    original = deepcopy((records, sections))
    issues = []
    suffix = {
        "quantity": ".quantity должен быть > 0", "typical_quantity": ".typical_quantity должен быть > 0",
        "floor_to": ".floor_to не может быть ниже floor_from", "dn_mm": ".dn_mm должен быть > 0",
        "slope_per_mille": ".slope_per_mille не может быть отрицательным",
        "layout_column": ".layout_column не может быть < 0",
        "service_chainage_m": ".service_chainage_m не может быть < 0",
        "element_id": ": обозначение пустое или повторяется",
    }[field]
    expected = ["sewer_elements[1]" + suffix]
    assert validate_sewer_elements(records, sections) == expected
    assert validate_sewer_elements(records, sections, input_issues=issues) == expected
    assert (records, sections) == original
    assert [(i["code"], i["field"], i["row_index"]) for i in issues] == [(code, field, 1)]


@pytest.mark.parametrize("field,value", [
    ("quantity", 1), ("typical_quantity", 1), ("typical_quantity", None),
    ("floor_to", 0), ("floor_to", None), ("dn_mm", 1), ("dn_mm", None),
    ("slope_per_mille", 0), ("slope_per_mille", None), ("layout_column", 0),
    ("service_chainage_m", 0), ("service_chainage_m", None), ("floor_from", -1)])
def test_existing_accepted_boundaries_not_tightened(field, value):
    records = [SewerElementRequest(**{**minimal(), field: value})]
    issues = []
    assert validate_sewer_elements(records, [], input_issues=issues) == []
    assert issues == []


@pytest.mark.parametrize("field", ["quantity", "typical_quantity", "dn_mm"])
def test_negative_values_keep_positive_requirement(field):
    records = [SewerElementRequest(**{**minimal(), field: -1})]
    issues = []
    assert validate_sewer_elements(records, [], input_issues=issues) == [f"sewer_elements[0].{field} должен быть > 0"]
    assert issues[0]["field"] == field


def test_multiple_duplicates_and_range_errors_have_distinct_addresses_and_no_mutation():
    registry = [minimal(), {**minimal(), "quantity": 0}, {**minimal(), "dn_mm": 0}]
    original = deepcopy(registry)
    with pytest.raises(RegistryInputError) as caught:
        elements.validate_network({"sewer_elements": registry})
    assert [(i["row_index"], i["field"]) for i in caught.value.input_issues] == [
        (1, "element_id"), (1, "quantity"), (2, "element_id"), (2, "dn_mm")]
    assert caught.value.input_message is not None
    assert registry == original
    registry[1]["name"] = ""
    with pytest.raises(RegistryInputError) as mixed:
        elements.validate_network({"sewer_elements": registry})
    assert mixed.value.input_message is None
    assert mixed.value.input_issues == caught.value.input_issues
    assert ".name" in str(mixed.value)


def test_empty_id_does_not_claim_duplicate_and_parser_still_reports_required_first():
    registry = [{**minimal(), "element_id": "", "quantity": 0}]
    issues = []
    errors = validate_sewer_elements([SewerElementRequest(**registry[0])], [], input_issues=issues)
    assert errors[0] == "sewer_elements[0]: обозначение пустое или повторяется"
    assert [i["code"] for i in issues] == ["element_quantity_positive"]
    with pytest.raises(RegistryInputError) as caught:
        elements.validate_registry(registry)
    assert caught.value.input_issues[0]["code"] == "required_value"


@pytest.mark.parametrize("field,value,code", [c for c in CHOICES if c[1] != "K3"])
def test_choice_metadata_preserves_canonical_contract(field, value, code):
    record = SewerElementRequest(**{**minimal(), "include_in_spec": True, "unit": "шт.", field: value})
    original = deepcopy(record)
    issues = []
    plain = validate_sewer_elements([record], [])
    assert plain == validate_sewer_elements([record], [], input_issues=issues)
    assert len(plain) == 1
    assert [(i["row_index"], i["field"], i["code"]) for i in issues] == [(0, field, code)]
    assert record == original


@pytest.mark.parametrize("field,value", [
    ("system", "K1"), ("system", "K2"), ("system", "K3"),
    ("service_direction", ""), ("service_direction", "downstream"),
    ("service_direction", "upstream"), ("service_direction", "both"),
    ("service_fitting", ""), ("service_fitting", "wye_45"), ("service_fitting", "revision_opening")])
def test_choice_boundaries_and_k3_outside_studio_remain_valid(field, value):
    issues = []
    assert validate_sewer_elements([SewerElementRequest(**{**minimal(), field: value})], [], input_issues=issues) == []
    assert not issues
    if value == "K3":
        with pytest.raises(RegistryInputError) as caught:
            elements.validate_registry([{**minimal(), field: value}])
        assert str(caught.value) == "Элемент 1: этот редактор поддерживает только К1 и К2."


@pytest.mark.parametrize("kind", elements.KINDS)
def test_every_existing_kind_remains_accepted(kind):
    registry = elements.validate_registry([{**minimal(), "kind": kind}])
    elements.validate_network({"sewer_elements": registry})


@pytest.mark.parametrize("included", [False, True])
@pytest.mark.parametrize("unit", ["", " ", "шт.", "м"])
def test_unit_is_required_only_for_explicit_spec_inclusion(included, unit):
    registry = [{**minimal(), "include_in_spec": included, "unit": unit}]
    clean = elements.validate_registry(registry)
    if included and not unit.strip():
        with pytest.raises(RegistryInputError) as caught:
            elements.validate_network({"sewer_elements": clean})
        assert str(caught.value) == "sewer_elements[0].unit обязателен для спецификации"
        assert caught.value.input_issues[0]["field"] == "unit"
    else:
        elements.validate_network({"sewer_elements": clean})
    assert registry[0]["unit"] == unit


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
def test_multiple_range_errors_recovery_and_mixed_error_atomicity(client, tmp_path, route):
    initial = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": initial["revision"],
        "answers": {**building_answers(), "sewer_elements": rows(), "sewer_pipes": pipes()}})
    assert response.status_code == 200
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    registry = broken("element_id", "duplicate")
    registry[1].update(quantity=0, floor_to=0)
    def send(value):
        payload = {"revision": state["revision"]}
        payload.update({"field": "sewer_elements", "value": value} if route == "answer"
                       else {"answers": {"sewer_elements": value}})
        return (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    for mixed in (False, True):
        registry[1]["service_direction"] = "unsupported" if mixed else ""
        response = send(registry)
        assert response.status_code == 422
        error = response.json()
        assert [(i["row_index"], i["field"]) for i in error["input_issues"]] == [
            (1, "element_id"), (1, "quantity"), (1, "floor_to")] + ([(1, "service_direction")] if mixed else [])
        assert error["input_message"] is not None
        if mixed:
            assert "service_direction" in error["detail"]
        assert file.read_bytes() == before
        assert client.get("/studio/api/draft").json() == state
    corrected = rows()
    corrected[1]["note"] = "TEST-ONLY: исправлено явно"
    response = send(corrected)
    assert response.status_code == 200, response.text
    saved = response.json()
    values = {r["key"]: r["value"] for r in saved["fields"]}
    assert values["sewer_elements"] == corrected
    assert saved["revision"] != state["revision"]
    if route == "calculate":
        assert saved["project_calculation"]["can_release"] is False
    else:
        assert saved["project_calculation"] is None


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
def test_only_pipes_changed_error_points_to_unchanged_elements(client, tmp_path, route):
    initial = studio_tests.new(client)
    sections = pipes()
    element = {**minimal(), "section_id": sections[0]["section_id"], "system": sections[0]["system"]}
    response = client.post("/studio/api/calculate", json={"revision": initial["revision"],
        "answers": {**building_answers(), "sewer_elements": [element], "sewer_pipes": sections}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    sections[0]["section_id"] = "renamed TEST-ONLY"
    payload = {"revision": state["revision"]}
    payload.update({"field": "sewer_pipes", "value": sections} if route == "answer"
                   else {"answers": {"sewer_pipes": sections}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422
    issue, = response.json()["input_issues"]
    assert (issue["registry"], issue["row_index"], issue["code"]) == ("sewer_elements", 0, "unknown_element_section")
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state

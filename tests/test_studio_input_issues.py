"""Structured error addresses do not change acceptance or transaction boundaries."""
from copy import deepcopy

import pytest

from app.intake import studio_risers, studio_sewer_pipes
from app.intake.registry_input_error import RegistryInputError
from app.intake.request_dto import (
    SewageRiserRequest, SewerPipeRequest, validate_sewage_risers, validate_sewer_pipes,
)
from app.intake.studio_store import StudioStore
from tests import test_studio as studio_tests
from tests.test_studio_risers import building_answers, rows as risers
from tests.test_studio_sewer_pipes import rows as pipes

client = studio_tests.client


@pytest.mark.parametrize("key", ["sewage_risers", "sewer_pipes"])
@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
def test_addresses_preserve_detail_and_atomicity(client, tmp_path, key, route):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": state["revision"],
        "answers": {**building_answers(), "sewage_risers": risers(), "sewer_pipes": pipes()}})
    assert response.status_code == 200
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    value = deepcopy(risers() if key == "sewage_risers" else pipes())
    if key == "sewage_risers":
        index, field, code = 1, "riser_id", "duplicate_riser_id"
        value[1].update(riser_id=value[0]["riser_id"], design_flow_lps=4.125)
        records = [SewageRiserRequest(**row) for row in value]
        validator = validate_sewage_risers
    else:
        index = next(i for i, row in enumerate(value) if row["section_id"] == "К1-М1")
        field, code = "wall_thickness_mm", "blocked_pipe_section"
        value[index].update(wall_thickness_mm=1000, calculation_length_m=53)
        records = [SewerPipeRequest(**row) for row in value]
        validator = validate_sewer_pipes
    original = deepcopy(records)
    issues = []
    assert validator(records) == validator(records, input_issues=issues)
    assert records == original
    assert len(issues) == 1
    payload = {"revision": state["revision"]}
    payload.update({"field": key, "value": value} if route == "answer" else {"answers": {key: value}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422
    error = response.json()
    assert isinstance(error["detail"], str)
    assert validator(records)[0] in error["detail"]
    assert error["input_issues"] == issues
    assert issues[0]["row_index"] == index
    assert issues[0]["field"] == field
    assert issues[0]["code"] == code
    assert str(index + 1) in error["input_message"]
    assert key + "[" not in error["input_message"]
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


def test_unaddressed_errors_are_not_hidden():
    from app.intake.registry_input_error import RegistryInputError
    from app.intake.studio_risers import validate_value
    value = risers()
    value[1].update(riser_id=value[0]["riser_id"], design_flow_lps=-1)
    with pytest.raises(RegistryInputError) as caught:
        validate_value(value)
    assert len(caught.value.input_issues) == 1
    assert caught.value.input_message is None
    assert "design_flow_lps" in str(caught.value)


@pytest.mark.parametrize("mode", ["unsupported", "mixed"])
def test_api_keeps_safe_fallback_for_other_errors(client, tmp_path, mode):
    state = studio_tests.new(client)
    value = risers()
    if mode == "unsupported":
        value[1]["material"] = "unknown"
    else:
        value[1]["design_flow_lps"] = -1
    if mode == "mixed":
        value[1]["riser_id"] = value[0]["riser_id"]
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    response = client.patch("/studio/api/answers", json={"revision": state["revision"],
        "answers": {"sewage_risers": value}})
    assert response.status_code == 422
    error = response.json()
    assert isinstance(error["detail"], str)
    if mode == "unsupported":
        assert "material" in error["detail"]
        assert "input_issues" not in error
    else:
        assert "design_flow_lps" in error["detail"]
        assert error["input_message"] is None
        assert len(error["input_issues"]) == 1
    assert file.read_bytes() == before


def test_multiple_duplicate_rows_keep_separate_addresses():
    from app.intake.registry_input_error import RegistryInputError
    from app.intake.studio_risers import validate_value
    value = [deepcopy(risers()[0]) for _ in range(3)]
    with pytest.raises(RegistryInputError) as caught:
        validate_value(value)
    assert [issue["row_index"] for issue in caught.value.input_issues] == [1, 2]
    assert "строка 2" in caught.value.input_message
    assert "строка 3" in caught.value.input_message


PARSERS = {"sewage_risers": (studio_risers, risers), "sewer_pipes": (studio_sewer_pipes, pipes)}
PARSER_CASES = []
for registry, (module, _) in PARSERS.items():
    for column in module.editor_columns():
        if column["required"]:
            for raw in (None, "", "  "):
                PARSER_CASES.append((registry, column["key"], raw, "required_value"))
        if column["kind"] in {"number", "integer"}:
            for raw, code in [("not-a-number", "invalid_number"), (True, "invalid_number"),
                              ("nan", "nonfinite_number"), ("1e999", "nonfinite_number")]:
                PARSER_CASES.append((registry, column["key"], raw, code))
        if column["kind"] == "integer":
            PARSER_CASES.append((registry, column["key"], "110.5", "integer_required"))


@pytest.mark.parametrize("registry,key,raw,code", PARSER_CASES)
def test_parser_addresses_all_supported_fields_without_rewriting_detail(registry, key, raw, code):
    module, factory = PARSERS[registry]
    value = factory()
    value[1][key] = raw
    before = deepcopy(value)
    parse = module.validate_value if registry == "sewage_risers" else module.validate_registry
    with pytest.raises(RegistryInputError) as caught:
        parse(value)
    label = module.LABELS[key]
    if code == "required_value":
        detail = f"{'Стояк' if registry == 'sewage_risers' else 'Участок'} 2: укажите «{label}»."
    else:
        reason = {"invalid_number": "число", "nonfinite_number": "конечное число",
                  "integer_required": "целое число"}[code]
        detail = (f"{label}: требуется {reason}." if registry == "sewage_risers"
                  else f"Участок 2: {label} — {reason}.")
    assert str(caught.value) == detail
    issue, = caught.value.input_issues
    assert (issue["code"], issue["registry"], issue["row_index"], issue["field"]) == (code, registry, 1, key)
    assert "строка 2" in caught.value.input_message
    assert label in caught.value.input_message
    assert value == before


@pytest.mark.parametrize("registry", PARSERS)
@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("code,raw", [("required_value", ""), ("invalid_number", "oops"),
    ("nonfinite_number", "nan"), ("integer_required", "110.5")])
def test_parser_http_atomicity(client, tmp_path, registry, route, code, raw):
    state = studio_tests.new(client)
    module, factory = PARSERS[registry]
    value = factory()
    key = "riser_dn_mm" if registry == "sewage_risers" else "outer_diameter_mm"
    if registry == "sewer_pipes" and code == "integer_required":
        key = "nominal_diameter_mm"
    value[1][key] = raw
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    payload = {"revision": state["revision"]}
    payload.update({"field": registry, "value": value} if route == "answer" else {"answers": {registry: value}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422
    issue, = response.json()["input_issues"]
    assert (issue["code"], issue["row_index"], issue["field"]) == (code, 1, key)
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


@pytest.mark.parametrize("registry", PARSERS)
def test_first_error_order_and_sequential_correction_preserved(registry):
    module, factory = PARSERS[registry]
    parse = module.validate_value if registry == "sewage_risers" else module.validate_registry
    value = factory()
    keys = [c["key"] for c in module.editor_columns() if c["required"]][:2]
    originals = deepcopy(value[0])
    for key in keys:
        value[0][key] = ""
    for key in keys:
        with pytest.raises(RegistryInputError) as caught:
            parse(value)
        assert len(caught.value.input_issues) == 1
        assert caught.value.input_issues[0]["field"] == key
        value[0][key] = originals[key]
    assert parse(value) == parse(factory())


@pytest.mark.parametrize("registry,field", [("sewage_risers", "has_toilet"),
    ("sewer_pipes", "insulated"), ("sewer_pipes", "pressure_rated")])
@pytest.mark.parametrize("raw", ["true", "false", "unknown", 0, 1, [], {}])
def test_boolean_types_keep_existing_strict_refusal(registry, field, raw):
    module, factory = PARSERS[registry]
    value = factory()
    value[1][field] = raw
    before = deepcopy(value)
    parse = module.validate_value if registry == "sewage_risers" else module.validate_registry
    with pytest.raises(RegistryInputError) as caught:
        parse(value)
    expected = ("Наличие унитаза: явно да или нет." if registry == "sewage_risers"
        else f"Участок 2: {module.LABELS[field]} — явно да или нет.")
    assert str(caught.value) == expected
    issue, = caught.value.input_issues
    assert (issue["code"], issue["field"], issue["row_index"]) == ("boolean_required", field, 1)
    assert value == before


@pytest.mark.parametrize("registry,field", [("sewage_risers", "has_toilet"),
    ("sewer_pipes", "insulated"), ("sewer_pipes", "pressure_rated")])
@pytest.mark.parametrize("raw", [True, False])
def test_boolean_false_is_not_missing_and_true_is_not_inferred(registry, field, raw):
    module, factory = PARSERS[registry]
    value = factory()
    value[1][field] = raw
    parse = module.validate_value if registry == "sewage_risers" else module.validate_registry
    assert parse(value)[1][field] is raw


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
@pytest.mark.parametrize("kind", ["riser_boolean", "pipe_boolean", "unlinked", "pipe_only"])
def test_link_and_boolean_http_atomicity(client, tmp_path, route, kind):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": state["revision"],
        "answers": {**building_answers(), "sewage_risers": risers(), "sewer_pipes": pipes()}})
    assert response.status_code == 200
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    before = file.read_bytes()
    registry = "sewage_risers" if kind in {"riser_boolean", "unlinked"} else "sewer_pipes"
    value = risers() if registry == "sewage_risers" else pipes()
    if kind == "riser_boolean":
        value[1]["has_toilet"] = "unknown"
        field, code = "has_toilet", "boolean_required"
    elif kind == "pipe_boolean":
        value[1]["insulated"] = "unknown"
        field, code = "insulated", "boolean_required"
    elif kind == "unlinked":
        value[1]["riser_id"] = "К1-Нет-Такого"
        field, code = "riser_id", "unlinked_riser"
    else:
        target = risers()[1]["riser_id"]
        value = [row for row in value if row["section_id"] != target]
        field, code = "riser_id", "unlinked_riser"
    payload = {"revision": state["revision"]}
    payload.update({"field": registry, "value": value} if route == "answer" else {"answers": {registry: value}})
    response = (client.post if route == "calculate" else client.patch)("/studio/api/" + route, json=payload)
    assert response.status_code == 422, response.text
    issue, = response.json()["input_issues"]
    assert (issue["code"], issue["field"], issue["row_index"]) == (code, field, 1)
    assert issue["registry"] == ("sewage_risers" if code == "unlinked_riser" else registry)
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


@pytest.mark.parametrize("target", ["unknown", "k2", "main"])
def test_unlinked_riser_still_requires_exact_k1_riser(target):
    values = {"sewer_pipes": pipes(), "sewage_risers": risers()}
    row = values["sewage_risers"][1]
    if target == "unknown":
        row["riser_id"] += "-unknown"
    else:
        pipe = next(p for p in values["sewer_pipes"] if p["section_id"] == row["riser_id"])
        if target == "k2":
            pipe["system"] = "K2"
        else:
            pipe["purpose"] = "горизонтальная магистраль"
    before = deepcopy(values)
    with pytest.raises(RegistryInputError) as caught:
        studio_risers.validate_links(values)
    assert str(caught.value) == f"{row['riser_id']}: расчётная запись не связана с введённым стояком К1."
    assert caught.value.input_issues[0]["row_index"] == 1
    assert values == before

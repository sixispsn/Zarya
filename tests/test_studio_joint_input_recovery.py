"""Four registries, sequential refusals and stale versions through real HTTP."""
from copy import deepcopy

import pytest

from app.intake.studio_store import StudioStore
from tests import test_studio as studio_tests
from tests.test_studio_risers import building_answers, rows as risers
from tests.test_studio_sewer_pipes import rows as pipes
from tests.test_studio_sewer_elements import rows as elements
from tests.test_studio_fans import evidence

client = studio_tests.client
KEYS = ("sewer_pipes", "sewer_elements", "sewage_risers", "wastewater_fan_ventilation")


def registry_values():
    return dict(zip(KEYS, (pipes(), elements(), risers(), evidence())))


def values(state):
    return {row["key"]: row["value"] for row in state["fields"]}


def initialized(client, tmp_path):
    state = studio_tests.new(client)
    response = client.post("/studio/api/calculate", json={"revision": state["revision"],
        "answers": {**building_answers(), **registry_values()}})
    assert response.status_code == 200, response.text
    state = response.json()
    file = StudioStore(tmp_path / "studio").folder(state["project_id"]) / "draft.json"
    return state, file


def edits(state):
    original = values(state)
    data = {key: deepcopy(original[key]) for key in KEYS}
    data[KEYS[0]][1]["room"] = "TEST-ONLY: совместная правка трубы"
    data[KEYS[1]][1]["note"] = "TEST-ONLY: совместная правка элемента"
    data[KEYS[2]][1]["pressure_input_source"] = "TEST-ONLY: совместная правка стояка"
    data[KEYS[3]]["external_ventilation_ref"] = "TEST-ONLY: совместная правка вентиляции"
    return data


@pytest.mark.parametrize("route", ["answers", "calculate"])
@pytest.mark.parametrize("rotation", range(4))
def test_four_registry_sequential_refusals_are_atomic_in_payload_order(client, tmp_path, route, rotation):
    state, file = initialized(client, tmp_path)
    before = file.read_bytes()
    good = edits(state)
    broken = deepcopy(good)
    bad_fields = dict(zip(KEYS, ("section_id", "element_id", "riser_id", "terminal_id")))
    for key in KEYS:
        rows = broken[key]["terminals"] if key == KEYS[3] else broken[key]
        rows[1][bad_fields[key]] = ""
    order = KEYS[rotation:] + KEYS[:rotation]
    broken = {"object_name": "TEST-ONLY: title must not partially save",
              **{key: broken[key] for key in order}}
    send = client.post if route == "calculate" else client.patch
    for key in order:
        response = send("/studio/api/" + route, json={"revision": state["revision"], "answers": broken})
        assert response.status_code == 422, response.text
        assert "input_issues" in response.json(), response.text
        issue = response.json()["input_issues"][0]
        assert (issue["registry"], issue["row_index"], issue["field"]) == (key, 1, bad_fields[key])
        assert file.read_bytes() == before
        assert client.get("/studio/api/draft").json() == state
        rows = broken[key]["terminals"] if key == KEYS[3] else broken[key]
        source = good[key]["terminals"] if key == KEYS[3] else good[key]
        rows[1][bad_fields[key]] = source[1][bad_fields[key]]
    response = send("/studio/api/" + route, json={"revision": state["revision"], "answers": broken})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == state["revision"] + 1
    assert values(saved) == {**values(state), **good, "object_name": broken["object_name"]}
    if route == "calculate":
        assert saved["project_calculation"]["can_release"] is False
    else:
        assert saved["project_calculation"] is None


@pytest.mark.parametrize("route", ["answers", "calculate"])
@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("remote_key", ["object_name", "wastewater_fan_ventilation"])
def test_stale_batch_never_overwrites_remote_or_publishes_field_addresses(client, tmp_path, route, invalid, remote_key):
    base, file = initialized(client, tmp_path)
    local = edits(base)
    if invalid:
        local["sewer_pipes"][1]["section_id"] = ""
    remote = "TEST-ONLY: other tab" if remote_key == "object_name" else {
        **values(base)[remote_key], "external_ventilation_ref": "TEST-ONLY: other tab"}
    response = client.patch("/studio/api/answers", json={"revision": base["revision"], "answers": {remote_key: remote}})
    assert response.status_code == 200, response.text
    current, before = response.json(), file.read_bytes()
    send = client.post if route == "calculate" else client.patch
    for _ in range(2):
        response = send("/studio/api/" + route, json={"revision": base["revision"], "answers": local})
        assert response.status_code == 409, response.text
        assert "input_issues" not in response.json()
        assert file.read_bytes() == before
        assert client.get("/studio/api/draft").json() == current
    # A fresh explicit, non-overlapping edit retains the other tab's value.
    response = client.patch("/studio/api/answers", json={"revision": current["revision"],
        "answers": {"sewer_elements": local["sewer_elements"]}})
    assert response.status_code == 200, response.text
    assert values(response.json())[remote_key] == remote
    assert values(response.json())["sewer_pipes"] == values(current)["sewer_pipes"]


@pytest.mark.parametrize("route", ["answer", "answers", "calculate"])
def test_different_active_project_rejects_even_matching_revision(client, tmp_path, route):
    base, original_file = initialized(client, tmp_path)
    original_bytes = original_file.read_bytes()
    # Simulate an active cookie changing in another tab, using real draft creation.
    client.cookies.clear()
    response = client.post("/studio/api/draft")
    assert response.status_code == 200, response.text
    current = response.json()
    target = StudioStore(tmp_path / "studio").folder(current["project_id"]) / "draft.json"
    before = target.read_bytes()
    payload = {"revision": current["revision"]}
    payload.update({"field": "object_name", "value": "wrong target"} if route == "answer" else {"answers": edits(base)})
    send = client.post if route == "calculate" else client.patch
    response = send("/studio/api/" + route, headers={"X-Zarya-Draft": base["project_id"]}, json=payload)
    assert response.status_code == 409, response.text[:500]
    assert target.read_bytes() == before
    assert original_file.read_bytes() == original_bytes
    # The same explicit header is accepted when it identifies the active project.
    response = client.patch("/studio/api/answer", headers={"X-Zarya-Draft": current["project_id"]},
        json={"revision": current["revision"], "field": "object_name", "value": "right target"})
    assert response.status_code == 200, response.text[:500]
    assert original_file.read_bytes() == original_bytes

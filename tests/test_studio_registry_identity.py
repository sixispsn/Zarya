"""Explicit identity changes never infer cascades or preserve stale results."""
from copy import deepcopy
from itertools import combinations

import pytest

from tests.test_studio_joint_input_recovery import client as client_fixture, initialized, values, KEYS

client = client_fixture


def renamed(state):
    source = values(state)
    data = {key: deepcopy(source[key]) for key in KEYS}
    old = data["sewage_risers"][1]["riser_id"]
    new = "К1-Переименован-TEST"
    for row in data["sewer_pipes"]:
        for key in ("section_id", "from_node", "to_node"):
            if row[key] == old:
                row[key] = new
    for row in data["sewer_elements"]:
        for key in ("section_id", "connects_to"):
            if row[key] == old:
                row[key] = new
    data["sewage_risers"][1]["riser_id"] = new
    for row in data["wastewater_fan_ventilation"]["terminals"]:
        row["riser_ids"] = [new if value == old else value for value in row["riser_ids"]]
    return data, old, new


SUBSETS = [group for count in range(1, 4) for group in combinations(KEYS, count)]


@pytest.mark.parametrize("route", ["answers", "calculate"])
@pytest.mark.parametrize("subset", SUBSETS)
def test_partial_rename_refused_without_cascade_or_partial_save(client, tmp_path, route, subset):
    state, file = initialized(client, tmp_path)
    before = file.read_bytes()
    data, _, _ = renamed(state)
    send = client.post if route == "calculate" else client.patch
    response = send("/studio/api/" + route, json={"revision": state["revision"],
        "answers": {key: data[key] for key in subset}})
    assert response.status_code == 422, response.text[:500]
    assert response.json()["input_issues"]
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state


@pytest.mark.parametrize("route", ["answers", "calculate"])
@pytest.mark.parametrize("reverse", [False, True])
def test_joint_rename_keeps_arithmetic_and_rebuilds_ids(client, tmp_path, route, reverse):
    state, _ = initialized(client, tmp_path)
    data, old, new = renamed(state)
    if reverse:
        data = dict(reversed(list(data.items())))
    send = client.post if route == "calculate" else client.patch
    response = send("/studio/api/" + route, json={"revision": state["revision"], "answers": data})
    assert response.status_code == 200, response.text[:500]
    saved = response.json()
    assert saved["revision"] == state["revision"] + 1
    assert values(saved) == {**values(state), **data}
    if route == "answers":
        assert saved["project_calculation"] is None
        response = client.post("/studio/api/calculate", json={"revision": saved["revision"]})
        assert response.status_code == 200, response.text[:500]
        saved = response.json()
    assert saved["calculation"] == state["calculation"]
    report = saved["project_calculation"]["sewage_riser_review"]["risers"]
    assert new in [r["riser_id"] for r in report]
    assert old not in [r["riser_id"] for r in report]
    assert saved["project_calculation"]["can_release"] is False


@pytest.mark.parametrize("route", ["answers", "calculate"])
@pytest.mark.parametrize("key", ["sewer_pipes", "sewage_risers", "wastewater_fan_ventilation", "all"])
def test_explicit_deletion_respects_existing_links_and_missing_data(client, tmp_path, route, key):
    state, file = initialized(client, tmp_path)
    base = values(state)
    if key == "all":
        changes = {name: None if name == KEYS[3] else [] for name in KEYS}
    elif key == KEYS[3]:
        changes = {key: {**base[key], "terminals": base[key]["terminals"][1:]}}
    else:
        changes = {key: base[key][1:]}
    before = file.read_bytes()
    send = client.post if route == "calculate" else client.patch
    response = send("/studio/api/" + route, json={"revision": state["revision"], "answers": changes})
    if key == "sewer_pipes":
        assert response.status_code == 422, response.text[:500]
        assert file.read_bytes() == before
        assert client.get("/studio/api/draft").json() == state
        return
    assert response.status_code == 200, response.text[:500]
    saved = response.json()
    for name in KEYS:
        expected = changes.get(name, base[name])
        assert values(saved)[name] == (None if expected == [] else expected)
    if route == "answers":
        assert saved["project_calculation"] is None
        response = client.post("/studio/api/calculate", json={"revision": saved["revision"]})
        assert response.status_code == 200, response.text[:500]
        saved = response.json()
    assert saved["project_calculation"]["can_release"] is False
    assert saved["project_calculation"]["sewer_scheme"]["ready"] is False

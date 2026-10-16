"""Three presentation steps preserve sources, calculations and scope limits."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.intake.studio_intake import FIELDS, extract_candidates
from tests import test_studio as studio_tests

client = studio_tests.client
new, answer, values = studio_tests.new, studio_tests.answer, studio_tests.values


def test_groups_cover_every_input_once():
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    assert node
    result = subprocess.run([node, "-e", "global.window={}; require('./app/web/static/studio_configurator.js'); console.log(JSON.stringify(window.ZaryaConfigurator.groups.map(g=>({id:g.id,keys:window.ZaryaConfigurator.allKeys(g)}))));"], capture_output=True, text=True, check=True)
    groups = json.loads(result.stdout)
    assert [g["id"] for g in groups] == ["building", "connection", "consumers"]
    keys = [k for g in groups for k in g["keys"]]
    assert len(keys) == len(set(keys))
    assert set(keys) == {f.key for f in FIELDS}
    html = Path("app/web/templates/studio.html").read_text()
    assert html.index("studio_configurator.js") < html.index("studio.js")
    assert "roof_profiles.js" not in html


def test_context_persists_without_changing_residential_demand(client):
    state = studio_tests.residential_project(client)
    original = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    state = original
    context = {"building_area_m2": 500, "building_volume_m3": 1900,
               "attic_kind": "cold", "foundation_kind": "piles",
               "geology_status": "pending", "geology_note": "Изыскания в работе",
               "permafrost": "unknown", "seismic_zone": "unknown",
               "technology_presence": "no", "building_operation": "Круглосуточный",
               "connection_note": "ТУ проверяются"}
    for key, value in context.items():
        state = answer(client, state, key, value)
    restored = client.get("/studio/api/draft").json()
    assert {key: values(restored)[key]["value"] for key in context} == context
    calculated = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert calculated["calculation"] == original["calculation"]
    assert calculated["project_calculation"]["flows"] == original["project_calculation"]["flows"]


@pytest.mark.parametrize("key,value", [("building_purpose", "mixed"), ("building_purpose", "individual"), ("technology_presence", "yes"), ("permafrost", "yes"), ("seismic_zone", "yes")])
def test_known_unsupported_context_cannot_silently_become_residential_package(client, key, value):
    state = answer(client, studio_tests.residential_project(client), key, value)
    result = client.post("/studio/api/calculate", json={"revision": state["revision"]}).json()
    assert result["calculation"]["total"]["q_day"] == 3.6  # Clearly labelled residential group only.
    assert result["project_calculation"]["state"] == "blocked"
    assert not result["project_calculation"]["can_preview"]
    handoff = client.post("/studio/api/handoff", json={"revision": result["revision"]})
    assert handoff.status_code == 422


def test_no_implied_negative_special_conditions(client):
    state = values(new(client))
    for key in ("permafrost", "seismic_zone", "geology_status", "technology_presence", "foundation_kind"):
        assert state[key]["status"] == "missing" and state[key]["value"] is None


def test_area_volume_candidates_require_explicit_source_labels():
    rows = extract_candidates("Площадь кухни 10 м². Общая площадь здания: 500 м². Строительный объём здания: 1900 м³.", "a" * 24, 1)
    assert {r["field"]: r["value"] for r in rows} == {"building_area_m2": 500., "building_volume_m3": 1900.}


@pytest.mark.parametrize("key,value", [("building_area_m2", -1), ("building_volume_m3", "nan"), ("foundation_kind", "guess"), ("seismic_zone", True)])
def test_new_input_validation(client, key, value):
    state = new(client)
    result = client.patch("/studio/api/answer", json={"revision": state["revision"], "field": key, "value": value})
    assert result.status_code == 422

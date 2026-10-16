"""An unresolved fire input after PDF upload is a question, not an HTTP 500."""
import pytest

from app.intake.fire_applicability import calculate_request_fire
from app.intake.studio_intake import (
    answer_field, build_handoff_request, fire_missing, public_draft,
)
from app.intake.studio_project import calculate_project
from app.intake.yaml_io import dump_request, load_request
from tests import test_studio as api_tests
from tests.test_studio_apartment_meters import draft

client = api_tests.client


@pytest.mark.parametrize("floors,height,needs_corridor", [
    (2, 4.8, False), (9, 27, False), (12, 30, True), (15, 45, True),
    (16, 50, True), (17, 50, False), (9, 31, True), (12, 51, False),
])
def test_conditional_question_uses_canonical_table(floors, height, needs_corridor):
    d = draft(floors=floors, fire_height_m=height, building_height_m=height + 3)
    assert bool(fire_missing(d)) is needs_corridor
    state = public_draft(d)
    assert ("fire_corridor_length_m" in state["handoff_missing"]) is needs_corridor
    assert any("fire_corridor_length_m" in step["fields"]
               for step in state["next_steps"]) is needs_corridor
    if needs_corridor:
        assert calculate_project(d)["state"] == "needs_inputs"
        assert d["calculation"]["sewage_flow"] == 2.293


def test_topology_is_asked_only_when_fire_is_required_and_not_guessed():
    low = draft()
    assert "fire_topology" not in public_draft(low)["handoff_missing"]
    high = draft(floors=17, building_height_m=54, fire_height_m=50)
    state = public_draft(high)
    assert "fire_topology" in state["handoff_missing"]
    assert calculate_project(high)["state"] == "needs_inputs"
    assert high["calculation"]["sewage_flow"] == 2.293
    high["preview"] = {"id": "stale"}
    answer_field(high, "fire_topology", "separate")
    assert high["preview"] is None
    assert build_handoff_request(high).fire_topology == "separate"
    answer_field(high, "fire_topology", None)
    assert "fire_topology" in public_draft(high)["handoff_missing"]


@pytest.mark.parametrize("topology,coefficient", [
    ("separate", .3), ("pre_meter_branch", .3), ("combined", .2),
])
def test_explicit_topology_controls_approved_local_losses(topology, coefficient):
    d = draft(floors=15, fire_height_m=45, building_height_m=48,
              fire_corridor_length_m=12, fire_topology=topology)
    restored = load_request(dump_request(build_handoff_request(d)))
    assert restored.fire_topology == topology
    assert restored.fire_category == "residential_f13"
    result = calculate_project(d)
    assert result["fire"]["network_topology"] == topology
    assert all(path["head"]["km"] == coefficient for path in result["head"]["paths"])


def test_old_implicit_topology_cache_cannot_show_current_preview(client, monkeypatch):
    from types import SimpleNamespace
    from app.web import studio
    d = draft(floors=17, building_height_m=54, fire_height_m=50)
    d["project_calculation"] = {"state": "calculated", "can_preview": True,
                                "preview_notes": [], "sewer_scheme": {"presentation": "representative"}}
    d["preview"] = {"id": "old", "documents": [{"name": "old.pdf"}]}
    monkeypatch.setattr(studio, "store", lambda request=None: SimpleNamespace(load=lambda _: d))
    state = client.get("/studio/api/draft").json()
    assert state["project_calculation"]["state"] == "needs_inputs"
    assert state["preview"] is None
    assert client.get("/studio/api/preview/old/files/old.pdf").status_code == 404
    assert d["preview"]["id"] == "old"  # no destructive read-time migration


@pytest.mark.parametrize("length,streams", [(0, 1), (10, 1), (10.01, 2), (25, 2)])
def test_answer_survives_yaml_without_inventing_rooms(length, streams):
    d = draft(floors=15, fire_height_m=45, building_height_m=48)
    answer_field(d, "fire_corridor_length_m", length)
    answer_field(d, "fire_topology", "separate")
    req = build_handoff_request(d)
    assert not req.rooms and req.network is None
    assert not fire_missing(d)
    assert calculate_request_fire(req).streams == streams
    restored = load_request(dump_request(req))
    assert restored.fire_corridor_length_m == length
    assert not restored.rooms
    assert calculate_request_fire(restored) == calculate_request_fire(req)
    assert calculate_project(d)["state"] == "calculated"


def test_expected_domain_refusal_keeps_demand(monkeypatch):
    def refuse(_):
        raise ValueError("Уточните исходные данные для В2")
    monkeypatch.setattr("app.intake.studio_project.build_project", refuse)
    d = draft()
    result = calculate_project(d)
    assert result["state"] == "blocked" and not result["can_preview"]
    assert result["issues"][0]["message"] == "Уточните исходные данные для В2"
    assert d["calculation"]["sewage_flow"] == 2.293


def test_uploaded_pdf_calculates_then_asks_and_recovers(client, tmp_path, monkeypatch):
    from app.intake.project_store import ProjectStore
    monkeypatch.setattr("app.web.wizard._STORE", ProjectStore(tmp_path / "projects"))
    state = api_tests.new(client)
    state = api_tests.upload(client, state, "Этажность: 15. Количество жителей: 20.")
    document_id = state["documents"][0]["id"]
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": {
            "floors": 15, "residents": 20, "apartments": 8,
            "consumer_code": "residential_full_bath", "hws_type": "central",
            "building_height_m": 48, "fire_height_m": 45,
        },
    })
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["calculation"]["total"]["q_day"] == 3.6
    assert state["project_calculation"]["missing"] == ["fire_corridor_length_m"]
    assert state["documents"][0]["id"] == document_id
    assert any(step["id"] == "fire" for step in state["next_steps"])
    response = client.post("/studio/api/calculate", json={
        "revision": state["revision"], "answers": {"fire_corridor_length_m": 12, "fire_topology": "separate"},
    })
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["project_calculation"]["state"] == "calculated"
    assert state["project_calculation"]["fire"]["streams"] == 2
    assert state["documents"][0]["id"] == document_id
    assert not any(step["id"] == "fire" for step in state["next_steps"])
    response = client.post("/studio/api/handoff", json={"revision": state["revision"]})
    assert response.status_code == 200, response.text
    form = client.get(response.json()["next_url"]).text
    assert 'name="fire_corridor_length_m" value="12.0"' in form

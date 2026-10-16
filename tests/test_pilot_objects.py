"""Explicit consent, immutable snapshots, ownership, retries, provenance and limits."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import uuid

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.intake.pilot_access import Principal
from app.intake.pilot_objects import PilotObjectStore, calculation_stamp, make_snapshot
from app.intake.studio_intake import answer_field
from app.intake.studio_store import StudioStore
from tests.test_pilot_access import pilot as pilot_fixture, client_for, draft, WRITE, ORIGIN

pilot = pilot_fixture


def setup(client):
    state = draft(client)
    result = client.post("/studio/api/calculate", headers=WRITE, json={"revision": state["revision"], "answers": {
        "residents": 20, "consumer_code": "residential_full_bath", "floors": 2, "apartments": 8,
        "building_height_m": 6.6, "fire_height_m": 4.8, "hws_type": "central",
    }})
    assert result.status_code == 200, result.text
    return result.json()


def payload(client, **changes):
    preview = client.get("/studio/api/pilot-snapshot")
    assert preview.status_code == 200, preview.text
    data = preview.json()
    return {"revision": data["revision"], "snapshot_sha256": data["snapshot_sha256"],
            "request_id": uuid.uuid4().hex, "title": "Дом-01", "note": "Проверка расходов", "consent": True, **changes}


def save(client, data):
    return client.post("/studio/api/pilot-versions", json=data, headers=WRITE)


def test_version_is_immutable_and_working_draft_is_untouched(pilot):
    access, users, root = pilot
    alice = client_for(users["alice"][1])
    state = setup(alice)
    did = access.active_draft(users["alice"][0])
    path = root / "studio" / "_users" / users["alice"][0] / did / "draft.json"
    original = path.read_bytes()
    first = save(alice, payload(alice)).json()
    assert path.read_bytes() == original
    assert alice.get(first["url"]).status_code == 200
    archive = PilotObjectStore()
    user = Principal(users["alice"][0], "Алиса", "tester", did)
    before = archive.version(user, first["object_id"], 1)[1]
    assert before["snapshot"]["results"]["demand"]["total"]["q_day"] == 3.6
    result = alice.post("/studio/api/calculate", headers=WRITE, json={"revision": state["revision"], "answers": {"residents": 40}})
    assert result.status_code == 200
    second = save(alice, payload(alice, object_id=first["object_id"], title="", note="Уточнены жители")).json()
    assert second["version"] == 2 and second["object_id"] == first["object_id"]
    assert archive.version(user, first["object_id"], 1)[1] == before
    assert archive.version(user, first["object_id"], 2)[1]["snapshot"]["results"]["demand"]["total"]["q_day"] == 7.2
    with access.connect() as db, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE pilot_versions SET note='overwrite'")


def test_shared_only_with_owner_and_no_write_on_behalf_of_tester(pilot):
    _, users, _ = pilot
    alice, bob, owner = [client_for(users[name][1]) for name in ("alice", "bob", "owner")]
    setup(alice)
    first = save(alice, payload(alice, title="Секретный псевдоним")).json()
    assert "Секретный псевдоним" in alice.get("/studio/pilot-objects").text
    assert "Секретный псевдоним" in owner.get("/studio/pilot-objects").text
    assert "Секретный псевдоним" not in bob.get("/studio/pilot-objects").text
    for path in (first["url"], f"/studio/pilot-objects/{first['object_id']}"):
        assert bob.get(path).status_code == 404
        assert owner.get(path).status_code == 200
        assert "no-store" in owner.get(path).headers["cache-control"]
    for client in (bob, owner):
        setup(client)
        assert save(client, payload(client, object_id=first["object_id"])).status_code == 404
        assert not client.get("/studio/api/pilot-snapshot").json()["objects"]


def test_consent_and_source_allowlist(pilot):
    access, users, root = pilot
    alice = client_for(users["alice"][1])
    setup(alice)
    did = access.active_draft(users["alice"][0])
    storage = StudioStore(root / "studio" / "_users" / users["alice"][0])
    with storage.edit(did, storage.load(did)["revision"]) as state:
        state["documents"] = [{"id": "a"*24, "name": "PRIVATE_FILENAME.pdf", "candidates": [{"field": "floors", "value": 2, "document_id": "a"*24, "page": 1, "quote": "PRIVATE_QUOTE"}]}]
        answer_field(state, "floors", 2)
        answer_field(state, "object_name", "PRIVATE_ORIGINAL_TITLE")
    preview = alice.get("/studio/api/pilot-snapshot")
    assert all(text not in preview.text for text in ("PRIVATE_FILENAME", "PRIVATE_QUOTE", "PRIVATE_ORIGINAL_TITLE", "a"*24, "evidence", "candidates"))
    assert preview.json()["snapshot"]["results"]["state"] == "needs_recalculation"
    assert save(alice, payload(alice, consent=False)).status_code == 422
    assert not PilotObjectStore().objects(Principal(users["alice"][0], "Алиса", "tester", did))[0]
    result = save(alice, payload(alice))
    assert result.status_code == 200
    assert "только исходные" in alice.get(result.json()["url"]).text


def test_retries_after_lost_reply_and_draft_change_are_idempotent(pilot):
    alice = client_for(pilot[1]["alice"][1])
    state = setup(alice)
    data = payload(alice)
    first = save(alice, data)
    assert first.status_code == 200
    assert save(alice, {**data, "request_id": uuid.uuid4().hex}).json() == first.json()
    alice.patch("/studio/api/answer", headers=WRITE, json={"revision": state["revision"], "field": "residents", "value": 30})
    assert save(alice, data).json() == first.json()
    assert save(alice, {**data, "note": "Другая цель"}).status_code == 409
    versions = alice.get(f"/studio/pilot-objects/{first.json()['object_id']}")
    assert "Версия 2" not in versions.text


def test_old_preview_and_build_change_cannot_be_saved_unseen(pilot, monkeypatch):
    alice = client_for(pilot[1]["alice"][1])
    state = setup(alice)
    data = payload(alice)
    monkeypatch.setenv("ZARYA_BUILD_COMMIT", "changed-build")
    assert save(alice, data).status_code == 409
    preview = alice.get("/studio/api/pilot-snapshot").json()
    assert preview["snapshot"]["results"] == {"state": "needs_recalculation", "demand": None, "project": None}
    data = payload(alice)
    alice.patch("/studio/api/answer", headers=WRITE, json={"revision": state["revision"], "field": "residents", "value": 30})
    assert save(alice, data).status_code == 409


@pytest.mark.parametrize("changes", [{"consent": "true"}, {"consent": 1}, {"title": " "}, {"title": "a"*121}, {"note": "a"*1001}, {"request_id": "../bad"}, {"object_id": "../bad"}, {"snapshot_sha256": "f"*64}, {"user_id": "forged"}, {"snapshot": {"forged": True}}, {"revision": True}])
def test_invalid_or_forged_request(pilot, changes):
    alice = client_for(pilot[1]["alice"][1])
    setup(alice)
    assert save(alice, payload(alice, **changes)).status_code in (409, 422)


def test_auth_origin_rate_body_limit_and_disabled_mode(pilot, monkeypatch):
    alice = client_for(pilot[1]["alice"][1])
    setup(alice)
    data = payload(alice)
    assert TestClient(app, base_url=ORIGIN).post("/studio/api/pilot-versions", json=data, headers=WRITE).status_code == 401
    assert alice.post("/studio/api/pilot-versions", json=data, headers={**WRITE, "Origin":"https://evil.test"}).status_code == 403
    assert alice.post("/studio/api/pilot-versions", content=b"x"*16385, headers=WRITE).status_code == 413
    for i in range(20):
        assert save(alice, {**data, "request_id": uuid.uuid4().hex, "title": f"Дом {i}"}).status_code == 200
    assert save(alice, {**data, "title":"Лимит"}).status_code == 429
    monkeypatch.setenv("ZARYA_PILOT_ENABLED", "0")
    for path in ("/studio/pilot-objects", "/studio/api/pilot-snapshot"):
        assert alice.get(path).status_code == 404
    assert save(alice, data).status_code == 404
    assert "pilot-snapshot" not in alice.get("/studio").text


def test_concurrent_first_save_and_version_numbers(pilot):
    uid = pilot[1]["alice"][0]
    user = Principal(uid, "Алиса", "tester", None)
    archive = PilotObjectStore()
    params = dict(request_id="1"*32, intent="2"*64, object_id=None, title="Дом", note="", snapshot={"test":1})
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: archive.add(user, **params), range(4)))
    assert all(row == receipts[0] for row in receipts)
    oid = receipts[0]["object_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda n: archive.add(user, **{**params, "object_id": oid, "request_id":str(n)*32, "intent":str(n)*64}), range(3, 7)))
    assert sorted(row["version"] for row in receipts) == [2,3,4,5]


def test_render_escapes_content_and_data_is_durable(pilot):
    access, users, _ = pilot
    alice = client_for(users["alice"][1])
    setup(alice)
    saved = save(alice, payload(alice, title="<script>alert(1)</script>", note="<img src=x onerror=alert(2)>")).json()
    for path in ("/studio/pilot-objects", saved["url"]):
        html = alice.get(path).text
        assert "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in alice.get(saved["url"]).text
    assert client_for(users["alice"][1]).get(saved["url"]).status_code == 200
    assert access.path.stat().st_mode & 0o777 == 0o600


def test_inputs_and_calculation_stamp_no_false_current_result():
    state = {"revision": 0, "documents": [], "answers": {}, "calculation": {"old": True}, "project_calculation": {}}
    assert make_snapshot(state)["results"]["state"] == "needs_recalculation"
    state["calculation_stamp"] = calculation_stamp(state)
    assert make_snapshot(state)["results"]["state"] == "current"
    answer_field(state, "residents", 25)
    assert make_snapshot(state)["results"]["state"] == "needs_recalculation"
    state["study"] = {"kind":"two"}
    with pytest.raises(ValueError, match="Учебный"):
        make_snapshot(state)

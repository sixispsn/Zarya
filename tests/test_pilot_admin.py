import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from app.intake.pilot_access import Principal
from app.intake.pilot_admin import PARTICIPATION, PilotAdminStore
from tests.test_pilot_access import pilot as pilot_fixture, client_for, draft, LOGIN, WRITE, ORIGIN

pilot = pilot_fixture


def invitation(owner, **changes):
    body = {"operation": "issue", "name": "Инженер", "days": 30, "request_id": uuid.uuid4().hex, **changes}
    return owner.post("/access/admin", json=body, headers=LOGIN), body


def accept(client):
    r = client.post("/access/participation", json={"accepted": True, "version": PARTICIPATION}, headers=LOGIN)
    assert r.status_code == 200, r.text


def test_owner_invites_consent_gates_and_secrets_not_stored(pilot):
    access, users, _ = pilot
    owner = client_for(users["owner"][1])
    r, body = invitation(owner)
    assert r.status_code == 200, r.text
    uid, key = r.json()["user_id"], r.json()["key"]
    assert key.startswith("zarya_")
    tester = client_for(key)
    assert tester.post("/studio/api/draft", headers=WRITE).status_code == 403
    assert tester.get("/studio", headers={"Accept":"text/html"}, follow_redirects=False).headers["location"] == "/access/participation"
    html = tester.get("/access/participation").text
    assert "Исходные загруженные" in html and 'name="accepted" required' in html
    assert 'name="accepted" checked' not in html
    assert tester.post("/access/participation", json={"accepted": False, "version":PARTICIPATION}, headers=LOGIN).status_code == 422
    accept(tester)
    assert draft(tester)["revision"] == 0
    assert tester.get("/wizard/projects").status_code == 403
    assert tester.get("/access/admin").status_code == 403
    assert tester.post("/access/admin", json=body, headers=LOGIN).status_code == 403
    retry = owner.post("/access/admin", json=body, headers=LOGIN)
    assert retry.json() == {"user_id":uid,"key":None,"repeated":True}
    assert key.encode() not in access.path.read_bytes()
    assert key not in owner.get("/access/admin").text
    assert key not in json.dumps(PilotAdminStore().users())


def test_reissue_and_revoke_preserve_identity_and_draft(pilot):
    access, users, _ = pilot
    owner = client_for(users["owner"][1])
    created, _ = invitation(owner)
    uid, key = created.json()["user_id"], created.json()["key"]
    tester = client_for(key)
    accept(tester)
    draft(tester)
    did = access.active_draft(uid)
    replacement, _ = invitation(owner, operation="reissue", user_id=uid)
    assert replacement.status_code == 200
    assert tester.get("/studio/api/draft").status_code == 401
    second = client_for(replacement.json()["key"])
    assert second.get("/studio/api/draft").status_code == 200
    assert access.active_draft(uid) == did
    revoked, _ = invitation(owner, operation="revoke", user_id=uid)
    assert revoked.status_code == 200 and second.get("/studio/api/draft").status_code == 401
    assert access.active_draft(users["owner"][0]) is None
    forbidden, _ = invitation(owner, operation="revoke", user_id=users["owner"][0])
    assert forbidden.status_code == 422


def test_concurrent_lost_response_creates_only_one_key(pilot):
    _, users, _ = pilot
    uid = users["owner"][0]
    owner = Principal(uid, "Владелец", "admin", None)
    admin = PilotAdminStore()
    args = dict(request_id=uuid.uuid4().hex, operation="issue", name="Один")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: admin.operate(owner, **args), range(2)))
    assert len({r["user_id"] for r in results}) == 1
    assert sum(r["key"] is not None for r in results) == 1


def test_admin_csrf_body_limits_and_no_role_escalation(pilot):
    _, users, _ = pilot
    owner = client_for(users["owner"][1])
    assert owner.post("/access/admin", json={}, headers={**LOGIN, "Origin":"https://evil.test"}).status_code == 403
    assert owner.post("/access/admin", content="x"*8193, headers=LOGIN).status_code == 413
    r, _ = invitation(owner, role="admin")
    assert r.status_code == 422


def test_personal_login_disabled_on_single_entry_deployment_is_closed(monkeypatch):
    monkeypatch.setenv("ZARYA_REQUIRE_PILOT", "1")
    monkeypatch.setenv("ZARYA_PILOT_ENABLED", "0")
    client = TestClient(app, base_url=ORIGIN)
    for path in ["/", "/studio", "/wizard/projects", "/docs", "/static/studio.js", "/access/login"]:
        assert client.get(path).status_code == 503

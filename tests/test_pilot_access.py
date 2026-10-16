"""Real two-client authorization tests, including direct legacy/file access."""
from concurrent.futures import ThreadPoolExecutor
import json
import io
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest
from reportlab.pdfgen import canvas

from app.main import app
from app.intake.pilot_access import AccessStore, IDLE_SECONDS
from app.intake.studio_store import StudioStore
from app.intake.project_store import ProjectStore
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.web import wizard, studio

ORIGIN = "https://testserver"
WRITE = {"X-Zarya-Studio": "1", "Origin": ORIGIN}
LOGIN = {"X-Zarya-Access": "1", "Origin": ORIGIN}


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setenv("ZARYA_PILOT_ENABLED", "1")
    monkeypatch.setenv("ZARYA_PILOT_DIR", str(tmp_path / "access"))
    monkeypatch.setenv("ZARYA_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("ZARYA_STUDIO_ENABLED", "1")
    monkeypatch.setenv("ZARYA_NORMATIVE_MONITOR_ENABLED", "0")
    monkeypatch.setattr(wizard, "_STORE", ProjectStore(str(tmp_path / "legacy")))
    access = AccessStore()
    alice, ak = access.issue("Алиса")
    bob, bk = access.issue("Борис")
    owner, ok = access.issue("Владелец", role="admin")
    return access, {"alice": (alice, ak), "bob": (bob, bk), "owner": (owner, ok)}, tmp_path


def client_for(key):
    client = TestClient(app, base_url=ORIGIN)
    result = client.post("/access/login", json={"key": key}, headers=LOGIN)
    assert result.status_code == 200, result.text
    return client


def draft(client):
    result = client.post("/studio/api/draft", headers=WRITE)
    assert result.status_code == 200, result.text
    return result.json()


def pdf_bytes():
    target = io.BytesIO()
    doc = canvas.Canvas(target)
    doc.drawString(60, 800, "Private test PDF")
    doc.save()
    return target.getvalue()


def test_session_is_opaque_private_revocable_and_recoverable(pilot):
    access, users, root = pilot
    uid, key = users["alice"]
    alice = client_for(key)
    response = alice.post("/access/login", json={"key": key}, headers=LOGIN)
    cookie = response.headers["set-cookie"]
    assert all(flag in cookie for flag in ["HttpOnly", "Secure", "SameSite=strict", "Path=/"])
    token = alice.cookies.get("zarya_pilot_session")
    state = draft(alice)
    result = alice.patch("/studio/api/answer", json={"revision": state["revision"], "field": "object_name", "value": "Дом Алисы"}, headers=WRITE)
    assert result.status_code == 200
    did = access.active_draft(uid)
    assert (root / "studio" / "_users" / uid / did / "draft.json").is_file()
    # A browser change does not lose the personal draft, nor adopt another cookie.
    second = client_for(key)
    second.cookies.set(studio.COOKIE, "e" * 32, path="/studio")
    assert "Дом Алисы" in second.get("/studio/projects").text
    assert second.get("/studio/api/draft").json() == result.json()
    assert "Дом Алисы" not in client_for(users["bob"][1]).get("/studio/projects").text
    raw = access.path.read_bytes()
    assert key.encode() not in raw and token.encode() not in raw
    access.revoke(uid)
    assert alice.get("/studio/api/draft").status_code == 401
    assert second.get("/studio/api/draft").status_code == 401
    assert alice.post("/access/login", json={"key": key}, headers=LOGIN).status_code == 401
    # Reissue restores identity, not a different empty account.
    same_uid, replacement = access.issue("Алиса", user_id=uid)
    assert same_uid == uid
    assert "Дом Алисы" in client_for(replacement).get("/studio/projects").text


@pytest.mark.parametrize("path", [
    "/studio", "/studio/api/draft", "/studio/projects", "/wizard/projects",
    "/wizard/open/abc", "/wizard/file/abc/file.pdf", "/wizard/view/abc/file.pdf",
    "/p/abc", "/docs", "/openapi.json", "/api/water-demand",
])
def test_unauthenticated_cannot_read_any_project_surface(pilot, path):
    client = TestClient(app, base_url=ORIGIN)
    assert client.get(path).status_code == 401
    response = client.get(path, headers={"Accept": "text/html"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/access/login"


def test_login_page_is_white_accessible_and_no_secret_in_url(pilot):
    client = TestClient(app, base_url=ORIGIN)
    response = client.get("/access/login")
    assert response.status_code == 200
    assert 'type="password"' in response.text and "альфа 0.02" in response.text
    assert 'aria-live="polite"' in response.text
    assert "no-store" in response.headers["cache-control"]
    assert client.get("/static/pilot.css").status_code == 200


def test_legacy_archive_and_files_are_admin_only_and_not_auto_claimed(pilot):
    access, users, root = pilot
    pid = wizard._STORE.save(IOS2Request(
        document=DocumentRequest("ТЕСТ", "Старый секретный проект", "Москва"),
        building_type="residential", floors=2, building_height_m=6.6,
    ))
    old_store = StudioStore(root / "studio")
    old_id, _ = old_store.create()
    original = (old_store.folder(old_id) / "draft.json").read_bytes()
    alice = client_for(users["alice"][1])
    alice.cookies.set(studio.COOKIE, old_id, path="/studio")
    assert alice.get("/studio/api/draft").json() == {"draft": None}
    assert "Старый секретный" not in alice.get("/studio/projects").text
    for path in [f"/studio/archive/{pid}/source.yaml", "/wizard/projects", f"/wizard/open/{pid}",
                 "/wizard/file/abc/file.pdf", "/wizard/view/abc/file.pdf", "/p/abc",
                 "/wizard/architecture", "/wizard/analyze", "/docs", "/openapi.json"]:
        assert alice.get(path).status_code == 403, path
    assert alice.post(f"/wizard/projects/{pid}/delete", headers=WRITE).status_code == 403
    assert alice.post("/studio/api/handoff", headers=WRITE, json={"revision": 0}).status_code == 403
    assert wizard._STORE.exists(pid)
    assert original == (old_store.folder(old_id) / "draft.json").read_bytes()
    owner = client_for(users["owner"][1])
    assert "Старый секретный" in owner.get("/studio/projects").text
    assert owner.get(f"/studio/archive/{pid}/source.yaml").status_code == 200
    assert owner.get(f"/wizard/open/{pid}").status_code == 200


def test_two_users_cannot_read_or_mutate_each_others_uploads_or_previews(pilot, monkeypatch):
    access, users, root = pilot
    alice = client_for(users["alice"][1])
    bob = client_for(users["bob"][1])
    state = draft(alice)
    upload = alice.post("/studio/api/files", data={"revision": state["revision"]},
                        files={"files": ("private.pdf", pdf_bytes(), "application/pdf")}, headers=WRITE)
    assert upload.status_code == 200, upload.text
    doc_id = upload.json()["documents"][0]["id"]
    url = f"/studio/api/files/{doc_id}"
    assert alice.get(url).status_code == 200
    assert bob.get(url).status_code == 404
    bob.cookies.set(studio.COOKIE, access.active_draft(users["alice"][0]), path="/studio")
    bstate = draft(bob)
    assert bstate["documents"] == []
    assert bob.get(url).status_code == 404
    # Exercise real file authorization with a stored preview, no renderer mocks.
    uid = users["alice"][0]
    scoped = StudioStore(root / "studio" / "_users" / uid)
    did = access.active_draft(uid)
    preview_id = "a" * 32
    folder = scoped.folder(did) / "previews" / preview_id
    folder.mkdir(parents=True)
    (folder / "private.pdf").write_bytes(pdf_bytes())
    with scoped.edit(did, upload.json()["revision"]) as saved:
        saved["project_calculation"] = {"handoff_version": studio.STUDIO_HANDOFF_VERSION}
        saved["preview"] = {"id": preview_id, "documents": [{"name": "private.pdf"}],
                            "render_version": studio.DOCUMENT_RENDER_VERSION,
                            "handoff_version": studio.STUDIO_HANDOFF_VERSION,
                            "stamp": studio.calculation_stamp(saved)}
    preview = f"/studio/api/preview/{preview_id}/files/private.pdf"
    assert alice.get(preview).status_code == 200
    assert bob.get(preview).status_code == 404
    with monkeypatch.context() as changed_build:
        changed_build.setenv("ZARYA_BUILD_COMMIT", "another-build")
        assert alice.get(preview).status_code == 404
    assert alice.get(preview).status_code == 200
    with pytest.raises(HTTPException):
        studio.store()  # no request context must not fall back to shared storage


def test_cross_site_mutations_preflight_and_http_are_rejected(pilot):
    _, users, _ = pilot
    alice = client_for(users["alice"][1])
    for headers in [{}, {**WRITE, "Origin": "https://evil.example"},
                    {**WRITE, "Origin": "http://testserver"},
                    {**WRITE, "Sec-Fetch-Site": "cross-site"},
                    {**WRITE, "Origin": "null"}]:
        result = alice.post("/studio/api/draft", headers=headers)
        assert result.status_code == 403
    response = alice.options("/studio/api/draft", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    assert TestClient(app).get("/studio").status_code == 400
    assert TestClient(app).get("/health").status_code == 200
    assert alice.get("/studio", headers={"Origin": "https://evil.example"}).headers.get("access-control-allow-credentials") is None


def test_logout_and_expiry(pilot, monkeypatch):
    access, users, _ = pilot
    alice = client_for(users["alice"][1])
    token = alice.cookies.get("zarya_pilot_session")
    result = alice.post("/access/logout", headers=WRITE, follow_redirects=False)
    assert result.status_code == 303
    assert access.authenticate(token) is None
    response = alice.post("/access/login", json={"key": users["alice"][1], "remember_device": False}, headers=LOGIN)
    assert response.status_code == 200
    token = alice.cookies.get("zarya_pilot_session")
    import time
    now = time.time()
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now + IDLE_SECONDS + 1)
    assert access.authenticate(token) is None


def test_login_throttled_and_reissue_revokes_all_sessions(pilot):
    access, users, _ = pilot
    alice = client_for(users["alice"][1])
    token = alice.cookies.get("zarya_pilot_session")
    uid, new_key = access.issue("Алиса", user_id=users["alice"][0])
    assert access.authenticate(token) is None
    assert client_for(new_key).get("/studio").status_code == 200
    unauth = TestClient(app, base_url=ORIGIN)
    for _ in range(18):
        assert unauth.post("/access/login", json={"key": "wrong"}, headers=LOGIN).status_code == 401
    assert unauth.post("/access/login", json={"key": new_key}, headers=LOGIN).status_code == 429


def test_first_draft_is_shared_between_own_tabs_not_between_users(pilot):
    access, users, root = pilot
    first, second = client_for(users["alice"][1]), client_for(users["alice"][1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(draft, [first, second]))
    assert result[0] == result[1]
    personal = root / "studio" / "_users" / users["alice"][0]
    assert len(list(personal.glob("*/draft.json"))) == 1


def test_study_switch_return_and_stale_tab_are_personal(pilot):
    access, users, _ = pilot
    uid, key = users["alice"]
    alice = client_for(key)
    state = draft(alice)
    original = access.active_draft(uid)
    state = alice.post("/studio/api/study", json={"kind": "two", "revision": state["revision"]}, headers=WRITE).json()
    study_id = access.active_draft(uid)
    assert study_id != original and state["study"]["kind"] == "two"
    resumed = client_for(key)
    assert resumed.get("/studio/api/draft").json()["study"]["kind"] == "two"
    result = resumed.post("/studio/api/study/exit", json={"revision": state["revision"]}, headers=WRITE)
    assert result.status_code == 200 and access.active_draft(uid) == original
    state = result.json()
    saved = alice.patch("/studio/api/answer", json={"revision": state["revision"], "field": "residents", "value": 20}, headers=WRITE)
    assert saved.status_code == 200
    stale = resumed.patch("/studio/api/answer", json={"revision": state["revision"], "field": "residents", "value": 30}, headers=WRITE)
    assert stale.status_code == 409


def test_package_files_are_personal_even_when_legacy_store_is_shared(pilot, monkeypatch):
    access, users, root = pilot
    alice, bob = client_for(users["alice"][1]), client_for(users["bob"][1])
    draft(alice)
    draft(bob)
    uid = users["alice"][0]
    scoped = StudioStore(root / "studio" / "_users" / uid)
    did = access.active_draft(uid)
    run_id = "b" * 10
    path = root / "package.pdf"
    path.write_bytes(pdf_bytes())
    with scoped.edit(did, 0) as saved:
        saved["package"] = {"state": "ready", "run_id": run_id, "documents": [{"name": "package.pdf"}],
                            "render_version": studio.DOCUMENT_RENDER_VERSION,
                            "handoff_version": studio.STUDIO_HANDOFF_VERSION,
                            "stamp": studio.calculation_stamp(saved)}
    monkeypatch.setattr(wizard, "_get_run", lambda _: {"id": run_id})
    monkeypatch.setattr(wizard, "_run_file", lambda *_: path)
    for suffix in ["files/package.pdf", "download"]:
        url = f"/studio/api/package/{run_id}/{suffix}"
        assert alice.get(url).status_code == 200
        assert bob.get(url).status_code == 404
    access.revoke(uid)
    assert alice.get(url).status_code == 401


def test_absolute_expiry_applies_even_with_activity_and_expired_key_cannot_login(pilot, monkeypatch):
    import time
    access, users, _ = pilot
    alice = TestClient(app, base_url=ORIGIN)
    response = alice.post("/access/login", json={"key": users["alice"][1], "remember_device": False}, headers=LOGIN)
    assert response.status_code == 200
    token = alice.cookies.get("zarya_pilot_session")
    now = time.time()
    # Advance in small increments so the session never goes idle.
    for hour in range(1, 169):
        monkeypatch.setattr("app.intake.pilot_access.time.time", lambda hour=hour: now + hour * 3600)
        assert (access.authenticate(token) is not None) == (hour < 168)
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now + 31 * 86400)
    assert access.login(users["alice"][1], "fresh-address") is None


def test_cli_does_not_print_secret_and_writes_restricted_new_file(pilot):
    access, _, root = pilot
    output = root / "invitation.txt"
    command = [sys.executable, "-m", "scripts.pilot_access", "issue", "--name", "Тест CLI", "--output", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    key = output.read_text().strip()
    assert key.startswith("zarya_") and key not in result.stdout and key not in result.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    assert key.encode() not in access.path.read_bytes()
    before = len(access.list_users())
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert len(access.list_users()) == before and output.read_text().strip() == key
    listing = subprocess.run([sys.executable, "-m", "scripts.pilot_access", "list"], capture_output=True, text=True, check=True)
    assert key not in listing.stdout and "key_hash" not in listing.stdout
    assert any(row["name"] == "Тест CLI" for row in json.loads(listing.stdout))


def test_access_store_failure_fails_closed(pilot, monkeypatch):
    from app.web import pilot as web
    def broken():
        raise sqlite3.OperationalError("sensitive path must not leak")
    monkeypatch.setattr(web, "AccessStore", broken)
    response = TestClient(app, base_url=ORIGIN).get("/wizard/projects")
    assert response.status_code == 503 and "sensitive" not in response.text


def test_disabled_feature_preserves_single_owner_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("ZARYA_PILOT_ENABLED", "0")
    monkeypatch.setenv("ZARYA_STUDIO_DIR", str(tmp_path))
    client = TestClient(app)
    assert client.get("/studio").status_code == 200
    assert client.get("/access/login").status_code == 404
    assert client.post("/studio/api/draft", headers={"X-Zarya-Studio": "1"}).status_code == 200

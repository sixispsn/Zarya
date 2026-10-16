"""Remembered-device lifetime, short sessions, key bounds and safe migration."""
import sqlite3
import time

from fastapi.testclient import TestClient

from app.main import app
from app.intake.pilot_access import AccessStore, IDLE_SECONDS, REMEMBER_SECONDS, digest
from tests.test_pilot_access import pilot as pilot_fixture, ORIGIN, LOGIN, WRITE

pilot = pilot_fixture


def test_remembered_survives_idle_restart_and_login_cleanup_but_not_day_30(pilot, monkeypatch):
    access, _, _ = pilot
    now = time.time()
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now)
    _, key = access.issue("Long lived", days=90)
    token = access.login(key, "device-a")
    with access.connect() as db:
        expiry = db.execute("SELECT expires FROM sessions WHERE token_hash=?", (digest(token),)).fetchone()[0]
    assert expiry == now + REMEMBER_SECONDS
    for elapsed in (24*3600, 8*86400, 29*86400):
        monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now + elapsed)
        restarted = AccessStore(access.root)
        # A login on another device must not prune the long-idle remembered one.
        other = restarted.login(key, "device-b")
        assert other and restarted.authenticate(token)
        with access.connect() as db:
            assert db.execute("SELECT expires FROM sessions WHERE token_hash=?", (digest(token),)).fetchone()[0] == expiry
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: expiry)
    assert access.authenticate(token) is None  # No unbounded rolling extension.


def test_new_login_choice_controls_cookie_and_session(pilot):
    access, _, _ = pilot
    uid, key = access.issue("My computer", days=90)
    client = TestClient(app, base_url=ORIGIN)
    page = client.get("/access/login")
    assert 'name="remember_device" type="checkbox" checked' in page.text
    assert "30 дней" in page.text
    result = client.post("/access/login", json={"key":key,"remember_device":True}, headers=LOGIN)
    assert result.status_code == 200
    cookie = result.cookies.get("zarya_pilot_session")
    assert all(flag in result.headers["set-cookie"] for flag in ("Max-Age=259199", "Secure", "HttpOnly", "SameSite=strict"))
    assert REMEMBER_SECONDS-5 <= access.cookie_max_age(cookie) <= REMEMBER_SECONDS
    normal = client.post("/access/login", json={"key":key,"remember_device":False}, headers=LOGIN)
    assert normal.status_code == 200
    # Ignore the separate deletion cookie for the old anonymous draft.
    session_cookie = next(h for h in normal.headers.get_list("set-cookie") if h.startswith("zarya_pilot_session="))
    assert "Max-Age" not in session_cookie and "expires=" not in session_cookie.lower()
    assert access.authenticate(cookie) is None  # Re-login rotates the current session.
    with access.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM remembered_sessions").fetchone()[0] == 0


def test_remember_cannot_extend_key_and_revoke_is_immediate(pilot, monkeypatch):
    access, _, _ = pilot
    now = time.time()
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now)
    uid, key = access.issue("Short invitation", days=2)
    token = access.login(key, "a", remember_device=True)
    assert access.cookie_max_age(token) == 2 * 86400
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now + 2*86400)
    assert access.authenticate(token) is None
    _, key = access.issue("Reissued", user_id=uid)
    remembered = access.login(key, "a")
    short = access.login(key, "b", remember_device=False)
    access.revoke(uid)
    assert access.authenticate(remembered) is None and access.authenticate(short) is None
    with access.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM remembered_sessions").fetchone()[0] == 0


def test_nonremembered_still_has_idle_limit_and_logout_deletes_remember_marker(pilot, monkeypatch):
    access, users, _ = pilot
    token = access.login(users["alice"][1], "a", remember_device=False)
    now = time.time()
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now + IDLE_SECONDS + 1)
    assert access.authenticate(token) is None
    client = TestClient(app, base_url=ORIGIN)
    result = client.post("/access/login", json={"key":users["alice"][1]}, headers=LOGIN)
    token = result.cookies.get("zarya_pilot_session")
    assert access.authenticate(token)
    assert client.post("/access/logout", headers=WRITE, follow_redirects=False).status_code == 303
    assert access.authenticate(token) is None
    with access.connect() as db:
        assert not db.execute("SELECT 1 FROM remembered_sessions WHERE token_hash=?", (digest(token),)).fetchone()


def test_old_session_is_not_extended_or_revived_and_schema_stays_compatible(pilot, monkeypatch):
    access, users, _ = pilot
    now = time.time()
    # Old release INSERT with 4 columns must still work after the additive upgrade.
    old_token, dead_token = "a"*43, "b"*43
    with access.connect() as db:
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(old_token),users["alice"][0],now+7*86400,now))
        db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest(dead_token),users["alice"][0],now+7*86400,now-2*86400))
    migrated = AccessStore(access.root)
    assert migrated.authenticate(old_token)
    assert migrated.authenticate(dead_token) is None
    monkeypatch.setattr("app.intake.pilot_access.time.time", lambda: now+IDLE_SECONDS+2)
    assert migrated.authenticate(old_token) is None


def test_old_sqlite_with_no_remember_table_is_upgraded_without_touching_sessions(tmp_path):
    with sqlite3.connect(tmp_path/"access.sqlite3") as db:
        db.execute("CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL,seen REAL NOT NULL)")
        db.execute("INSERT INTO sessions VALUES('old','user',1,1)")
    access = AccessStore(tmp_path)
    with access.connect() as db:
        assert tuple(db.execute("SELECT * FROM sessions").fetchone()) == ("old","user",1,1)
        assert db.execute("SELECT COUNT(*) FROM remembered_sessions").fetchone()[0] == 0

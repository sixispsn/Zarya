"""Feedback is opt-in text, private to the owner, bounded and retry-safe."""
import uuid

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.intake.pilot_feedback import FeedbackStore
from tests.test_pilot_access import pilot as pilot_fixture, client_for, WRITE, ORIGIN

pilot = pilot_fixture


def payload(**changes):
    return {"request_id": uuid.uuid4().hex, "category": "interface",
            "message": "Кнопка расчёта не сработала при первом нажатии.", **changes}


def test_feedback_is_saved_private_and_idempotent(pilot):
    access, users, _ = pilot
    alice = client_for(users["alice"][1])
    data = payload(message="<script>alert('x')</script> — неожиданное поведение")
    first = alice.post("/access/feedback", json=data, headers=WRITE)
    assert first.status_code == 200
    assert first.json() == {"ticket": "ZR-000001"}
    assert alice.post("/access/feedback", json=data, headers=WRITE).json() == first.json()
    changed = {**data, "message": "Изменённое описание проблемы"}
    assert alice.post("/access/feedback", json=changed, headers=WRITE).status_code == 409
    assert alice.get("/access/feedback").status_code == 403
    assert client_for(users["bob"][1]).get("/access/feedback").status_code == 403
    owner = client_for(users["owner"][1])
    result = owner.get("/access/feedback")
    assert result.status_code == 200
    assert "ZR-000001" in result.text and "Алиса" in result.text
    assert "<script>alert" not in result.text and "&lt;script&gt;" in result.text
    with access.connect() as db:
        rows = list(db.execute("SELECT * FROM feedback"))
        assert len(rows) == 1
        assert set(rows[0].keys()) == {"id", "user_id", "user_name", "request_id", "category", "message", "build", "created"}
    assert "no-store" in result.headers["cache-control"]


@pytest.mark.parametrize("changes", [
    {"message": " " * 15}, {"message": "short"}, {"message": "я" * 4001},
    {"category": "invalid"}, {"request_id": "../bad"}, {"attachment": "private.pdf"},
    {"user_id": "forged"}, {"draft_id": "forged"},
])
def test_feedback_validates_fields(pilot, changes):
    client = client_for(pilot[1]["alice"][1])
    assert client.post("/access/feedback", json=payload(**changes), headers=WRITE).status_code == 422


def test_feedback_auth_origin_size_and_rate(pilot):
    alice = client_for(pilot[1]["alice"][1])
    assert TestClient(app, base_url=ORIGIN).post("/access/feedback", json=payload(), headers=WRITE).status_code == 401
    assert alice.post("/access/feedback", json=payload(), headers={**WRITE, "Origin": "https://evil.test"}).status_code == 403
    assert alice.post("/access/feedback", content=b"x" * 32769, headers=WRITE).status_code == 413
    for _ in range(20):
        assert alice.post("/access/feedback", json=payload(), headers=WRITE).status_code == 200
    assert alice.post("/access/feedback", json=payload(), headers=WRITE).status_code == 429
    assert client_for(pilot[1]["bob"][1]).post("/access/feedback", json=payload(), headers=WRITE).status_code == 200


def test_feedback_is_closed_when_pilot_disabled(pilot, monkeypatch):
    monkeypatch.setenv("ZARYA_PILOT_ENABLED", "0")
    client = TestClient(app, base_url=ORIGIN)
    assert client.get("/access/feedback").status_code == 404
    assert client.post("/access/feedback", json=payload(), headers=WRITE).status_code == 404
    assert 'data-feedback-open' not in client.get("/studio").text


def test_feedback_pagination(pilot):
    access, _, _ = pilot
    store = FeedbackStore()
    with access.connect() as db:
        db.executemany("INSERT INTO feedback(user_id,user_name,request_id,category,message,build,created) VALUES(?,?,?,?,?,?,?)",
                       [("u", "Тест", str(i), "other", "Замечание", "local", 1) for i in range(56)])
    page, cursor = store.page()
    assert len(page) == 50 and cursor == 7
    second, cursor = store.page(cursor)
    assert [row["id"] for row in second] == list(range(6, 0, -1)) and cursor is None

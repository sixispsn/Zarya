"""Disk transaction tests; sentinel files are deliberately NOT rendered PDFs."""
import json
from pathlib import Path

import pytest

from app.intake import studio_store
from app.intake.studio_store import StudioStore
from app.pz import ios2_orchestrator as renderer
from app.pz.commission import build_commission_report
from app.web import wizard
from tests import test_studio as studio_tests
from tests.test_studio_preview_atomicity import baseline

client = studio_tests.client


def completed_renderer(monkeypatch):
    attempts = []

    def render(project, *, output_dir):
        folder = Path(output_dir)
        folder.mkdir(parents=True)
        (folder / "completed.pdf").write_bytes(b"NOT PDF: completed transaction sentinel")
        attempts.append(folder)
        return renderer.IOS2DesignBundle(
            project=project, commission_report=build_commission_report(project, artifacts={}))

    monkeypatch.setattr(renderer, "design_ios2", render)
    monkeypatch.setattr(wizard, "_bundle_documents", lambda _: ([dict(
        name="completed.pdf", label="Transaction sentinel", kind="extra_pdf", state="preliminary")], []))
    return attempts


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("phase", ["tempfile", "fsync", "replace"])
def test_disk_failure_preserves_draft_and_allows_only_explicit_retry(client, tmp_path, monkeypatch, history, phase):
    state, file, old = baseline(client, tmp_path, history)
    before = file.read_bytes()
    attempts = completed_renderer(monkeypatch)
    target = studio_store.tempfile if phase == "tempfile" else studio_store.os
    method = "mkstemp" if phase == "tempfile" else phase

    def fail(*args, **kwargs):
        assert len(attempts) == 1, "Failure must follow completed rendering"
        raise OSError("TEST-ONLY: disk write refused")

    with monkeypatch.context() as fault:
        fault.setattr(target, method, fail)
        failed = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert failed.status_code == 503
    assert "сохранение предпросмотра" in failed.json()["detail"]
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state
    assert not attempts[0].exists()
    assert list(old.parent.iterdir()) == [old]
    assert not list(file.parent.glob("*.tmp"))
    assert client.get(f"/studio/api/preview/{attempts[0].name}/files/completed.pdf").status_code == 404
    assert client.get(f"/studio/api/preview/{old.name}/files/sentinel.pdf").status_code == (200 if history else 404)
    assert len(attempts) == 1  # Reading/recovery never retries a write.
    retried = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert retried.status_code == 200, retried.text
    saved = retried.json()
    assert saved["revision"] == state["revision"] + 1
    assert len(attempts) == 2 and saved["preview"]["id"] == attempts[1].name
    assert client.get(f"/studio/api/preview/{attempts[1].name}/files/completed.pdf").status_code == 200
    assert (old / "sentinel.pdf").read_bytes() == b"NOT PDF: historical presence sentinel"
    assert saved["project_calculation"]["can_release"] is False


def test_error_after_replace_never_deletes_committed_preview(client, tmp_path, monkeypatch):
    state, file, old = baseline(client, tmp_path, True)
    attempts = completed_renderer(monkeypatch)
    original = StudioStore._write

    def committed_then_error(folder, draft):
        original(folder, draft)
        raise OSError("TEST-ONLY: error after durable replacement")

    with monkeypatch.context() as fault:
        fault.setattr(StudioStore, "_write", staticmethod(committed_then_error))
        failed = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert failed.status_code == 503
    persisted = file.read_bytes()
    saved = client.get("/studio/api/draft").json()
    assert saved["revision"] == state["revision"] + 1
    assert saved["preview"]["id"] == attempts[0].name
    assert attempts[0].exists() and old.exists()
    assert client.get(f"/studio/api/preview/{attempts[0].name}/files/completed.pdf").status_code == 200
    assert file.read_bytes() == persisted and len(attempts) == 1
    assert json.loads(persisted)["preview"]["id"] == saved["preview"]["id"]


def test_unknown_commit_outcome_preserves_files_but_never_grants_access(client, tmp_path, monkeypatch):
    state, file, old = baseline(client, tmp_path, True)
    before = file.read_bytes()
    attempts = completed_renderer(monkeypatch)
    original_load = StudioStore.load
    failed = False

    def fail_write(*args):
        nonlocal failed
        failed = True
        raise OSError("TEST-ONLY: storage unavailable")

    def uncertain_load(self, did):
        if failed:
            raise OSError("TEST-ONLY: cannot determine commit outcome")
        return original_load(self, did)

    with monkeypatch.context() as fault:
        fault.setattr(StudioStore, "_write", staticmethod(fail_write))
        fault.setattr(StudioStore, "load", uncertain_load)
        response = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert response.status_code == 503
    assert attempts[0].exists() and old.exists()
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state
    assert client.get(f"/studio/api/preview/{attempts[0].name}/files/completed.pdf").status_code == 404

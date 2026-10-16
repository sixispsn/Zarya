"""Transaction failures, not PDF-layout tests: partial files are explicit non-PDF sentinels."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

from app.intake.pilot_objects import calculation_stamp
from app.intake.studio_intake import IntakeError
from app.intake.studio_project import STUDIO_HANDOFF_VERSION
from app.intake.studio_store import StudioStore
from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION
from app.pz import ios2_orchestrator as renderer
from tests import test_studio as studio_tests
from tests.test_studio_joint_input_recovery import initialized

client = studio_tests.client


def baseline(client, tmp_path, history):
    state, file = initialized(client, tmp_path)
    old = file.parent / "previews" / ("a" * 32)
    old.mkdir(parents=True)
    (old / "sentinel.pdf").write_bytes(b"NOT PDF: historical presence sentinel")
    if history:
        store = StudioStore(tmp_path / "studio")
        with store.edit(state["project_id"], state["revision"]) as draft:
            draft["preview"] = dict(id=old.name, state="preview",
                render_version=DOCUMENT_RENDER_VERSION, handoff_version=STUDIO_HANDOFF_VERSION,
                stamp=calculation_stamp(draft), documents=[dict(name="sentinel.pdf",
                    label="Transaction sentinel", kind="extra_pdf", state="preliminary")])
    return client.get("/studio/api/draft").json(), file, old


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("failure_kind", ["before_folder", "partial", "domain"])
def test_failed_preview_is_atomic_and_cleans_only_its_partial_folder(client, tmp_path, monkeypatch, history, failure_kind):
    state, file, old = baseline(client, tmp_path, history)
    before = file.read_bytes()
    attempted = []

    def fail(project, *, output_dir):
        folder = Path(output_dir)
        attempted.append(folder)
        if failure_kind != "before_folder":
            folder.mkdir(parents=True)
            (folder / "partial.pdf").write_bytes(b"NOT PDF: unfinished renderer output")
        if failure_kind == "domain":
            raise IntakeError("TEST-ONLY: controlled renderer refusal")
        raise OSError("TEST-ONLY: renderer failure")

    monkeypatch.setattr(renderer, "design_ios2", fail)
    response = client.post("/studio/api/preview", json={"revision": state["revision"]})
    assert response.status_code == 422
    assert "preview" not in response.json()
    expected_message = "TEST-ONLY: controlled" if failure_kind == "domain" else "не сформирован"
    assert expected_message in response.text
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state
    assert len(attempted) == 1 and not attempted[0].exists()
    assert list(old.parent.iterdir()) == [old]
    assert (old / "sentinel.pdf").read_bytes() == b"NOT PDF: historical presence sentinel"
    url = f"/studio/api/preview/{old.name}/files/sentinel.pdf"
    assert client.get(url).status_code == (200 if history else 404)
    assert file.read_bytes() == before


@pytest.mark.parametrize("history", [False, True])
def test_stale_preview_refused_before_renderer_or_new_files(client, tmp_path, monkeypatch, history):
    state, file, old = baseline(client, tmp_path, history)
    stale = state["revision"]
    state = studio_tests.answer(client, state, "object_name", "TEST-ONLY: another tab")
    before = file.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("Stale revision must never reach renderer")

    monkeypatch.setattr(renderer, "design_ios2", forbidden)
    response = client.post("/studio/api/preview", json={"revision": stale})
    assert response.status_code == 409
    assert file.read_bytes() == before
    assert client.get("/studio/api/draft").json() == state
    assert list(old.parent.iterdir()) == [old]


def test_waiting_edit_commits_after_failed_preview_without_losing_its_input(client, tmp_path, monkeypatch):
    state, file, old = baseline(client, tmp_path, True)
    entered, attempted, release = Event(), Event(), Event()
    original_edit = StudioStore.edit

    @contextmanager
    def observed_edit(self, did, revision, **kwargs):
        if entered.is_set():
            attempted.set()
        with original_edit(self, did, revision, **kwargs) as draft:
            yield draft

    def blocked_renderer(project, *, output_dir):
        folder = Path(output_dir)
        folder.mkdir(parents=True)
        (folder / "partial.pdf").write_bytes(b"NOT PDF: incomplete transaction")
        entered.set()
        assert release.wait(10)
        raise OSError("TEST-ONLY: generation aborted before commit")

    monkeypatch.setattr(StudioStore, "edit", observed_edit)
    monkeypatch.setattr(renderer, "design_ios2", blocked_renderer)
    before = file.read_bytes()
    with ThreadPoolExecutor(max_workers=2) as pool:
        build = pool.submit(client.post, "/studio/api/preview", json={"revision": state["revision"]})
        try:
            assert entered.wait(10)
            edit = pool.submit(client.patch, "/studio/api/answer", json={
                "revision": state["revision"], "field": "object_name", "value": "TEST-ONLY: waiting tab"})
            assert attempted.wait(10)
            assert file.read_bytes() == before
            assert not edit.done()
        finally:
            release.set()
        assert build.result(timeout=10).status_code == 422
        saved = edit.result(timeout=10)
    assert saved.status_code == 200, saved.text
    result = client.get("/studio/api/draft").json()
    assert result["revision"] == state["revision"] + 1
    assert next(r["value"] for r in result["fields"] if r["key"] == "object_name") == "TEST-ONLY: waiting tab"
    assert result["preview"] is None and result["project_calculation"] is None
    assert list(old.parent.iterdir()) == [old]

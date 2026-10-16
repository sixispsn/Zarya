"""Source deletion revokes evidence, derived results and direct file access."""
from pathlib import Path

import pytest

from app.intake.studio_intake import answer_field, accepted_values
from app.intake.studio_store import StudioStore, StaleDraft
from tests.test_pilot_access import pilot as pilot_fixture, client_for, draft, pdf_bytes, WRITE

pilot = pilot_fixture


def document(identifier="a" * 24, residents=20):
    return {"id": identifier, "name": "ТЗ.pdf", "bytes": 3, "pages": 1, "text_pages": 1, "status": "text",
            "candidates": [{"field": "residents", "value": residents, "document_id": identifier,
                            "page": 1, "quote": f"Жителей: {residents}"}]}


def setup_store(tmp_path, documents=None):
    store = StudioStore(tmp_path)
    did, state = store.create()
    state = store.add_documents(did, state["revision"], [(d, b"pdf") for d in (documents or [document()])])
    with store.edit(did, state["revision"]) as state:
        answer_field(state, "residents", 20)
        answer_field(state, "floors", 2)
        for key in ("calculation", "project_calculation", "preview", "package", "handoff"):
            state[key] = {"old": True}
    return store, did, state


def test_delete_invalidates_source_answers_and_outputs_not_manual(tmp_path):
    store, did, state = setup_store(tmp_path)
    old_revision = state["revision"]
    state = store.delete_document(did, old_revision, "a" * 24)
    assert not (store.folder(did) / ("a" * 24 + ".pdf")).exists()
    assert state["documents"] == []
    assert "residents" not in accepted_values(state)
    assert accepted_values(state)["floors"] == 2
    assert all(state[key] is None for key in ("calculation", "project_calculation", "preview", "package"))
    assert "handoff" not in state and "pending_document_deletions" not in state
    assert state["revision"] == old_revision + 1 and store.load(did) == state
    # Re-uploading is possible; removed answers are not auto-confirmed.
    state = store.add_documents(did, state["revision"], [(document(), b"pdf")])
    assert len(state["documents"]) == 1 and "residents" not in accepted_values(state)


def test_other_evidence_and_manual_override_survive(tmp_path):
    store, did, state = setup_store(tmp_path, [document(), document("b" * 24)])
    state = store.delete_document(did, state["revision"], "a" * 24)
    assert accepted_values(state)["residents"] == 20
    assert {item["document_id"] for item in state["answers"]["residents"]["source"]["evidence"]} == {"b" * 24}
    with store.edit(did, state["revision"]) as state:
        answer_field(state, "residents", 25)
    state = store.delete_document(did, state["revision"], "b" * 24)
    assert accepted_values(state)["residents"] == 25


def test_stale_or_missing_delete_changes_nothing(tmp_path):
    store, did, state = setup_store(tmp_path)
    with pytest.raises(StaleDraft):
        store.delete_document(did, state["revision"] - 1, "a" * 24)
    with pytest.raises(FileNotFoundError):
        store.delete_document(did, state["revision"], "b" * 24)
    assert store.load(did) == state
    assert (store.folder(did) / ("a" * 24 + ".pdf")).exists()


def test_failed_metadata_write_does_not_remove_pdf(tmp_path, monkeypatch):
    store, did, state = setup_store(tmp_path)
    def fail(*args):
        raise OSError("test write failure")
    monkeypatch.setattr(store, "_write", fail)
    with pytest.raises(OSError):
        store.delete_document(did, state["revision"], "a" * 24)
    assert store.load(did) == state
    assert (store.folder(did) / ("a" * 24 + ".pdf")).exists()


def test_failed_unlink_is_revoked_and_retried_on_next_edit(tmp_path, monkeypatch):
    store, did, state = setup_store(tmp_path)
    original = Path.unlink
    def fail_pdf(path, *args, **kwargs):
        if path.suffix == ".pdf":
            raise OSError("test unlink failure")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_pdf)
        with pytest.raises(OSError):
            store.delete_document(did, state["revision"], "a" * 24)
    saved = store.load(did)
    assert saved["documents"] == [] and saved["pending_document_deletions"] == ["a" * 24]
    with pytest.raises(FileNotFoundError):
        store.document(did, "a" * 24)
    with store.edit(did, saved["revision"]) as saved:
        answer_field(saved, "floors", 3)
    assert "pending_document_deletions" not in store.load(did)
    assert not (store.folder(did) / ("a" * 24 + ".pdf")).exists()


def test_delete_http_is_scoped_and_csrf_protected(pilot):
    access, users, root = pilot
    alice, bob = client_for(users["alice"][1]), client_for(users["bob"][1])
    state = draft(alice)
    response = alice.post("/studio/api/files", data={"revision": state["revision"]},
                          files={"files": ("ТЗ.pdf", pdf_bytes(), "application/pdf")}, headers=WRITE)
    assert response.status_code == 200
    state = response.json()
    docid = state["documents"][0]["id"]
    bob_state = draft(bob)
    payload = {"revision": state["revision"], "document_id": docid}
    assert bob.post("/studio/api/files/delete", json={**payload, "revision": bob_state["revision"]}, headers=WRITE).status_code == 404
    assert alice.get(f"/studio/api/files/{docid}").status_code == 200
    assert alice.post("/studio/api/files/delete", json=payload, headers={**WRITE, "Origin": "https://evil.test"}).status_code == 403
    assert alice.post("/studio/api/files/delete", json={**payload, "document_id": "../private"}, headers=WRITE).status_code == 422
    assert alice.post("/studio/api/files/delete", json={**payload, "revision": 0}, headers=WRITE).status_code == 409
    result = alice.post("/studio/api/files/delete", json=payload, headers=WRITE)
    assert result.status_code == 200 and result.json()["documents"] == []
    assert alice.get(f"/studio/api/files/{docid}").status_code == 404
    did = access.active_draft(users["alice"][0])
    assert not (root / "studio" / "_users" / users["alice"][0] / did / f"{docid}.pdf").exists()


def test_delete_ui_discloses_scope_and_has_explicit_confirmation():
    template = Path("app/web/templates/studio.html").read_text()
    script = Path("app/web/static/studio.js").read_text()
    assert 'id="delete-document-dialog"' in template
    assert "резервные копии этим действием не удаляются" in template
    assert 'data-action="confirm-delete-document"' in template
    assert "if(dirty && !(await saveForm(false))) return;" in script

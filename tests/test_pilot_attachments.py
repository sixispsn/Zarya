"""Real bounded PDFs, explicit rights, immutable association and private downloads."""
from concurrent.futures import ThreadPoolExecutor
import io
import hashlib
import json
from pathlib import Path
import sqlite3
import tarfile
import uuid

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from app.main import app
from app.intake.pilot_access import Principal
from app.intake.pilot_attachments import PilotAttachmentStore, MAX_FILE_BYTES
from app.intake import pilot_attachments as storage_module
from app.intake.pilot_objects import PilotObjectStore, SnapshotLimit
from app.intake.studio_intake import IntakeError
from tests.test_pilot_access import pilot as pilot_fixture, client_for, pdf_bytes, WRITE, ORIGIN
from tests.test_pilot_objects import setup, payload, save

pilot = pilot_fixture


def seed(pilot):
    client = client_for(pilot[1]["alice"][1])
    setup(client)
    saved = save(client, payload(client)).json()
    metadata = dict(object_id=saved["object_id"], version=1, request_id=uuid.uuid4().hex,
                    consent=True, expertise_declared=True, note="Уточнили трубы", expertise_ref="Тест № 123")
    return client, saved, metadata


def upload(client, metadata, files=None, headers=None):
    return client.post("/studio/api/pilot-attachments", headers=headers or WRITE,
                       data={"metadata": json.dumps(metadata)},
                       files=[("files", (name, content, "application/pdf")) for name, content in
                              (files if files is not None else [("ПЗ.pdf", pdf_bytes())])])


def user(pilot, name="alice"):
    return Principal(pilot[1][name][0], name, "admin" if name == "owner" else "tester", None)


def test_two_bundles_do_not_change_baseline_and_owner_can_download(pilot):
    alice, saved, data = seed(pilot)
    before = PilotObjectStore().version(user(pilot), saved["object_id"], 1)[1]
    content = pdf_bytes()
    first = upload(alice, data, [("ПЗ.pdf", content), ("Схемы.pdf", content)])
    assert first.status_code == 200, first.text
    archive = PilotAttachmentStore()
    bundles = archive.list(user(pilot), saved["object_id"], 1)
    assert len(bundles) == 1 and bundles[0]["consent_version"] == "pilot-expertise-pdf-v1"
    bundle = bundles[0]
    assert bundle["status"] == "passed_declared"
    assert len(bundle["files"]) == 2
    file = bundle["files"][0]
    route = f'/studio/pilot-attachments/{bundle["id"]}/files/{file["id"]}'
    owner, bob = client_for(pilot[1]["owner"][1]), client_for(pilot[1]["bob"][1])
    for client in (alice, owner):
        result = client.get(route)
        assert result.content == content and result.status_code == 200
        assert "attachment" in result.headers["content-disposition"]
        assert result.headers["content-type"] == "application/octet-stream"
        assert result.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in result.headers["content-security-policy"]
        assert "no-store" in result.headers["cache-control"]
    assert bob.get(route).status_code == 404
    assert TestClient(app, base_url=ORIGIN).get(route).status_code == 401
    assert upload(owner, data).status_code == 404
    assert upload(bob, data).status_code == 404
    assert upload(alice, {**data, "request_id":uuid.uuid4().hex, "note":"Вторая редакция"}).status_code == 200
    assert len(archive.list(user(pilot), saved["object_id"], 1)) == 2
    assert PilotObjectStore().version(user(pilot), saved["object_id"], 1)[1] == before
    assert client_for(pilot[1]["alice"][1]).get(route).content == content
    assert (archive.root / bundle["id"] / (file["id"] + ".pdf")).stat().st_mode & 0o777 == 0o600
    assert "со слов инженера" in owner.get(saved["url"]).text
    assert "data-bundle-open" not in owner.get(saved["url"]).text
    with pilot[0].connect() as db, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE pilot_bundles SET note='other'")
    pilot[0].revoke(pilot[1]["alice"][0])
    assert alice.get(route).status_code == 401


@pytest.mark.parametrize("change", [{"consent":False},{"expertise_declared":False},{"consent":"true"},
                                    {"version":True},{"object_id":"../private"},{"note":"x"*2001},
                                    {"expertise_ref":"x"*201},{"status":"verified"},{"user_id":"owner"}])
def test_invalid_metadata_and_absent_consent_never_write_files(pilot, change):
    alice, _, data = seed(pilot)
    assert upload(alice, {**data, **change}).status_code == 422
    assert not list((pilot[2] / "access" / "bundles").glob("*"))


@pytest.mark.parametrize("name,content", [("file.txt", b"%PDF-1.7\n"),("../file.pdf", b"%PDF-1.7\n"),
                                         ("file.pdf", b"<html>not a PDF</html>"),("file.pdf", b"%PDF-1.7\nbroken"),
                                         ("a\x00.pdf", b"%PDF-1.7\n")])
def test_invalid_files_rejected_without_partial_bundle(pilot, name, content):
    alice, saved, data = seed(pilot)
    result = upload(alice, data, [("valid.pdf",pdf_bytes()),(name,content)])
    assert result.status_code == 422, result.text
    assert not PilotAttachmentStore().list(user(pilot), saved["object_id"], 1)
    assert not list((pilot[2] / "access" / "bundles").iterdir())


def test_encrypted_pdf_and_size_and_too_many_files(pilot):
    alice, _, data = seed(pilot)
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt("test-password")
    out = io.BytesIO()
    writer.write(out)
    assert upload(alice, data, [("locked.pdf", out.getvalue())]).status_code == 422
    assert upload(alice, data, [("big.pdf",b"%PDF-"+b"a"*MAX_FILE_BYTES)]).status_code == 413
    assert upload(alice, data, [(f"{i}.pdf",pdf_bytes()) for i in range(11)]).status_code == 400


def test_retry_same_id_and_new_id_are_deduplicated_changed_intent_conflicts(pilot):
    alice, saved, data = seed(pilot)
    files = [("one.pdf", pdf_bytes()), ("two.pdf",pdf_bytes())]
    first = upload(alice, data, files)
    assert first.status_code == 200
    assert upload(alice, data, files).json() == first.json()
    assert upload(alice, {**data, "request_id":uuid.uuid4().hex}, list(reversed(files))).json() == first.json()
    assert upload(alice, {**data, "note":"Other"}, files).status_code == 409
    assert len(PilotAttachmentStore().list(user(pilot), saved["object_id"], 1)) == 1


def test_csrf_disabled_mode_and_wrong_baseline(pilot, monkeypatch):
    alice, saved, data = seed(pilot)
    assert upload(alice, data, headers={**WRITE,"Origin":"https://evil.test"}).status_code == 403
    assert upload(alice, {**data,"version":999}).status_code == 404
    assert upload(alice, {**data,"object_id":"0"*32}).status_code == 404
    assert TestClient(app, base_url=ORIGIN).post("/studio/api/pilot-attachments",headers=WRITE).status_code == 401
    monkeypatch.setenv("ZARYA_PILOT_ENABLED","0")
    assert upload(alice,data).status_code == 404


def test_integrity_escaping_and_no_file_under_static(pilot):
    alice, saved, data = seed(pilot)
    result = upload(alice, {**data,"note":"<script>alert(1)</script>"},[("<script>.pdf",pdf_bytes())])
    assert result.status_code == 200
    page = alice.get(saved["url"])
    assert "<script>alert" not in page.text and "&lt;script&gt;.pdf" in page.text
    archive = PilotAttachmentStore()
    bundle = archive.list(user(pilot), saved["object_id"],1)[0]
    fid = bundle["files"][0]["id"]
    path = archive.root / bundle["id"] / (fid+".pdf")
    path.write_bytes(b"corrupt test")
    assert alice.get(f'/studio/pilot-attachments/{bundle["id"]}/files/{fid}').status_code == 409
    assert alice.get(f'/static/{bundle["id"]}/{fid}.pdf').status_code == 404


def test_atomic_failure_quota_and_concurrent_retry(pilot, monkeypatch):
    _, saved, _ = seed(pilot)
    archive = PilotAttachmentStore()
    args = dict(object_id=saved["object_id"],number=1,request_id=uuid.uuid4().hex,note="",expertise_ref="",uploads=[("test.pdf",pdf_bytes())])
    def fail_probe(path):
        raise IntakeError("bad PDF")
    with monkeypatch.context() as patch:
        patch.setattr(storage_module,"probe",fail_probe)
        with pytest.raises(IntakeError):
            archive.add(user(pilot),**args)
    assert not list(archive.root.iterdir())
    with monkeypatch.context() as patch:
        patch.setattr(storage_module,"USER_QUOTA",1)
        with pytest.raises(SnapshotLimit):
            archive.add(user(pilot),**args)
    assert not list(archive.root.iterdir())
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: archive.add(user(pilot),**args), range(2)))
    assert receipts[0] == receipts[1] and len(list(archive.root.iterdir())) == 1
    assert len(archive.list(user(pilot),saved["object_id"],1)) == 1


def test_ui_has_two_unchecked_consents_and_no_hidden_upload():
    template = Path("app/web/templates/pilot_attachment_dialog.html").read_text()
    assert 'name="consent" required' in template and 'name="expertise_declared" required' in template
    assert " checked" not in template
    assert "обезличьте" in template and "третьим лицам не разрешаю" in template


def test_bundle_restores_with_snapshot_and_files(pilot, monkeypatch):
    from scripts.verify_backup_restore import restore
    alice, saved, data = seed(pilot)
    assert upload(alice, data).status_code == 200
    storage = PilotAttachmentStore()
    bundle = storage.list(user(pilot), saved["object_id"], 1)[0]
    file_id = bundle["files"][0]["id"]
    original = storage.download(user(pilot), bundle["id"], file_id)[0].read_bytes()
    archive, restored = pilot[2] / "backup.tar.gz", pilot[2] / "restored"
    with tarfile.open(archive, "w:gz") as target:
        target.add(storage.access.root, arcname=".")
    result = restore(archive, restored, hashlib.sha256(archive.read_bytes()).hexdigest())
    assert result["sqlite_checked"] == 1 and result["pdf_files"] == 1
    monkeypatch.setenv("ZARYA_PILOT_DIR", str(restored))
    recovered = PilotAttachmentStore()
    assert recovered.download(user(pilot), bundle["id"], file_id)[0].read_bytes() == original
    assert recovered.list(user(pilot), saved["object_id"], 1) == [bundle]


def test_rename_failure_rolls_back_metadata_and_rate_limit(pilot, monkeypatch):
    _, saved, _ = seed(pilot)
    store = PilotAttachmentStore()
    args = dict(object_id=saved["object_id"], number=1, request_id=uuid.uuid4().hex,
                note="", expertise_ref="", uploads=[("test.pdf", pdf_bytes())])
    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError("disk error")
        patch.setattr(Path, "rename", fail)
        with pytest.raises(OSError):
            store.add(user(pilot), **args)
    assert not store.list(user(pilot), saved["object_id"], 1)
    assert not list(store.root.iterdir())
    for i in range(5):
        store.add(user(pilot), **{**args,"request_id":uuid.uuid4().hex,"note":str(i)})
    with pytest.raises(SnapshotLimit):
        store.add(user(pilot), **{**args,"request_id":uuid.uuid4().hex,"note":"sixth"})
    assert len(list(store.root.iterdir())) == 5

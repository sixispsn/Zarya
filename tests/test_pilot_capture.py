import hashlib
import sqlite3

import pytest

from app.intake.pilot_access import Principal
from app.intake.pilot_admin import PilotAdminStore
from app.intake.pilot_capture import PilotCaptureStore, SnapshotLimit
from app.intake.pilot_objects import calculation_stamp
from app.intake.studio_intake import IntakeError, answer_field, calculate_draft
from app.intake.studio_project import calculate_project
from tests.test_pilot_access import pilot as pilot_fixture, client_for, draft, WRITE, pdf_bytes
from tests.test_pilot_admin import accept

pilot = pilot_fixture
ANSWERS = {"residents":20,"consumer_code":"residential_full_bath","hws_type":"central"}


def calculated():
    data = {"revision":1,"documents":[],"answers":{},"calculation":None}
    for field, value in ANSWERS.items():
        answer_field(data,field,value)
    data["calculation"] = calculate_draft(data)
    data["project_calculation"] = calculate_project(data)
    data["calculation_stamp"] = calculation_stamp(data)
    return data


def actors(users):
    return [Principal(users[k][0], k, "admin" if k == "owner" else "tester", None) for k in ["alice","bob","owner"]]


def test_capture_requires_consent_and_skips_studies(pilot):
    _, users, _ = pilot
    alice, _, _ = actors(users)
    archive = PilotCaptureStore()
    data = calculated()
    assert archive.capture(alice,"a"*32,data,"calculation") is None
    PilotAdminStore().accept(alice)
    assert archive.capture(alice,"a"*32,{**data,"study":{"kind":"test"}},"calculation") is None


def test_immutable_exact_pdf_private_after_source_deleted_and_dedupe(pilot, tmp_path):
    _, users, _ = pilot
    alice, bob, owner = actors(users)
    PilotAdminStore().accept(alice)
    archive = PilotCaptureStore()
    data = calculated()
    path = tmp_path / "issued.pdf"
    original = pdf_bytes()
    path.write_bytes(original)
    metadata = {"name":path.name,"state":"incomplete","state_note":"Предпросмотр"}
    first = archive.capture(alice,"a"*32,data,"preview",[(path,metadata)])
    repeat = archive.capture(alice,"a"*32,{**data,"revision":2},"preview",[(path,metadata)])
    assert first == repeat
    bundle = archive.generated(alice,first["object_id"],first["version"])
    fid = bundle["files"][0]["id"]
    path.unlink()
    stored, _ = archive.file(owner,bundle["bundle_id"],fid)
    assert stored.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == bundle["files"][0]["sha256"]
    with pytest.raises(FileNotFoundError):
        archive.file(bob,bundle["bundle_id"],fid)
    url = f"/studio/pilot-generated/{bundle['bundle_id']}/files/{fid}"
    assert client_for(users["alice"][1]).get(url).content == original
    assert client_for(users["bob"][1]).get(url).status_code == 404
    assert client_for(users["owner"][1]).get(first["url"]).status_code == 200
    # Changes produce the next version on the same object, never overwrite.
    answer_field(data,"residents",25)
    next_version = archive.capture(alice,"a"*32,data,"calculation")
    assert next_version["object_id"] == first["object_id"] and next_version["version"] == 2
    stored.write_bytes(b"tampered")
    with pytest.raises(IntakeError):
        archive.file(alice,bundle["bundle_id"],fid)


def test_invalid_pdf_rolls_back_without_empty_object_or_files(pilot, tmp_path):
    _, users, _ = pilot
    alice, _, _ = actors(users)
    PilotAdminStore().accept(alice)
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"NOT PDF")
    archive = PilotCaptureStore()
    with pytest.raises(IntakeError):
        archive.capture(alice,"a"*32,calculated(),"preview",[(path,{"name":"bad.pdf"})])
    assert not list(archive.root.iterdir())
    assert archive.archive.objects(alice)[0] == []


def test_calculation_endpoint_auto_saves_and_survives_archive_failure(pilot, monkeypatch):
    _, users, _ = pilot
    alice = client_for(users["alice"][1])
    accept(alice)
    state = draft(alice)
    result = alice.post("/studio/api/calculate", headers=WRITE, json={"revision":state["revision"],"answers":ANSWERS,"preset_keys":[]})
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["pilot_archive"]["state"] == "saved"
    assert alice.get(saved["pilot_archive"]["url"]).status_code == 200
    def fail(*args, **kwargs):
        raise SnapshotLimit("quota")
    monkeypatch.setattr(PilotCaptureStore,"capture",fail)
    again = alice.post("/studio/api/calculate",headers=WRITE,json={"revision":saved["revision"],"answers":{},"preset_keys":[]})
    assert again.status_code == 200
    assert again.json()["calculation"] and again.json()["pilot_archive"]["state"] == "failed"


def test_failed_manifest_commit_rolls_back_copied_pdfs_and_snapshot(pilot, tmp_path):
    _, users, _ = pilot
    alice, _, _ = actors(users)
    PilotAdminStore().accept(alice)
    archive = PilotCaptureStore()
    with archive.access.connect() as db:
        db.execute("CREATE TRIGGER fail_manifest BEFORE INSERT ON pilot_generated BEGIN SELECT RAISE(ABORT, 'test failure'); END;")
    path = tmp_path / "issued.pdf"
    path.write_bytes(pdf_bytes())
    with pytest.raises(sqlite3.IntegrityError):
        archive.capture(alice,"b"*32,calculated(),"preview",[(path,{"name":path.name})])
    assert archive.archive.objects(alice)[0] == []
    assert not list(archive.root.iterdir())
    with archive.access.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pilot_drafts").fetchone()[0] == 0

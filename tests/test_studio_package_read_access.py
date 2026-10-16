"""Read-only availability of a saved release; no rendering or release approval."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.web import studio, wizard
from app.intake.studio_project import STUDIO_HANDOFF_VERSION
from app.quality_gates import build_release_quality_report
from tests import test_studio_package_download_integrity as download_tests

client = download_tests.client
package = download_tests.package
REAL_RUN_FILE = download_tests.REAL_RUN_FILE


@pytest.fixture
def saved_package(package, monkeypatch):
    storage, saved, output, contents = package
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["project_calculation"] = dict(
            state="calculated", handoff_version=STUDIO_HANDOFF_VERSION, preview_notes=[],
            sewer_scheme={"presentation": "registry", "ready": True}, flows={"q": 1.23},
            can_release=True, quality=build_release_quality_report(None, None).to_dict(),
        )
    monkeypatch.setitem(wizard._RUNS, "abc", dict(outdir=str(output)))
    def forbidden(*args, **kwargs):
        pytest.fail("Opening a release must not restore or calculate its project")
    monkeypatch.setattr(wizard, "_restore_run", forbidden)
    monkeypatch.setattr(wizard, "design_ios2", forbidden)
    monkeypatch.setattr(studio, "calculate_project", forbidden)
    return storage, storage.load(saved["project_id"]), output, contents


@pytest.mark.parametrize("damage", ["missing", "empty", "directory"])
def test_open_withdraws_ready_without_touching_release(client, saved_package, damage):
    storage, saved, output, contents = saved_package
    (output / "scheme.pdf").unlink()
    if damage == "empty":
        (output / "scheme.pdf").touch()
    elif damage == "directory":
        (output / "scheme.pdf").mkdir()
    draft_file = storage.folder(saved["project_id"]) / "draft.json"
    before = draft_file.read_bytes()
    response = client.get("/studio/api/draft")
    assert response.status_code == 200
    public = response.json()
    assert public["package"]["state"] == "unavailable"
    assert public["package"]["missing_files"] == ["scheme.pdf"]
    documents = {row["name"]: row for row in public["package"]["documents"]}
    assert documents["scheme.pdf"]["file_missing"]
    assert not documents["ПЗ.pdf"]["file_missing"]
    assert not public["project_calculation"]["can_release"]
    assert public["project_calculation"]["quality"]["state"] == "blocked"
    assert any(row["code"] == "PACKAGE-FILES" for gate in public["project_calculation"]["quality"]["gates"]
               for row in gate["findings"])
    assert public["project_calculation"]["flows"] == saved["project_calculation"]["flows"]
    assert public["project_calculation"]["sewer_scheme"] == saved["project_calculation"]["sewer_scheme"]
    assert public["revision"] == saved["revision"]
    assert draft_file.read_bytes() == before and storage.load(saved["project_id"]) == saved
    assert (output / "ПЗ.pdf").read_bytes() == contents["ПЗ.pdf"]
    assert client.get("/studio/api/draft").json() == public
    assert client.get("/studio/api/package/abc/download").status_code == 404
    assert client.get("/studio/api/package/abc/files/ПЗ.pdf").status_code == 200


def test_healthy_package_is_unchanged_and_returned_file_restores_saved_view(client, saved_package):
    storage, saved, output, contents = saved_package
    before = client.get("/studio/api/draft").json()
    assert before["package"] == saved["package"]
    assert before["project_calculation"] == saved["project_calculation"]
    (output / "scheme.pdf").write_bytes(b"")
    assert client.get("/studio/api/draft").json()["package"]["state"] == "unavailable"
    (output / "scheme.pdf").write_bytes(contents["scheme.pdf"])
    assert client.get("/studio/api/draft").json() == before


def test_cold_context_reads_snapshot_metadata_without_restoring_model(client, saved_package, monkeypatch):
    storage, saved, output, contents = saved_package
    monkeypatch.delitem(wizard._RUNS, "abc")
    monkeypatch.setattr(wizard, "_OUT_ROOT", str(output.parent))
    output.rename(output.parent / "abc")
    monkeypatch.setattr(wizard, "_run_file", REAL_RUN_FILE)
    calls = []
    def load(run_id):
        calls.append(run_id)
        return SimpleNamespace(passport_id="saved-passport", release_id=run_id)
    monkeypatch.setattr(wizard, "_RELEASE_STORE", SimpleNamespace(load=load))
    assert client.get("/studio/api/draft").json()["package"] == saved["package"]
    assert calls == ["abc"]
    assert "abc" not in wizard._RUNS


def test_saved_passport_fallback_remains_available(client, saved_package, monkeypatch):
    storage, saved, output, contents = saved_package
    (output / "scheme.pdf").unlink()
    backup = output.parent / "backup.pdf"
    backup.write_bytes(contents["scheme.pdf"])
    monkeypatch.setattr(wizard, "_run_file", REAL_RUN_FILE)
    monkeypatch.setattr(wizard, "_PASSPORT_STORE", SimpleNamespace(document=lambda *_: (backup, {})))
    assert client.get("/studio/api/draft").json()["package"] == saved["package"]


@pytest.mark.parametrize("documents", [[], None, [None], [{}], [dict(name="../other.pdf")],
                                      [dict(name="scheme.pdf"), dict(name="scheme.pdf")]])
def test_bad_manifest_does_not_remain_ready(client, saved_package, documents):
    storage, saved, output, contents = saved_package
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["package"]["documents"] = deepcopy(documents)
    before = storage.load(saved["project_id"])
    response = client.get("/studio/api/draft")
    assert response.status_code == 200
    assert response.json()["package"]["state"] == "unavailable"
    assert response.json()["package"]["availability_note"]
    assert storage.load(saved["project_id"]) == before


@pytest.mark.parametrize("error", [wizard.ReleaseNotFoundError, wizard.ReleaseIntegrityError, OSError])
def test_unavailable_cold_snapshot_fails_closed(client, saved_package, monkeypatch, error):
    storage, saved, output, contents = saved_package
    monkeypatch.delitem(wizard._RUNS, "abc")
    def load(run_id):
        raise error("test unavailable snapshot")
    monkeypatch.setattr(wizard, "_RELEASE_STORE", SimpleNamespace(load=load))
    public = client.get("/studio/api/draft").json()
    assert public["package"]["state"] == "unavailable"
    assert set(public["package"]["missing_files"]) == set(contents)
    assert storage.load(saved["project_id"]) == saved
    assert "abc" not in wizard._RUNS


def test_resolver_io_failure_does_not_hide_healthy_document(client, saved_package, monkeypatch):
    storage, saved, output, contents = saved_package
    def resolve(run, name):
        if name == "scheme.pdf":
            raise OSError("test access failure")
        return output / name
    monkeypatch.setattr(wizard, "_run_file", resolve)
    public = client.get("/studio/api/draft").json()
    assert public["package"]["missing_files"] == ["scheme.pdf"]
    assert storage.load(saved["project_id"]) == saved


def test_returning_file_does_not_grant_previously_denied_release(client, saved_package):
    storage, saved, output, contents = saved_package
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["project_calculation"]["can_release"] = False
    before = client.get("/studio/api/draft").json()
    (output / "scheme.pdf").write_bytes(b"")
    assert client.get("/studio/api/draft").json()["package"]["state"] == "unavailable"
    (output / "scheme.pdf").write_bytes(contents["scheme.pdf"])
    after = client.get("/studio/api/draft").json()
    assert after == before
    assert not after["project_calculation"]["can_release"]

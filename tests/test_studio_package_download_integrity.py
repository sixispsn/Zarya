"""ZIP transport completeness, using bytes fixtures (not authored PDFs)."""
import io
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.intake.studio_store import StudioStore
from app.intake.pilot_objects import calculation_stamp
from app.intake.studio_project import STUDIO_HANDOFF_VERSION
from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION
from app.web import wizard
from tests import test_studio as studio_tests

client = studio_tests.client
REAL_RUN_FILE = wizard._run_file


@pytest.fixture
def package(client, tmp_path, monkeypatch):
    state = studio_tests.new(client)
    storage = StudioStore(tmp_path / "studio")
    output = tmp_path / "release"
    output.mkdir()
    contents = {"ПЗ.pdf": b"first test file", "scheme.pdf": b"second test file"}
    for name, content in contents.items():
        (output / name).write_bytes(content)
    with storage.edit(state["project_id"], state["revision"]) as data:
        data["package"] = dict(
            state="ready", run_id="abc", render_version=DOCUMENT_RENDER_VERSION,
            handoff_version=STUDIO_HANDOFF_VERSION, stamp=calculation_stamp(data),
            documents=[dict(name=name, state="ready", label=name) for name in contents],
        )
    monkeypatch.setattr(wizard, "_get_run", lambda _: dict(outdir=str(output)))
    # Scope is the Studio download boundary; resolver fallback is tested separately.
    monkeypatch.setattr(wizard, "_run_file", lambda run, name: str(output / name))
    return storage, storage.load(state["project_id"]), output, contents


@pytest.mark.parametrize("damage", ["missing", "empty", "directory"])
@pytest.mark.parametrize("endpoint", ["download", "files/scheme.pdf"])
def test_damaged_file_never_downloads_as_success(client, package, damage, endpoint):
    storage, saved, output, contents = package
    damaged = output / "scheme.pdf"
    damaged.unlink()
    if damage == "empty":
        damaged.touch()
    elif damage == "directory":
        damaged.mkdir()
    snapshot = (storage.folder(saved["project_id"]) / "draft.json").read_bytes()
    response = client.get("/studio/api/package/abc/" + endpoint)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert not response.content.startswith(b"PK")
    assert (storage.folder(saved["project_id"]) / "draft.json").read_bytes() == snapshot
    assert (output / "ПЗ.pdf").read_bytes() == contents["ПЗ.pdf"]


def test_complete_zip_contains_exact_manifest_and_bytes_and_keeps_access_private(client, package):
    storage, saved, output, contents = package
    response = client.get("/studio/api/package/abc/download")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == list(contents)
        assert archive.testzip() is None
        assert {name: archive.read(name) for name in archive.namelist()} == contents
    assert storage.load(saved["project_id"]) == saved
    with TestClient(studio_tests.app) as other:
        assert other.get("/studio/api/package/abc/download").status_code == 404
    assert client.get("/studio/api/package/other/download").status_code == 404


@pytest.mark.parametrize("names", [[], ["scheme.pdf", "scheme.pdf"], ["../scheme.pdf"],
                                  ["dir\\scheme.pdf"], [""], [None]])
def test_invalid_manifest_is_not_a_successful_zip(client, package, names):
    storage, saved, output, contents = package
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["package"]["documents"] = [dict(name=name) for name in names]
    assert client.get("/studio/api/package/abc/download").status_code == 404


def test_file_disappearing_during_read_returns_no_partial_zip(client, package, monkeypatch):
    storage, saved, output, contents = package
    original = Path.open
    def failing_open(path, *args, **kwargs):
        if path == output / "scheme.pdf":
            raise FileNotFoundError("simulated removal after validation")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", failing_open)
    response = client.get("/studio/api/package/abc/download")
    assert response.status_code == 404
    assert not response.content.startswith(b"PK")


@pytest.mark.parametrize("replacement", [b"", b"x" * 16])
def test_file_changed_while_reading_cannot_produce_success(client, package, monkeypatch, replacement):
    storage, saved, output, contents = package
    original = Path.open
    class ChangingReader:
        def __enter__(self):
            self.stream = original(output / "scheme.pdf", "rb")
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self):
            data = self.stream.read()
            with original(output / "scheme.pdf", "wb") as writer:
                writer.write(replacement)
            return data
    def changing_open(path, *args, **kwargs):
        return ChangingReader() if path == output / "scheme.pdf" else original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", changing_open)
    response = client.get("/studio/api/package/abc/download")
    assert response.status_code == 404
    assert not response.content.startswith(b"PK")


def test_archive_uses_checked_bytes_without_second_file_read(client, package, monkeypatch):
    storage, saved, output, contents = package
    original = zipfile.ZipFile.writestr
    def replace_after_read(archive, name, data, *args, **kwargs):
        (output / name).write_bytes(b"replaced after completed read")
        return original(archive, name, data, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "writestr", replace_after_read)
    response = client.get("/studio/api/package/abc/download")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == contents


def test_existing_resolver_can_use_saved_passport_copy(client, package, monkeypatch):
    storage, saved, output, contents = package
    # Restore the real resolver, preserving its documented fallback instead of
    # imposing a new location or regenerating missing historical documents.
    backup = output.parent / "passport-copy.pdf"
    backup.write_bytes(contents["scheme.pdf"])
    (output / "scheme.pdf").unlink()
    monkeypatch.setattr(wizard, "_run_file", REAL_RUN_FILE)
    monkeypatch.setattr(wizard, "_PASSPORT_STORE", SimpleNamespace(
        document=lambda ident, name: (backup, {})))
    response = client.get("/studio/api/package/abc/download")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == contents


@pytest.mark.parametrize("documents", [None, "scheme.pdf", [None], [{}]])
def test_malformed_document_metadata_fails_closed(client, package, documents):
    storage, saved, output, contents = package
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["package"]["documents"] = documents
    assert client.get("/studio/api/package/abc/download").status_code == 404

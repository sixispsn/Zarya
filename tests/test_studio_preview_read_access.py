"""Read-time file checks use byte-presence fixtures, not authored PDFs."""
from copy import deepcopy

import pytest

from app.intake.studio_store import StudioStore
from app.intake.studio_project import calculate_project, STUDIO_HANDOFF_VERSION
from app.intake.pilot_objects import calculation_stamp
from app.pz.water_scheme_delivery import DOCUMENT_RENDER_VERSION
from app.web import studio
from tests import test_studio as studio_tests
from tests.test_studio_apartment_meters import draft
from tests.test_studio_preview_readiness import findings
from tests.test_normative_audit_matrix import _all_artifacts

client = studio_tests.client
LABEL = "Принципиальная схема К1/К2"
PACKAGE = "Комплект ИОС3"


@pytest.fixture
def saved_preview(client, tmp_path, monkeypatch):
    state = studio_tests.new(client)
    storage = StudioStore(tmp_path / "studio")
    data = draft()
    data["project_calculation"] = calculate_project(data, artifacts=_all_artifacts())
    folder = storage.folder(state["project_id"]) / "previews" / ("a" * 32)
    folder.mkdir(parents=True)
    for name in ("scheme.pdf", "package.pdf", "spec.pdf"):
        (folder / name).write_bytes(b"presence-only fixture, not a PDF")
    with storage.edit(state["project_id"], state["revision"]) as stored:
        stored.update(data)
        stored["preview"] = {
            "id": "a" * 32, "state": "preview", "stamp": calculation_stamp(stored),
            "handoff_version": STUDIO_HANDOFF_VERSION, "render_version": DOCUMENT_RENDER_VERSION,
            "artifact_files": {LABEL: ["scheme.pdf"], PACKAGE: ["package.pdf"],
                               "Спецификация": ["spec.pdf"]},
            "artifact_readiness": {LABEL: True, PACKAGE: True},
            "graphic_artifact_requirements": [LABEL],
            "documents": [
                {"name": "scheme.pdf", "label": LABEL, "kind": "wastewater_scheme_pdf", "state": "ready"},
                {"name": "package.pdf", "label": PACKAGE, "kind": "wastewater_package_pdf", "state": "preliminary"},
                {"name": "spec.pdf", "label": "Спецификация", "kind": "spec_pdf", "state": "ready"},
            ],
        }
    # Valid read must not invoke the expensive calculation path.
    def forbidden(*args, **kwargs):
        pytest.fail("Opening current preview must not run calculations")
    monkeypatch.setattr(studio, "calculate_project", forbidden)
    return storage, storage.load(state["project_id"]), folder


@pytest.mark.parametrize("damage", ["missing", "empty", "directory"])
def test_open_restricts_missing_pdf_without_writing_or_recalculating(client, saved_preview, damage):
    storage, saved, folder = saved_preview
    original = deepcopy(saved)
    path = folder / "scheme.pdf"
    content = path.read_bytes()
    path.unlink()
    if damage == "empty":
        path.touch()
    elif damage == "directory":
        path.mkdir()
    disk = (storage.folder(saved["project_id"]) / "draft.json").read_bytes()
    response = client.get("/studio/api/draft")
    assert response.status_code == 200
    public = response.json()
    assert public["documents_need_refresh"] is True
    assert public["project_calculation"]["can_release"] is False
    assert findings(public["project_calculation"])["K-GOST-A03"]["state"] == "blocked"
    assert findings(public["project_calculation"])["DOC-03"]["state"] == "blocked"
    assert findings(public["project_calculation"])["V-GOST-A03"] == findings(saved["project_calculation"])["V-GOST-A03"]
    assert any(row["code"] == "PREVIEW-FILES" for row in findings(public["project_calculation"]).values())
    for key in ("flows", "meters", "head", "pumps", "storm", "sewer_scheme"):
        assert public["project_calculation"][key] == original["project_calculation"][key]
    documents = {doc["name"]: doc for doc in public["preview"]["documents"]}
    assert documents["scheme.pdf"]["state"] == "incomplete"
    assert documents["package.pdf"]["state"] == "incomplete"
    assert documents["spec.pdf"]["state"] == "ready"
    assert public["preview"]["artifact_readiness"][LABEL] is False
    assert public["preview"]["artifact_readiness"][PACKAGE] is False
    assert public["revision"] == saved["revision"]
    assert storage.load(saved["project_id"]) == original
    assert (storage.folder(saved["project_id"]) / "draft.json").read_bytes() == disk
    assert (folder / "package.pdf").read_bytes() == content
    assert client.get(f"/studio/api/preview/{saved['preview']['id']}/files/scheme.pdf").status_code == 404
    assert client.get(f"/studio/api/preview/{saved['preview']['id']}/files/spec.pdf").status_code == 200
    # Repeated GET is idempotent; no duplicate findings or cumulative counters.
    assert client.get("/studio/api/draft").json() == public


def test_intact_open_is_unchanged_and_cannot_grant_release(client, saved_preview):
    storage, saved, folder = saved_preview
    public = client.get("/studio/api/draft").json()
    assert public["documents_need_refresh"] is False
    assert public["preview"] == saved["preview"]
    assert public["project_calculation"] == saved["project_calculation"]
    assert not public["project_calculation"]["can_release"]
    assert storage.load(saved["project_id"]) == saved


def test_restored_file_returns_original_view_not_new_release(client, saved_preview):
    storage, saved, folder = saved_preview
    path = folder / "scheme.pdf"
    content = path.read_bytes()
    path.write_bytes(b"")
    assert client.get("/studio/api/draft").json()["documents_need_refresh"]
    path.write_bytes(content)
    public = client.get("/studio/api/draft").json()
    assert public["preview"] == saved["preview"]
    assert public["project_calculation"] == saved["project_calculation"]
    assert not public["project_calculation"]["can_release"]


def test_loss_withdraws_previously_true_permission_and_updates_counts(client, saved_preview):
    storage, saved, folder = saved_preview
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["project_calculation"]["can_release"] = True
    (folder / "scheme.pdf").write_bytes(b"")
    (folder / "spec.pdf").write_bytes(b"")
    public = client.get("/studio/api/draft").json()
    calculation = public["project_calculation"]
    assert calculation["can_release"] is False
    assert findings(calculation)["V-GOST-A03"]["state"] == "blocked"
    assert findings(calculation)["DOC-01"]["state"] == "blocked"
    quality = calculation["quality"]
    assert quality["state"] == "blocked" and not quality["can_release"]
    assert quality["blocking_count"] == sum(
        row["state"] == "blocked" and row["source"] != "quality_gates"
        for gate in quality["gates"] for row in gate["findings"])
    for gate in quality["gates"]:
        assert gate["counts"]["blocked"] == sum(r["state"] == "blocked" for r in gate["findings"])
    assert storage.load(saved["project_id"])["project_calculation"]["can_release"] is True


def test_optional_file_loss_blocks_technical_guard_not_unrelated_audits(client, saved_preview):
    storage, saved, folder = saved_preview
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["preview"]["documents"].append(dict(name="extra.pdf", label="Дополнение",
                                                  kind="extra_pdf", state="ready"))
    public = client.get("/studio/api/draft").json()
    assert public["documents_missing_files"] == ["extra.pdf"]
    assert public["documents_need_refresh"]
    assert not public["project_calculation"]["can_release"]
    for code, row in findings(saved["project_calculation"]).items():
        assert findings(public["project_calculation"])[code] == row


def test_alternative_existing_file_keeps_artifact_ready(client, saved_preview):
    storage, saved, folder = saved_preview
    with storage.edit(saved["project_id"], saved["revision"]) as data:
        data["preview"]["artifact_files"]["Спецификация"].append("alternative.pdf")
    (folder / "alternative.pdf").write_bytes(b"alternative presence fixture")
    (folder / "spec.pdf").write_bytes(b"")
    public = client.get("/studio/api/draft").json()
    assert public["documents_need_refresh"]
    assert findings(public["project_calculation"])["V-GOST-A03"] == findings(saved["project_calculation"])["V-GOST-A03"]
    assert public["preview"]["artifact_readiness"][LABEL] is True


def test_stat_error_is_unavailable_not_server_error(tmp_path, monkeypatch):
    from pathlib import Path
    def unavailable(_path):
        raise OSError("simulated filesystem race")
    monkeypatch.setattr(Path, "is_file", unavailable)
    assert not studio.preview_file_exists(tmp_path, "gone.pdf")


@pytest.mark.parametrize("name", ["", "../other.pdf", "/absolute.pdf", None])
def test_invalid_preview_filename_cannot_escape_folder(tmp_path, name):
    assert not studio.preview_file_exists(tmp_path, name)

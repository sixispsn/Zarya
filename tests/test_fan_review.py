from copy import deepcopy
from dataclasses import replace
from io import BytesIO

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from app.intake.project_store import ProjectStore
from app.intake.yaml_io import dump_request, load_request
from app.web import wizard
from app.web.fan_review import assess_fan_preview
from tests.fan_binding_fixture import fan_binding_request_fixture
from tests.test_wizard_fan_inputs import request


def test_review_saved_roundtrip_is_read_only_and_never_approves_pd():
    req = load_request(dump_request(fan_binding_request_fixture()))
    before = deepcopy(req)
    report = assess_fan_preview(req)
    assert req == before
    assert report.preview_ready
    result = report.to_mapping("test-version")
    assert result["production_ready"] is False
    assert result["revision"] == "test-version"
    assert any(c["code"] == "FAN-DRAWING" for c in result["checks"])


@pytest.mark.parametrize(
    "change,code",
    [
        ("proof", "FAN-EXTERNAL"),
        ("confirmation", "FAN-GEOMETRY"),
        ("roof", "FAN-ROOF-LEVEL"),
        ("mode", "FAN-MODE"),
        ("member", "FAN-MEMBER"),
        ("input", "INPUT-0"),
        ("port", "FAN-BUILDING-BINDING"),
        ("outline", "FAN-BUILDING-BINDING"),
    ],
)
def test_review_rejects_missing_or_conflicting_data(change, code):
    req = fan_binding_request_fixture()
    if change == "proof":
        req.wastewater_fan_ventilation = replace(
            req.wastewater_fan_ventilation, external_ventilation_verified=None
        )
    if change == "confirmation":
        req.wastewater_fan_geometry = replace(
            req.wastewater_fan_geometry, confirmed=False
        )
    if change == "roof":
        req.wastewater_roof_relative_elevation_m = None
    if change == "mode":
        req.sewage_risers[-1].ventilation = "ventilated"
    if change == "member":
        evidence = req.wastewater_fan_ventilation
        req.wastewater_fan_ventilation = replace(
            evidence,
            terminals=(
                replace(evidence.terminals[0], riser_ids=("К1-UNKNOWN",)),
                evidence.terminals[1],
            ),
        )
    if change == "input":
        req.floors = -1
    if change == "port":
        req.sewer_pipes[0].elevation_start_m = 4.6
    if change == "outline":
        g = req.wastewater_fan_geometry
        req.wastewater_fan_geometry = replace(
            g, valves=(replace(g.valves[0], outline_ref="unknown"),)
        )
    result = assess_fan_preview(req)
    assert not result.preview_ready
    assert any(c["code"] == code and c["status"] != "verified" for c in result.checks)


def test_graphic_audit_failure_blocks_preview(monkeypatch):
    from app.web import fan_review

    def fail(*args):
        raise ValueError("annotation collision")

    monkeypatch.setattr(fan_review, "build_bound_fan_preview_svgs", fail)
    result = assess_fan_preview(fan_binding_request_fixture())
    assert not result.preview_ready
    assert result.checks[-1]["code"] == "FAN-DRAWING"


@pytest.fixture
def saved(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    monkeypatch.setattr(wizard, "_STORE", store)
    req = fan_binding_request_fixture()
    pid = store.save(req)
    return store, req, pid, store.source_sha256(pid)


def test_check_endpoint_reports_saved_revision(saved):
    import json

    store, req, pid, revision = saved
    response = wizard.check_saved_fan_project(request(revision=revision), pid)
    body = json.loads(response.body)
    assert body["preview_ready"] and not body["production_ready"]
    assert body["revision"] == revision
    assert store.load(pid) == req
    assert response.headers["cache-control"] == "no-store"


def test_pdf_endpoint_rechecks_and_returns_control_bytes(saved):
    store, req, pid, revision = saved
    response = wizard.download_saved_fan_preview(request(revision=revision), pid)
    assert response.media_type == "application/pdf"
    assert response.headers["x-zarya-project-revision"] == revision
    assert response.headers["x-zarya-control-only"] == "true"
    reader = PdfReader(BytesIO(response.body))
    assert len(reader.pages) == 7
    assert all(
        "Контроль" in p.extract_text() or "контроль" in p.extract_text()
        for p in reader.pages
    )
    assert store.load(pid) == req
    assert store.source_sha256(pid) == revision


def test_missing_proof_never_calls_pdf_writer(saved, monkeypatch):
    store, req, pid, _ = saved
    req.wastewater_fan_geometry = replace(req.wastewater_fan_geometry, confirmed=False)
    store.save(req, pid)
    monkeypatch.setattr(
        wizard,
        "generate_saved_fan_binding_preview",
        lambda *args: pytest.fail("must not render"),
    )
    response = wizard.download_saved_fan_preview(
        request(revision=store.source_sha256(pid)), pid
    )
    assert response.status_code == 422 and response.media_type == "application/json"


@pytest.mark.parametrize(
    "endpoint", [wizard.check_saved_fan_project, wizard.download_saved_fan_preview]
)
@pytest.mark.parametrize("revision", [None, "0" * 64])
def test_stale_or_missing_version_is_not_accepted(saved, endpoint, revision):
    _, _, pid, _ = saved
    with pytest.raises(HTTPException) as error:
        endpoint(request(revision=revision), pid)
    assert error.value.status_code == 409


def test_version_changed_during_pdf_generation_is_not_returned(saved, monkeypatch):
    store, req, pid, revision = saved
    real = wizard.generate_saved_fan_binding_preview

    def render_and_change(*args):
        result = real(*args)
        store.save(replace(req, document=replace(req.document, cipher="CHANGED")), pid)
        return result

    monkeypatch.setattr(wizard, "generate_saved_fan_binding_preview", render_and_change)
    with pytest.raises(HTTPException) as error:
        wizard.download_saved_fan_preview(request(revision=revision), pid)
    assert error.value.status_code == 409


def test_unknown_project_has_no_preview():
    with pytest.raises(HTTPException) as error:
        wizard.check_saved_fan_project(request(revision="0" * 64), "../bad")
    assert error.value.status_code == 404

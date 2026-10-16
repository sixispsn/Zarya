"""A downloadable control sheet must never close a graphic completeness check."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.pz.artifact_readiness import WASTEWATER_GRAPHIC_ARTIFACTS as GRAPHICS
from app.pz.artifact_readiness import WASTEWATER_PACKAGE as PACKAGE
from app.pz.ios2_orchestrator import (
    IOS2DesignBundle, bundle_artifact_files, bundle_artifact_readiness, bundle_artifacts,
)
from app.pz.wastewater_graphic_exports import (
    WastewaterGraphicGenerationResult, generate_wastewater_graphic_export,
)
from tests.test_wastewater_scheme_service import _project
from tests.test_wastewater_k3_scheme import _k3_project
from tests.test_wastewater_pressure_scheme import _pressure_project


@pytest.mark.parametrize("key,factory", [("k1-k2", _project), ("k3", _k3_project),
                                         ("pressure", _pressure_project)])
@pytest.mark.parametrize("complete", [False, True])
def test_real_generator_status_qualifies_existing_pdf(tmp_path, key, factory, complete):
    project = factory()
    if not complete:
        if key == "k1-k2":
            project.sewage.elements = [e for e in project.sewage.elements if e.element_id != "К1-ПрНП1"]
        elif key == "k3":
            project.sewage.elements = [e for e in project.sewage.elements if e.element_id != "К3-ЖУ1"]
            next(e for e in project.sewage.elements if e.element_id == "К3-Мой1").connects_to = "К3-Ст1"
        else:
            project.sewage.pump_curve = []
    path = tmp_path / f"{key}.pdf"
    result = generate_wastewater_graphic_export(project, key, str(path))
    assert result.ready is complete
    assert path.is_file() and path.stat().st_size > 0
    bundle = IOS2DesignBundle(project=project, wastewater_graphic_results={key: result},
                              wastewater_graphic_required=(key,))
    label, attribute = GRAPHICS[key]
    setattr(bundle, attribute, str(path))
    assert bundle_artifact_files(bundle)[label] == [str(path)]
    assert bundle_artifacts(bundle)[label] is complete
    from app.web.wizard import _bundle_documents
    documents, _ = _bundle_documents(bundle)
    document = next(d for d in documents if d["kind"] == attribute)
    assert document["state"] == ("ready" if complete else "incomplete")
    if not complete:
        assert document["state_note"]


def _bundle(tmp_path):
    bundle = IOS2DesignBundle(project=_project(), wastewater_graphic_required=tuple(GRAPHICS))
    for key, (_, attribute) in GRAPHICS.items():
        path = tmp_path / f"{key}.pdf"
        path.write_bytes(b"presence fixture, not a rendered PDF")
        setattr(bundle, attribute, str(path))
        bundle.wastewater_graphic_results[key] = WastewaterGraphicGenerationResult(
            key, str(path), True, "test-evidence",
        )
    package = tmp_path / "package.pdf"
    package.write_bytes(b"presence fixture, not a rendered PDF")
    bundle.wastewater_package_pdf = str(package)
    return bundle


@pytest.mark.parametrize("key", GRAPHICS)
@pytest.mark.parametrize("change", ["missing-result", "false", "truthy", "wrong-key", "wrong-path", "deleted", "empty"])
def test_no_file_or_no_exact_generation_evidence_cannot_complete_package(tmp_path, key, change):
    bundle = _bundle(tmp_path)
    label, attribute = GRAPHICS[key]
    assert bundle_artifacts(bundle)[PACKAGE]
    result = bundle.wastewater_graphic_results[key]
    if change == "missing-result":
        del bundle.wastewater_graphic_results[key]
    elif change == "deleted":
        Path(getattr(bundle, attribute)).unlink()
    elif change == "empty":
        Path(getattr(bundle, attribute)).write_bytes(b"")
    else:
        changes = {"false": {"ready": False}, "truthy": {"ready": 1},
                   "wrong-key": {"key": "other"}, "wrong-path": {"output_path": "old.pdf"}}
        bundle.wastewater_graphic_results[key] = replace(result, **changes[change])
    assert not bundle_artifacts(bundle)[label]
    assert not bundle_artifacts(bundle)[PACKAGE]
    assert bundle_artifact_files(bundle)[label]  # control/review link is retained


@pytest.mark.parametrize("required", [None, (), ("k3",), ("k1-k2", "unknown")])
def test_unknown_required_set_cannot_confirm_package(tmp_path, required):
    bundle = _bundle(tmp_path)
    bundle.wastewater_graphic_required = required
    assert not bundle_artifacts(bundle)[PACKAGE]


@pytest.mark.parametrize("change", ["none", "false", "missing", "deleted", "requirements-missing",
                                    "requirements-invalid", "requirements-unknown", "stale-version"])
def test_saved_preview_rechecks_readiness_and_required_files(tmp_path, monkeypatch, change):
    from app.web import studio
    bundle = _bundle(tmp_path)
    preview_id = "a" * 32
    folder = tmp_path / "previews" / preview_id
    folder.mkdir(parents=True)
    files = {label: [Path(p).name for p in paths] for label, paths in bundle_artifact_files(bundle).items()}
    for paths in bundle_artifact_files(bundle).values():
        for path in paths:
            (folder / Path(path).name).write_bytes(Path(path).read_bytes())
    saved = {"id": preview_id, "artifact_files": files,
             "artifact_readiness": bundle_artifact_readiness(bundle),
             "graphic_artifact_requirements": [label for label, _ in GRAPHICS.values()]}
    label = GRAPHICS["k3"][0]
    if change == "false":
        saved["artifact_readiness"][label] = False
    elif change == "missing":
        del saved["artifact_readiness"]
    elif change == "deleted":
        (folder / "k3.pdf").unlink()
    elif change == "requirements-missing":
        del saved["graphic_artifact_requirements"]
    elif change == "requirements-invalid":
        saved["graphic_artifact_requirements"] = "k3"
    elif change == "requirements-unknown":
        saved["graphic_artifact_requirements"].append("unknown")
    monkeypatch.setattr(studio, "store", lambda request: SimpleNamespace(folder=lambda did: tmp_path))
    monkeypatch.setattr(studio, "documents_current", lambda saved, draft: change != "stale-version")
    artifacts = studio.current_preview_artifacts(None, "draft", {"preview": saved})
    if change == "stale-version":
        assert artifacts is None
    else:
        assert artifacts[PACKAGE] is (change == "none")
        if change in {"false", "missing", "deleted"}:
            assert not artifacts[label]


def test_real_demo_control_sheet_blocks_commission_but_keeps_download(tmp_path):
    from app.intake.project_builder import build_project
    from app.intake.yaml_io import load_request_file
    from app.pz.commission import build_commission_report
    from app.pz.ios2_orchestrator import design_ios2
    project = design_ios2(build_project(load_request_file("demo/demo_project.yaml")),
                          render_documents=False).project
    path = tmp_path / "control.pdf"
    result = generate_wastewater_graphic_export(project, "k1-k2", str(path))
    assert not result.ready and any("вентиляции" in reason for reason in result.reasons)
    bundle = IOS2DesignBundle(project=project, wastewater_scheme_pdf=str(path),
                              wastewater_graphic_results={"k1-k2": result},
                              wastewater_graphic_required=("k1-k2",))
    report = build_commission_report(project, bundle_artifacts(bundle))
    rows = {row["rule_id"]: row for audit in report.normative_audits for row in audit["rows"]}
    assert rows["K-GOST-A03"]["blocks_release"]
    assert next(check for check in report.checks if check.code == "DOC-03").blocking
    assert bundle_artifact_files(bundle)[GRAPHICS["k1-k2"][0]] == [str(path)]

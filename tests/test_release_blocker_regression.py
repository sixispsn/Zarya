"""Контроль выпуска не скрывает пробелы исходных данных и ошибки диагностики."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.intake.preflight import preflight_request
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.commission import build_commission_report
from app.pz.ios2_orchestrator import design_ios2
from app.pz.wastewater_diagnostics import WastewaterDiagnosticAssessment
from app.pz.wastewater_gost import _current_calculated_fill, audit_wastewater_gost
from app.quality_gates import build_release_quality_report
from scripts.verify_control_release import blocker_snapshot, check_expected_blockers
from scripts import verify_control_release as control_release
from tests.test_normative_audit_matrix import _all_artifacts


@pytest.fixture(scope="module")
def demo():
    request = load_request_file("demo/demo_project.yaml")
    return request, design_ios2(build_project(request), render_documents=False).project


def _hydraulic_row(project):
    return next(row for row in audit_wastewater_gost(project).checks if row.code == "K-GOST-08")


def test_gost_reads_existing_calculation_without_writing_fictional_input(demo):
    _, original = demo
    project = deepcopy(original)
    row = _hydraulic_row(project)
    assert "h/d из выполненного расчёта: К1-М1, К1-Вып1" in row.evidence
    missing = row.evidence.split("не задано и не рассчитано h/d: ")[1]
    assert "К1-М1" not in missing and "К1-Вып1" not in missing
    assert "К1-Ветв-Кух1" in missing and "К2-М1" in missing
    assert row.status == "missing"
    assert all(pipe.fill_ratio is None for pipe in project.sewage.pipes)
    assert project.sewage.hydraulic_assessment == original.sewage.hydraulic_assessment


def test_calculated_horizontal_sections_do_not_require_retyping_fill(demo):
    project = deepcopy(demo[1])
    project.sewage.pipes = [p for p in project.sewage.pipes if p.section_id in {"К1-М1", "К1-Вып1"}]
    assert _hydraulic_row(project).status == "verified"


@pytest.mark.parametrize("field,value", [
    ("outer_diameter_mm", 160.0),
    ("slope_per_mille", 12.0),
    ("manning_n", 0.02),
    ("hydraulic_source", "другой паспорт"),
])
def test_stale_hydraulic_result_cannot_close_missing_fill(demo, field, value):
    project = deepcopy(demo[1])
    pipe = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    setattr(pipe, field, value)
    assert _current_calculated_fill(pipe, project.sewage.hydraulic_assessment) is None


@pytest.mark.parametrize("changes", [{"status": "fail"}, {"fill_ratio": float("nan")}, {"fill_ratio": None}])
def test_failed_or_invalid_calculated_fill_is_not_accepted(demo, changes):
    project = deepcopy(demo[1])
    assessment = project.sewage.hydraulic_assessment
    assessment.hydraulics[0] = replace(assessment.hydraulics[0], **changes)
    pipe = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    assert _current_calculated_fill(pipe, assessment) is None


def test_pressure_rated_material_does_not_prove_pressure_flow(demo):
    project = deepcopy(demo[1])
    project.sewage.pipes = [p for p in project.sewage.pipes if p.section_id == "К2-М1"]
    assert project.sewage.pipes[0].pressure_rated is True
    assert _hydraulic_row(project).status == "missing"


def test_real_demo_service_error_reaches_commission_and_quality(demo):
    request, project = demo
    report = build_commission_report(project)
    check = next(row for row in report.checks if row.code == "K1-05")
    assert check.blocking
    assert "К1-М1" in check.result and "0–52 м" in check.result
    quality = build_release_quality_report(preflight_request(request), report)
    assert "K1-05" in {row.code for row in quality.blocking_findings}


@pytest.mark.parametrize("diagnostic,status", [
    (None, "stage_r"),
    (WastewaterDiagnosticAssessment(warnings=["нужна точная привязка"]), "stage_r"),
    (WastewaterDiagnosticAssessment(), "verified"),
])
def test_missing_diagnostics_and_stage_r_are_not_passed_as_engineering_errors(demo, diagnostic, status):
    project = deepcopy(demo[1])
    project.sewage.hydraulic_assessment = diagnostic
    check = next(c for c in build_commission_report(project).checks if c.code == "K1-05")
    assert check.status == status
    assert not check.blocking
    assert check.result


def test_snapshot_exposes_leaf_causes_not_blanket_doc_exceptions(demo):
    request, project = demo
    artifacts = _all_artifacts()
    artifacts["План сетей водоснабжения"] = False
    report = build_commission_report(project, artifacts)
    quality = build_release_quality_report(preflight_request(request), report)
    rows = blocker_snapshot(quality, report)
    assert {row["code"] for row in rows} == {"SP54-01", "K1-05", "K-GOST-08", "V-GOST-A07"}
    assert "опорный план" in next(row["detail"] for row in rows if row["code"] == "V-GOST-A07")
    check_expected_blockers(rows, deepcopy(rows))
    baseline = json.loads(Path("demo/control_blockers.json").read_text())
    check_expected_blockers(rows, baseline["blockers"])

    # Новое требование внутри всё того же агрегированного DOC-04 не разрешено.
    changed = deepcopy(rows) + [{"code": "K-GOST-13", "detail": "нет схемы", "reference": "ГОСТ"}]
    with pytest.raises(RuntimeError, match="инженерная ревизия"):
        check_expected_blockers(changed, rows)
    # Новая ошибка другого участка под тем же кодом тоже не маскируется.
    changed = deepcopy(rows)
    changed[0]["detail"] += "; новая ошибка на К2-М1"
    with pytest.raises(RuntimeError):
        check_expected_blockers(changed, rows)
    with pytest.raises(RuntimeError):
        check_expected_blockers(rows[:-1], rows)
    with pytest.raises(ValueError):
        check_expected_blockers([], [])


def test_ci_is_explicitly_a_negative_case_not_permission_to_release():
    workflow = Path(".github/workflows/quality.yml").read_text()
    assert "--allow-blocker" not in workflow
    assert "--expected-blockers demo/control_blockers.json" in workflow
    assert "not release approval" in workflow


def test_control_runner_rejects_blockers_by_default_and_labels_negative_case(demo, monkeypatch, tmp_path):
    artifacts = _all_artifacts()
    artifacts["План сетей водоснабжения"] = False
    report = build_commission_report(demo[1], artifacts)
    bundle = SimpleNamespace(
        commission_report=report,
        **{name: tmp_path / f"{name}.pdf" for name in control_release.REQUIRED_DOCUMENTS},
    )
    monkeypatch.setattr(control_release, "design_ios2", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(control_release, "_inspect_pdf", lambda path: {"name": path.name})
    monkeypatch.setattr(control_release, "_render_first_pages", lambda *args: [])
    source = Path("demo/demo_project.yaml").resolve()
    with pytest.raises(RuntimeError, match="контрольный выпуск заблокирован"):
        control_release.verify_control_release(source, tmp_path / "strict")
    baseline = json.loads(Path("demo/control_blockers.json").read_text())
    manifest = control_release.verify_control_release(
        source, tmp_path / "negative", expected_blockers=baseline,
    )
    assert manifest["verification_mode"] == "expected_blocked"
    assert manifest["release_ready"] is False
    assert manifest["quality"]["state"] == "blocked"
    assert len(manifest["blocker_details"]) == 4

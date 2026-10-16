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
from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
from app.pz.wastewater_diagnostics import pipe_horizontal_flow
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


def _control_artifacts():
    artifacts = _all_artifacts()
    artifacts["План сетей водоснабжения"] = False
    # Real demo generation returns a control sheet, not a completed scheme.
    # Covered independently by test_real_demo_control_sheet_blocks_commission_but_keeps_download.
    artifacts["Принципиальная схема К1/К2"] = False
    artifacts["Комплект ИОС3"] = False
    return artifacts


@pytest.fixture(params=["manual", "formula"])
def calculated_project(demo, request):
    """Synthetic section loads, never amendments to the control YAML."""
    project = deepcopy(demo[1])
    for pipe in project.sewage.pipes:
        if pipe.section_id not in {"К1-М1", "К1-Вып1"}:
            continue
        if request.param == "manual":
            pipe.design_flow_lps = 4.0 if pipe.section_id == "К1-М1" else 8.0
            pipe.flow_source = "Синтетический расход отдельного участка для теста кэша"
        else:
            pipe.q_hour_max_m3h = 10.8 if pipe.section_id == "К1-М1" else 25.2
            pipe.fixtures_count = 32
            pipe.receiving_length_m = 10.0
            pipe.fixture_max_lps = 1.6
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    expected_flows = (4.0, 8.0) if request.param == "manual" else (3.752, 7.752)
    for ident, expected_flow in zip(("К1-М1", "К1-Вып1"), expected_flows):
        pipe = next(p for p in project.sewage.pipes if p.section_id == ident)
        assert pipe_horizontal_flow(pipe)[0] == pytest.approx(expected_flow)
        assert _current_calculated_fill(
            pipe, project.sewage.hydraulic_assessment, design_flow_lps=expected_flow,
        ) is not None
    return project


def test_unchanged_demo_never_inherits_riser_flow_or_cached_fill(demo, calculated_project):
    project = deepcopy(demo[1])
    assessment = project.sewage.hydraulic_assessment
    assert not assessment.hydraulics and not assessment.resolved_flows_lps
    expected = {"К1-Ветв-Кух1", "К1-Ветв-СУ1", "К1-Ветв-СУ2", "К1-Ветв-Кух2", "К1-М1", "К1-Вып1"}
    assert set(assessment.pending_horizontal_flows) == expected
    assert all(p.design_flow_lps is None for p in project.sewage.pipes if p.section_id in expected)
    # Even a previously valid cached result cannot supply missing current inputs.
    project.sewage.hydraulic_assessment = calculated_project.sewage.hydraulic_assessment
    checks = {r.code: r for r in audit_wastewater_gost(project).checks}
    assert checks["K-GOST-08F"].status == "missing"
    assert all(ident in checks["K-GOST-08F"].evidence for ident in expected)
    assert "h/d из выполненного расчёта" not in checks["K-GOST-08"].evidence


def test_gost_reads_existing_calculation_without_writing_fictional_input(calculated_project):
    original = calculated_project
    project = deepcopy(original)
    row = _hydraulic_row(project)
    assert "h/d из выполненного расчёта: К1-М1, К1-Вып1" in row.evidence
    missing = row.evidence.split("не задано и не рассчитано h/d: ")[1]
    assert "К1-М1" not in missing and "К1-Вып1" not in missing
    assert "К1-Ветв-Кух1" in missing and "К2-М1" in missing
    assert row.status == "missing"
    assert all(pipe.fill_ratio is None for pipe in project.sewage.pipes)
    assert project.sewage.hydraulic_assessment == original.sewage.hydraulic_assessment


def test_calculated_horizontal_sections_do_not_require_retyping_fill(calculated_project):
    project = deepcopy(calculated_project)
    project.sewage.pipes = [p for p in project.sewage.pipes if p.section_id in {"К1-М1", "К1-Вып1"}]
    assert _hydraulic_row(project).status == "verified"


@pytest.mark.parametrize("field,value", [
    ("outer_diameter_mm", 160.0),
    ("slope_per_mille", 12.0),
    ("manning_n", 0.02),
    ("hydraulic_source", "другой паспорт"),
])
def test_stale_hydraulic_result_cannot_close_missing_fill(calculated_project, field, value):
    project = deepcopy(calculated_project)
    pipe = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    setattr(pipe, field, value)
    assert _current_calculated_fill(
        pipe, project.sewage.hydraulic_assessment, design_flow_lps=pipe_horizontal_flow(pipe)[0],
    ) is None


@pytest.mark.parametrize("changes", [{"status": "fail"}, {"fill_ratio": float("nan")}, {"fill_ratio": None}])
def test_failed_or_invalid_calculated_fill_is_not_accepted(calculated_project, changes):
    project = deepcopy(calculated_project)
    assessment = project.sewage.hydraulic_assessment
    assessment.hydraulics[0] = replace(assessment.hydraulics[0], **changes)
    pipe = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    assert _current_calculated_fill(pipe, assessment, design_flow_lps=pipe_horizontal_flow(pipe)[0]) is None


@pytest.mark.parametrize("change", ["value", "removed", "basis"])
def test_changed_flow_cannot_reuse_old_fill_even_if_geometry_is_unchanged(calculated_project, change):
    project = deepcopy(calculated_project)
    main = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    old_flow = pipe_horizontal_flow(main)[0]
    if main.design_flow_lps is not None:
        if change == "basis":
            main.flow_source = ""
        else:
            main.design_flow_lps = 3.5 if change == "value" else None
    else:
        if change == "basis":
            main.fixtures_count = None
        else:
            main.q_hour_max_m3h = 14.4 if change == "value" else None
    # The cached resolver result also belongs to the OLD load. Re-read inputs.
    assert project.sewage.hydraulic_assessment.resolved_flows_lps["К1-М1"] == old_flow
    missing = _hydraulic_row(project).evidence.split("не задано и не рассчитано h/d: ")[1]
    assert "К1-М1" in missing


@pytest.mark.parametrize("remove", [False, True])
def test_riser_maximum_does_not_replace_explicit_horizontal_load(calculated_project, remove):
    project = deepcopy(calculated_project)
    main = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    old_flow = pipe_horizontal_flow(main)[0]
    if remove:
        project.sewage.risers = []
    else:
        for riser in project.sewage.risers:
            riser.design_flow_lps = 100
    assert pipe_horizontal_flow(main)[0] == old_flow
    assert "h/d из выполненного расчёта: К1-М1, К1-Вып1" in _hydraulic_row(project).evidence


@pytest.mark.parametrize("field,value", [
    ("fixtures_count", 40), ("receiving_length_m", 7.0), ("fixture_max_lps", 1.8),
])
def test_formula_inputs_invalidate_old_fill(demo, field, value):
    project = deepcopy(demo[1])
    main = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    main.q_hour_max_m3h = 10.8
    main.fixtures_count = 32
    main.receiving_length_m = 10.0
    main.fixture_max_lps = 1.6
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    assert _current_calculated_fill(
        main, project.sewage.hydraulic_assessment, design_flow_lps=3.752,
    ) is not None
    setattr(main, field, value)
    assert pipe_horizontal_flow(main)[0] != pytest.approx(3.752)
    assert "К1-М1" in _hydraulic_row(project).evidence.split("не задано и не рассчитано h/d: ")[1]


def test_manual_horizontal_flow_without_basis_stays_missing(demo):
    project = deepcopy(demo[1])
    main = next(p for p in project.sewage.pipes if p.section_id == "К1-М1")
    main.design_flow_lps = 4.0
    assert main.flow_source == ""
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    assert "К1-М1" in project.sewage.hydraulic_assessment.pending_horizontal_flows
    assert not project.sewage.hydraulic_assessment.hydraulics


def test_supplied_branch_load_is_calculated_without_retyping_fill(demo):
    project = deepcopy(demo[1])
    branch = next(p for p in project.sewage.pipes if p.section_id == "К1-Ветв-СУ1")
    branch.design_flow_lps = 2.758
    branch.flow_source = "Синтетический расчёт квартирной ветви; не расход стояка"
    branch.manning_n = 0.011
    branch.hydraulic_source = "явные исходные данные только теста"
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    calculated = next(h for h in project.sewage.hydraulic_assessment.hydraulics if h.section_id == branch.section_id)
    assert calculated.status == "verified"
    assert calculated.fill_ratio is not None
    assert branch.fill_ratio is None
    missing = _hydraulic_row(project).evidence.split("не задано и не рассчитано h/d: ")[1]
    assert branch.section_id not in missing
    branch.design_flow_lps = 3.5
    missing = _hydraulic_row(project).evidence.split("не задано и не рассчитано h/d: ")[1]
    assert branch.section_id in missing


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
    artifacts = _control_artifacts()
    report = build_commission_report(project, artifacts)
    quality = build_release_quality_report(preflight_request(request), report)
    rows = blocker_snapshot(quality, report)
    assert {row["code"] for row in rows} == {
        "CALC-03", "SP54-01", "K1-05", "K-GOST-08", "K-GOST-08F", "V-GOST-A07",
        "DOC-03", "K-GOST-A03",
    }
    assert "минимальный паспортный расход" in next(row["detail"] for row in rows if row["code"] == "CALC-03")
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
    # Neither the new requirement nor its correct source can be silently lost.
    without_flow = [r for r in rows if r["code"] != "K-GOST-08F"]
    with pytest.raises(RuntimeError):
        check_expected_blockers(without_flow, rows)
    wrong_source = deepcopy(rows)
    next(r for r in wrong_source if r["code"] == "K-GOST-08F")["reference"] = "ГОСТ, 5.7(7)"
    with pytest.raises(RuntimeError):
        check_expected_blockers(wrong_source, rows)
    with pytest.raises(ValueError):
        check_expected_blockers([], [])


def test_ci_is_explicitly_a_negative_case_not_permission_to_release():
    workflow = Path(".github/workflows/quality.yml").read_text()
    assert "--allow-blocker" not in workflow
    assert "--expected-blockers demo/control_blockers.json" in workflow
    assert "not release approval" in workflow


def test_snapshot_deduplicates_only_identical_leaf_causes():
    row = dict(rule_id="K-GOST-08", evidence="участок А", reference="ГОСТ", blocks_release=True)
    commission = SimpleNamespace(normative_audits=[dict(discipline="ИОС3", rows=[row])])
    quality = SimpleNamespace(blocking_findings=[
        SimpleNamespace(code="DOC-04", detail="сводка", reference="ГОСТ"),
        SimpleNamespace(code="K-GOST-08", detail="участок А", reference="ГОСТ"),
        SimpleNamespace(code="K-GOST-08", detail="участок Б", reference="ГОСТ"),
        SimpleNamespace(code="K-GOST-08", detail="участок А", reference="другая норма"),
    ])
    result = blocker_snapshot(quality, commission)
    assert len(result) == 3
    assert {(r["detail"], r["reference"]) for r in result} == {
        ("участок А", "ГОСТ"), ("участок Б", "ГОСТ"), ("участок А", "другая норма")}


def test_control_runner_rejects_blockers_by_default_and_labels_negative_case(demo, monkeypatch, tmp_path):
    artifacts = _control_artifacts()
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
    assert len(manifest["blocker_details"]) == 8
    bundle.commission_report = None
    with pytest.raises(RuntimeError, match="не сформировал комиссионный отчёт"):
        control_release.verify_control_release(
            source, tmp_path / "missing-report", expected_blockers=baseline,
        )

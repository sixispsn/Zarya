"""Комиссионный паспорт, трассировка и честные статусы выпуска."""
from pathlib import Path

from app.calc.storm import StormInput, StormNetworkInput, assess_storm_network, calculate_storm
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.commission import build_commission_report
from app.pz.demand_bridge import compute_flows
from app.pz.normative import derive_requirements
from app.pz.project import MeterRow
from app.pz.rules import calc_required_head


def _calculated_project():
    request = load_request(
        Path("demo/demo_project.yaml").read_text(encoding="utf-8")
    )
    project = build_project(request)
    project.flows = compute_flows(project.consumer_groups)
    project.meters.rows = [
        MeterRow(label="Счётчик ХВС", dn=40, h_a=1.2),
    ]
    project.source.h_vod_m = 1.2
    head = calc_required_head(project.source, h_vod_m=1.2)
    project.pumps.required = bool(head.pump_needed)
    project.pumps.model = "Контрольный насос"
    project.pumps.wp_q = 12.5
    project.pumps.wp_h = head.h_pump_m or 0
    project.fire.required_head_m = 60.5
    project.fire.available_head_m = 32.0
    project.fire.needs_pump = True
    return project


def test_passport_has_reproducible_fingerprints_and_version():
    project = _calculated_project()
    first = build_commission_report(project)
    second = build_commission_report(project)
    assert first.project_fingerprint == second.project_fingerprint
    assert len(first.project_fingerprint) == 16
    assert len(first.legacy_fingerprint) == 16
    assert any(item.label == "Версия приложения / commit" for item in first.passport)
    assert any(item.label == "Граница стадии" for item in first.passport)


def test_missing_consumers_and_head_block_release():
    request = load_request(
        Path("demo/demo_project.yaml").read_text(encoding="utf-8")
    )
    project = build_project(request)
    project.consumer_groups = []
    project.flows.q_day_tot = 0
    project.source.guaranteed_head_m = None
    project.source.h_vod_m = None
    report = build_commission_report(project)
    assert report.blocking_count >= 3
    assert "блокирующие" in report.release_status.lower()
    blocking_codes = {row.code for row in report.checks if row.blocking}
    assert {"SRC-01", "CALC-01", "CALC-02"}.issubset(blocking_codes)


def test_stage_r_items_are_visible_but_do_not_block():
    project = _calculated_project()
    project.storm.roof_type = "flat"
    project.storm.system_kind = "internal"
    project.storm.system_note = "Предусмотреть внутренний водосток."
    project.storm.city_code = "moscow"
    project.storm.roof_area_m2 = 1200
    project.storm.result = calculate_storm(StormInput("moscow", 1200))
    project.grease_trap.preparation_type = "raw"
    project.grease_trap.seats = 200
    project.grease_trap.required = True
    project.grease_trap.decision_note = "Предусмотреть жироуловители."
    report = build_commission_report(project)
    assert any(row.code == "K2-02" and row.status == "stage_r" for row in report.checks)
    assert any(row.code == "K1-01" and row.status == "stage_r" for row in report.checks)
    assert not any(
        row.blocking for row in report.checks
        if row.code in {"K2-02", "K1-01", "STAGE-01"}
    )


def test_empty_storm_assessment_explains_unchecked_elements_without_blocking():
    project = _calculated_project()
    project.storm.system_kind = "internal"
    project.storm.result = calculate_storm(StormInput("moscow", 1200))
    project.storm.network_assessment = assess_storm_network(
        project.storm.result, StormNetworkInput(roof_type="flat"),
    )
    assert project.storm.network_assessment.notes == ()  # current no-elements case
    row = next(r for r in build_commission_report(project).checks if r.code == "K2-02")
    assert row.status == "stage_r" and not row.blocking
    assert "ворон" in row.result and "стояк" in row.result
    assert "расход" in row.result.lower()


def test_explicit_storm_failure_retains_original_reason_and_blocking():
    project = _calculated_project()
    project.storm.system_kind = "internal"
    project.storm.result = calculate_storm(StormInput("moscow", 1200))
    assessment = assess_storm_network(project.storm.result, StormNetworkInput(
        roof_type="flat", funnels_count=1, roof_sections=1,
        selected_riser_dn_mm=85, risers_count=1, max_riser_flow_lps=20,
    ))
    project.storm.network_assessment = assessment
    row = next(r for r in build_commission_report(project).checks if r.code == "K2-02")
    assert row.blocking and row.status == "missing"
    assert row.result == "; ".join(assessment.notes)


def test_high_rise_requirements_are_traced_to_documents():
    project = _calculated_project()
    project.building.height_m = 76
    project.consumer_groups.append(("office", 100))
    project.normative = derive_requirements(
        project.building,
        [code for code, _ in project.consumer_groups],
        owner_groups_count=3,
    )
    project.meters.owner_groups_count = 3
    report = build_commission_report(project)
    requirements = {row.requirement: row for row in report.trace_rows}
    assert "Раздельные системы В1 и В2 высотного здания" in requirements
    assert "Теплоизоляция трубопроводов высотного здания" in requirements
    assert "Автономный учёт групп разных собственников" in requirements
    assert any(row.code == "SP253-01" for row in report.checks)


def test_changing_input_changes_project_fingerprint():
    project = _calculated_project()
    before = build_commission_report(project).project_fingerprint
    project.source.guaranteed_head_m += 1
    after = build_commission_report(project).project_fingerprint
    assert before != after


def test_missing_required_artifact_blocks_commission_release():
    project = _calculated_project()
    report = build_commission_report(project, artifacts={
        "Пояснительная записка": True,
        "Расчёты В1": True,
        "Баланс ВиВ": True,
        "Подбор насосов": True,
        "Спецификация": True,
        "Принципиальная схема": False,
        "Гидравлический расчёт В2": False,
    })
    blocking_codes = {row.code for row in report.checks if row.blocking}
    assert {"DOC-01", "DOC-02", "DOC-03"}.issubset(blocking_codes)

"""Единый машинный контракт ГОСТ-аудита ИОС2/ИОС3."""
from app.intake.project_builder import build_project
from app.normative.audit_matrix import (
    build_ios2_gost_matrix,
    build_ios3_gost_matrix,
    build_project_gost_matrices,
)
from app.pz.commission import build_commission_report
from app.pz.ios2_orchestrator import design_ios2
from app.pz.proof import build_proof_graph
from tests.test_wastewater_gost_21620 import _gost_request


def _project(tmp_path):
    return design_ios2(
        build_project(_gost_request()),
        output_dir=str(tmp_path),
        render_documents=False,
    ).project


def _all_artifacts():
    return {
        name: True for name in (
            "Пояснительная записка",
            "Расчёты В1",
            "Баланс ВиВ",
            "Подбор насосов",
            "Спецификация",
            "Принципиальная схема",
            "Схема вводов и узлов учёта",
            "Схема насосов, зон и ГВС",
            "План сетей водоснабжения",
            "Пояснительная записка К1/К2",
            "Расчёты К1/К2",
            "Баланс ИОС3 по ГОСТ Р 21.620",
            "Принципиальная схема К1/К2",
            "Спецификация ИОС3",
            "Комплект ИОС3",
            "Гидравлический расчёт В2",
        )
    }


def test_every_row_is_bound_to_baseline_clause_fact_and_stable_id(tmp_path):
    matrices = build_project_gost_matrices(_project(tmp_path))
    assert {matrix.discipline for matrix in matrices} == {"ИОС2", "ИОС3"}
    for matrix in matrices:
        ids = [row.rule_id for row in matrix.rows]
        assert len(ids) == len(set(ids))
        assert matrix.baseline_id == "ru-ios-2026-09-05-v1"
        assert len(matrix.baseline_fingerprint) == 64
        assert len(matrix.fingerprint) == 64
        for row in matrix.rows:
            assert row.document_id == matrix.document_id
            assert row.baseline_id == matrix.baseline_id
            assert row.clauses
            assert row.fact_ids
            assert row.deliverables
            assert row.designation in row.reference


def test_ios3_adapter_preserves_existing_stable_rule_ids(tmp_path):
    matrix = build_ios3_gost_matrix(_project(tmp_path))
    ids = {row.rule_id for row in matrix.rows}
    assert {"K-GOST-01", "K-GOST-08", "K-GOST-13", "K-GOST-16"} <= ids
    assert {"K-GOST-A01", "K-GOST-A02", "K-GOST-A03"} <= ids


def test_artifacts_are_pending_before_build_and_block_when_missing_after(tmp_path):
    project = _project(tmp_path)
    preview = build_ios2_gost_matrix(project)
    assert all(
        row.status == "pending_build"
        for row in preview.rows if row.rule_id.startswith("V-GOST-A0")
        and row.rule_id != "V-GOST-A08"
        and row.status != "not_applicable"
    )
    artifacts = _all_artifacts()
    artifacts["План сетей водоснабжения"] = False
    final = build_ios2_gost_matrix(project, artifacts)
    plan = next(row for row in final.rows if row.rule_id == "V-GOST-A07")
    assert plan.status == "missing"
    assert plan.blocks_release
    assert plan in final.release_blockers


def test_fire_row_is_not_applicable_when_v2_is_not_required(tmp_path):
    project = _project(tmp_path)
    project.fire.required = False
    matrix = build_ios2_gost_matrix(project)
    row = next(row for row in matrix.rows if row.rule_id == "V-GOST-05")
    assert row.status == "not_applicable"
    assert not row.blocks_release


def test_commission_and_proof_expose_the_same_sealed_matrices(tmp_path):
    report = build_commission_report(_project(tmp_path), artifacts=_all_artifacts())
    assert [row["discipline"] for row in report.normative_audits] == ["ИОС2", "ИОС3"]
    assert any(check.code == "DOC-05" for check in report.checks)
    graph = build_proof_graph(_project(tmp_path / "proof"), report)
    decisions = {row.id: row for row in graph.decisions}
    assert {"gost-ios2-audit", "gost-ios3-audit"} <= decisions.keys()
    assert report.normative_audits[0]["fingerprint_sha256"] in (
        step.value for step in decisions["gost-ios2-audit"].steps
    )

"""Доказательный граф проекта не меняет расчёты и раскрывает их происхождение."""
from pathlib import Path

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.commission import build_commission_report
from app.pz.demand_bridge import compute_flows
from app.pz.project import MeterRow
from app.pz.proof import build_proof_graph


def _project_with_results():
    request = load_request(
        Path("demo/demo_project.yaml").read_text(encoding="utf-8")
    )
    project = build_project(request)
    project.flows = compute_flows(project.consumer_groups)
    project.meters.rows = [
        MeterRow(
            label="Счётчик ХВС",
            dn=40,
            type_label="крыльчатый",
            h_a=1.2,
            lim_a=5.0,
            ok_a=True,
            ok_b=True,
            ok_v=True,
        ),
    ]
    project.source.h_vod_m = 1.2
    return project


def test_proof_graph_exposes_exact_daily_flow_formula():
    project = _project_with_results()
    graph = build_proof_graph(project, build_commission_report(project))
    decision = next(item for item in graph.decisions if item.id == "v1-q-day")

    assert decision.status == "verified"
    assert decision.value == "86,4"
    assert any("480×180/1000=86,400" in step.value for step in decision.steps)
    assert any("legacy/sp30_calculator.html" in step.detail for step in decision.steps)
    assert "Баланс ВиВ" in decision.artifacts


def test_proof_graph_exposes_alpha_and_free_head_without_new_assumptions():
    project = _project_with_results()
    graph = build_proof_graph(project, build_commission_report(project))
    second = next(item for item in graph.decisions if item.id == "v1-q-sec")
    head = next(item for item in graph.decisions if item.id == "v1-head")

    assert second.status == "verified"
    assert any("q = 5 × q₀,ср × α" in step.value for step in second.steps)
    assert any("Hпр=20,0 м" in step.detail for step in head.steps)
    assert any("формула (14)" in step.value for step in head.steps)


def test_proof_graph_keeps_stage_p_r_boundary_visible():
    project = _project_with_results()
    graph = build_proof_graph(project, build_commission_report(project))
    boundary = next(item for item in graph.decisions if item.id == "t3-t4-stage")

    assert boundary.status == "stage_r"
    assert any("без фиктивных Kv" in step.value for step in boundary.steps)
    assert "циркуляционные клапаны" in boundary.impact


def test_fire_proof_uses_sp10_and_current_fire_result():
    project = _project_with_results()
    graph = build_proof_graph(project, build_commission_report(project))
    fire = next(item for item in graph.decisions if item.id == "v2-requirement")

    assert fire.status == "verified"
    assert fire.value == "5,2 л/с"
    assert any("СП 10.13130.2020" in step.value for step in fire.steps)
    assert any("Интерполяции" in step.detail for step in fire.steps)


def test_machine_readable_proof_has_fingerprints_and_summary():
    project = _project_with_results()
    report = build_commission_report(project)
    graph = build_proof_graph(project, report)
    payload = graph.to_dict()

    assert payload["project_fingerprint"] == report.project_fingerprint
    assert payload["legacy_fingerprint"] == report.legacy_fingerprint
    assert payload["summary"]["total"] == len(payload["decisions"])
    assert payload["summary"]["proven"] == graph.proven_count
    assert all("status_label" in item for item in payload["decisions"])
    assert all(
        "kind_label" in step
        for item in payload["decisions"]
        for step in item["steps"]
    )

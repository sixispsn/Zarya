from pathlib import Path

from app.api.preflight import ProjectPreflightInput, run_preflight
from app.intake.preflight import PreflightLevel, preflight_request
from app.intake.project_intent import ProjectIntent
from app.intake.questions import evaluate_questions, questions_for_web
from app.intake.request_dto import ConsumerGroupRequest


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _intent() -> ProjectIntent:
    return ProjectIntent.from_yaml(DEMO.read_text(encoding="utf-8"))


def test_demo_passes_preflight_and_exposes_stage_r_boundary():
    report = preflight_request(_intent())
    assert report.can_calculate
    assert not report.can_release
    assert report.has_stage_r_boundaries
    assert not report.blockers
    assert report.release_blockers[0].level == PreflightLevel.RELEASE_BLOCKING
    assert report.normative_baseline.baseline_id == "ru-ios-2026-09-03-v1"
    assert any(
        row.rule.rule_id == "SP10-EDITION-ADOPTION-001"
        and row.release_blocking
        for row in report.normative_verdicts
    )
    assert any(
        row.code == "stage_r.t3_t4_circulation_topology"
        for row in report.issues
    )


def test_applicable_unanswered_question_is_a_blocker():
    intent = _intent()
    intent.request.consumers.append(
        ConsumerGroupRequest("sport_pool", 120, "Спортивный комплекс")
    )
    states = evaluate_questions(intent)
    group_showers = next(
        row for row in states
        if row.definition.question_id == "technology.group_showers"
    )
    report = preflight_request(intent)

    assert group_showers.applicable
    assert not group_showers.answered
    assert not report.can_calculate
    assert any("групповых душевых" in row.message for row in report.blockers)


def test_missing_ios3_topology_is_explicit_stage_r_not_invented():
    intent = _intent()
    intent.request.sewer_pipes = []
    intent.request.sewer_elements = []
    intent.request.sewage_risers = []
    intent.request.sewer_discharge_events = []
    intent.request.sewer_fixture_safety_inputs = []
    intent.request.sewer_first_manholes = []
    intent.request.sewer_internal_nodes = []
    report = preflight_request(intent)

    issue = next(
        row for row in report.issues
        if row.code == "stage_r.ios3_topology_missing"
    )
    assert issue.level == PreflightLevel.STAGE_R
    assert report.can_calculate
    assert issue.fact_ids == ("sewage.topology",)


def test_missing_exact_scheme_geometry_is_stage_r_not_a_silent_default():
    intent = _intent()
    intent.request.wastewater_floor_height_m = None
    intent.request.wastewater_roof_kind = "unknown"

    report = preflight_request(intent)

    issue = next(
        row for row in report.issues
        if row.code == "stage_r.ios3_scheme_geometry_missing"
    )
    assert issue.level == PreflightLevel.STAGE_R
    assert issue.fact_ids == ("sewage.scheme_geometry",)


def test_question_registry_keeps_legacy_js_triggers_and_metadata():
    payload = questions_for_web()
    assert "sport_pool" in payload["group_showers_consumer_codes"]
    assert any(
        row["id"] == "technology.grease_trap_location"
        for row in payload["questions"]
    )


def test_preflight_api_returns_structured_report_without_calculation():
    payload = run_preflight(ProjectPreflightInput(
        project_yaml=DEMO.read_text(encoding="utf-8"),
    ))
    assert payload["can_calculate"] is True
    assert "facts" in payload
    assert payload["counts"]["blocking"] == 0
    assert payload["counts"]["release_blocking"] == 1
    assert payload["normative_baseline"]["fingerprint_sha256"]
    assert payload["normative_verdicts"][0]["rule_id"] == (
        "SP10-EDITION-ADOPTION-001"
    )


def test_auto_residential_without_v2_is_not_blocked_by_sp10_adoption():
    intent = _intent()
    intent.request.floors = 9
    intent.request.building_height_m = 27.0
    intent.request.fire_height_m = 27.0

    report = preflight_request(intent)

    assert report.can_calculate
    assert report.can_release
    verdict = next(
        row for row in report.normative_verdicts
        if row.rule.rule_id == "SP10-EDITION-ADOPTION-001"
    )
    assert verdict.status.value == "not_applicable"
    assert not verdict.release_blocking

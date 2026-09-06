from pathlib import Path

from app.intake.preflight import preflight_request
from app.intake.yaml_io import load_request_file
from app.pz.commission import CommissionReport, ControlCheck
from app.quality_gates import QualityState, build_release_quality_report


DEMO = Path("demo/demo_project.yaml")


def _check(
    code: str,
    status: str = "verified",
    *,
    blocking: bool = False,
) -> ControlCheck:
    return ControlCheck(
        code=code,
        check=f"Проверка {code}",
        status=status,
        result=f"Результат {code}",
        action="Нет действий" if not blocking else "Исправить",
        reference="Контрольная ссылка",
        blocking=blocking,
    )


def test_quality_report_has_seven_named_gates_and_allows_stage_p_boundaries():
    preflight = preflight_request(load_request_file(str(DEMO)))
    commission = CommissionReport(checks=[
        _check("SRC-01"),
        _check("CALC-01"),
        _check("K1-03", "stage_r"),
        _check("DOC-01"),
        _check("DOC-04"),
    ])

    report = build_release_quality_report(preflight, commission)

    assert [gate.gate_id for gate in report.gates] == [
        "inputs",
        "normatives",
        "calculations",
        "engineering",
        "coordination",
        "documentation",
        "release",
    ]
    assert report.state == QualityState.CONDITIONAL
    assert report.can_release
    assert report.blocking_findings == ()
    assert "стадии Р" in report.release_status


def test_blocking_commission_check_stops_release_and_keeps_action():
    preflight = preflight_request(load_request_file(str(DEMO)))
    commission = CommissionReport(checks=[
        _check("CALC-04", "missing", blocking=True),
    ])

    report = build_release_quality_report(preflight, commission)

    assert report.state == QualityState.BLOCKED
    assert not report.can_release
    assert report.blocking_findings[0].code == "CALC-04"
    assert report.blocking_findings[0].action == "Исправить"
    assert report.gates[-1].state == QualityState.BLOCKED


def test_serialized_preflight_builds_same_gate_statuses():
    preflight = preflight_request(load_request_file(str(DEMO)))
    commission = CommissionReport(checks=[_check("DOC-05")])

    typed = build_release_quality_report(preflight, commission).to_dict()
    serialized = build_release_quality_report(
        preflight.to_dict(), commission,
    ).to_dict()

    assert serialized["state"] == typed["state"]
    assert [row["state"] for row in serialized["gates"]] == [
        row["state"] for row in typed["gates"]
    ]
    assert serialized["gates"][1]["findings"]

from copy import deepcopy

import pytest

from app.intake.studio_readiness import finding_section, section_readiness
from app.quality_gates import build_release_quality_report


@pytest.mark.parametrize("code,systems,expected", [
    ("CALC-03", [], "ios2"), ("CALC-01", [], "common"),
    ("FIRE-L06", [], "ios2"), ("K1-03", [], "ios3"),
    ("DOC-03", [], "ios3"), ("DOC-05", [], "ios2"),
    ("x", ["V1", "Т3"], "ios2"), ("x", ["K1", "К2"], "ios3"),
    ("x", ["В1", "К1"], "common"), ("x", ["В1", "UNKNOWN"], "common"),
    ("new-check", [], "common"), ("RAIN-01", [], "common"),
    ("V-GOST-A02", ["В1", "Т3", "К1"], "ios2"),
])
def test_classification_keeps_unknown_and_cross_section_checks_visible(code, systems, expected):
    assert finding_section(dict(code=code, systems=systems, source="commission")) == expected


def test_partition_preserves_blockers_stage_r_and_release_decision_without_mutation():
    quality = build_release_quality_report({"issues": [
        dict(code="stage_r.t3", level="stage_r", systems=["T3"], message="Аксонометрия"),
        dict(code="new", level="release_blocking", systems=[], message="Новый контроль"),
    ]}, {"checks": [
        dict(code="CALC-03", status="missing", blocking=True, check="Водомер", result="Нет минимума"),
        dict(code="K1-03", status="stage_r", blocking=False, check="К1"),
    ]}).to_dict()
    before = deepcopy(quality)
    result = section_readiness(quality)
    rows = [row for section in result for row in section["findings"]]
    original = [row for gate in quality["gates"] for row in gate["findings"]
                if row["state"] != "ready" and row["source"] != "quality_gates"]
    assert len(rows) == len(original) == 4
    assert sum(s["blocking_count"] for s in result) == quality["blocking_count"] == 2
    assert {(r["code"], r["state"], r["detail"]) for r in rows} == {
        (r["code"], r["state"], r["detail"]) for r in original}
    assert quality == before and not quality["can_release"]
    assert all("can_release" not in section for section in result)
    rows[0]["systems"].append("test")
    assert quality == before


def test_empty_groups_are_not_certified_as_ready():
    sections = section_readiness({"gates": []})
    assert len(sections) == 3
    assert all(s["blocking_count"] == s["review_count"] == 0 for s in sections)
    assert all("state" not in s and "can_release" not in s for s in sections)

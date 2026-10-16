"""Presentation-only partition of existing findings; never a release authority."""
from __future__ import annotations

from copy import deepcopy


_WATER = {"В1", "В2", "Т3", "Т4", "V1", "V2", "B1", "B2", "T3", "T4"}
_SEWER = {"К1", "К2", "К3", "K1", "K2", "K3"}
_CHECK_SECTIONS = {
    "CALC-02": "ios2", "CALC-03": "ios2", "CALC-04": "ios2",
    "CALC-T3": "ios2", "VU-COMPOSITION": "ios2", "STAGE-01": "ios2",
    "DOC-01": "ios2", "DOC-02": "ios2", "DOC-05": "ios2",
    "DOC-03": "ios3", "DOC-04": "ios3",
}


def finding_section(finding: dict) -> str:
    # A document audit belongs to its document even when it mentions the
    # common water/wastewater balance. Do not classify by title substrings.
    code = finding.get("code", "")
    if code.startswith("V-GOST-"):
        return "ios2"
    if code.startswith("K-GOST-"):
        return "ios3"
    systems = {str(s).upper() for s in finding.get("systems", [])}
    if systems:
        if systems <= _WATER:
            return "ios2"
        if systems <= _SEWER:
            return "ios3"
        return "common"  # cross-section or unknown system: keep visible
    if code in _CHECK_SECTIONS:
        return _CHECK_SECTIONS[code]
    if finding.get("source") == "commission":
        if code.startswith(("FIRE-", "METER-", "SP54-", "SP253-")):
            return "ios2"
        if code.startswith(("K1-", "K2-", "K3-")):
            return "ios3"
    return "common"


def section_readiness(quality: dict) -> list[dict]:
    """Keep every actionable finding and its severity, without a false green badge.

    The RELEASE summary repeats the findings; it is not an additional task.
    No section can_release flag is produced: formal release still uses the
    original report and all other Studio guards.
    """
    sections = {
        key: {"id": key, "title": title, "findings": []}
        for key, title in (
            ("ios2", "ИОС2 · Водоснабжение"),
            ("ios3", "ИОС3 · Водоотведение"),
            ("common", "Общие исходные и согласования"),
        )
    }
    for gate in quality.get("gates", []):
        for finding in gate.get("findings", []):
            if finding.get("state") == "ready" or finding.get("source") == "quality_gates":
                continue
            row = deepcopy(finding)
            row["gate_id"] = gate["gate_id"]
            sections[finding_section(row)]["findings"].append(row)
    for section in sections.values():
        section["blocking_count"] = sum(f["state"] == "blocked" for f in section["findings"])
        section["review_count"] = len(section["findings"]) - section["blocking_count"]
    return list(sections.values())

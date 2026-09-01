# -*- coding: utf-8 -*-
"""Единый предвыпускной контроль исходного намерения проекта."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.intake.advisories import review_request
from app.intake.facts import FactRegistry, build_fact_registry
from app.intake.project_intent import IntentLike, as_project_intent
from app.intake.questions import QuestionState, evaluate_questions


class PreflightLevel(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    STAGE_R = "stage_r"
    INFO = "info"


@dataclass(frozen=True)
class PreflightIssue:
    level: PreflightLevel
    code: str
    message: str
    reference: str = ""
    systems: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "code": self.code,
            "message": self.message,
            "reference": self.reference,
            "systems": list(self.systems),
            "fact_ids": list(self.fact_ids),
        }


@dataclass(frozen=True)
class PreflightReport:
    issues: tuple[PreflightIssue, ...]
    facts: FactRegistry
    questions: tuple[QuestionState, ...]

    @property
    def blockers(self) -> tuple[PreflightIssue, ...]:
        return tuple(row for row in self.issues if row.level == PreflightLevel.BLOCKING)

    @property
    def can_calculate(self) -> bool:
        return not self.blockers

    @property
    def can_release(self) -> bool:
        return not self.blockers

    @property
    def has_stage_r_boundaries(self) -> bool:
        return any(row.level == PreflightLevel.STAGE_R for row in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_calculate": self.can_calculate,
            "can_release": self.can_release,
            "has_stage_r_boundaries": self.has_stage_r_boundaries,
            "counts": {
                level.value: sum(row.level == level for row in self.issues)
                for level in PreflightLevel
            },
            "issues": [row.to_dict() for row in self.issues],
            "questions": [row.to_dict() for row in self.questions],
            "facts": self.facts.to_dict(),
        }


def preflight_request(value: IntentLike) -> PreflightReport:
    intent = as_project_intent(value)
    req = intent.request
    issues: list[PreflightIssue] = [
        PreflightIssue(
            level=PreflightLevel.BLOCKING,
            code=f"input.validation.{index:03d}",
            message=message,
        )
        for index, message in enumerate(req.validate(), start=1)
    ]

    # Технологические advisories уже представлены строгой DTO-валидацией.
    # Остальные нормативные сигналы остаются неблокирующими.
    for advisory in review_request(req):
        if advisory.code.startswith("technology_"):
            continue
        level = (
            PreflightLevel.WARNING
            if advisory.level == "warning" else PreflightLevel.INFO
        )
        issues.append(PreflightIssue(
            level=level,
            code=advisory.code,
            message=advisory.message,
            reference=advisory.reference,
        ))

    if req.hws_type == "central":
        issues.append(PreflightIssue(
            level=PreflightLevel.STAGE_R,
            code="stage_r.t3_t4_circulation_topology",
            message=(
                "Окончательные циркуляционные расходы ветвей Т3/Т4, потери "
                "колец, Kv, настройки балансировочных клапанов и рабочая точка "
                "циркуляционного насоса уточняются по точной аксонометрии стадии Р."
            ),
            reference="Граница стадий П/Р; СП 30.13330.2020",
            systems=("T3", "T4"),
        ))
    if req.fire_mode != "not_required" and (not req.rooms or req.network is None):
        issues.append(PreflightIssue(
            level=PreflightLevel.STAGE_R,
            code="stage_r.v2_geometry_or_network",
            message=(
                "Расстановка пожарных кранов и точная гидравлика В2 требуют "
                "плановой геометрии и расчётной топологии сети."
            ),
            reference="СП 10.13130.2020",
            systems=("V2",),
        ))
    if not req.sewer_pipes:
        issues.append(PreflightIssue(
            level=PreflightLevel.STAGE_R,
            code="stage_r.ios3_topology_missing",
            message=(
                "Топология, длины, уклоны, отметки и точки сброса К1/К2/К3 "
                "не заданы; схема и спецификация ИОС3 требуют дополнения."
            ),
            reference="ГОСТ Р 21.620-2023, пп. 5.2.2–5.2.4",
            systems=("K1", "K2", "K3"),
            fact_ids=("sewage.topology",),
        ))
    elif any(not row.from_node or not row.to_node for row in req.sewer_pipes):
        issues.append(PreflightIssue(
            level=PreflightLevel.STAGE_R,
            code="stage_r.ios3_topology_incomplete",
            message=(
                "У части участков К1/К2/К3 не заданы начальный и конечный "
                "узлы; связную принципиальную схему необходимо дополнить."
            ),
            reference="ГОСТ Р 21.620-2023, пп. 5.2.2–5.2.4",
            systems=("K1", "K2", "K3"),
            fact_ids=("sewage.topology",),
        ))

    return PreflightReport(
        issues=tuple(issues),
        facts=build_fact_registry(intent),
        questions=tuple(evaluate_questions(intent)),
    )

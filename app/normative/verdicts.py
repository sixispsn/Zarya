"""Стабильные нормативные правила, отделённые от расчётных алгоритмов."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.intake.request_dto import IOS2Request
from app.normative.baseline import (
    NormativeBaseline,
    NormativeDocumentState,
)


class NormativeVerdictStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class NormativeRuleRef:
    rule_id: str
    document_id: str
    clauses: tuple[str, ...]
    title: str
    systems: tuple[str, ...]
    fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class NormativeVerdict:
    rule: NormativeRuleRef
    baseline_id: str
    designation: str
    edition: str
    status: NormativeVerdictStatus
    message: str
    release_blocking: bool = False

    @property
    def reference(self) -> str:
        clauses = ", ".join(self.rule.clauses)
        return f"{self.designation}, {self.edition}; {clauses}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule.rule_id,
            "baseline_id": self.baseline_id,
            "document_id": self.rule.document_id,
            "designation": self.designation,
            "edition": self.edition,
            "clauses": list(self.rule.clauses),
            "title": self.rule.title,
            "systems": list(self.rule.systems),
            "fact_ids": list(self.rule.fact_ids),
            "status": self.status.value,
            "message": self.message,
            "release_blocking": self.release_blocking,
        }


SP10_CHANGE_1_ADOPTION = NormativeRuleRef(
    rule_id="SP10-EDITION-ADOPTION-001",
    document_id="sp_10_13130_2020",
    clauses=("Изменение № 1",),
    title="Применение актуальной редакции СП 10 для В2",
    systems=("V2",),
    fact_ids=("fire.mode", "building.floors", "building.fire_height"),
)

GOST_21620_TOPOLOGY = NormativeRuleRef(
    rule_id="GOST21620-SCHEME-TOPOLOGY-001",
    document_id="gost_r_21_620_2023",
    clauses=("5.2.2", "5.2.3", "5.2.4"),
    title="Исходная топология для графической части ИОС3",
    systems=("K1", "K2", "K3"),
    fact_ids=("sewage.topology",),
)


def _v2_applicability(request: IOS2Request) -> bool | None:
    """Определить применимость В2 тем же нормативным расчётом, что Builder."""
    if request.fire_mode == "not_required":
        return False
    if request.fire_mode == "manual":
        return True
    try:
        from app.intake.fire_applicability import calculate_request_fire

        return calculate_request_fire(request).required
    except (KeyError, TypeError, ValueError):
        # Невалидное намерение уже блокируется DTO; применимость пока неизвестна.
        return None


def evaluate_normative_verdicts(
    request: IOS2Request,
    baseline: NormativeBaseline,
) -> tuple[NormativeVerdict, ...]:
    verdicts: list[NormativeVerdict] = []

    sp10 = baseline.document(SP10_CHANGE_1_ADOPTION.document_id)
    v2_applicable = _v2_applicability(request)
    if v2_applicable is False:
        status = NormativeVerdictStatus.NOT_APPLICABLE
        blocking = False
        message = "В2 для заданного объекта не требуется; контроль редакции СП 10 не применим."
    elif v2_applicable is None:
        status = NormativeVerdictStatus.DEFERRED
        blocking = False
        message = "Применимость В2 будет определена после исправления исходных данных."
    elif sp10.state == NormativeDocumentState.REVIEW_REQUIRED:
        status = NormativeVerdictStatus.FAIL
        blocking = True
        message = (
            "Выпуск с В2 остановлен: обнаруженная действующая редакция СП 10 "
            "ещё не принята локальным расчётным ядром. Нужны анализ влияния, "
            "regression/golden-тесты и новый baseline."
        )
    else:
        status = NormativeVerdictStatus.PASS
        blocking = False
        message = "Принятая редакция СП 10 соответствует активному baseline."
    verdicts.append(NormativeVerdict(
        rule=SP10_CHANGE_1_ADOPTION,
        baseline_id=baseline.baseline_id,
        designation=sp10.designation,
        edition=sp10.edition,
        status=status,
        message=message,
        release_blocking=blocking,
    ))

    gost = baseline.document(GOST_21620_TOPOLOGY.document_id)
    topology_complete = bool(request.sewer_pipes) and all(
        row.from_node and row.to_node for row in request.sewer_pipes
    )
    verdicts.append(NormativeVerdict(
        rule=GOST_21620_TOPOLOGY,
        baseline_id=baseline.baseline_id,
        designation=gost.designation,
        edition=gost.edition,
        status=(
            NormativeVerdictStatus.PASS
            if topology_complete else NormativeVerdictStatus.DEFERRED
        ),
        message=(
            "Связная топология ИОС3 задана."
            if topology_complete else
            "Графическая часть ИОС3 требует дополнения исходной топологии."
        ),
    ))
    return tuple(verdicts)

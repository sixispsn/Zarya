# -*- coding: utf-8 -*-
"""Единые ворота качества выпуска без новых инженерных расчётов.

Модуль агрегирует результаты уже существующих слоёв Preflight,
CommissionReport и нормативных матриц. Он не переоценивает формулы и не
подменяет профильные валидаторы — только даёт выпуску один машиночитаемый
статус и объясняет, какой именно слой требует внимания.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class QualityState(str, Enum):
    READY = "ready"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


STATE_LABELS = {
    QualityState.READY: "Готово",
    QualityState.CONDITIONAL: "С оговорками стадии П",
    QualityState.BLOCKED: "Выпуск заблокирован",
}


@dataclass(frozen=True)
class QualityFinding:
    code: str
    title: str
    detail: str
    action: str
    reference: str
    state: QualityState
    source: str
    systems: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "detail": self.detail,
            "action": self.action,
            "reference": self.reference,
            "state": self.state.value,
            "state_label": STATE_LABELS[self.state],
            "source": self.source,
            "systems": list(self.systems),
            "fact_ids": list(self.fact_ids),
        }


@dataclass(frozen=True)
class QualityGate:
    gate_id: str
    title: str
    description: str
    state: QualityState
    findings: tuple[QualityFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "title": self.title,
            "description": self.description,
            "state": self.state.value,
            "state_label": STATE_LABELS[self.state],
            "findings": [row.to_dict() for row in self.findings],
            "counts": {
                state.value: sum(row.state == state for row in self.findings)
                for state in QualityState
            },
        }


@dataclass(frozen=True)
class ReleaseQualityReport:
    gates: tuple[QualityGate, ...]
    state: QualityState
    schema_version: str = "1.0"

    @property
    def can_release(self) -> bool:
        return self.state != QualityState.BLOCKED

    @property
    def release_status(self) -> str:
        if self.state == QualityState.BLOCKED:
            return "Выпуск заблокирован: устраните критические замечания"
        if self.state == QualityState.CONDITIONAL:
            return "Комплект стадии П можно выпускать с зафиксированными границами стадии Р"
        return "Комплект прошёл автоматические ворота качества"

    @property
    def blocking_findings(self) -> tuple[QualityFinding, ...]:
        return tuple(
            row
            for gate in self.gates
            for row in gate.findings
            if row.state == QualityState.BLOCKED
            and row.source != "quality_gates"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "state_label": STATE_LABELS[self.state],
            "release_status": self.release_status,
            "can_release": self.can_release,
            "counts": {
                state.value: sum(gate.state == state for gate in self.gates)
                for state in QualityState
            },
            "blocking_count": len(self.blocking_findings),
            "gates": [gate.to_dict() for gate in self.gates],
        }


_GATE_DEFINITIONS = (
    (
        "inputs",
        "Исходные данные",
        "Обязательные параметры, ответы оркестратора и происхождение фактов.",
    ),
    (
        "normatives",
        "Нормативная применимость",
        "Редакции СП/ГОСТ, область применения и обязательные нормативные решения.",
    ),
    (
        "calculations",
        "Расчёты",
        "Расходы, напоры, водомеры, насосы и профильные расчётные результаты.",
    ),
    (
        "engineering",
        "Инженерная логика",
        "В2, К1/К2/К3, безопасность приборов и эксплуатационная доступность.",
    ),
    (
        "coordination",
        "Согласованность комплекта",
        "Наличие взаимосвязанных документов и расчётных приложений.",
    ),
    (
        "documentation",
        "Оформление",
        "Состав текстовой и графической частей по профильным ГОСТ.",
    ),
)


def _value(row: Any, name: str, default: Any = "") -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _rows(value: Any, name: str) -> tuple[Any, ...]:
    rows = _value(value, name, ()) if value is not None else ()
    return tuple(rows or ())


def _text(value: Any) -> str:
    return str(getattr(value, "value", value))


def _preflight_state(level: str) -> QualityState:
    if level in {"blocking", "release_blocking"}:
        return QualityState.BLOCKED
    if level in {"warning", "stage_r"}:
        return QualityState.CONDITIONAL
    return QualityState.READY


def _commission_state(row: Any) -> QualityState:
    if bool(_value(row, "blocking", False)):
        return QualityState.BLOCKED
    if str(_value(row, "status")) in {"missing", "fail", "stage_r"}:
        return QualityState.CONDITIONAL
    return QualityState.READY


def _commission_gate(code: str) -> str:
    if code.startswith("SRC-"):
        return "inputs"
    if code in {"DOC-04", "DOC-05"}:
        return "documentation"
    if code.startswith("DOC-"):
        return "coordination"
    if code.startswith(("CALC-", "METER-")) or code in {
        "K1-00",
        "K1-02",
        "K2-01",
    }:
        return "calculations"
    if code.startswith(("FIRE-", "K1-", "K2-", "K3-", "SP54-", "SP253-")):
        return "engineering"
    return "coordination"


def _gate_state(findings: tuple[QualityFinding, ...]) -> QualityState:
    states = {row.state for row in findings}
    if QualityState.BLOCKED in states:
        return QualityState.BLOCKED
    if QualityState.CONDITIONAL in states:
        return QualityState.CONDITIONAL
    return QualityState.READY


def build_release_quality_report(
    preflight: Any,
    commission: Any | None = None,
) -> ReleaseQualityReport:
    """Собрать семь ворот из уже рассчитанных и проверенных результатов."""
    grouped: dict[str, dict[str, QualityFinding]] = {
        gate_id: {} for gate_id, *_ in _GATE_DEFINITIONS
    }

    def add(gate_id: str, finding: QualityFinding) -> None:
        existing = grouped[gate_id].get(finding.code.casefold())
        priority = {
            QualityState.READY: 0,
            QualityState.CONDITIONAL: 1,
            QualityState.BLOCKED: 2,
        }
        if existing is None or priority[finding.state] > priority[existing.state]:
            grouped[gate_id][finding.code.casefold()] = finding

    for issue in _rows(preflight, "issues"):
        code = str(_value(issue, "code"))
        gate_id = (
            "normatives" if code.startswith("normative.")
            else "inputs" if code.startswith(("input.", "question."))
            else "engineering" if code.startswith("stage_r.ios3")
            else "coordination"
        )
        message = str(_value(issue, "message"))
        add(gate_id, QualityFinding(
            code=code,
            title=message,
            detail=message,
            action=(
                "Дополнить исходные данные до публикации выпуска"
                if _preflight_state(_text(_value(issue, "level"))) == QualityState.BLOCKED
                else "Сохранить ограничение в ПЗ и закрыть на соответствующей стадии"
            ),
            reference=str(_value(issue, "reference")),
            state=_preflight_state(_text(_value(issue, "level"))),
            source="preflight",
            systems=tuple(_value(issue, "systems", ()) or ()),
            fact_ids=tuple(_value(issue, "fact_ids", ()) or ()),
        ))

    # PASS/DEFERRED нормативные вердикты нужны, чтобы зелёные ворота не были
    # просто пустыми. Блокирующий FAIL уже присутствует среди issues.
    for verdict in _rows(preflight, "normative_verdicts"):
        rule = _value(verdict, "rule", None)
        code = str(
            _value(verdict, "rule_id")
            or _value(rule, "rule_id")
        )
        status = _text(_value(verdict, "status"))
        state = (
            QualityState.BLOCKED
            if status == "fail" and bool(_value(verdict, "release_blocking", False))
            else QualityState.CONDITIONAL
            if status in {"fail", "deferred"}
            else QualityState.READY
        )
        add("normatives", QualityFinding(
            code=code,
            title=str(
                _value(verdict, "title")
                or _value(rule, "title")
                or code
            ),
            detail=str(_value(verdict, "message")),
            action=(
                "Принять новую нормативную редакцию через анализ влияния"
                if state == QualityState.BLOCKED
                else "Нет действий" if state == QualityState.READY
                else "Закрыть после уточнения исходных данных"
            ),
            reference=str(_value(verdict, "reference")),
            state=state,
            source="normative_verdict",
            systems=tuple(
                _value(verdict, "systems")
                or _value(rule, "systems", ())
                or ()
            ),
            fact_ids=tuple(
                _value(verdict, "fact_ids")
                or _value(rule, "fact_ids", ())
                or ()
            ),
        ))

    for check in _rows(commission, "checks"):
        code = str(_value(check, "code"))
        add(_commission_gate(code), QualityFinding(
            code=code,
            title=str(_value(check, "check")),
            detail=str(_value(check, "result")),
            action=str(_value(check, "action")),
            reference=str(_value(check, "reference")),
            state=_commission_state(check),
            source="commission",
        ))

    gates = tuple(
        QualityGate(
            gate_id=gate_id,
            title=title,
            description=description,
            findings=tuple(grouped[gate_id].values()),
            state=_gate_state(tuple(grouped[gate_id].values())),
        )
        for gate_id, title, description in _GATE_DEFINITIONS
    )
    base_states = {gate.state for gate in gates}
    overall = (
        QualityState.BLOCKED
        if QualityState.BLOCKED in base_states
        else QualityState.CONDITIONAL
        if QualityState.CONDITIONAL in base_states
        else QualityState.READY
    )
    release_finding = QualityFinding(
        code="RELEASE-001",
        title="Итоговый статус выпуска",
        detail=(
            "Есть критические замечания в предвыпускном контроле."
            if overall == QualityState.BLOCKED
            else "Границы стадии Р явно сохранены в комплекте."
            if overall == QualityState.CONDITIONAL
            else "Критические замечания отсутствуют."
        ),
        action=(
            "Устранить блокирующие замечания и повторить сборку"
            if overall == QualityState.BLOCKED
            else "Выпуск разрешён"
        ),
        reference="Сводный автоматический контроль Zarya",
        state=overall,
        source="quality_gates",
    )
    gates += (QualityGate(
        gate_id="release",
        title="Готовность к выпуску",
        description="Сводный статус шести независимых контуров контроля.",
        state=overall,
        findings=(release_finding,),
    ),)
    return ReleaseQualityReport(gates=gates, state=overall)

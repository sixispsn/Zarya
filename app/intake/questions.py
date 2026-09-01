# -*- coding: utf-8 -*-
"""Декларативный реестр уточняющих вопросов к исходным данным."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.intake.applicability import (
    applicability_rules_for_web,
    infer_applicability_scope,
)
from app.intake.project_intent import IntentLike, unwrap_project_intent


@dataclass(frozen=True)
class QuestionDefinition:
    question_id: str
    title: str
    prompt: str
    answer_field: str
    systems: tuple[str, ...]
    reference: str
    options: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "title": self.title,
            "prompt": self.prompt,
            "answer_field": self.answer_field,
            "systems": list(self.systems),
            "reference": self.reference,
            "options": list(self.options),
        }


@dataclass(frozen=True)
class QuestionState:
    definition: QuestionDefinition
    applicable: bool
    answered: bool
    answer: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.definition.to_dict(),
            "applicable": self.applicable,
            "answered": self.answered,
            "answer": self.answer,
        }


QUESTION_DEFINITIONS = (
    QuestionDefinition(
        "technology.group_showers",
        "Групповые душевые",
        "Предусмотрена ли группа душевых и сколько душевых сеток задано ТХ/ТЗ?",
        "group_showers_answer",
        ("V1", "T3", "K1"),
        "СП 30.13330.2020; задание ТХ/ТЗ",
        ("yes", "no"),
    ),
    QuestionDefinition(
        "technology.food_service",
        "Предприятие питания",
        "Есть ли общепит и каков тип приготовления пищи?",
        "food_service_answer",
        ("V1", "T3", "K1"),
        "СП 118.13330.2022; задание ТХ",
        ("yes", "no"),
    ),
    QuestionDefinition(
        "technology.grease_wastewater",
        "Жиросодержащие стоки",
        "Образуются ли жиросодержащие производственные стоки?",
        "grease_wastewater_answer",
        ("K1",),
        "Задание ТХ; условия приёма стоков",
        ("yes", "no"),
    ),
    QuestionDefinition(
        "technology.grease_trap_location",
        "Размещение жироуловителя",
        "Где предусмотрен жироуловитель либо перенесён ли подбор на стадию Р?",
        "grease_trap_location",
        ("K1",),
        "Задание ТХ; архитектурно-планировочные решения",
        ("under_sink", "technical_room", "outside_building", "stage_r"),
    ),
)


def evaluate_questions(value: IntentLike) -> list[QuestionState]:
    req = unwrap_project_intent(value)
    scope = infer_applicability_scope(
        req.consumers,
        group_showers_answer=req.group_showers_answer,
        food_service_answer=req.food_service_answer,
        catering_type=req.catering_type,
    )
    applicability = {
        "technology.group_showers": scope.group_showers,
        "technology.food_service": scope.food_service,
        "technology.grease_wastewater": req.food_service_answer == "yes",
        "technology.grease_trap_location": req.grease_wastewater_answer == "yes",
    }
    states: list[QuestionState] = []
    for definition in QUESTION_DEFINITIONS:
        answer = getattr(req, definition.answer_field)
        applicable = applicability[definition.question_id]
        answered = (not applicable) or answer not in ("", "unknown", None)
        states.append(QuestionState(definition, applicable, answered, answer))
    return states


def questions_for_web() -> dict[str, list[Any]]:
    """Совместимый payload: старые JS-триггеры плюс определения вопросов."""
    return {
        **applicability_rules_for_web(),
        "questions": [row.to_dict() for row in QUESTION_DEFINITIONS],
    }

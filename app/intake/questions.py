# -*- coding: utf-8 -*-
"""Декларативный реестр уточняющих вопросов к исходным данным.

Один и тот же реестр используется серверным Preflight и браузером. Клиент
только отображает полученное состояние и больше не повторяет условия
применимости или полноты технологической анкеты.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.intake.applicability import (
    applicability_rules_for_web,
    infer_applicability_scope,
)
from app.intake.project_intent import IntentLike, unwrap_project_intent


@dataclass(frozen=True)
class QuestionCondition:
    kind: str
    key: str
    value: Any = True

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "value": self.value}


@dataclass(frozen=True)
class QuestionRequirement:
    field: str
    fact_id: str
    validator: str
    message: str
    values: tuple[Any, ...] = ()
    when: QuestionCondition | None = None
    label: str = ""
    widget: str = "text"
    option_labels: tuple[str, ...] = ()
    placeholder: str = ""
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "fact_id": self.fact_id,
            "validator": self.validator,
            "message": self.message,
            "values": list(self.values),
            "when": self.when.to_dict() if self.when else None,
            "label": self.label,
            "widget": self.widget,
            "option_labels": list(self.option_labels),
            "placeholder": self.placeholder,
            "help_text": self.help_text,
        }


@dataclass(frozen=True)
class QuestionDefinition:
    question_id: str
    title: str
    prompt: str
    answer_field: str
    systems: tuple[str, ...]
    reference: str
    options: tuple[str, ...]
    applicable_when: QuestionCondition
    requirements: tuple[QuestionRequirement, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "title": self.title,
            "prompt": self.prompt,
            "answer_field": self.answer_field,
            "systems": list(self.systems),
            "reference": self.reference,
            "options": list(self.options),
            "applicable_when": self.applicable_when.to_dict(),
            "requirements": [row.to_dict() for row in self.requirements],
        }


@dataclass(frozen=True)
class QuestionState:
    definition: QuestionDefinition
    applicable: bool
    answered: bool
    answer: Any
    active_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    missing_messages: tuple[str, ...] = ()

    @property
    def total_count(self) -> int:
        return len(self.active_fields) if self.applicable else 0

    @property
    def completed_count(self) -> int:
        return self.total_count - len(self.missing_fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.definition.to_dict(),
            "applicable": self.applicable,
            "answered": self.answered,
            "answer": self.answer,
            "active_fields": list(self.active_fields),
            "missing_fields": list(self.missing_fields),
            "missing_messages": list(self.missing_messages),
            "total_count": self.total_count,
            "completed_count": self.completed_count,
        }


def _yes(field: str) -> QuestionCondition:
    return QuestionCondition("field_equals", field, "yes")


QUESTION_DEFINITIONS = (
    QuestionDefinition(
        "technology.group_showers",
        "Групповые душевые",
        "Предусмотрена ли группа душевых и сколько душевых сеток задано ТХ/ТЗ?",
        "group_showers_answer",
        ("V1", "T3", "K1"),
        "СП 30.13330.2020; задание ТХ/ТЗ",
        ("yes", "no"),
        QuestionCondition("scope", "group_showers"),
        (
            QuestionRequirement(
                "group_showers_answer", "technology.group_showers", "one_of",
                "подтвердите наличие групповых душевых по технологической анкете",
                ("yes", "no"),
                label="Наличие групповых душевых",
                widget="radio",
                option_labels=("Да", "Нет"),
            ),
            QuestionRequirement(
                "group_showers_count", "technology.group_showers_count", "positive_integer",
                "для групповых душевых задайте число душевых сеток больше нуля",
                when=_yes("group_showers_answer"),
                label="Количество душевых сеток, шт.",
                widget="number",
                placeholder="По ТХ / ТЗ",
                help_text=(
                    "Количество фиксируется как исходное ТХ. Расходы считаются "
                    "по выбранным строкам таблицы А.2 СП 30 и legacy-алгоритму."
                ),
            ),
        ),
    ),
    QuestionDefinition(
        "technology.food_service",
        "Предприятие питания",
        "Есть ли общепит и каков тип приготовления пищи?",
        "food_service_answer",
        ("V1", "T3", "K1", "K3"),
        "СП 118.13330.2022; задание ТХ",
        ("yes", "no"),
        QuestionCondition("scope", "food_service"),
        (
            QuestionRequirement(
                "food_service_answer", "technology.food_service", "one_of",
                "подтвердите наличие предприятия питания по технологической анкете",
                ("yes", "no"),
                label="Наличие предприятия питания",
                widget="radio",
                option_labels=("Да", "Нет"),
            ),
            QuestionRequirement(
                "catering_type", "technology.catering_type", "one_of",
                "для предприятия питания задайте тип приготовления пищи",
                ("semi_finished", "raw", "school"),
                when=_yes("food_service_answer"),
                label="Тип приготовления",
                widget="select",
                option_labels=(
                    "На полуфабрикатах", "На сырье", "Пищеблок школы / ДОО",
                ),
                placeholder="Выберите по ТХ",
            ),
        ),
    ),
    QuestionDefinition(
        "technology.grease_wastewater",
        "Жиросодержащие стоки",
        "Образуются ли жиросодержащие производственные стоки?",
        "grease_wastewater_answer",
        ("K1", "K3"),
        "Задание ТХ; условия приёма стоков",
        ("yes", "no"),
        _yes("food_service_answer"),
        (
            QuestionRequirement(
                "grease_wastewater_answer", "technology.grease_wastewater", "one_of",
                "подтвердите наличие жиросодержащих производственных стоков",
                ("yes", "no"),
                label="Наличие жиросодержащих производственных стоков",
                widget="radio",
                option_labels=("Да", "Нет"),
                help_text=(
                    "Необходимость оборудования проверяется по СП 118; ответ "
                    "не подменяет нормативное решение."
                ),
            ),
        ),
    ),
    QuestionDefinition(
        "technology.grease_trap_location",
        "Размещение жироуловителя",
        "Где предусмотрен жироуловитель либо перенесён ли подбор на стадию Р?",
        "grease_trap_location",
        ("K1", "K3"),
        "Задание ТХ; архитектурно-планировочные решения",
        ("under_sink", "technical_room", "outside_building", "stage_r"),
        _yes("grease_wastewater_answer"),
        (
            QuestionRequirement(
                "grease_trap_location", "technology.grease_trap_location", "one_of",
                "для жиросодержащих стоков выберите место жироуловителя либо явно укажите уточнение на стадии Р",
                ("under_sink", "technical_room", "outside_building", "stage_r"),
                label="Предварительное размещение жироуловителя",
                widget="select",
                option_labels=(
                    "Локально под мойками",
                    "В техническом помещении здания",
                    "За пределами здания",
                    "Уточнить по ТХ и аксонометрии стадии Р",
                ),
                placeholder="Выберите решение",
            ),
        ),
    ),
)


def _condition_matches(req, scope, condition: QuestionCondition | None) -> bool:
    if condition is None:
        return True
    if condition.kind == "scope":
        return bool(getattr(scope, condition.key)) == bool(condition.value)
    if condition.kind == "field_equals":
        return getattr(req, condition.key) == condition.value
    raise ValueError(f"неизвестное условие вопроса: {condition.kind}")


def _requirement_valid(value: Any, requirement: QuestionRequirement) -> bool:
    if requirement.validator == "one_of":
        return value in requirement.values
    if requirement.validator == "positive_integer":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if requirement.validator == "nonempty":
        return value not in (None, "")
    raise ValueError(f"неизвестный валидатор вопроса: {requirement.validator}")


def evaluate_questions(value: IntentLike) -> list[QuestionState]:
    req = unwrap_project_intent(value)
    scope = infer_applicability_scope(
        req.consumers,
        group_showers_answer=req.group_showers_answer,
        food_service_answer=req.food_service_answer,
        catering_type=req.catering_type,
    )
    states: list[QuestionState] = []
    for definition in QUESTION_DEFINITIONS:
        answer = getattr(req, definition.answer_field)
        applicable = _condition_matches(req, scope, definition.applicable_when)
        active_requirements = tuple(
            row for row in definition.requirements
            if applicable and _condition_matches(req, scope, row.when)
        )
        missing_requirements = tuple(
            row for row in active_requirements
            if not _requirement_valid(getattr(req, row.field), row)
        )
        states.append(QuestionState(
            definition=definition,
            applicable=applicable,
            answered=(not applicable) or not missing_requirements,
            answer=answer,
            active_fields=tuple(row.field for row in active_requirements),
            missing_fields=tuple(row.field for row in missing_requirements),
            missing_messages=tuple(row.message for row in missing_requirements),
        ))
    return states


def question_owned_validation_messages() -> frozenset[str]:
    """Сообщения DTO, которые Preflight заменяет структурными issue вопроса."""
    return frozenset(
        requirement.message
        for definition in QUESTION_DEFINITIONS
        for requirement in definition.requirements
    )


def questions_for_web() -> dict[str, list[Any]]:
    """Описание вопросов; старые массивы триггеров оставлены для API v1."""
    return {
        **applicability_rules_for_web(),
        "questions": [row.to_dict() for row in QUESTION_DEFINITIONS],
    }

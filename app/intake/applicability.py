# -*- coding: utf-8 -*-
"""Правила показа технологической анкеты по функциональному составу.

Модуль только определяет, какие вопросы нужно задать проектировщику. Он не
назначает приборы, расходы, жироуловители или иные проектные решения.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Protocol


class ConsumerLike(Protocol):
    code: str
    name: str


GROUP_SHOWERS_CONSUMER_CODES = frozenset({
    "dorm_shared_showers",
    "hospital_shared_baths",
    "sanatorium_shared",
    "school",
    "sport_pool",
})

FOOD_SERVICE_CONSUMER_CODES = frozenset({
    "cafe_dining_in",
    "cafe_takeaway",
    "school",
    "kindergarten_day_pf",
    "kindergarten_day_raw",
})

GROUP_SHOWERS_KEYWORDS = (
    "групповые душ",
    "общие душ",
    "душевые",
    "спорт",
    "бассейн",
    "общежит",
    "производ",
    "цех",
)

FOOD_SERVICE_KEYWORDS = (
    "общепит",
    "кафе",
    "ресторан",
    "столов",
    "фастфуд",
    "фаст фуд",
    "пищеблок",
    "кухня",
)


@dataclass(frozen=True)
class ApplicabilityScope:
    group_showers: bool = False
    food_service: bool = False


def _normalise_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def _contains_keyword(name: str, keywords: tuple[str, ...]) -> bool:
    normalised = _normalise_name(name)
    return any(keyword in normalised for keyword in keywords)


def infer_applicability_scope(
    consumers: Iterable[ConsumerLike],
    *,
    group_showers_answer: str = "unknown",
    food_service_answer: str = "unknown",
    catering_type: str = "none",
) -> ApplicabilityScope:
    """Определить состав вопросов, не делая выводов вместо пользователя."""
    groups = list(consumers)
    codes = {group.code for group in groups if group.code}
    names = [group.name for group in groups if group.name]
    group_showers = (
        group_showers_answer == "yes"
        or bool(codes & GROUP_SHOWERS_CONSUMER_CODES)
        or any(_contains_keyword(name, GROUP_SHOWERS_KEYWORDS) for name in names)
    )
    food_service = (
        food_service_answer == "yes"
        or catering_type != "none"
        or bool(codes & FOOD_SERVICE_CONSUMER_CODES)
        or any(_contains_keyword(name, FOOD_SERVICE_KEYWORDS) for name in names)
    )
    return ApplicabilityScope(
        group_showers=group_showers,
        food_service=food_service,
    )


def applicability_rules_for_web() -> dict[str, list[str]]:
    """Единый справочник для браузера, чтобы не дублировать триггеры в JS."""
    return {
        "group_showers_consumer_codes": sorted(GROUP_SHOWERS_CONSUMER_CODES),
        "food_service_consumer_codes": sorted(FOOD_SERVICE_CONSUMER_CODES),
        "group_showers_keywords": list(GROUP_SHOWERS_KEYWORDS),
        "food_service_keywords": list(FOOD_SERVICE_KEYWORDS),
    }

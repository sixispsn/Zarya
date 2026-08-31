# -*- coding: utf-8 -*-
"""Неблокирующие нормативные замечания к исходным данным Wizard.

Это не расчётное ядро и не замена экспертизы. Правила только выявляют область
применения СП и сочетания функциональных частей, которые проектировщик должен
явно проверить до выпуска комплекта.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.intake.request_dto import IOS2Request
from app.intake.applicability import infer_applicability_scope


@dataclass(frozen=True)
class InputAdvisory:
    level: str          # info / warning
    code: str
    message: str
    reference: str


def _consumer_purposes(req: IOS2Request) -> set[str]:
    """Грубое назначение только для обнаружения смешанного состава.

    Нормы жилых домов в canonical-справочнике имеют префикс residential_.
    Все остальные строки таблицы А.2 относятся к нежилым потребителям.
    """
    return {
        "residential" if group.code.startswith("residential_") else "public"
        for group in req.consumers if group.code
    }


def review_request(req: IOS2Request) -> list[InputAdvisory]:
    """Вернуть только подтверждённые нормативные замечания к анкете."""
    result: list[InputAdvisory] = []
    height = req.building_height_m

    if req.building_type == "residential" and height > 75:
        result.append(InputAdvisory(
            level="warning",
            code="sp30_4_1_high_rise_residential",
            message=(
                f"Жилое здание высотой {height:g} м выше 75 м: требования "
                "СП 30 следует применять совместно с СП 253.1325800."
            ),
            reference="СП 30.13330.2020, п. 4.1",
        ))
    elif req.building_type == "public" and height > 50:
        result.append(InputAdvisory(
            level="warning",
            code="sp30_4_1_high_rise_public",
            message=(
                f"Общественное здание высотой {height:g} м выше 50 м: требования "
                "СП 30 следует применять совместно с СП 253.1325800."
            ),
            reference="СП 30.13330.2020, п. 4.1",
        ))

    purposes = _consumer_purposes(req)
    declared = req.building_type
    mixed = len(purposes) > 1
    mismatch = bool(purposes) and declared in ("residential", "public") \
        and declared not in purposes
    if mixed or mismatch:
        result.append(InputAdvisory(
            level="info",
            code="sp30_mixed_use",
            message=(
                "Обнаружен смешанный функциональный состав. Это допустимо, но "
                "назначение частей и пожарные отсеки следует подтвердить по АР/ТЗ; "
                "расход В2 проверяется отдельно для соответствующих частей."
            ),
            reference="СП 30.13330.2020, пп. 1.1, 7.5–7.6",
        ))

    if req.fire_mode == "auto" and not req.fire_category:
        result.append(InputAdvisory(
            level="warning",
            code="sp10_fire_category_missing",
            message=(
                "Не выбрана диктующая функциональная категория В2. "
                "Общественное или смешанное здание нельзя автоматически "
                "подменять офисной строкой."
            ),
            reference="СП 10.13130.2020, таблица 7.1",
        ))

    high_rise = (
        req.building_type == "residential" and height > 75
        or req.building_type == "public" and height > 50
    )
    if high_rise:
        result.append(InputAdvisory(
            level="info",
            code="sp253_mandatory_systems",
            message=(
                "Будут приняты раздельные В1/В2, изоляция не менее 10/25 мм, "
                "100%-ный резерв, частотный привод и диспетчеризация насосов."
            ),
            reference="СП 253.1325800.2016, пп. 10.3, 10.15, 10.23, 10.25, 10.27",
        ))

    if req.roof_type != "not_set" and (
        not req.storm_city or req.storm_roof_area_m2 <= 0
    ):
        result.append(InputAdvisory(
            level="warning",
            code="storm_missing_inputs",
            message="Для расчёта К2 задайте город и площадь кровли.",
            reference="СП 30.13330.2020, раздел 21",
        ))

    scope = infer_applicability_scope(
        req.consumers,
        group_showers_answer=req.group_showers_answer,
        food_service_answer=req.food_service_answer,
        catering_type=req.catering_type,
    )
    if scope.group_showers and req.group_showers_answer == "unknown":
        result.append(InputAdvisory(
            level="warning",
            code="technology_group_showers_missing",
            message=(
                "Функциональный состав допускает групповые душевые. "
                "Подтвердите их наличие и число душевых сеток по ТХ/ТЗ."
            ),
            reference="СП 30.13330.2020; задание ТХ/ТЗ",
        ))
    if scope.food_service and req.food_service_answer == "unknown":
        result.append(InputAdvisory(
            level="warning",
            code="technology_food_service_missing",
            message=(
                "В составе объекта обнаружено предприятие питания. Уточните "
                "тип приготовления и наличие жиросодержащих стоков."
            ),
            reference="СП 118.13330.2022; задание ТХ",
        ))

    return result

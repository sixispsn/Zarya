"""Единая политика высотной привязки ревизий канализационных стояков.

СП 30.13330.2020 задаёт места установки и доступность ревизий, но не задаёт
размер от чистого пола.  Поэтому 1,000 м в этом модуле является явно
обозначенным проектным правилом Zarya, а не нормативной цитатой.

Обычная этажная ревизия размещается в доступной рабочей зоне около 1 м от
чистого пола.  Явная проектная отметка сохраняется, если она остаётся в этой
зоне.  Для кухонного стояка вызывающий код обязан передать отметку борта
мойки: тогда действует отдельное ограничение СП 30 - не выше этого борта.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


REVISION_PREFERRED_HEIGHT_ABOVE_FLOOR_M = 1.0
REVISION_ACCESSIBLE_HEIGHT_MIN_M = 0.8
REVISION_ACCESSIBLE_HEIGHT_MAX_M = 1.2
REVISION_MIN_CLEARANCE_BELOW_CEILING_M = 0.6
REVISION_PLACEMENT_RULE_ID = "zarya-project-accessibility"


@dataclass(frozen=True)
class RiserRevisionPlacement:
    """Разрешённая высотная привязка одной этажной ревизии."""

    height_above_clean_floor_m: float
    source: str
    kitchen_riser_exception: bool = False


def resolve_riser_revision_placement(
    *,
    floor_height_m: float,
    requested_height_m: float | None = None,
    kitchen_sink_rim_height_m: float | None = None,
) -> RiserRevisionPlacement:
    """Вернуть доступную отметку ревизии и не допустить её у потолка.

    Диапазон 0,8-1,2 м - внутреннее проектное правило доступности Zarya.
    Он не выдаётся за требование СП.  Для кухонного стояка верхней границей
    становится явно заданная отметка борта мойки.
    """
    if not isfinite(floor_height_m) or floor_height_m <= 0:
        raise ValueError("floor height for revision placement must be positive")
    if requested_height_m is not None and (
        not isfinite(requested_height_m) or requested_height_m <= 0
    ):
        raise ValueError("revision height above clean floor must be positive")
    if kitchen_sink_rim_height_m is not None and (
        not isfinite(kitchen_sink_rim_height_m)
        or kitchen_sink_rim_height_m <= 0
    ):
        raise ValueError("kitchen sink rim height must be positive")

    height = (
        REVISION_PREFERRED_HEIGHT_ABOVE_FLOOR_M
        if requested_height_m is None
        else requested_height_m
    )
    source = "project-default" if requested_height_m is None else "project-input"
    kitchen_exception = kitchen_sink_rim_height_m is not None

    if kitchen_exception:
        height = min(height, float(kitchen_sink_rim_height_m))
        source = "sp30-kitchen-riser-limit"
    elif not (
        REVISION_ACCESSIBLE_HEIGHT_MIN_M - 1e-6
        <= height
        <= REVISION_ACCESSIBLE_HEIGHT_MAX_M + 1e-6
    ):
        raise ValueError(
            "general riser revision must be 0.8-1.2 m above clean floor "
            "under the Zarya accessibility rule"
        )

    ceiling_limit = floor_height_m - REVISION_MIN_CLEARANCE_BELOW_CEILING_M
    if height > ceiling_limit:
        raise ValueError(
            "riser revision is too close to the ceiling for safe servicing"
        )
    return RiserRevisionPlacement(
        height_above_clean_floor_m=float(height),
        source=source,
        kitchen_riser_exception=kitchen_exception,
    )


def revision_y_from_clean_floor(
    *,
    clean_floor_y: float,
    graphic_floor_height: float,
    real_floor_height_m: float,
    placement: RiserRevisionPlacement,
) -> float:
    """Перевести реальную высоту над полом в координату схемы SVG."""
    if graphic_floor_height <= 0:
        raise ValueError("graphic floor height must be positive")
    if real_floor_height_m <= 0:
        raise ValueError("real floor height must be positive")
    units_per_m = graphic_floor_height / real_floor_height_m
    return clean_floor_y - placement.height_above_clean_floor_m * units_per_m

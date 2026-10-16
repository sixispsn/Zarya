"""Display-only numbers shared by IOS2 drawings; never round calculation inputs."""
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite


def water_elevation_value(value: float) -> Decimal:
    if isinstance(value, bool) or not isfinite(value):
        raise ValueError("Отметка должна быть конечным числом")
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def water_elevation_text(value: float) -> str:
    rounded = water_elevation_value(value)
    return (f'{rounded:+.2f}' if rounded else '0.00').replace('.', ',')

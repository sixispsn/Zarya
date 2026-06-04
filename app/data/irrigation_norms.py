"""
Нормы расхода воды на поливку (СП 30.13330.2020, п. 26-27).

Перенесены из legacy/sp30_calculator.html.
"""
from dataclasses import dataclass
from typing import Literal


# Тип покрытия для покрытий/тротуаров
PavingNorm = Literal["0.4", "0.5"]

# Тип грунта для газонов/насаждений
LawnSoil = Literal["sand", "loam", "clay"]


# Нормы по типу покрытия (л/м²)
PAVING_NORMS: dict[str, float] = {
    "0.4": 0.4,  # пониженная норма
    "0.5": 0.5,  # стандарт
}

LAWN_NORMS: dict[str, float] = {
    "sand": 6.0,   # песок
    "loam": 4.0,   # суглинок (по умолчанию)
    "clay": 3.0,   # глина
}

LAWN_LABELS: dict[str, str] = {
    "sand": "Песок",
    "loam": "Суглинок",
    "clay": "Глина",
}


@dataclass(frozen=True)
class IrrigationNorms:
    """Фиксированные нормы СП 30, не меняющиеся."""
    grass: float = 3.0       # травяной покров, л/м²
    football: float = 0.5    # футбольное поле, л/м²
    sport: float = 1.5       # прочие спортивные сооружения, л/м²
    rink: float = 0.5        # каток (заливка), л/м²


NORMS = IrrigationNorms()
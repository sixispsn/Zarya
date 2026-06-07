"""
База насосов с кривыми Q-H.

ВАЖНО: на старте используется архивная база Grundfos (из каталога, реальные кривые).
В продукте заменяется на российских производителей (Спрут, ЦНС, Беламос и др.)
через админку/БД. Механика подбора от бренда не зависит.

Перенесено из legacy/sp30_calculator.html (массив PUMP_CURVES).
"""
from dataclasses import dataclass, field
from typing import Literal


PumpType = Literal["boost", "circ", "fire"]


@dataclass(frozen=True)
class PumpCurvePoint:
    """Точка кривой Q-H."""
    q: float   # расход, м³/ч
    h: float   # напор, м


@dataclass(frozen=True)
class Pump:
    """Насос с характеристиками и кривой Q-H."""
    model: str
    brand: str
    type: PumpType
    p_kw: float              # мощность, кВт
    p_max_bar: float         # макс. давление, бар
    t_max: float             # макс. температура, °С
    npshr: float             # требуемый кавитационный запас, м
    q_opt: float             # оптимальный расход (BEP), м³/ч
    note: str
    curve: tuple[PumpCurvePoint, ...]
    archived: bool = False   # архивная база (Grundfos)


# Архивная база Grundfos (реальные кривые из каталога)
PUMPS: list[Pump] = [
    Pump(
        model="MAGNA3 32-80", brand="Grundfos", type="circ",
        p_kw=0.130, p_max_bar=10, t_max=110, npshr=2.0, q_opt=3.5,
        note="Резьбовое DN32, 1×230В, ЧРП встроен", archived=True,
        curve=(
            PumpCurvePoint(0, 8.5), PumpCurvePoint(1, 8.3), PumpCurvePoint(2, 8.0),
            PumpCurvePoint(3, 7.5), PumpCurvePoint(4, 6.5), PumpCurvePoint(5, 5.0),
            PumpCurvePoint(6, 3.0),
        ),
    ),
    Pump(
        model="CR 10-4", brand="Grundfos", type="boost",
        p_kw=2.2, p_max_bar=10, t_max=120, npshr=3.5, q_opt=6.0,
        note="Вертикальный многоступенчатый, DN50", archived=True,
        curve=(
            PumpCurvePoint(0, 40), PumpCurvePoint(2, 39), PumpCurvePoint(4, 37),
            PumpCurvePoint(6, 34), PumpCurvePoint(8, 29), PumpCurvePoint(10, 22),
            PumpCurvePoint(11, 16),
        ),
    ),
    Pump(
        model="CR 5-8", brand="Grundfos", type="boost",
        p_kw=1.1, p_max_bar=10, t_max=120, npshr=3.0, q_opt=3.5,
        note="Вертикальный многоступенчатый, DN32", archived=True,
        curve=(
            PumpCurvePoint(0, 66), PumpCurvePoint(1, 64), PumpCurvePoint(2, 62),
            PumpCurvePoint(3, 58), PumpCurvePoint(4, 52), PumpCurvePoint(5, 44),
            PumpCurvePoint(6, 34), PumpCurvePoint(7, 20),
        ),
    ),
    Pump(
        model="Hydro MX-A CR15-9", brand="Grundfos", type="fire",
        p_kw=11.0, p_max_bar=16, t_max=40, npshr=4.0, q_opt=12.0,
        note="1 осн.+1 рез., шкаф автоматики, DN65, СП 10", archived=True,
        curve=(
            PumpCurvePoint(0, 97), PumpCurvePoint(3, 95), PumpCurvePoint(6, 92),
            PumpCurvePoint(9, 87), PumpCurvePoint(12, 80), PumpCurvePoint(15, 70),
            PumpCurvePoint(18, 57), PumpCurvePoint(20, 45), PumpCurvePoint(22, 28),
        ),
    ),
]


def list_pumps(pump_type: str | None = None) -> list[Pump]:
    """Список насосов, опционально отфильтрованный по типу."""
    if pump_type is None:
        return list(PUMPS)
    return [p for p in PUMPS if p.type == pump_type]
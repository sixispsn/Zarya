"""
База насосов с кривыми Q-H.

Архивная база Grundfos из legacy хранится отдельно от актуального расширения
каталога. Это позволяет запускать неизменные golden/parity-тесты legacy и
одновременно выполнять проектный подбор по проверенным кривым изготовителей.

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
    source_url: str = ""     # официальная карточка/кривая изготовителя
    source_note: str = ""    # идентификатор изделия и дата проверки


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

# Актуальное расширение каталога. Эти позиции не входят в PUMPS намеренно:
# PUMPS остаётся дословным зеркалом legacy для source-parity теста.
#
# Wilo Helix FIRST V 1606:
# - артикул 4200993, P2=4 кВт, PN16, Tmax=120 °C — карточка Wilo;
# - точки Q-H перенесены из официального SVG интерактивной характеристики;
# - NPSHr=1,8 м принят по официальной NPSH-кривой в зоне BEP Q≈17,5 м³/ч.
CURRENT_PUMPS: list[Pump] = [
    Pump(
        model="Helix FIRST V 1606-5/16/E/S/400-50",
        brand="Wilo",
        type="boost",
        p_kw=4.0,
        p_max_bar=16.0,
        t_max=120.0,
        npshr=1.8,
        q_opt=17.5,
        note="Вертикальный многоступенчатый, G 2, 3~400 В; артикул 4200993",
        curve=(
            PumpCurvePoint(0, 75.9),
            PumpCurvePoint(2, 75.2),
            PumpCurvePoint(4, 74.6),
            PumpCurvePoint(6, 73.7),
            PumpCurvePoint(8, 72.0),
            PumpCurvePoint(10, 70.1),
            PumpCurvePoint(12, 67.0),
            PumpCurvePoint(14, 63.7),
            PumpCurvePoint(16, 59.7),
            PumpCurvePoint(18, 54.7),
            PumpCurvePoint(20, 48.6),
            PumpCurvePoint(22, 41.0),
            PumpCurvePoint(24, 32.8),
            PumpCurvePoint(26, 24.6),
            PumpCurvePoint(28, 15.0),
            PumpCurvePoint(30, 6.6),
        ),
        source_url=(
            "https://wilo.com/oem/en/Products/en/application/heating/heating/"
            "renewables-heating/wilo-helix-first-v/"
            "helix-first-v-1606-5-16-e-s-400-50?t=1"
        ),
        source_note="Wilo, артикул 4200993; Q-H/NPSH проверены 23.07.2026",
    ),
]


def list_pumps(
    pump_type: str | None = None,
    *,
    include_current: bool = False,
) -> list[Pump]:
    """Список насосов, опционально отфильтрованный по типу.

    ``include_current=False`` сохраняет дословный legacy-каталог и его golden
    результаты. Проектные мосты явно включают актуальное расширение.
    """
    catalog = PUMPS + (CURRENT_PUMPS if include_current else [])
    if pump_type is None:
        return list(catalog)
    return [p for p in catalog if p.type == pump_type]

"""
Таблица 12.1 СП 30.13330.2020 — счётчики воды.

Содержит параметры 12 типоразмеров счётчиков (DN 15…250 мм):
- расходы (минимальный, эксплуатационный, максимальный, порог чувствительности);
- гидравлическое сопротивление S;
- тип (крыльчатый/турбинный).

Перенесено из legacy/sp30_calculator.html (массив METERS).
"""
from dataclasses import dataclass
from typing import Literal


# Тип счётчика
MeterType = Literal["wing", "turbine"]


@dataclass(frozen=True)
class WaterMeter:
    """Один типоразмер счётчика воды."""
    d_mm: int                # калибр (диаметр), мм
    q_min: float             # минимальный расход, м³/ч
    q_expl: float            # эксплуатационный расход, м³/ч
    q_max: float             # максимальный расход, м³/ч
    q_threshold: float       # порог чувствительности, м³/ч
    s: float                 # гидр. сопротивление, м/(л/с)²
    type: MeterType          # "wing" (крыльчатый) или "turbine" (турбинный)


# ============================================================
# ТАБЛИЦА 12.1 СП 30.13330.2020
# Гидр. сопротивление S — в м/(л/с)², где скорость в л/с.
# h_потерь = S × q²
# ============================================================

WATER_METERS: list[WaterMeter] = [
    WaterMeter(d_mm=15,  q_min=0.03, q_expl=1.2,  q_max=3,    q_threshold=0.015, s=14.5,    type="wing"),
    WaterMeter(d_mm=20,  q_min=0.05, q_expl=2,    q_max=5,    q_threshold=0.025, s=5.18,    type="wing"),
    WaterMeter(d_mm=25,  q_min=0.07, q_expl=2.8,  q_max=7,    q_threshold=0.035, s=2.64,    type="wing"),
    WaterMeter(d_mm=32,  q_min=0.1,  q_expl=4,    q_max=10,   q_threshold=0.05,  s=1.3,     type="wing"),
    WaterMeter(d_mm=40,  q_min=0.16, q_expl=6.4,  q_max=16,   q_threshold=0.08,  s=0.5,     type="wing"),
    WaterMeter(d_mm=50,  q_min=0.3,  q_expl=12,   q_max=30,   q_threshold=0.15,  s=0.143,   type="wing"),
    WaterMeter(d_mm=65,  q_min=1.5,  q_expl=17,   q_max=70,   q_threshold=0.6,   s=0.00081, type="turbine"),
    WaterMeter(d_mm=80,  q_min=2,    q_expl=36,   q_max=110,  q_threshold=0.7,   s=0.00264, type="turbine"),
    WaterMeter(d_mm=100, q_min=3,    q_expl=65,   q_max=180,  q_threshold=1.2,   s=0.000766,type="turbine"),
    WaterMeter(d_mm=150, q_min=4,    q_expl=140,  q_max=350,  q_threshold=1.6,   s=0.00013, type="turbine"),
    WaterMeter(d_mm=200, q_min=6,    q_expl=210,  q_max=600,  q_threshold=3,     s=0.000035,type="turbine"),
    WaterMeter(d_mm=250, q_min=15,   q_expl=380,  q_max=1000, q_threshold=7,     s=0.000018,type="turbine"),
]


# Пределы потерь напора (м), п. 12.17 СП 30
HEAD_LIMITS_NORMAL: dict[MeterType, float] = {
    "wing": 5.0,
    "turbine": 2.5,
}

HEAD_LIMITS_FIRE: dict[MeterType, float] = {
    "wing": 10.0,
    "turbine": 5.0,
}


def pick_meter(q_sr_hr: float) -> WaterMeter:
    """
    Подобрать наименьший счётчик, у которого q_expl ≥ заданный средний расход.

    Если требуемый расход больше максимально доступного — возвращаем самый большой.
    """
    for m in WATER_METERS:
        if m.q_expl >= q_sr_hr:
            return m
    return WATER_METERS[-1]


def get_meter_by_d(d_mm: int) -> WaterMeter | None:
    """Получить счётчик по диаметру."""
    for m in WATER_METERS:
        if m.d_mm == d_mm:
            return m
    return None


def get_next_larger(meter: WaterMeter) -> WaterMeter | None:
    """Получить следующий больший счётчик. None если этот уже максимальный."""
    idx = WATER_METERS.index(meter)
    if idx >= len(WATER_METERS) - 1:
        return None
    return WATER_METERS[idx + 1]
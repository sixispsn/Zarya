"""
Расчёт расхода воды на поливку (СП 30.13330.2020, п. 26-27).

Алгоритм 1-в-1 из legacy/sp30_calculator.html, функция calcIrr().

Формулы:
  summer_l_per_day = (
    grass_m2 × 3 +
    football_m2 × 0.5 +
    sport_m2 × 1.5 +
    paving_m2 × paving_norm +
    lawn_m2 × lawn_norm
  ) × irrigation_times

  winter_l_total = rink_m2 × 0.5   (разово за зиму)

Результаты в м³ (делим на 1000).

Полив учитывается в суточном водопотреблении, но НЕ в стоках (п. 5.13 СП 30).
"""
from dataclasses import dataclass

from app.data.irrigation_norms import LAWN_NORMS, NORMS, PAVING_NORMS


@dataclass
class IrrigationInput:
    """Входные данные расчёта полива."""
    grass_m2: float = 0.0           # травяной покров, м²
    football_m2: float = 0.0        # футбольное поле, м²
    sport_m2: float = 0.0           # прочие спортивные сооружения, м²
    paving_m2: float = 0.0          # усоверш. покрытия, тротуары, м²
    paving_norm: str = "0.5"        # норма покрытия: "0.4" или "0.5"
    lawn_m2: float = 0.0            # газоны/насаждения/цветники, м²
    lawn_soil: str = "loam"         # грунт: "sand", "loam", "clay"
    rink_m2: float = 0.0            # каток (заливка), м²
    irrigation_times: int = 1       # число поливок в сутки (1-3)


@dataclass
class IrrigationItem:
    """Одна строка расчёта (для детализации)."""
    name: str           # название (травяной покров, газоны и т.д.)
    area_m2: float      # площадь
    norm_l_per_m2: float  # норма
    value_m3: float     # результат в м³


@dataclass
class IrrigationResult:
    """Полный результат расчёта полива."""
    summer_m3_per_day: float        # суточный летний расход, м³/сут
    winter_m3_per_season: float     # зимний расход (каток), м³ разово
    irrigation_times: int           # число поливок (для информации)
    items: list[IrrigationItem]     # детализация по строкам


def calculate_irrigation(data: IrrigationInput) -> IrrigationResult:
    """
    Главная функция расчёта полива.

    Args:
        data: входные данные (площади, нормы, число поливок)

    Returns:
        IrrigationResult с летним и зимним расходами.

    Raises:
        ValueError: некорректные параметры (нормы, число поливок).
    """
    # Валидация
    if data.paving_norm not in PAVING_NORMS:
        raise ValueError(
            f"Неизвестная норма покрытия: {data.paving_norm}. "
            f"Допустимые: {list(PAVING_NORMS.keys())}"
        )
    if data.lawn_soil not in LAWN_NORMS:
        raise ValueError(
            f"Неизвестный тип грунта: {data.lawn_soil}. "
            f"Допустимые: {list(LAWN_NORMS.keys())}"
        )
    if data.irrigation_times < 1 or data.irrigation_times > 3:
        raise ValueError(
            f"Число поливок в сутки должно быть 1-3, получено: {data.irrigation_times}"
        )

    paving_norm_val = PAVING_NORMS[data.paving_norm]
    lawn_norm_val = LAWN_NORMS[data.lawn_soil]

    # Считаем по строкам в литрах
    items: list[IrrigationItem] = []
    summer_total_l = 0.0

    if data.grass_m2 > 0:
        v = data.grass_m2 * NORMS.grass
        summer_total_l += v
        items.append(IrrigationItem(
            name="Травяной покров",
            area_m2=data.grass_m2,
            norm_l_per_m2=NORMS.grass,
            value_m3=round(v / 1000.0, 3),
        ))

    if data.football_m2 > 0:
        v = data.football_m2 * NORMS.football
        summer_total_l += v
        items.append(IrrigationItem(
            name="Футбольное поле",
            area_m2=data.football_m2,
            norm_l_per_m2=NORMS.football,
            value_m3=round(v / 1000.0, 3),
        ))

    if data.sport_m2 > 0:
        v = data.sport_m2 * NORMS.sport
        summer_total_l += v
        items.append(IrrigationItem(
            name="Спортивные сооружения",
            area_m2=data.sport_m2,
            norm_l_per_m2=NORMS.sport,
            value_m3=round(v / 1000.0, 3),
        ))

    if data.paving_m2 > 0:
        v = data.paving_m2 * paving_norm_val
        summer_total_l += v
        items.append(IrrigationItem(
            name="Усоверш. покрытия, тротуары",
            area_m2=data.paving_m2,
            norm_l_per_m2=paving_norm_val,
            value_m3=round(v / 1000.0, 3),
        ))

    if data.lawn_m2 > 0:
        v = data.lawn_m2 * lawn_norm_val
        summer_total_l += v
        items.append(IrrigationItem(
            name=f"Газоны / насаждения / цветники",
            area_m2=data.lawn_m2,
            norm_l_per_m2=lawn_norm_val,
            value_m3=round(v / 1000.0, 3),
        ))

    # Умножаем суммарный летний на число поливок
    summer_total_l *= data.irrigation_times

    # Каток - разово, не умножается на irrigation_times
    winter_total_l = 0.0
    if data.rink_m2 > 0:
        v = data.rink_m2 * NORMS.rink
        winter_total_l = v
        items.append(IrrigationItem(
            name="Каток (заливка, 1 раз за зиму)",
            area_m2=data.rink_m2,
            norm_l_per_m2=NORMS.rink,
            value_m3=round(v / 1000.0, 3),
        ))

    return IrrigationResult(
        summer_m3_per_day=round(summer_total_l / 1000.0, 3),
        winter_m3_per_season=round(winter_total_l / 1000.0, 3),
        irrigation_times=data.irrigation_times,
        items=items,
    )
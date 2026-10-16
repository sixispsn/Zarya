"""Предварительный тепловой баланс циркуляции: СП 30, п. 10.10, формула (16).

Отдельное нормативное расширение, не перенос из legacy. Принимает рассчитанные
теплопотери, не выводит их из пиковой мощности ГВС или допустимых норм изоляции.
Не подбирает диаметры, не распределяет расход по ветвям, не увязывает кольца.
"""
from dataclasses import dataclass
import math
from typing import Sequence

from app.calc.pump_system_curve import finite_value


@dataclass(frozen=True)
class CirculationHeatLoss:
    element_id: str
    system: str  # T3, T4, equipment
    heat_loss_w: float | None
    basis: str


@dataclass(frozen=True)
class CirculationThermalResult:
    status: str
    heat_loss_kw: float | None
    delta_t_c: float | None
    flow_lps: float | None
    flow_m3h: float | None
    missing: tuple[str, ...]
    notes: tuple[str, ...]
    method: str = "СП 30.13330.2020, п. 10.10, формула (16)"


def calculate_circulation_demand(
    components: Sequence[CirculationHeatLoss], *, delta_t_c: float | None,
    temperature_basis: str, heat_losses_complete: bool = False,
) -> CirculationThermalResult:
    """q = ΣQht / (4.2 Δt), кВт -> л/с. Общие участки учитываются однократно.

    Результат — предварительный агрегированный баланс указанного контура,
    не окончательная подача насоса разветвлённой/многозонной системы.
    """
    missing, losses, seen, systems = [], [], set(), set()
    for part in components:
        key = part.element_id.strip()
        if not key or key in seen:
            raise ValueError("Теплопотери: нужны уникальные непустые ID; общий участок нельзя считать дважды")
        seen.add(key)
        if part.system not in {"T3", "T4", "equipment"}:
            raise ValueError(f"{key}: допустимы T3, T4 или equipment")
        systems.add(part.system)
        if part.heat_loss_w is None:
            missing.append(f"{key}: не заданы теплопотери")
        else:
            losses.append(finite_value(f"{key}: теплопотери", part.heat_loss_w, nonnegative=True))
        if not part.basis.strip():
            missing.append(f"{key}: нет основания теплопотерь")
    for system in ("T3", "T4", "equipment"):
        if system not in systems:
            missing.append(f"{system}: не учтены теплопотери; отсутствие оборудования задаётся явно с основанием")
    if heat_losses_complete is not True:
        missing.append("Не подтверждена полнота теплопотерь контура без повторного учёта общих участков")
    dt = None
    if delta_t_c is None:
        missing.append("Не задан допустимый перепад температуры Δt")
    else:
        dt = finite_value("Перепад температуры Δt", delta_t_c, nonnegative=True)
        if not 0 < dt <= 10:
            raise ValueError("СП 30, п. 10.10: требуется 0 < Δt ≤ 10 °C")
    if not temperature_basis.strip():
        missing.append("Нет обоснования Δt с обеспечением температуры у потребителя не ниже 60 °C")
    notes = (
        "Предварительный тепловой баланс контура. Для разветвлённой системы необходимы "
        "расходы участков и увязка колец по пп. 10.10–10.13; для нескольких зон — учёт каждой зоны. "
        "Результат не подтверждает диаметры, напор насоса и настройки клапанов.",
        "Теплопотери подающих и циркуляционных трубопроводов принимаются по приложению Л "
        "с проверкой применимости либо обоснованному расчёту; оборудование учитывается отдельно. "
        "Пиковая мощность нагрева воды и допустимая норма изоляции не заменяют теплопотери сети.",
        "Температурное основание задано проектировщиком; локальные температуры у потребителей "
        "этим агрегированным балансом не проверяются. Δt = 10 °C автоматически не назначается.",
    )
    if missing:
        return CirculationThermalResult("needs_data", None, dt, None, None, tuple(missing), notes)
    assert dt is not None
    try:
        heat_kw = math.fsum(losses) / 1000
    except OverflowError as error:
        raise ValueError("Сумма теплопотерь вышла за конечный числовой диапазон") from error
    flow = heat_kw / (4.2 * dt)
    if not all(math.isfinite(x) for x in (heat_kw, flow, flow * 3.6)):
        raise ValueError("Тепловой баланс вышел за конечный числовой диапазон")
    return CirculationThermalResult("preliminary", heat_kw, dt, flow, flow * 3.6, (), notes)

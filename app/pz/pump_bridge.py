# -*- coding: utf-8 -*-
"""
app/pz/pump_bridge.py — мост подбора насоса в модель проекта.

Берёт расчётный расход и параметры системы, гонит штатный calculate_pump
(требуемый напор → кривая системы H=H_ст+k·Q² → рабочая точка → кавитация →
подбор насоса), раскладывает лучший вариант в PumpSystem проекта — откуда
ПЗ берёт модель, рабочую точку, мощность и строит график Q-H.

Мост, не расчётчик: подбор и рабочая точка — в app/calc/pumps.py.
"""
from __future__ import annotations

from app.calc.pumps import PumpInput, calculate_pump
from app.pz.project import PumpSystem


def compute_pump(
    *,
    q_design_m3h: float,
    floors: int,
    floor_height_m: float = 3.0,
    h_losses_m: float = 8.0,
    h_pr_m: float = 20.0,
    h_gar_m: float = 20.0,
    npsh_a_m: float = 8.0,
    purpose: str = "хозяйственно-питьевой",
) -> tuple[PumpSystem, float]:
    """Подбор насоса → (PumpSystem, требуемый напор H_тр).

    Возвращает и PumpSystem (для ПЗ), и H_тр отдельно (для раздела напора).
    Если кандидатов нет — PumpSystem.required=True, но без модели (честно:
    подбор не дал результата, проектировщик подбирает вручную).
    """
    if q_design_m3h <= 0:
        return PumpSystem(required=False), 0.0

    res = calculate_pump(PumpInput(
        q_design_m3h=q_design_m3h, pump_type="boost", floors=floors,
        floor_height=floor_height_m, h_losses=h_losses_m,
        h_pr=h_pr_m, h_gar=h_gar_m, npsh_a=npsh_a_m))

    ps = PumpSystem(
        required=True, purpose=purpose,
        h_stat=round(res.h_stat, 2), k_sys=round(res.k_sys, 5))

    if not res.candidates:
        ps.count_note = "подбор не дал результата — подобрать вручную"
        return ps, round(res.h_required, 2)

    best = res.candidates[0]
    pump = best.pump
    wp = best.working_point
    ps.model = f"{pump.brand} {pump.model}"
    ps.q_m3h = round(wp.q, 2)
    ps.head_m = round(wp.h, 2)
    ps.power_kw = pump.p_kw
    ps.wp_q = round(wp.q, 2)
    ps.wp_h = round(wp.h, 2)
    ps.q_opt = pump.q_opt
    ps.curve = [(pt.q, pt.h) for pt in pump.curve]   # формат графика: (q, h)
    ps.count_note = "1 рабочий + 1 резервный"
    ps.top3 = [f"{c.pump.brand} {c.pump.model} "
               f"(Q={c.working_point.q:.1f} м³/ч, H={c.working_point.h:.1f} м)"
               for c in res.candidates[:3]]
    return ps, round(res.h_required, 2)


def head_components(
    *,
    q_design_m3h: float,
    floors: int,
    floor_height_m: float = 3.0,
    h_losses_m: float = 8.0,
    h_pr_m: float = 20.0,
    h_gar_m: float = 20.0,
) -> dict:
    """Разложение требуемого напора для таблицы ПЗ (формула 14 п.8.27).
    H_тр = H_геом + ∑потери + H_пр (− H_гар даёт напор насоса)."""
    res = calculate_pump(PumpInput(
        q_design_m3h=q_design_m3h, pump_type="boost", floors=floors,
        floor_height=floor_height_m, h_losses=h_losses_m,
        h_pr=h_pr_m, h_gar=h_gar_m))
    return {
        "h_required_m": round(res.h_required, 2),
        "h_geom_m": round(res.h_geom, 2),
        "h_losses_m": round(h_losses_m, 2),
        "h_pr_m": round(h_pr_m, 2),
        "h_gar_m": round(h_gar_m, 2),
    }

# -*- coding: utf-8 -*-
"""
app/pz/demand_bridge.py — мост расчёта расходов В1/Т3 в модель проекта.

Берёт группы потребителей (намерение), гонит их через штатный
calculate_water_demand (СП 30, вероятностный метод с коэффициентом α)
и раскладывает результат в FlowsData проекта — откуда его читает ПЗ.

Мост, не расчётчик: вся физика в app/calc/water_demand.py. Здесь только
перекладка полей результата в поля модели (как flows_bridge для В2).
"""
from __future__ import annotations

from typing import List, Tuple

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.pz.project import FlowsData


def compute_flows(consumer_groups: List[Tuple[str, int]]) -> FlowsData:
    """[(код, количество), ...] → FlowsData (расходы В1/Т3/К1 по СП 30).

    Пустой список → нулевой FlowsData (честно: не задано — не посчитано).
    """
    if not consumer_groups:
        return FlowsData()

    groups = [ConsumerGroup(code=c, count=n) for c, n in consumer_groups if n > 0]
    if not groups:
        return FlowsData()

    r = calculate_water_demand(groups)
    tot, cold, hot = r.total, r.cold, r.hot

    return FlowsData(
        q_day_tot=round(tot.q_day, 3), q_day_c=round(cold.q_day, 3),
        q_day_h=round(hot.q_day, 3),
        q_sec_tot=round(tot.q_sec, 3), q_sec_c=round(cold.q_sec, 3),
        q_sec_h=round(hot.q_sec, 3),
        q_hr_tot=round(tot.q_hr, 3), q_hr_c=round(cold.q_hr, 3),
        q_hr_h=round(hot.q_hr, 3),
        sewage_l_per_s=round(getattr(r, "sewage_flow", tot.q_sec), 3),
        heat_max_kw=round(getattr(r, "heat_max_kw", 0.0), 1),
        q_year_m3=round(tot.q_day * 365, 1))


def project_has_consumers(project) -> bool:
    """Есть ли у проекта данные для расчёта расходов В1."""
    return bool(getattr(project, "consumer_groups", None))

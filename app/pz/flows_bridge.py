"""
Мост между расчётным ядром (app.calc.water_demand) и моделью ПЗ (FlowsData).

Расходы в пояснительной записке должны считаться ядром из состава потребителей,
а не задаваться вручную. Эта функция берёт результат calculate_water_demand()
и раскладывает его в FlowsData, который потребляет генератор ПЗ.
"""
from app.calc.water_demand import WaterDemandResult, calculate_water_demand, ConsumerGroup
from app.pz.project import FlowsData


def flows_from_demand(
    result: WaterDemandResult,
    *,
    irrigation_m3_day: float = 0.0,
    q_year_m3: float = 0.0,
) -> FlowsData:
    """
    Собрать FlowsData из результата расчёта водопотребления.

    Args:
        result: выход calculate_water_demand()
        irrigation_m3_day: суточный расход на полив (из блока irrigation, если есть)
        q_year_m3: годовой расход (если посчитан отдельно; иначе ПЗ возьмёт q_day*365)
    """
    return FlowsData(
        q_day_tot=result.total.q_day,
        q_day_c=result.cold.q_day,
        q_day_h=result.hot.q_day,
        q_sec_tot=result.total.q_sec,
        q_sec_c=result.cold.q_sec,
        q_sec_h=result.hot.q_sec,
        q_hr_tot=result.total.q_hr,
        q_hr_c=result.cold.q_hr,
        q_hr_h=result.hot.q_hr,
        sewage_l_per_s=result.sewage_flow,
        heat_max_kw=result.heat_max_kw,
        irrigation_m3_day=irrigation_m3_day,
        q_year_m3=q_year_m3,
    )


def flows_from_consumers(
    groups: list[ConsumerGroup],
    *,
    apply_k06: bool = False,
    irrigation_m3_day: float = 0.0,
    q_year_m3: float = 0.0,
) -> FlowsData:
    """
    Удобная обёртка: состав потребителей -> расчёт ядром -> FlowsData.
    """
    result = calculate_water_demand(groups, apply_k06=apply_k06)
    return flows_from_demand(
        result, irrigation_m3_day=irrigation_m3_day, q_year_m3=q_year_m3
    )

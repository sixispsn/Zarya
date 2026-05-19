"""
Расчёт водопотребления по СП 30.13330.2020.

Основные формулы:
  q_сек = 5 × q0 × α        - секундный расход (л/с)
  q_час = 0.005 × q0_hr × α_hr  - часовой расход (м³/ч)
  q_сут = (qu × U) / 1000   - суточный расход (м³/сут)

где:
  q0     - секундный расход прибора (л/с)
  q0_hr  - часовой расход прибора (л/ч)
  qu     - суточный расход на потребителя (л/сут)
  U      - количество потребителей
  α      - коэффициент по таблице Б.2 (в зависимости от NP)
  N      - число санитарно-технических приборов
  P      - вероятность действия прибора
  NP     - произведение N × P

Вероятность действия прибора:
  P = (qu × U) / (3600 × q0 × N × T)
  где T - период водопотребления (часы в сутки)

Для группы потребителей с разными нормами q0 нужно использовать
усреднённое (средневзвешенное) значение q0.
"""
from dataclasses import dataclass, field
from typing import Literal

from app.data.sp30_tables import ConsumerNorm, get_alpha, get_consumer_norm


# Тип расхода: общий / холодный / горячий
FlowType = Literal["tot", "c", "h"]


@dataclass
class ConsumerGroup:
    """Группа однотипных потребителей в здании."""
    code: str           # код типа потребителя из CONSUMER_NORMS
    count: int          # количество потребителей U
    appliances: int = 0  # число приборов N (если 0 - примем равным count)


@dataclass
class FlowResult:
    """Результат расчёта для одного типа потока (общий/холодный/горячий)."""
    q_sec: float        # секундный расход, л/с
    q_hr: float         # часовой расход, м³/ч
    q_day: float        # суточный расход, м³/сут
    np_value: float     # произведение NP (для отладки)
    alpha: float        # коэффициент α
    alpha_hr: float     # коэффициент α_hr (часовой)


@dataclass
class WaterDemandResult:
    """
    Полный результат расчёта водопотребления.
    
    Содержит расчёты для трёх потоков: общего (tot), холодного (c), горячего (h).
    """
    total: FlowResult       # общий поток
    cold: FlowResult        # холодная вода
    hot: FlowResult         # горячая вода
    sewage_flow: float      # расход хозяйственно-бытовых стоков, л/с
    heat_max_kw: float      # максимальный тепловой поток на ГВС, кВт
    heat_avg_kw: float      # среднечасовой тепловой поток на ГВС, кВт
    groups: list[ConsumerGroup] = field(default_factory=list)  # исходные данные


def _calc_flow(
    groups: list[ConsumerGroup],
    norms: list[ConsumerNorm],
    flow_type: FlowType,
    period_hours: float = 24.0,
) -> FlowResult:
    """
    Расчёт для одного типа потока (общий, холодный или горячий).
    
    Args:
        groups: группы потребителей
        norms: соответствующие нормы (тот же порядок что и groups)
        flow_type: тип потока ("tot", "c", "h")
        period_hours: период водопотребления T, часов в сутки
    """
    # Извлекаем нужные значения q0, q0_hr, qu из норм
    def q0_of(n: ConsumerNorm) -> float:
        return getattr(n, f"q0_{flow_type}")

    def q0_hr_of(n: ConsumerNorm) -> float:
        return getattr(n, f"q0_hr_{flow_type}")

    def qu_of(n: ConsumerNorm) -> float:
        return getattr(n, f"qu_{flow_type}")

    # Общее суточное потребление по группам (л/сут)
    total_daily = sum(qu_of(n) * g.count for g, n in zip(groups, norms))

    # Если суточное потребление = 0 - значит этого потока нет (например, горячая вода
    # при местном ГВС - там вся вода считается как холодная).
    if total_daily == 0:
        return FlowResult(
            q_sec=0.0, q_hr=0.0, q_day=0.0,
            np_value=0.0, alpha=0.0, alpha_hr=0.0,
        )

    # Средневзвешенное q0 по группам
    # Веса = qu × U (вклад каждой группы в суточное потребление)
    total_weight = sum(qu_of(n) * g.count for g, n in zip(groups, norms))
    q0_avg = sum(q0_of(n) * qu_of(n) * g.count for g, n in zip(groups, norms)) / total_weight
    q0_hr_avg = sum(q0_hr_of(n) * qu_of(n) * g.count for g, n in zip(groups, norms)) / total_weight

    # Общее число приборов N
    total_appliances = sum(g.appliances if g.appliances > 0 else g.count for g in groups)

    # Вероятность действия прибора:
    # P = (qu_avg × U_total) / (3600 × q0_avg × N × T)
    # где qu_avg × U_total = total_daily (общее суточное потребление)
    p_value = total_daily / (3600.0 * q0_avg * total_appliances * period_hours)

    # NP - произведение
    np_value = total_appliances * p_value

    # Коэффициент α по таблице Б.2
    alpha = get_alpha(np_value)

    # Секундный расход: q_сек = 5 × q0 × α (л/с)
    q_sec = 5.0 * q0_avg * alpha

    # Для часового расхода используется отдельный NP_hr и α_hr
    # P_hr = 3600 × P × q0 / q0_hr
    p_hr = 3600.0 * p_value * q0_avg / q0_hr_avg
    np_hr = total_appliances * p_hr
    alpha_hr = get_alpha(np_hr)

    # Часовой расход: q_час = 0.005 × q0_hr × α_hr (м³/ч)
    q_hr = 0.005 * q0_hr_avg * alpha_hr

    # Суточный расход (м³/сут)
    q_day = total_daily / 1000.0

    return FlowResult(
        q_sec=round(q_sec, 3),
        q_hr=round(q_hr, 3),
        q_day=round(q_day, 3),
        np_value=round(np_value, 4),
        alpha=round(alpha, 4),
        alpha_hr=round(alpha_hr, 4),
    )


def calculate_water_demand(
    groups: list[ConsumerGroup],
    period_hours: float = 24.0,
    apply_k06: bool = False,
) -> WaterDemandResult:
    """
    Главная функция расчёта водопотребления.
    
    Args:
        groups: список групп потребителей в здании
        period_hours: период водопотребления T, часов в сутки (по умолчанию 24)
        apply_k06: применить коэффициент 0.6 (для бытового корпуса промпредприятия,
                   примечание 7 СП 30.13330.2020)

    Returns:
        WaterDemandResult с расчётами для общего, холодного и горячего потоков.

    Raises:
        ValueError: если в groups неизвестный код потребителя или пустой список.
    """
    if not groups:
        raise ValueError("Список групп потребителей пуст")

    # Получаем нормы для каждой группы
    norms: list[ConsumerNorm] = []
    for g in groups:
        norm = get_consumer_norm(g.code)
        if norm is None:
            raise ValueError(f"Неизвестный код потребителя: {g.code}")
        norms.append(norm)

    # Считаем три потока
    total = _calc_flow(groups, norms, "tot", period_hours)
    cold = _calc_flow(groups, norms, "c", period_hours)
    hot = _calc_flow(groups, norms, "h", period_hours)

    # Применяем коэффициент 0.6 если нужно
    if apply_k06:
        for flow in (total, cold, hot):
            flow.q_sec = round(flow.q_sec * 0.6, 3)
            flow.q_hr = round(flow.q_hr * 0.6, 3)
            flow.q_day = round(flow.q_day * 0.6, 3)

    # Расход хозяйственно-бытовых стоков (п. 7.7 СП 30):
    # q_s = q_tot + 1.6 л/с (если q_tot > 8 л/с) или q_s = q_tot (если ≤ 8)
    if total.q_sec > 8.0:
        sewage = total.q_sec + 1.6
    else:
        sewage = total.q_sec
    sewage = round(sewage, 3)

    # Тепловой поток ГВС: Q = 1.16 × q_h × (t_h - t_c), кВт
    # t_h = 65°C, t_c = 5°C, разница 60°C
    # Максимальный = по часовому расходу горячей воды
    heat_max = round(1.16 * hot.q_hr * 60.0, 2)
    # Среднечасовой = по среднесуточному
    avg_h_per_hour = hot.q_day * 1000 / 24 / 1000  # м³/ч в среднем
    heat_avg = round(1.16 * avg_h_per_hour * 60.0, 2)

    return WaterDemandResult(
        total=total,
        cold=cold,
        hot=hot,
        sewage_flow=sewage,
        heat_max_kw=heat_max,
        heat_avg_kw=heat_avg,
        groups=groups,
    )
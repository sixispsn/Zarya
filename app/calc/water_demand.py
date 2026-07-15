"""
Расчёт водопотребления по СП 30.13330.2020.

Алгоритм 1-в-1 как в legacy/sp30_calculator.html, функция calcBlock().

Ключевая идея: расчёт идёт по часовой норме q_hr (л/ч на потребителя),
без использования отдельного числа санитарных приборов N.

  СЕКУНДНЫЙ:
    NP_i = q_hr_u_i × U_i / (q0_i × 3600)          для каждой группы
    ∑NP  = сумма по группам
    q0_avg = ∑(NP_i × q0_i) / ∑NP                  (средневзвешенное)
    α = get_alpha(∑NP)                             по таблице Б.2
    q_sec = 5 × q0_avg × α                         л/с

  ЧАСОВОЙ:
    NP_hr_i = 3600 × NP_сек_i × q0_i / q0hr_i      для каждой группы
    ∑NP_hr = сумма по группам
    q0hr_avg = ∑(NP_hr_i × q0hr_i) / ∑NP_hr
    α_hr = get_alpha(∑NP_hr)
    q_hr = 0.005 × q0hr_avg × α_hr                  м³/ч

  СУТОЧНЫЙ:
    q_day = ∑(qu_i × U_i) / 1000                    м³/сут (арифметическая сумма)

  ХОЛОДНАЯ ВОДА:
    qhr_c = qhr_tot - qhr_h, qu_c = qu_tot - qu_h
    q0_c — отдельная величина из таблицы (НЕ tot - h)

  СТОКИ:
    q_sewage = q_sec_tot + q_0s  (п. 5.5, формула (5)); q_0s задаётся
    по фактическому прибору с максимальным водоотведением из таблицы А.1.

  ТЕПЛО ГВС:
    Q_max = 1.16 × q_hr_hot × (65 - 5)              кВт
    Q_avg = 1.16 × (q_day_hot / 24) × (65 - 5)      кВт
"""
from dataclasses import dataclass, field
from typing import Callable

from app.data.sp30_tables import ConsumerNorm, get_alpha, get_consumer_norm


@dataclass
class ConsumerGroup:
    """Группа однотипных потребителей в здании."""
    code: str    # код типа потребителя из CONSUMER_NORMS
    count: int   # количество потребителей U


@dataclass
class FlowResult:
    """Результат расчёта для одного типа потока (общий/холодный/горячий)."""
    q_sec: float        # секундный расход, л/с
    q_hr: float         # часовой расход, м³/ч
    q_day: float        # суточный расход, м³/сут
    np_sec: float       # ∑NP для секундного (для отладки)
    np_hr: float        # ∑NP для часового
    q0_avg: float       # средневзвешенное q0
    q0hr_avg: float     # средневзвешенное q0hr
    alpha: float        # коэффициент α
    alpha_hr: float     # коэффициент α_hr


@dataclass
class WaterDemandResult:
    """Полный результат расчёта водопотребления."""
    total: FlowResult       # общий поток
    cold: FlowResult        # холодная вода
    hot: FlowResult         # горячая вода
    sewage_flow: float      # расход хозяйственно-бытовых стоков, л/с
    sewage_fixture_discharge: float  # q_0s диктующего прибора, л/с
    heat_max_kw: float      # максимальный тепловой поток на ГВС, кВт
    heat_avg_kw: float      # среднечасовой тепловой поток на ГВС, кВт
    groups: list[ConsumerGroup] = field(default_factory=list)


def _calc_block(
    groups: list[ConsumerGroup],
    norms: list[ConsumerNorm],
    qhr_fn: Callable[[ConsumerNorm], float],
    q0_fn: Callable[[ConsumerNorm], float],
    q0hr_fn: Callable[[ConsumerNorm], float],
) -> tuple[float, float, float, float, float, float, float, float]:
    """
    Расчёт секундного и часового расхода для одного потока (tot, h или c).

    Возвращает кортеж: (q_sec, q_hr, sum_np, sum_nph, q0_avg, q0hr_avg, alpha, alpha_hr).
    Если данных нет (q0=0 или qhr=0 для всех групп) — возвращает нули.
    """
    # === СЕКУНДНЫЙ ===
    items: list[tuple[float, float]] = []  # список (np_i, q0_i)
    sum_np = 0.0
    sum_npq0 = 0.0

    for g, n in zip(groups, norms):
        qhr = qhr_fn(n)
        q0 = q0_fn(n)
        if q0 == 0 or qhr <= 0:
            continue
        np_i = qhr * g.count / (q0 * 3600.0)
        items.append((np_i, q0))
        sum_np += np_i
        sum_npq0 += np_i * q0

    if sum_np == 0:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    q0_avg = sum_npq0 / sum_np
    alpha = get_alpha(sum_np)
    q_sec = 5.0 * q0_avg * alpha

    # === ЧАСОВОЙ ===
    sum_nph = 0.0
    sum_nphq0hr = 0.0

    # idx items соответствует idx groups (с пропусками для нулевых q0)
    idx = 0
    for g, n in zip(groups, norms):
        qhr = qhr_fn(n)
        q0 = q0_fn(n)
        if q0 == 0 or qhr <= 0:
            continue
        q0hr = q0hr_fn(n)
        if q0hr == 0:
            idx += 1
            continue
        np_sec_i = items[idx][0]
        np_hr_i = 3600.0 * np_sec_i * q0 / q0hr
        sum_nph += np_hr_i
        sum_nphq0hr += np_hr_i * q0hr
        idx += 1

    if sum_nph == 0:
        return (q_sec, 0.0, sum_np, 0.0, q0_avg, 0.0, alpha, 0.0)

    q0hr_avg = sum_nphq0hr / sum_nph
    alpha_hr = get_alpha(sum_nph)
    q_hr = 0.005 * q0hr_avg * alpha_hr

    return (q_sec, q_hr, sum_np, sum_nph, q0_avg, q0hr_avg, alpha, alpha_hr)


def calculate_water_demand(
    groups: list[ConsumerGroup],
    apply_k06: bool = False,
    sewage_max_fixture_lps: float = 1.6,
) -> WaterDemandResult:
    """
    Главная функция расчёта водопотребления.

    Args:
        groups: список групп потребителей в здании
        apply_k06: применить коэффициент 0.6 к числу потребителей U
                   (для бытового корпуса промпредприятия, прим. 7 СП 30)

    Returns:
        WaterDemandResult с расчётами для трёх потоков.

    Raises:
        ValueError: если groups пуст или содержит неизвестный код.
    """
    if not groups:
        raise ValueError("Список групп потребителей пуст")

    # Применяем k06 — округляем U как в HTML (Math.round)
    k = 0.6 if apply_k06 else 1.0
    eff_groups = [
        ConsumerGroup(code=g.code, count=round(g.count * k))
        for g in groups
    ]
    # Фильтруем пустые группы
    eff_groups = [g for g in eff_groups if g.count > 0]
    if not eff_groups:
        raise ValueError("После применения коэффициентов не осталось потребителей")

    # Получаем нормы
    norms: list[ConsumerNorm] = []
    for g in eff_groups:
        norm = get_consumer_norm(g.code)
        if norm is None:
            raise ValueError(f"Неизвестный код потребителя: {g.code}")
        norms.append(norm)

    # === Общий поток (tot) ===
    tot = _calc_block(
        eff_groups, norms,
        qhr_fn=lambda n: n.q_hr_tot,
        q0_fn=lambda n: n.q0_tot,
        q0hr_fn=lambda n: n.q0hr_tot,
    )

    # === Горячий поток (h) ===
    hot = _calc_block(
        eff_groups, norms,
        qhr_fn=lambda n: n.q_hr_h,
        q0_fn=lambda n: n.q0_h,
        q0hr_fn=lambda n: n.q0hr_h,
    )

    # === Холодный поток (c) ===
    # ВАЖНО: q_hr_c = q_hr_tot - q_hr_h (как в HTML)
    cld = _calc_block(
        eff_groups, norms,
        qhr_fn=lambda n: n.q_hr_tot - n.q_hr_h,
        q0_fn=lambda n: n.q0_c,
        q0hr_fn=lambda n: n.q0hr_c,
    )

    # === Суточный расход (арифметическая сумма) ===
    day_tot = sum(n.qu_tot * g.count / 1000.0 for g, n in zip(eff_groups, norms))
    day_h = sum(n.qu_h * g.count / 1000.0 for g, n in zip(eff_groups, norms))
    day_c = day_tot - day_h

    # === Стоки и тепло ===
    from app.calc.sewage import calculate_domestic_sewage
    sewage_calc = calculate_domestic_sewage(tot[0], sewage_max_fixture_lps)
    heat_max = 1.16 * hot[1] * (65 - 5)  # hot[1] = q_hr_hot
    heat_avg = 1.16 * (day_h / 24.0) * (65 - 5)

    # Округление как в HTML (через toFixed)
    def round_flow(flow_tuple, day):
        q_sec, q_hr, sum_np, sum_nph, q0_avg, q0hr_avg, alpha, alpha_hr = flow_tuple
        return FlowResult(
            q_sec=round(q_sec, 3),
            q_hr=round(q_hr, 3),
            q_day=round(day, 3),
            np_sec=round(sum_np, 4),
            np_hr=round(sum_nph, 4),
            q0_avg=round(q0_avg, 4),
            q0hr_avg=round(q0hr_avg, 2),
            alpha=round(alpha, 3),
            alpha_hr=round(alpha_hr, 3),
        )

    return WaterDemandResult(
        total=round_flow(tot, day_tot),
        cold=round_flow(cld, day_c),
        hot=round_flow(hot, day_h),
        sewage_flow=sewage_calc.q_sewage_lps,
        sewage_fixture_discharge=sewage_calc.q_fixture_max_lps,
        heat_max_kw=round(heat_max, 1),
        heat_avg_kw=round(heat_avg, 1),
        groups=eff_groups,
    )

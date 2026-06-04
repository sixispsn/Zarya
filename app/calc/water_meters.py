"""
Подбор счётчиков воды (СП 30.13330.2020, п. 12.14-12.17).

Алгоритм 1-в-1 из legacy/sp30_calculator.html.

Логика:
  1. q_sr = q_day / T  (средний часовой расход)
  2. Выбираем наименьший счётчик с q_expl >= q_sr
  3. Проверка (а): h = S × q_sec² <= лимит. Если нет — берём больший и повторяем
  4. Проверка (б): h = S × (q_sec + q_fire)² <= лимит. Если нет — нужна обводная линия
  5. Проверка (в): q_threshold <= q_hr. Если нет — рекомендуем комбинированный счётчик

Сценарии:
  - "central" (централизованное ГВС): 2 счётчика — ХВС и ГВС
  - "local"   (местный нагрев): 3 счётчика — общий ввод, ХВС, ГВС перед нагревателем
"""
from dataclasses import dataclass, field
from typing import Literal

from app.data.water_meters import (
    HEAD_LIMITS_FIRE,
    HEAD_LIMITS_NORMAL,
    WATER_METERS,
    WaterMeter,
    get_next_larger,
    pick_meter,
)


# Тип системы ГВС
HwsType = Literal["central", "local"]


@dataclass
class MeterInput:
    """Входные данные подбора счётчиков."""
    hws_type: HwsType = "central"          # "central" / "local"
    period_hours: float = 24.0             # T - период водопотребления, ч
    q_fire_l_per_s: float = 0.0            # расход на пожаротушение, л/с (0 если нет)
    inputs_count: int = 1                  # количество вводов
    is_individual_house: bool = False      # индивидуальный жилой дом
    # Расходы из блока водопотребления
    q_sec_tot: float = 0.0                 # л/с
    q_sec_c: float = 0.0
    q_sec_h: float = 0.0
    q_day_tot: float = 0.0                 # м³/сут
    q_day_c: float = 0.0
    q_day_h: float = 0.0
    q_hr_c: float = 0.0                    # м³/ч
    q_hr_h: float = 0.0


@dataclass
class MeterCheck:
    """Результат проверки одного счётчика."""
    label: str                       # описание счётчика (для UI)
    meter: WaterMeter                # выбранный типоразмер
    # Проверка (а) - норм. расход
    h_normal: float                  # потери напора, м
    h_limit_normal: float            # лимит, м
    pass_normal: bool                # прошла ли (а)
    # Проверка (б) - с пожарным
    h_fire: float | None             # None если q_fire=0
    h_limit_fire: float | None
    pass_fire: bool | None
    need_bypass: bool                # нужна ли обводная линия
    # Проверка (в) - чувствительность
    pass_sensitivity: bool           # прошла ли (в)
    need_combo: bool                 # рекомендовать комбинированный
    # Доп. флаги
    has_fire_check: bool             # применяется ли проверка (б)


@dataclass
class MeterResult:
    """Полный результат подбора."""
    hws_type: HwsType
    meters: list[MeterCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _check_meter(
    meter: WaterMeter,
    q_sec_l_per_s: float,
    q_fire_l_per_s: float,
    q_hr_m3_per_h: float,
    label: str,
    has_fire_check: bool,
) -> MeterCheck:
    """
    Проверить один счётчик по трём критериям.

    Если не проходит (а) — автоматически берём больший и рекурсивно проверяем.
    """
    type_ = meter.type
    h_limit_normal = HEAD_LIMITS_NORMAL[type_]
    h_limit_fire = HEAD_LIMITS_FIRE[type_]

    # === Проверка (а): h = S × q² ≤ лимит ===
    h_normal = meter.s * q_sec_l_per_s ** 2
    pass_normal = h_normal <= h_limit_normal

    # Если не прошла (а) — пробуем следующий больший
    if not pass_normal:
        next_m = get_next_larger(meter)
        if next_m is not None:
            return _check_meter(
                next_m, q_sec_l_per_s, q_fire_l_per_s,
                q_hr_m3_per_h, label, has_fire_check,
            )
        # Иначе остаёмся с самым большим, но фиксируем что не прошла

    # === Проверка (б): с пожарным расходом ===
    h_fire: float | None = None
    pass_fire: bool | None = None
    need_bypass = False
    if has_fire_check and q_fire_l_per_s > 0:
        h_fire = meter.s * (q_sec_l_per_s + q_fire_l_per_s) ** 2
        pass_fire = h_fire <= h_limit_fire
        if not pass_fire:
            need_bypass = True

    # === Проверка (в): чувствительность ===
    pass_sensitivity = meter.q_threshold <= q_hr_m3_per_h
    # Комбинированный счётчик рекомендуем только если (а) прошла,
    # но (в) не прошла, и диаметр больше 15 мм
    need_combo = pass_normal and not pass_sensitivity and meter.d_mm > 15

    return MeterCheck(
        label=label,
        meter=meter,
        h_normal=round(h_normal, 3),
        h_limit_normal=h_limit_normal,
        pass_normal=pass_normal,
        h_fire=round(h_fire, 3) if h_fire is not None else None,
        h_limit_fire=h_limit_fire if has_fire_check and q_fire_l_per_s > 0 else None,
        pass_fire=pass_fire,
        need_bypass=need_bypass,
        pass_sensitivity=pass_sensitivity,
        need_combo=need_combo,
        has_fire_check=has_fire_check and q_fire_l_per_s > 0,
    )


def calculate_meters(data: MeterInput) -> MeterResult:
    """
    Подбор счётчиков воды по СП 30, п. 12.14-12.17.

    Returns:
        MeterResult со списком подобранных счётчиков и примечаниями.
    """
    if data.period_hours <= 0:
        raise ValueError("Период водопотребления должен быть больше 0")
    if data.q_sec_tot == 0 and data.q_sec_c == 0 and data.q_sec_h == 0:
        raise ValueError("Все секундные расходы равны 0 — нечего считать")

    result = MeterResult(hws_type=data.hws_type)
    T = data.period_hours

    if data.hws_type == "central":
        # 2 счётчика: ХВС и ГВС

        # ХВС - с проверкой по пожарному
        q_sr_c = data.q_day_c / T
        m_c = pick_meter(q_sr_c)
        check_c = _check_meter(
            m_c, data.q_sec_c, data.q_fire_l_per_s, data.q_hr_c,
            "Счётчик ХВС (холодная вода)",
            has_fire_check=True,
        )
        result.meters.append(check_c)

        # ГВС - без пожарного (п. 12.12 — обводная не требуется)
        q_sr_h = data.q_day_h / T
        m_h = pick_meter(q_sr_h)
        check_h = _check_meter(
            m_h, data.q_sec_h, 0.0, data.q_hr_h,
            "Счётчик ГВС (горячая вода, п. 12.12 — обводная не требуется)",
            has_fire_check=False,
        )
        result.meters.append(check_h)

    else:  # local
        # 3 счётчика: общий ввод, ХВС, ГВС перед нагревателем

        # Общий ввод (tot) — с проверкой по пожарному
        q_sr_tot = data.q_day_tot / T
        m_tot = pick_meter(q_sr_tot)
        check_tot = _check_meter(
            m_tot, data.q_sec_tot, data.q_fire_l_per_s, data.q_hr_c + data.q_hr_h,
            "Счётчик на вводе (общий)",
            has_fire_check=True,
        )
        result.meters.append(check_tot)

        # ХВС - без пожарного (тут пожарный учитывается на вводе)
        q_sr_c = data.q_day_c / T
        m_c = pick_meter(q_sr_c)
        check_c = _check_meter(
            m_c, data.q_sec_c, 0.0, data.q_hr_c,
            "Счётчик ХВС",
            has_fire_check=False,
        )
        result.meters.append(check_c)

        # ГВС перед нагревателем - без пожарного
        q_sr_h = data.q_day_h / T
        m_h = pick_meter(q_sr_h)
        check_h = _check_meter(
            m_h, data.q_sec_h, 0.0, data.q_hr_h,
            "Счётчик перед водонагревателем (ГВС, п. 12.12)",
            has_fire_check=False,
        )
        result.meters.append(check_h)

    # Примечания
    if data.inputs_count == 1 and not data.is_individual_house:
        result.notes.append(
            "При одном вводе водопровода обводная линия у счётчика ХВС "
            "предусматривается обязательно (п. 12.10 СП 30)."
        )

    return result
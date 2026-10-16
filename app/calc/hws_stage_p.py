"""Укрупнённая оценка ГВС стадии П: п. 5.12 + тепловой баланс п. 10.10.

Отдельное согласованное расширение, не замена legacy и не гидравлика колец.
Диапазон теплопотерь не превращается в выбранный коэффициент или точку насоса.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class HwsStagePInput:
    enabled: bool = False
    apartment_building: bool | None = None
    water_towel_rails: bool | None = None
    zones: int | None = None
    hot_temp_c: float = 65.0  # п. 5.12: допускается для предварительных расчётов
    cold_temp_c: float = 5.0  # п. 5.12: при отсутствии данных
    delta_t_c: float | None = None  # не назначается автоматически
    loss_percent: float | None = None  # пусто — диапазон, не скрытые 30/35/40%

    def validate(self) -> list[str]:
        errors = []
        for key in ('enabled', 'apartment_building', 'water_towel_rails'):
            v = getattr(self, key)
            if type(v) is not bool and not (key != 'enabled' and v is None):
                errors.append(f'{key}: требуется логическое значение')
        if self.zones is not None and (type(self.zones) is not int or self.zones < 1):
            errors.append('Число зон должно быть положительным целым')
        for key in ('hot_temp_c', 'cold_temp_c', 'delta_t_c', 'loss_percent'):
            v = getattr(self, key)
            if v is None and key in ('delta_t_c', 'loss_percent'):
                continue
            if type(v) not in (int, float) or not math.isfinite(v):
                errors.append(f'{key}: требуется конечное число')
        if errors:
            return errors
        if not 60 <= self.hot_temp_c <= 75 or not 0 <= self.cold_temp_c < self.hot_temp_c:
            errors.append('Температуры: горячая вода 60–75 °C, холодная — от 0 °C и ниже горячей')
        if self.delta_t_c is not None and not 0 < self.delta_t_c <= 10:
            errors.append('Перепад циркуляции: 0 < Δt ≤ 10 °C')
        # Conservative sufficient condition for this aggregate estimate. This
        # is not a model of local temperatures along individual branches.
        if self.delta_t_c is not None and self.hot_temp_c - self.delta_t_c < 60:
            errors.append('Для этой укрупнённой оценки tгор − Δt должно быть не ниже 60 °C')
        limit = 60 if self.zones == 2 else 40
        if self.loss_percent is not None and not 30 <= self.loss_percent <= limit:
            errors.append(f'Доля теплопотерь: 30–{limit}% для заданного числа зон')
        return errors


@dataclass(frozen=True)
class HwsStagePResult:
    status: str
    method: str = 'СП 30.13330.2020: п. 5.12, примечание; п. 10.10, формула (16)'
    hot_hour_m3h: float | None = None
    base_heat_kw: float | None = None
    percent_range: tuple[float, float] | None = None
    heat_loss_range_kw: tuple[float, float] | None = None
    flow_range_lps: tuple[float, float] | None = None
    flow_range_m3h: tuple[float, float] | None = None
    selected_heat_loss_kw: float | None = None
    selected_flow_lps: float | None = None
    selected_flow_m3h: float | None = None
    missing: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def calculate_stage_p_circulation(data: HwsStagePInput, hot_hour_m3h: float | None,
                                 *, stage='П', hws_type='central', purpose='residential') -> HwsStagePResult:
    if errors := data.validate():
        raise ValueError('; '.join(errors))
    if not data.enabled:
        return HwsStagePResult('not_requested')
    if (stage != 'П' or purpose != 'residential' or hws_type != 'central'
            or data.apartment_building is False or data.water_towel_rails is False
            or (data.zones is not None and data.zones > 2)):
        return HwsStagePResult('not_applicable', notes=(
            'Режим только для стадии П многоквартирного дома с водяными полотенцесушителями '
            'в системе централизованного ГВС; поддержаны одна или две зоны. '
            'Для иных случаев нужны обоснованные теплопотери, коэффициент не переносится.',))
    missing = []
    for key, title in (('apartment_building', 'Подтвердите: многоквартирный дом'),
                       ('water_towel_rails', 'Уточните: водяные полотенцесушители подключены к ГВС'),
                       ('zones', 'Укажите число зон ГВС'),
                       ('delta_t_c', 'Укажите допустимое охлаждение воды Δt')):
        if getattr(data, key) is None:
            missing.append(title)
    if hot_hour_m3h is None:
        missing.append('Нужен максимальный часовой расход ГВС')
    elif (type(hot_hour_m3h) not in (int, float) or not math.isfinite(hot_hour_m3h)
          or hot_hour_m3h <= 0):
        raise ValueError('Максимальный часовой расход ГВС должен быть конечным положительным числом')
    if missing:
        return HwsStagePResult('needs_data', missing=tuple(missing))
    base = 1.16 * hot_hour_m3h * (data.hot_temp_c - data.cold_temp_c)
    bounds = (30., 60. if data.zones == 2 else 40.)
    heat = tuple(base * percent / 100 for percent in bounds)
    flow = tuple(value / (4.2 * data.delta_t_c) for value in heat)
    if not all(math.isfinite(value * 3.6) for value in (base, *heat, *flow)):
        raise ValueError('Тепловой баланс вышел за конечный числовой диапазон')
    selected = base * data.loss_percent / 100 if data.loss_percent is not None else None
    selected_flow = selected / (4.2 * data.delta_t_c) if selected is not None else None
    return HwsStagePResult(
        'preliminary', hot_hour_m3h=hot_hour_m3h, base_heat_kw=base,
        percent_range=bounds, heat_loss_range_kw=heat, flow_range_lps=flow,
        flow_range_m3h=tuple(value * 3.6 for value in flow),
        selected_heat_loss_kw=selected, selected_flow_lps=selected_flow,
        selected_flow_m3h=selected_flow * 3.6 if selected_flow is not None else None,
        notes=(
            'Ориентировочные суммарные теплопотери по п. 5.12 использованы в тепловом '
            'балансе п. 10.10 для оценки общего расхода; не расчёт отдельных колец.',
            'Проценты относятся к мощности нагрева в максимальный час без теплопотерь, '
            'а не к расходу воды. Теплопотери повторно не прибавляются.',
            'Температуры 65/5 °C допускаются п. 5.12 для предварительного расчёта/при '
            'отсутствии данных; принятые температуры и Δt показываются в выдаче.',
            'Расход не назначает диаметры Т4, напор насоса, Kv и настройки клапанов '
            'и не подставляется автоматически в каждую ветвь Т3.',
            'Условие tгор − Δt ≥ 60 °C — консервативная проверка этой оценки, '
            'не подтверждение локальных температур во всех точках сети.',
        ),
    )

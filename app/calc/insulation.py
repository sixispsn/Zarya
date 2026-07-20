"""
Расчёт толщины тепловой изоляции трубопроводов.

ГВС (защита от теплопотерь, п. 10.3 СП 30, табл. 4 + В.3 СП 61):
  ln B = 2π × λ × (K × (t_гвс − t_помещ) / qL − RнL)
  B = e^(ln B)
  δ = d_нар × (B − 1) / 2

ХВС (защита от конденсата, п. 8.12/26.10 СП 30, В.2.4 СП 61):
  Δt = табл. В.4 (по t_помещ и влажности)
  t_крит = t_помещ − Δt
  если t_трубы ≥ t_крит → изоляция не требуется
  иначе: RнL = 1/(π × d × αн), αн = 7 Вт/(м²·°С)
         ln B = 2π × λ × RнL × (t_крит − t_трубы)/(t_помещ − t_крит)
         δ = d_нар × (B − 1) / 2

Толщина округляется вверх до 10 мм, минимум 10 мм.

Алгоритм 1-в-1 из legacy/sp30_calculator.html (calcGvs, calcHvs).
"""
import math
from dataclasses import dataclass
from typing import Literal, Optional

from app.data.insulation_tables import get_pipe_od, get_rnl, interp_ql, interp_tv4


# Место прокладки
Location = Literal["room_hot", "room_cold", "parking"]

# Коэффициенты теплопроводности изоляции, Вт/(м·°С)
LAMBDA_GVS = 0.05    # п. 10.3 СП 30
LAMBDA_HVS = 0.040   # вспен. полиэтилен / пенокаучук при 20°С
K_GVS = 1.2          # коэф. доп. потерь (стальные трубы, подвижные опоры DN<150)
ALPHA_N = 7.0        # коэф. теплоотдачи поверхности (высокий коэф. излучения)


@dataclass
class PipeGvs:
    """Трубопровод ГВС для расчёта изоляции."""
    dn: int             # условный диаметр, мм
    t_water: float      # температура воды, °С (обычно 60)
    label: str = ""     # описание (стояк, магистраль)
    outer_diameter_mm: Optional[float] = None  # фактический Dн; None сохраняет legacy


@dataclass
class PipeHvs:
    """Трубопровод ХВС для расчёта изоляции."""
    dn: int
    t_water: float      # температура воды, °С (обычно 5-15)
    label: str = ""
    outer_diameter_mm: Optional[float] = None


@dataclass
class InsulationParams:
    """Общие параметры расчёта."""
    location: Location = "room_hot"
    t_room_manual: float = 5.0    # температура помещения если room_cold
    humidity: int = 60            # относительная влажность, %


@dataclass
class GvsResult:
    """Результат для одной трубы ГВС."""
    dn: int
    label: str
    t_water: float
    d_mm: float          # наружный диаметр
    ql: float            # qL из табл. 4
    rnl: float           # RнL из табл. В.3
    delta_calc: float    # расчётная толщина, мм
    delta: int           # принятая толщина (округлено вверх до 10), мм


@dataclass
class HvsResult:
    """Результат для одной трубы ХВС."""
    dn: int
    label: str
    t_water: float
    need_insulation: bool
    dt: float            # перепад из В.4
    t_surf: float        # критическая температура поверхности
    d_mm: float
    delta_calc: Optional[float] = None  # None если изоляция не нужна
    delta: Optional[int] = None


@dataclass
class InsulationResult:
    """Полный результат."""
    t_room: float
    is_parking: bool
    gvs: list[GvsResult]
    hvs: list[HvsResult]


def _round_delta(delta_mm: float) -> int:
    """Округление вверх до 10 мм, минимум 10 мм."""
    return max(10, math.ceil(delta_mm / 10) * 10)


def _resolve_t_room(params: InsulationParams) -> tuple[float, bool]:
    """Определить температуру помещения и флаг паркинга."""
    if params.location == "room_hot":
        return 20.0, False
    if params.location == "parking":
        return 5.0, True
    return params.t_room_manual, False  # room_cold


def calc_gvs_pipe(pipe: PipeGvs, t_room: float) -> GvsResult:
    """Расчёт толщины изоляции для трубы ГВС."""
    d_m = (pipe.outer_diameter_mm or get_pipe_od(pipe.dn)) / 1000.0
    ql = interp_ql(pipe.dn, pipe.t_water)
    rnl = get_rnl(pipe.dn, pipe.t_water)

    ln_b = 2 * math.pi * LAMBDA_GVS * (K_GVS * (pipe.t_water - t_room) / ql - rnl)
    b = math.exp(ln_b)
    delta_calc = d_m * (b - 1) / 2 * 1000  # мм
    delta = _round_delta(delta_calc)

    return GvsResult(
        dn=pipe.dn,
        label=pipe.label,
        t_water=pipe.t_water,
        d_mm=round(d_m * 1000, 1),
        ql=round(ql, 1),
        rnl=round(rnl, 3),
        delta_calc=round(delta_calc, 1),
        delta=delta,
    )


def calc_hvs_pipe(pipe: PipeHvs, t_room: float, humidity: int) -> HvsResult:
    """Расчёт толщины изоляции для трубы ХВС (защита от конденсата)."""
    d_m = (pipe.outer_diameter_mm or get_pipe_od(pipe.dn)) / 1000.0
    dt = interp_tv4(t_room, humidity)
    t_surf = t_room - dt

    # Если температура воды выше критической поверхности — конденсата не будет
    if pipe.t_water >= t_surf:
        return HvsResult(
            dn=pipe.dn,
            label=pipe.label,
            t_water=pipe.t_water,
            need_insulation=False,
            dt=round(dt, 1),
            t_surf=round(t_surf, 1),
            d_mm=round(d_m * 1000, 1),
        )

    rnl = 1 / (math.pi * d_m * ALPHA_N)
    ln_b = 2 * math.pi * LAMBDA_HVS * rnl * (t_surf - pipe.t_water) / (t_room - t_surf)
    b = math.exp(ln_b)
    delta_calc = d_m * (b - 1) / 2 * 1000
    delta = _round_delta(delta_calc)

    return HvsResult(
        dn=pipe.dn,
        label=pipe.label,
        t_water=pipe.t_water,
        need_insulation=True,
        dt=round(dt, 1),
        t_surf=round(t_surf, 1),
        d_mm=round(d_m * 1000, 1),
        delta_calc=round(delta_calc, 1),
        delta=delta,
    )


def calculate_insulation(
    params: InsulationParams,
    gvs_pipes: list[PipeGvs],
    hvs_pipes: list[PipeHvs],
) -> InsulationResult:
    """Главная функция расчёта тепловой изоляции."""
    t_room, is_parking = _resolve_t_room(params)

    if params.humidity not in (40, 50, 60, 70, 80, 90):
        raise ValueError(
            f"Влажность {params.humidity}% не поддерживается. "
            "Допустимо: 40, 50, 60, 70, 80, 90."
        )

    gvs_results = [calc_gvs_pipe(p, t_room) for p in gvs_pipes]
    hvs_results = [calc_hvs_pipe(p, t_room, params.humidity) for p in hvs_pipes]

    return InsulationResult(
        t_room=t_room,
        is_parking=is_parking,
        gvs=gvs_results,
        hvs=hvs_results,
    )

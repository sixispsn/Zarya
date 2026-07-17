"""
Подбор насоса по рабочей точке (СП 30.13330, методика Grundfos).

Алгоритм 1-в-1 из legacy/sp30_calculator.html (calcPumpHead, findWorkingPoint, scoring).

  Требуемый напор: Hp = H_geom + ΣH_l + H_пр − H_гар
  H_geom (авто) = (n_этажей − 1) × h_этажа + 1
  Кривая системы: H_сист = H_стат + k × Q²,  k = (Hp − H_стат) / Q_расч²
  Рабочая точка: пересечение кривой насоса и кривой системы.
  Скоринг по BEP, запасу напора, близости к Q_расч, NPSH.
"""
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

from app.data.pumps import Pump, PumpCurvePoint, list_pumps


PumpMode = Literal["1", "2p", "2s"]  # 1 насос / 2 параллельно / 2 последовательно


@dataclass
class PumpInput:
    """Входные данные подбора насоса."""
    q_design_m3h: float          # расчётный расход, м³/ч
    pump_type: str = "boost"     # boost / circ / fire
    mode: PumpMode = "1"
    # Напор: либо авто (этажи), либо вручную
    h_geom_manual: Optional[float] = None  # если задан — используем его
    floors: int = 9
    floor_height: float = 3.0
    h_losses: float = 5.0        # ΣH_l, потери в сети, м
    h_pr: float = 20.0           # свободный напор у прибора, м
    h_gar: Optional[float] = None  # гарантированный напор сети из ТУ, м
    npsh_a: Optional[float] = None  # располагаемый кавитационный запас системы, м


@dataclass
class WorkingPoint:
    q: float
    h: float
    h_sys: float


@dataclass
class PumpCandidate:
    pump: Pump
    working_point: WorkingPoint
    score: int
    h_excess_pct: float
    q_ratio: float
    npsh_ok: Optional[bool]
    reasons: list[str] = field(default_factory=list)
    eff_curve: list[PumpCurvePoint] = field(default_factory=list)


@dataclass
class PumpResult:
    q_design: float
    h_required: float
    h_geom: float
    h_stat: float
    k_sys: float
    candidates: list[PumpCandidate]  # Top-3, отсортировано по score


def _interp_h(curve: list[PumpCurvePoint], q: float) -> float:
    """Напор насоса при заданном расходе (линейная интерполяция по кривой)."""
    if q <= curve[0].q:
        return curve[0].h
    if q >= curve[-1].q:
        return 0.0
    for i in range(len(curve) - 1):
        if curve[i].q <= q <= curve[i + 1].q:
            k = (q - curve[i].q) / (curve[i + 1].q - curve[i].q)
            return curve[i].h + k * (curve[i + 1].h - curve[i].h)
    return 0.0


def _build_effective_curve(curve: tuple[PumpCurvePoint, ...], mode: PumpMode) -> list[PumpCurvePoint]:
    """Кривая насоса с учётом режима (параллельно/последовательно)."""
    if mode == "2p":  # параллельно: Q удваивается при том же H
        return [PumpCurvePoint(p.q * 2, p.h) for p in curve]
    if mode == "2s":  # последовательно: H удваивается при том же Q
        return [PumpCurvePoint(p.q, p.h * 2) for p in curve]
    return list(curve)


def _find_working_point(curve: list[PumpCurvePoint], h_stat: float, k_sys: float) -> Optional[WorkingPoint]:
    """Найти точку пересечения кривой насоса и кривой системы."""
    q_max = curve[-1].q
    steps = 200
    best: Optional[WorkingPoint] = None
    best_diff = float("inf")
    for i in range(steps + 1):
        q = q_max * i / steps
        h_pump = _interp_h(curve, q)
        h_sys = h_stat + k_sys * q * q
        diff = abs(h_pump - h_sys)
        if diff < best_diff:
            best_diff = diff
            best = WorkingPoint(q=q, h=h_pump, h_sys=h_sys)
    return best


def calculate_pump(data: PumpInput) -> PumpResult:
    """Подбор насосов с расчётом рабочей точки и скорингом Top-3."""
    if data.q_design_m3h <= 0:
        raise ValueError("Расчётный расход должен быть больше 0")
    if data.h_gar is None:
        raise ValueError("Гарантированный напор Hгар должен быть задан по ТУ")

    # H_geom
    if data.h_geom_manual is not None:
        h_geom = data.h_geom_manual
    else:
        h_geom = (data.floors - 1) * data.floor_height + 1

    hp = h_geom + data.h_losses + data.h_pr - data.h_gar
    hp = max(hp, 0.0)

    # Точно как calcPumpHead() в legacy/sp30_calculator.html.
    # Не заменять инженерно «улучшенной» декомпозицией без решения пользователя.
    h_stat = data.h_gar if data.h_gar > 0 else 0.0
    k_sys = ((hp - h_stat) / (data.q_design_m3h ** 2)
             if hp > h_stat else 0.1)

    candidates_raw = list_pumps(data.pump_type)
    results: list[PumpCandidate] = []

    for pump in candidates_raw:
        eff_curve = _build_effective_curve(pump.curve, data.mode)
        wp = _find_working_point(eff_curve, h_stat, k_sys)
        if wp is None or wp.q <= 0:
            continue

        # Насос должен перекрывать расход и напор
        if wp.q < data.q_design_m3h * 0.85:
            continue
        if _interp_h(eff_curve, 0) < hp * 0.9:
            continue

        q_opt_eff = pump.q_opt * (2 if data.mode == "2p" else 1)
        q_ratio = wp.q / q_opt_eff if q_opt_eff > 0 else 0
        h_excess = (wp.h - hp) / hp * 100 if hp > 0 else 0

        # Скоринг
        score = 100
        if 0.7 <= q_ratio <= 1.1:
            score += 30
        elif 0.6 <= q_ratio <= 1.2:
            score += 15
        else:
            score -= 20

        if 5 <= h_excess <= 20:
            score += 20
        elif 0 <= h_excess <= 35:
            score += 5
        elif h_excess > 35:
            score -= 15
        else:
            score -= 30

        q_err = abs(wp.q - data.q_design_m3h) / data.q_design_m3h
        if q_err < 0.1:
            score += 20
        elif q_err < 0.2:
            score += 10

        npsh_ok = (data.npsh_a >= pump.npshr + 0.5) if data.npsh_a is not None else None
        if npsh_ok is False:
            score -= 50

        # Пояснения
        reasons: list[str] = []
        if 0.7 <= q_ratio <= 1.1:
            reasons.append("✓ рабочая точка близка к зоне макс. КПД")
        elif q_ratio < 0.7:
            reasons.append("⚠ насос работает на малом расходе (ниже BEP)")
        else:
            reasons.append("⚠ насос перегружен по расходу (выше BEP)")

        if 5 <= h_excess <= 20:
            reasons.append(f"✓ запас по напору +{h_excess:.0f}% — оптимально")
        elif h_excess > 20:
            reasons.append(f"⚠ большой запас по напору +{h_excess:.0f}% — насос избыточен")
        elif h_excess >= 0:
            reasons.append(f"✓ напора хватает (запас +{h_excess:.0f}%)")
        else:
            reasons.append("✗ напора недостаточно")

        if npsh_ok is False:
            reasons.append(f"✗ КАВИТАЦИЯ: NPSHa={data.npsh_a}м < NPSHr+0.5={pump.npshr + 0.5:.1f}м")
        elif npsh_ok is True:
            reasons.append(f"✓ кавитации нет: NPSHa={data.npsh_a}м > {pump.npshr + 0.5:.1f}м")
        else:
            reasons.append("⚠ NPSHa не задан — кавитационную проверку выполнить по данным изготовителя и схеме всасывания")

        if data.mode == "2p":
            reasons.append("↔ параллельная схема — увеличен расход")
        if data.mode == "2s":
            reasons.append("↕ последовательная схема — увеличен напор")

        results.append(PumpCandidate(
            pump=pump,
            working_point=WorkingPoint(q=round(wp.q, 2), h=round(wp.h, 1), h_sys=round(wp.h_sys, 1)),
            score=score,
            h_excess_pct=round(h_excess, 1),
            q_ratio=round(q_ratio, 2),
            npsh_ok=npsh_ok,
            reasons=reasons,
            eff_curve=eff_curve,
        ))

    results.sort(key=lambda r: r.score, reverse=True)

    return PumpResult(
        q_design=round(data.q_design_m3h, 2),
        h_required=round(hp, 1),
        h_geom=round(h_geom, 1),
        h_stat=round(h_stat, 1),
        k_sys=round(k_sys, 4),
        candidates=results[:3],
    )

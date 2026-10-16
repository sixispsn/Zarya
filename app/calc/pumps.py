"""
Подбор насоса по Q-H; баланс напора по СП 30, п. 13.11.

L02: исправленная кривая системы; L03: строгий допуск по расчётной паре Q/H.
L04: пересечение в опубликованном диапазоне. Скоринг legacy сохранён.
L07: чистая циркуляция отделена от повысительного режима (см. calculate_circulation_pump).
Это не полная проверка установки. Формулы ниже — для повысительного режима.

  Требуемый напор: Hp = H_geom + ΣH_l + H_пр − H_гар
  H_geom (авто) = (n_этажей − 1) × h_этажа + 1
  Оценка: H_сист = max(0, H_geom + H_пр − H_гар + k × Q²), k = ΣH_l / Q_расч²
  Рабочая точка: пересечение кривой насоса и кривой системы.
  Скоринг по BEP, запасу напора, близости к Q_расч, NPSH.
"""
from dataclasses import dataclass, field
import math
from typing import Literal, Optional

from app.data.pumps import Pump, PumpCurvePoint, list_pumps
from app.calc.pump_system_curve import PumpSystemCurve, finite_value
from app.calc.pump_curve import WorkingPoint, find_intersections, interpolate_head


PumpMode = Literal["1", "2p", "2s"]  # 1 насос / 2 параллельно / 2 последовательно


@dataclass
class PumpInput:
    """Входные данные подбора насоса."""
    q_design_m3h: float          # расчётный расход, м³/ч
    pump_type: str = "boost"     # boost / circ / fire
    mode: PumpMode = "1"
    # Напор: либо авто (этажи), либо вручную
    h_geom_manual: Optional[float] = None  # если задан — используем его
    floors: Optional[int] = None
    floor_height: float = 3.0
    h_losses: Optional[float] = None  # ΣH_l при Qрасч; отсутствие не равно нулю
    h_pr: float = 20.0           # свободный напор у прибора, м
    h_gar: Optional[float] = None  # гарантированный напор сети из ТУ, м
    npsh_a: Optional[float] = None  # располагаемый кавитационный запас системы, м
    include_current_catalog: bool = False  # False = архивный каталог
    circulation_head_m: Optional[float] = None  # отдельный напор циркуляционного кольца
    circulation_basis: str = ""  # источник Q/H; не подменяется потерями водоразбора


@dataclass
class PumpCandidate:
    pump: Pump
    working_point: WorkingPoint
    score: int
    h_excess_pct: float
    q_ratio: float
    npsh_ok: Optional[bool]
    npshr_at_working_point: Optional[float]
    reasons: list[str] = field(default_factory=list)
    eff_curve: list[PumpCurvePoint] = field(default_factory=list)
    head_at_design: Optional[float] = None


@dataclass
class PumpResult:
    q_design: float
    h_required: float
    h_geom: Optional[float]
    h_stat: Optional[float]  # signed intercept, not available source head
    k_sys: Optional[float]
    candidates: list[PumpCandidate]  # Top-3, отсортировано по score
    required: bool = True
    curve_kind: str = "quadratic_estimate"
    notes: list[str] = field(default_factory=list)


def interpolate_pump_head(curve, q: float) -> Optional[float]:
    """L04: линейная интерполяция только внутри опубликованного диапазона."""
    return interpolate_head([(p.q, p.h) for p in curve], q)


@dataclass(frozen=True)
class PumpDutyCheck:
    ok: bool
    reason: str
    head_at_design: Optional[float] = None


def check_pump_duty(curve, q_design: float, h_required: float) -> PumpDutyCheck:
    """L03: каталог должен обеспечивать всю пару Q/H, до рейтинга.

    За пределами опубликованных Q проверка не выполняется. L04 сохраняет
    обе крайние табличные точки, не продолжая характеристику за их пределы.
    """
    if (q_design is None or h_required is None
            or not math.isfinite(q_design) or not math.isfinite(h_required)
            or q_design <= 0 or h_required <= 0):
        return PumpDutyCheck(False, "Не задана конечная положительная расчётная пара Q/H")
    points = list(curve)
    if len(points) < 2 or any(
        not math.isfinite(p.q) or not math.isfinite(p.h) or p.q < 0 or p.h < 0
        for p in points
    ) or any(a.q >= b.q for a, b in zip(points, points[1:])):
        return PumpDutyCheck(False, "Нет корректной каталожной Q-H характеристики")
    if not points[0].q <= q_design <= points[-1].q:
        return PumpDutyCheck(False, "Расчётный расход вне опубликованного диапазона Q-H")
    h = interpolate_pump_head(points, q_design)
    if h is None:
        return PumpDutyCheck(False, "Нет каталожного напора при расчётном расходе")
    # 1e-9 м — только машинная погрешность, не инженерный процент недобора.
    ok = h >= h_required - 1e-9
    reason = (f"При Qрасч={q_design:.3f} м³/ч Hкат={h:.3f} м "
              f"{'≥' if ok else '<'} Hтреб={h_required:.3f} м")
    return PumpDutyCheck(ok, reason, h)


def interpolate_pump_npshr(pump: Pump, q: float) -> Optional[float]:
    """NPSHr насоса при расходе одного агрегата.

    Для каталога с Q-NPSHr применяется линейная интерполяция между
    опубликованными точками. Для legacy-позиций сохраняется скалярное
    каталожное значение. За границами Q-NPSHr используется крайняя точка,
    чтобы проверка не превращалась в фиктивный ноль.
    """
    curve = pump.npsh_curve
    if not curve:
        return pump.npshr
    if q <= curve[0].q:
        return curve[0].h
    if q >= curve[-1].q:
        return curve[-1].h
    for left, right in zip(curve, curve[1:]):
        if left.q <= q <= right.q:
            ratio = (q - left.q) / (right.q - left.q)
            return left.h + ratio * (right.h - left.h)
    return None


def _build_effective_curve(curve: tuple[PumpCurvePoint, ...], mode: PumpMode) -> list[PumpCurvePoint]:
    """Кривая насоса с учётом режима (параллельно/последовательно)."""
    if mode == "2p":  # параллельно: Q удваивается при том же H
        return [PumpCurvePoint(p.q * 2, p.h) for p in curve]
    if mode == "2s":  # последовательно: H удваивается при том же Q
        return [PumpCurvePoint(p.q, p.h * 2) for p in curve]
    return list(curve)


def _find_working_point(curve: list[PumpCurvePoint], h_stat: float, k_sys: float) -> Optional[WorkingPoint]:
    """Только единственное действительное пересечение, иначе None."""
    return find_intersections([(p.q, p.h) for p in curve], h_stat, k_sys).working_point


def calculate_pump(data: PumpInput) -> PumpResult:
    """Подбор насосов с расчётом рабочей точки и скорингом Top-3."""
    finite_value("Расчётный расход", data.q_design_m3h, nonnegative=True)
    if data.q_design_m3h <= 0:
        raise ValueError("Расчётный расход должен быть больше 0")
    if data.pump_type == "circ":
        return calculate_circulation_pump(data)
    if data.h_gar is None:
        raise ValueError("Гарантированный напор Hгар должен быть задан по ТУ")

    # H_geom
    if data.h_geom_manual is not None:
        h_geom = data.h_geom_manual
    else:
        if data.floors is None or data.floors < 1:
            raise ValueError("Для Hgeom нужны отметки либо явно заданная этажность")
        finite_value("Высота этажа", data.floor_height, nonnegative=True)
        if data.floor_height <= 0:
            raise ValueError("Высота этажа должна быть больше 0")
        h_geom = (data.floors - 1) * data.floor_height + 1

    system = PumpSystemCurve(
        data.q_design_m3h, h_geom,
        finite_value("Потери напора", data.h_losses, nonnegative=True), data.h_pr, data.h_gar,
    )
    notes = [
        "Кривая системы — квадратичная оценка по потерям при расчётном расходе; "
        "гарантированный напор и свободный напор приняты постоянными. "
        "Это не поучастковый расчёт сети во всех режимах и не характеристика "
        "частотного регулирования.",
        "Допуск по расчётной паре Q/H проверен. Подбор предварительный: "
        "для каждого кандидата требуется единственное пересечение в опубликованном диапазоне; "
        "регулирование и остальные условия установки проверяются отдельно.",
    ]
    if data.h_geom_manual is None:
        notes.append("Hgeom оценён по этажности; подтвердить отметками оси насоса и прибора.")
    if not system.h_required:
        notes.append(
            "При расчётном расходе повышение напора не требуется. "
            "Максимальное давление и необходимость его снижения проверяются отдельно."
        )
        return PumpResult(
            data.q_design_m3h, 0.0, h_geom, system.h_base, system.k_sys, [],
            required=False, notes=notes,
        )
    return _select_candidates(
        data, system.h_required, h_geom, system.h_base, system.k_sys,
        notes=notes,
    )


def calculate_circulation_pump(data: PumpInput) -> PumpResult:
    """L07: предварительный каталог по отдельной паре Q/H замкнутой циркуляции.

    Напор задаётся из расчёта кольца, а не из баланса подачи к прибору.
    Естественная циркуляция и циркуляционно-повысительная схема п. 13.12
    этим режимом не рассчитываются. Из одной пары Q/H кривую сети не строим.
    """
    if data.pump_type != "circ":
        raise ValueError("Расчёт циркуляции предназначен только для типа circ")
    if data.mode not in {"1", "2p", "2s"}:
        raise ValueError("Неизвестный режим циркуляционных насосов")
    if not isinstance(data.circulation_basis, str) or not data.circulation_basis.strip():
        raise ValueError("Т4: укажите основание циркуляционных Q/H по тепловому расчёту и кольцу")
    head = finite_value("Т4: отдельный требуемый напор циркуляции", data.circulation_head_m,
                        nonnegative=True)
    if head <= 0:
        raise ValueError("Т4: напор принудительной циркуляции должен быть положительным; "
                         "ноль не подтверждает естественную циркуляцию")
    if data.npsh_a is not None:
        finite_value("Располагаемый кавитационный запас", data.npsh_a, nonnegative=True)
    result = calculate_pump_at_duty(data, required_head_m=head)
    result.notes[:0] = [
        "Т4: замкнутый контур принудительной циркуляции. Q задаётся по тепловому расчёту, "
        "напор — по циркуляционному кольцу с оборудованием и балансировкой. "
        "Hgeom, Hпр, Hгар и потери пути водоразбора в этот расчёт не входят.",
        "СП 30.13330.2020, пп. 10.10–10.13. Рекомендуемые 2–5 м по п. 10.14 — "
        "не значение по умолчанию. Естественный циркуляционный напор, статическое давление, "
        "температура и пригодность материалов насоса для питьевой горячей воды "
        "проверяются отдельно. Циркуляционно-повысительная схема п. 13.12 не рассчитывается.",
        "Основание заданной пары Q/H: " + data.circulation_basis.strip(),
    ]
    return result


def calculate_pump_at_duty(
    data: PumpInput, *, required_head_m: float,
) -> PumpResult:
    """Только каталожная проверка при Qрасч; кривую сети из одной точки не выводим."""
    q = finite_value("Расчётный расход", data.q_design_m3h, nonnegative=True)
    if q <= 0:
        raise ValueError("Расчётный расход должен быть больше 0")
    hp = finite_value("Требуемый напор насоса", required_head_m, nonnegative=True)
    notes = [
        "Известна только расчётная точка Q/H. Разложение напора не задано: "
        "кривая системы и её пересечение с кривой насоса не определены. "
        "Показан каталожный напор при расчётном расходе; режим регулирования "
        "и фактическую рабочую точку требуется подтвердить."
    ]
    if hp == 0:
        return PumpResult(q, 0, None, None, None, [], required=False,
                          curve_kind="duty_only", notes=notes)
    return _select_candidates(data, hp, None, None, None, notes=notes,
                              curve_kind="duty_only")


def _select_candidates(
    data: PumpInput, hp: float, h_geom: Optional[float],
    h_stat: Optional[float], k_sys: Optional[float], *,
    notes: list[str], curve_kind: str = "quadratic_estimate",
) -> PumpResult:
    """Каталоги/скоринг прежние. Без кривой сети точка — каталог при Qрасч."""

    candidates_raw = list_pumps(
        data.pump_type,
        include_current=data.include_current_catalog,
    )
    results: list[PumpCandidate] = []
    intersection_notes: list[str] = []

    for pump in candidates_raw:
        eff_curve = _build_effective_curve(pump.curve, data.mode)
        duty = check_pump_duty(eff_curve, data.q_design_m3h, hp)
        if not duty.ok:
            continue
        if h_stat is not None and k_sys is not None:
            intersection = find_intersections([(p.q, p.h) for p in eff_curve], h_stat, k_sys)
            wp = intersection.working_point
            if wp is None:
                intersection_notes.append(f"{pump.model}: {intersection.reason}. "
                                          "Расчётная пара обеспечивается, рабочая точка не подтверждена.")
        else:
            assert duty.head_at_design is not None  # admitted by check_pump_duty above
            wp = WorkingPoint(data.q_design_m3h, duty.head_at_design, hp)
        if wp is None or wp.q <= 0:
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

        q_per_pump = wp.q / 2 if data.mode == "2p" else wp.q
        npshr_at_wp = interpolate_pump_npshr(pump, q_per_pump)
        npsh_ok = (
            data.npsh_a >= npshr_at_wp + 0.5
            if data.npsh_a is not None and npshr_at_wp is not None
            else None
        )
        if npsh_ok is False:
            score -= 50

        # Пояснения
        reasons: list[str] = ["✓ " + duty.reason]
        if 0.7 <= q_ratio <= 1.1:
            reasons.append("✓ рассматриваемая точка близка к зоне макс. КПД")
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

        if npsh_ok is False and npshr_at_wp is not None:
            reasons.append(
                f"✗ КАВИТАЦИЯ: NPSHa={data.npsh_a}м < "
                f"NPSHr+0.5={npshr_at_wp + 0.5:.1f}м"
            )
        elif npsh_ok is True and npshr_at_wp is not None:
            reasons.append(
                f"✓ кавитации нет: NPSHa={data.npsh_a}м > "
                f"NPSHr+0.5={npshr_at_wp + 0.5:.1f}м"
            )
        elif npshr_at_wp is None:
            reasons.append(
                "⚠ NPSHr не опубликован в каталоге установки — "
                "проверить по характеристике базового насоса"
            )
        else:
            reasons.append("⚠ NPSHa не задан — кавитационную проверку выполнить по данным изготовителя и схеме всасывания")

        if data.mode == "2p":
            reasons.append("↔ параллельная схема — увеличен расход")
        if data.mode == "2s":
            reasons.append("↕ последовательная схема — увеличен напор")

        results.append(PumpCandidate(
            pump=pump,
            working_point=wp,  # округление только в представлении, не в сохранённом пересечении
            score=score,
            h_excess_pct=round(h_excess, 1),
            q_ratio=round(q_ratio, 2),
            npsh_ok=npsh_ok,
            npshr_at_working_point=(
                round(npshr_at_wp, 2) if npshr_at_wp is not None else None
            ),
            reasons=reasons,
            eff_curve=eff_curve,
            head_at_design=duty.head_at_design,
        ))

    results.sort(key=lambda r: r.score, reverse=True)

    return PumpResult(
        # Не округляем параметры до отрисовки: это нарушало привязку Qрасч/Hрасч.
        q_design=data.q_design_m3h,
        h_required=hp,
        h_geom=h_geom,
        h_stat=h_stat,
        k_sys=k_sys,
        candidates=results[:3],
        curve_kind=curve_kind,
        notes=notes + intersection_notes + ([
            "Рабочая точка не подтверждена; требуется характеристика в нужном диапазоне "
            "либо отдельный расчёт регулирования."
        ] if not results and intersection_notes else [
            "В каталоге нет подтверждённого кандидата для полной расчётной пары Q/H; "
            "уменьшать требуемые расход или напор под каталог нельзя."
        ] if not results else []),
    )

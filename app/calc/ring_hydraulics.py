# -*- coding: utf-8 -*-
"""
app/calc/ring_hydraulics.py — увязка одного кольца В2 методом Хантера-Кросса (v3).

Hydraulic Engine v3 MVP. Топология (жёстко зафиксирована):
  • ровно один независимый цикл в графе;
  • ровно один активный источник в узле кольца;
  • все ПК — вне кольца, на тупиковых стояках/ветвях, подключённых к узлам кольца;
  • на участках кольца нет ПК и промежуточных отборов;
  • штатный режим одного активного ввода.

Смысл кольца — резервирование: при аварии на участке ПК питается по второму
плечу; два ввода дают запасной источник. В v3 считается ШТАТНЫЙ режим (один
активный ввод, оба плеча в работе). Аварийный режим и второй ввод — см. future
scope ниже (не реализовано, чтобы не выдумывать).

Метод Хантера-Кросса для потерь h = A·L_eff·Q²:
  невязка по контуру   Δh = Σ (A·L_eff·Q·|Q|)      (Q со знаком по обходу)
  поправка расхода     ΔQ = −Δh / (2·Σ A·L_eff·|Q|)
  Q_i ← Q_i + ΔQ  для всех участков кольца, до |Δh| < ε.

================================ FUTURE SCOPE ================================
НЕ реализовано в v3 (следующий слой поверх того же аппарата):
  • MultiSourceLoopProblem — основной + резервный ввод (два граничных условия);
  • сценарий отказа участка / плеча кольца (аварийный режим);
  • проверка подачи от второго ввода, живучесть сети;
  • сравнение нормального и аварийного режимов.
=============================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.calc.fire_hydraulics import PipeSegment


# ============================================================
# ВХОДНАЯ ЗАДАЧА КОЛЬЦА (агрегированная, не «сеть вообще»)
# ============================================================

@dataclass
class SingleLoopProblem:
    """Агрегированная задача одного кольца для солвера Кросса.

    source_node: узел активного ввода (на кольце).
    loop_nodes: узлы кольца в порядке обхода (замкнутый контур).
    loop_segments: участки кольца, упорядоченные по обходу (между соседними
        loop_nodes). len(loop_segments) == len(loop_nodes).
    node_demands: узловой отбор {node: Q_л/с} — суммарный расход тупиковых
        ветвей/стояков, висящих на узле кольца в расчётном сценарии.
    """
    source_node: str
    loop_nodes: List[str]
    loop_segments: List[PipeSegment]
    node_demands: Dict[str, float]

    def validate(self) -> List[str]:
        problems: List[str] = []
        n = len(self.loop_nodes)
        if n < 3:
            problems.append("кольцо должно иметь ≥3 узла")
        if len(self.loop_segments) != n:
            problems.append(f"участков кольца ({len(self.loop_segments)}) должно быть "
                            f"столько же, сколько узлов ({n})")
        if self.source_node not in self.loop_nodes:
            problems.append(f"источник {self.source_node} не на кольце")
        # баланс: суммарный отбор должен подаваться источником (проверка замкнутости)
        total_demand = sum(self.node_demands.get(nd, 0.0) for nd in self.loop_nodes)
        if total_demand <= 0:
            problems.append("суммарный узловой отбор кольца = 0 (нет расхода)")
        # участки должны соединять соседние узлы обхода
        for i, seg in enumerate(self.loop_segments):
            a = self.loop_nodes[i]
            b = self.loop_nodes[(i + 1) % n]
            ends = {seg.from_node, seg.to_node}
            if ends != {a, b}:
                problems.append(f"участок {seg.segment_id} не соединяет соседние "
                                f"узлы обхода {a}–{b} (а соединяет {ends})")
        return problems


# ============================================================
# РЕЗУЛЬТАТ УВЯЗКИ
# ============================================================

@dataclass
class RingSegmentFlow:
    """Расход и потери на участке кольца после увязки. Q со знаком по обходу:
    +Q — по направлению обхода, −Q — против."""
    segment_id: str
    from_node: str
    to_node: str
    flow_lps: float               # знаковый расход по обходу
    abs_flow_lps: float           # модуль (физический расход участка)
    head_loss_m: float            # знаковые потери (A·L_eff·Q·|Q|)


@dataclass
class RingSolveResult:
    """Итог увязки кольца методом Кросса."""
    converged: bool
    iterations: int
    final_residual_m: float                       # |Δh| на выходе
    segments: List[RingSegmentFlow] = field(default_factory=list)
    node_head_offset_m: Dict[str, float] = field(default_factory=dict)  # потери от источника до узла
    warnings: List[str] = field(default_factory=list)


# ============================================================
# НАЧАЛЬНОЕ РАСПРЕДЕЛЕНИЕ
# ============================================================

def _initial_distribution(problem: SingleLoopProblem) -> List[float]:
    """Начальное распределение расхода по участкам кольца (по обходу, знаковое).

    Источник подаёт суммарный отбор. Идём по обходу от источника, накапливая
    оставшийся расход после каждого узлового отбора. Это корректное начальное
    приближение, удовлетворяющее узловым балансам (Кросс дальше увяжет напоры).
    """
    n = len(problem.loop_nodes)
    total = sum(problem.node_demands.get(nd, 0.0) for nd in problem.loop_nodes)
    src_idx = problem.loop_nodes.index(problem.source_node)

    # половина суммарного расхода уходит в каждое плечо от источника — базовое
    # приближение; знак «+» по направлению обхода.
    flows = [0.0] * n
    carried = total / 2.0
    # обход по направлению loop_nodes начиная от источника
    for step in range(n):
        seg_i = (src_idx + step) % n
        flows[seg_i] = carried
        # после прохождения узла (конца участка) вычитаем его отбор
        next_node = problem.loop_nodes[(src_idx + step + 1) % n]
        carried -= problem.node_demands.get(next_node, 0.0)
    return flows


# ============================================================
# СОЛВЕР ХАНТЕРА-КРОССА
# ============================================================

def solve_single_loop(
    problem: SingleLoopProblem,
    *,
    tolerance_m: float = 1e-4,
    max_iterations: int = 100,
) -> RingSolveResult:
    """Увязка одного кольца методом Хантера-Кросса для h = A·L_eff·Q².

    Возвращает знаковые расходы по участкам (по обходу), потери и смещения напора
    по узлам относительно источника. converged=False, если не сошлось за
    max_iterations.
    """
    problems = problem.validate()
    if problems:
        return RingSolveResult(converged=False, iterations=0, final_residual_m=0.0,
                               warnings=["невалидная задача кольца: " + "; ".join(problems)])

    segs = problem.loop_segments
    n = len(segs)
    Q = _initial_distribution(problem)

    residual = 0.0
    it = 0
    for it in range(1, max_iterations + 1):
        # невязка по контуру и знаменатель поправки
        numer = 0.0   # Σ A·L_eff·Q·|Q|  (знаковая сумма потерь по обходу)
        denom = 0.0   # Σ 2·A·L_eff·|Q|
        for i, seg in enumerate(segs):
            k = seg.A * seg.effective_length_m
            numer += k * Q[i] * abs(Q[i])
            denom += 2.0 * k * abs(Q[i])
        residual = abs(numer)
        if denom < 1e-12:
            break
        dQ = -numer / denom
        for i in range(n):
            Q[i] += dQ
        if residual < tolerance_m:
            break

    # финальные потери по участкам (знаковые)
    seg_flows: List[RingSegmentFlow] = []
    for i, seg in enumerate(segs):
        k = seg.A * seg.effective_length_m
        hl = k * Q[i] * abs(Q[i])
        seg_flows.append(RingSegmentFlow(
            segment_id=seg.segment_id, from_node=seg.from_node, to_node=seg.to_node,
            flow_lps=Q[i], abs_flow_lps=abs(Q[i]), head_loss_m=hl))

    # смещение напора по узлам относительно источника: идём по обходу, накапливая
    # потери |h| по направлению фактического течения.
    node_offset: Dict[str, float] = {problem.source_node: 0.0}
    src_idx = problem.loop_nodes.index(problem.source_node)
    cum = 0.0
    for step in range(n):
        seg_i = (src_idx + step) % n
        # потеря напора вдоль участка по направлению обхода = A·L·Q·|Q| (со знаком)
        cum += abs(seg_flows[seg_i].head_loss_m) * (1 if Q[seg_i] >= 0 else 1)
        node = problem.loop_nodes[(src_idx + step + 1) % n]
        if node not in node_offset:
            node_offset[node] = cum

    converged = residual < tolerance_m
    warns = [] if converged else [
        f"увязка не сошлась за {max_iterations} итераций (невязка {residual:.2e} м)"]
    return RingSolveResult(
        converged=converged, iterations=it, final_residual_m=residual,
        segments=seg_flows, node_head_offset_m=node_offset, warnings=warns)


# ============================================================
# ПОСТРОЕНИЕ ЗАДАЧИ КОЛЬЦА ИЗ РАСХОДОВ СТОЯКОВ (шаг 1 постановки)
# ============================================================

def build_loop_problem(
    source_node: str,
    loop_nodes: List[str],
    loop_segments: List[PipeSegment],
    branch_demands_by_node: Dict[str, float],
) -> SingleLoopProblem:
    """Собирает SingleLoopProblem: узловые отборы = суммарный расход тупиковых
    ветвей, висящих на узле (шаг 1 — «сначала считаем тупиковые ветви»).

    branch_demands_by_node: {узел кольца: Σ расходов стояков из этого узла, л/с}.
    """
    demands = {nd: float(branch_demands_by_node.get(nd, 0.0)) for nd in loop_nodes}
    return SingleLoopProblem(
        source_node=source_node, loop_nodes=loop_nodes,
        loop_segments=loop_segments, node_demands=demands)


def _example() -> None:
    from app.calc.fire_hydraulics import PipeSegment
    # кольцо из 4 узлов R0(ввод)-R1-R2-R3, стояки висят на R1 (2.5) и R2 (2.6)
    segs = [
        PipeSegment("L01", "R0", "R1", length_m=20, A=0.002, equiv_length_m=2),
        PipeSegment("L12", "R1", "R2", length_m=25, A=0.002, equiv_length_m=2),
        PipeSegment("L23", "R2", "R3", length_m=20, A=0.002, equiv_length_m=2),
        PipeSegment("L30", "R3", "R0", length_m=25, A=0.002, equiv_length_m=2),
    ]
    problem = build_loop_problem(
        source_node="R0", loop_nodes=["R0", "R1", "R2", "R3"],
        loop_segments=segs, branch_demands_by_node={"R1": 2.5, "R2": 2.6})
    res = solve_single_loop(problem)
    print(f"сошлось: {res.converged} за {res.iterations} итер, невязка {res.final_residual_m:.2e} м")
    for s in res.segments:
        print(f"  {s.segment_id}: Q={s.flow_lps:+.3f} л/с (|Q|={s.abs_flow_lps:.3f}), "
              f"потери {s.head_loss_m:+.4f} м")
    print("смещение напора по узлам:", {k: round(v, 4) for k, v in res.node_head_offset_m.items()})
    # проверка: невязка по контуру ≈ 0
    total = sum(s.head_loss_m for s in res.segments)
    print(f"невязка Σh по контуру: {total:.2e} м (должна быть ≈0)")


if __name__ == "__main__":
    _example()


# ============================================================
# ШАГ 3: ПОЛНЫЙ ПУТЬ ДО ПК (кольцо + тупиковый стояк)
# ============================================================

@dataclass
class BranchToPK:
    """Тупиковая ветвь/стояк от узла кольца до ПК (расчётный сценарий).

    attach_node: узел кольца, откуда выходит ветвь.
    segments: участки ветви по порядку от кольца к ПК.
    flow_lps: расход ветви (расход ПК/ПК-ов на ней в сценарии).
    cabinet_id: ПК на конце ветви.
    cabinet_head_m: требуемый напор у клапана ПК (из табл. 7.3), м.
    cabinet_elevation_m: отметка ПК.
    source_elevation_m: отметка источника (ввода на кольце).
    """
    attach_node: str
    segments: List[PipeSegment]
    flow_lps: float
    cabinet_id: str
    cabinet_head_m: float
    cabinet_elevation_m: float
    source_elevation_m: float = 0.0


@dataclass
class PKRequiredHead:
    """Требуемый напор на источнике для ПК, питаемого через кольцо."""
    cabinet_id: str
    attach_node: str
    ring_loss_m: float           # потери по кольцу до узла подключения
    branch_loss_m: float         # потери по тупиковой ветви
    geodesic_lift_m: float       # Δz = отметка ПК − отметка источника
    cabinet_head_m: float        # H_ПК (табл. 7.3)
    required_head_at_source_m: float   # сумма


def required_head_via_ring(
    ring_result: RingSolveResult,
    branch: BranchToPK,
) -> PKRequiredHead:
    """Шаг 3: H_треб = H_ПК + Δz + h_кольца(до узла) + h_ветви.

    h_кольца — из node_head_offset_m увязанного кольца;
    h_ветви — по A·L_eff·Q² с расходом ветви (тупик: расход известен).
    """
    ring_loss = ring_result.node_head_offset_m.get(branch.attach_node)
    if ring_loss is None:
        raise ValueError(f"узел {branch.attach_node} не найден в результате увязки кольца")

    branch_loss = 0.0
    for seg in branch.segments:
        branch_loss += seg.A * seg.effective_length_m * (branch.flow_lps ** 2)

    dz = branch.cabinet_elevation_m - branch.source_elevation_m
    total = branch.cabinet_head_m + dz + ring_loss + branch_loss
    return PKRequiredHead(
        cabinet_id=branch.cabinet_id, attach_node=branch.attach_node,
        ring_loss_m=ring_loss, branch_loss_m=branch_loss,
        geodesic_lift_m=dz, cabinet_head_m=branch.cabinet_head_m,
        required_head_at_source_m=total)


def dictating_pk_via_ring(
    ring_result: RingSolveResult,
    branches: List[BranchToPK],
) -> Tuple[Optional[PKRequiredHead], List[PKRequiredHead]]:
    """Диктующий ПК на кольцевой сети: максимум требуемого напора по всем ветвям.
    Возвращает (диктующий, все)."""
    heads = [required_head_via_ring(ring_result, b) for b in branches]
    if not heads:
        return None, []
    dictating = max(heads, key=lambda h: h.required_head_at_source_m)
    return dictating, heads

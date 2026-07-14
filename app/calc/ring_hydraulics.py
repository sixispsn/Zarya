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


# ============================================================
# ИНТЕГРАЦИЯ С КОНВЕЙРОМ: сеть → кольцо+ветви → section-формат
# ============================================================
# Мост, позволяющий solve_fire_hydraulics_scenario принимать кольцевую сеть:
# находит контур, раскладывает сеть на кольцо + тупиковые ветви, гонит увязку
# Кросса и отдаёт результат в ЕДИНОМ section-формате (SectionFlow) — diameter
# audit, отчёт и гидролист работают с ним без единой правки.

from app.calc.fire_hydraulics import (
    FireNetwork, FireCabinetNode, SectionFlow, NetworkMode, velocity_mps,
    NORMATIVE_VELOCITY_LIMIT_MPS, DESIGN_VELOCITY_TARGET_MPS,
    STEEL_INNER_DIAMETER_MM,
)


def find_single_cycle(net: FireNetwork) -> Optional[Tuple[List[str], List[PipeSegment]]]:
    """Находит единственный цикл графа: (узлы по обходу, участки по обходу).
    None, если граф ацикличен или циклов больше одного (v3 = ровно одно кольцо)."""
    # число независимых циклов = E - V + C (cyclomatic number)
    nodes = set(net.nodes)
    edges = [(s.from_node, s.to_node, s) for s in net.segments
             if s.from_node in nodes and s.to_node in nodes]
    # компоненты связности
    parent = {n: n for n in nodes}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    comp_edges_extra = 0
    for a, b, _ in edges:
        ra, rb = find(a), find(b)
        if ra == rb:
            comp_edges_extra += 1
        else:
            parent[ra] = rb
    if comp_edges_extra != 1:
        return None   # 0 циклов (дерево) или >1 (не наш случай)

    # ищем сам цикл DFS-ом с отслеживанием пути
    adj: Dict[str, List[Tuple[str, PipeSegment]]] = {n: [] for n in nodes}
    for a, b, seg in edges:
        adj[a].append((b, seg)); adj[b].append((a, seg))

    visited: Dict[str, bool] = {}
    stack: List[Tuple[str, Optional[str], Optional[PipeSegment]]] = []
    path_nodes: List[str] = []
    path_segs: List[PipeSegment] = []

    def dfs(cur: str, prev_node: Optional[str], via: Optional[PipeSegment]):
        visited[cur] = True
        path_nodes.append(cur)
        if via is not None:
            path_segs.append(via)
        for nb, seg in adj[cur]:
            if seg is via:
                continue
            if not visited.get(nb):
                res = dfs(nb, cur, seg)
                if res:
                    return res
            elif nb in path_nodes:
                # цикл найден: от nb до конца path_nodes
                i = path_nodes.index(nb)
                cyc_nodes = path_nodes[i:]
                cyc_segs = path_segs[i:] + [seg]
                return (cyc_nodes, cyc_segs)
        path_nodes.pop()
        if via is not None:
            path_segs.pop()
        return None

    for start in nodes:
        if not visited.get(start):
            res = dfs(start, None, None)
            if res:
                return res
    return None


@dataclass
class RingNetworkDecomposition:
    """Разбор сети на кольцо + тупиковые ветви."""
    loop_nodes: List[str]
    loop_segments: List[PipeSegment]
    branches: List[BranchToPK]                 # ветви с ПК
    branch_demands_by_node: Dict[str, float]   # узловые отборы
    problems: List[str] = field(default_factory=list)


def decompose_ring_network(
    net: FireNetwork,
    active_cabinets: List[FireCabinetNode],
    flows_by_cabinet: Dict[str, float],
    heads_by_cabinet: Dict[str, float],
) -> RingNetworkDecomposition:
    """Раскладывает сеть с одним кольцом: контур + тупиковые ветви от узлов
    кольца до активных ПК. Проверяет топологию v3 (источник на кольце,
    ПК вне кольца)."""
    problems: List[str] = []
    cyc = find_single_cycle(net)
    if cyc is None:
        return RingNetworkDecomposition([], [], [], {}, ["сеть не содержит ровно одного кольца"])
    loop_nodes, loop_segs = cyc
    loop_node_set = set(loop_nodes)
    loop_seg_ids = {s.segment_id for s in loop_segs}

    if net.source.node_id not in loop_node_set:
        problems.append(f"источник {net.source.node_id} не на кольце (топология v3)")

    src_elev = net.nodes[net.source.node_id].elevation_m
    adj = net.adjacency()
    branches: List[BranchToPK] = []
    demands: Dict[str, float] = {}

    for cab in active_cabinets:
        if cab.node_id in loop_node_set:
            problems.append(f"ПК {cab.cabinet_id} на участке кольца — топология v3 "
                            "требует ПК на тупиковых ветвях")
            continue
        # путь от ПК до ближайшего узла кольца (BFS по не-кольцевым участкам)
        from collections import deque
        q = deque([cab.node_id]); prev: Dict[str, Tuple[str, PipeSegment]] = {}
        seen = {cab.node_id}; attach = None
        while q:
            cur = q.popleft()
            if cur in loop_node_set:
                attach = cur; break
            for nb, seg in adj.get(cur, []):
                if seg.segment_id in loop_seg_ids or nb in seen:
                    continue
                seen.add(nb); prev[nb] = (cur, seg); q.append(nb)
        if attach is None:
            problems.append(f"ПК {cab.cabinet_id}: нет пути до кольца")
            continue
        # восстановить участки ветви от кольца к ПК
        segs: List[PipeSegment] = []
        node = attach
        while node != cab.node_id:
            p, s = prev[node]; segs.append(s); node = p
        # segs идут от кольца к ПК — то, что нужно BranchToPK
        flow = flows_by_cabinet.get(cab.cabinet_id, 0.0)
        branches.append(BranchToPK(
            attach_node=attach, segments=segs, flow_lps=flow,
            cabinet_id=cab.cabinet_id,
            cabinet_head_m=heads_by_cabinet.get(cab.cabinet_id, 0.0),
            cabinet_elevation_m=net.nodes[cab.node_id].elevation_m,
            source_elevation_m=src_elev))
        demands[attach] = demands.get(attach, 0.0) + flow

    return RingNetworkDecomposition(loop_nodes, loop_segs, branches, demands, problems)


@dataclass
class RingScenarioOutcome:
    """Результат кольцевого сценария в едином формате конвейра."""
    required_head_at_source_m: float
    total_flow_lps: float
    dictating_cabinet_id: str
    sections: List[SectionFlow]
    ring_result: RingSolveResult
    per_pk: List[PKRequiredHead]
    warnings: List[str] = field(default_factory=list)


def solve_ring_scenario(
    net: FireNetwork,
    active_cabinets: List[FireCabinetNode],
    flows_by_cabinet: Dict[str, float],
    heads_by_cabinet: Dict[str, float],
    mode: NetworkMode = NetworkMode.PURE_FIRE,
) -> Optional[RingScenarioOutcome]:
    """Кольцевой сценарий: разбор сети → увязка Кросса → полный путь до ПК →
    sections в едином формате (аудит/отчёт/лист работают без правок)."""
    deco = decompose_ring_network(net, active_cabinets, flows_by_cabinet, heads_by_cabinet)
    if deco.problems:
        return None if not deco.loop_nodes else RingScenarioOutcome(
            0.0, 0.0, "", [], RingSolveResult(False, 0, 0.0), [],
            warnings=deco.problems)

    problem = build_loop_problem(net.source.node_id, deco.loop_nodes,
                                 deco.loop_segments, deco.branch_demands_by_node)
    ring = solve_single_loop(problem)
    if not ring.converged:
        return RingScenarioOutcome(0.0, 0.0, "", [], ring, [],
                                   warnings=ring.warnings + ["увязка кольца не сошлась"])

    dic, per_pk = dictating_pk_via_ring(ring, deco.branches)
    if dic is None:
        return RingScenarioOutcome(0.0, 0.0, "", [], ring, [],
                                   warnings=["нет ветвей с ПК"])

    # sections: кольцевые участки (расход из увязки) + ветви (тупики)
    norm_limit = NORMATIVE_VELOCITY_LIMIT_MPS[mode]
    design_limit = DESIGN_VELOCITY_TARGET_MPS[mode]
    sections: List[SectionFlow] = []

    def _mk_section(seg: PipeSegment, q_abs: float, hl: float,
                    shared: bool, serving: List[str]) -> SectionFlow:
        d_in = seg.inner_d_mm()
        v = velocity_mps(q_abs, d_in)
        return SectionFlow(
            segment_id=seg.segment_id, from_node=seg.from_node, to_node=seg.to_node,
            flow_lps=q_abs, effective_length_m=seg.effective_length_m,
            head_loss_m=abs(hl), inner_diameter_mm=d_in, velocity_mps=v,
            velocity_normative_limit_mps=norm_limit,
            velocity_normative_ok=(None if v is None else v <= norm_limit),
            velocity_design_limit_mps=design_limit,
            velocity_design_ok=(None if v is None else v <= design_limit),
            is_shared=shared, serving_cabinets=serving)

    seg_by_id = {s.segment_id: s for s in net.segments}
    all_pk = [b.cabinet_id for b in deco.branches]
    for rf in ring.segments:
        seg = seg_by_id[rf.segment_id]
        # кольцевые участки общие: несут перераспределённый расход всех ПК
        sections.append(_mk_section(seg, rf.abs_flow_lps, rf.head_loss_m,
                                    shared=True, serving=sorted(all_pk)))
    for b in deco.branches:
        for seg in b.segments:
            hl = seg.A * seg.effective_length_m * (b.flow_lps ** 2)
            sections.append(_mk_section(seg, b.flow_lps, hl,
                                        shared=False, serving=[b.cabinet_id]))
    sections.sort(key=lambda s: -s.flow_lps)

    return RingScenarioOutcome(
        required_head_at_source_m=dic.required_head_at_source_m,
        total_flow_lps=sum(flows_by_cabinet.get(c.cabinet_id, 0.0) for c in active_cabinets),
        dictating_cabinet_id=dic.cabinet_id,
        sections=sections, ring_result=ring, per_pk=per_pk,
        warnings=list(ring.warnings))


# ============================================================
# АВАРИЙНЫЕ РЕЖИМЫ КОЛЬЦА (живучесть): отказ участка
# ============================================================
# Смысл кольца — резервирование: при отказе участка вода приходит по второму
# плечу. Проверка: для каждого участка кольца по очереди выключаем его,
# оставшаяся сеть (разомкнутое кольцо = дерево) гонится тем же сценарным
# солвером; фиксируем требуемый напор. Худший отказ = максимальный напор.
#
# Границы (осознанно): один ввод (MultiSource — отдельная задача); отказы
# только участков КОЛЬЦА (отказ стояка-тупика меняет сам сценарий ПК);
# результат — справка живучести для проектировщика, не замена штатного расчёта.

@dataclass
class SegmentFailureCase:
    """Итог одного аварийного случая: отключён участок failed_segment_id."""
    failed_segment_id: str
    solved: bool                              # расчёт состоялся на остатке сети
    required_head_at_source_m: Optional[float]
    head_penalty_m: Optional[float]           # ухудшение против штатного режима
    available_head_ok: Optional[bool]
    needs_pump: Optional[bool]
    warnings: List[str] = field(default_factory=list)


@dataclass
class RingResilienceReport:
    """Сводка живучести кольца по одиночным отказам участков."""
    normal_required_head_m: float             # штатный режим (кольцо целое)
    cases: List[SegmentFailureCase] = field(default_factory=list)
    worst_case: Optional[SegmentFailureCase] = None
    all_cases_solved: bool = False
    survives_worst_case: Optional[bool] = None   # доступный напор/насос держит худшее
    survives_by_pump: bool = False               # выживание обеспечивает НАСОС, не источник

    def render_text(self) -> str:
        L = ["ПРОВЕРКА ЖИВУЧЕСТИ КОЛЬЦА (одиночный отказ участка)",
             f"Штатный режим (кольцо целое): требуемый напор "
             f"{self.normal_required_head_m:.1f} м."]
        for c in self.cases:
            if not c.solved:
                L.append(f"  отказ {c.failed_segment_id}: расчёт не состоялся "
                         f"({'; '.join(c.warnings) or 'нет решения'})")
                continue
            L.append(f"  отказ {c.failed_segment_id}: напор "
                     f"{c.required_head_at_source_m:.1f} м "
                     f"(+{c.head_penalty_m:.1f} к штатному)"
                     + ("" if c.available_head_ok is None else
                        f", источник {'держит' if c.available_head_ok else 'НЕ держит'}"))
        if self.worst_case and self.worst_case.solved:
            L.append(f"Худший отказ: {self.worst_case.failed_segment_id} — "
                     f"{self.worst_case.required_head_at_source_m:.1f} м.")
        if self.survives_worst_case is True:
            L.append("Вывод: сеть сохраняет работоспособность при любом одиночном "
                     "отказе участка кольца.")
        elif self.survives_worst_case is False:
            L.append("Вывод: при худшем отказе доступного напора НЕДОСТАТОЧНО — "
                     "требуется резерв (насос с запасом / второй ввод).")
        return "\n".join(L)


def analyze_ring_resilience(
    net,                                   # FireNetwork с кольцом (топология v3)
    required_jets: int,
    *,
    mode=None,
    scenario_filter=None,
) -> Optional[RingResilienceReport]:
    """Живучесть кольца: поочерёдный отказ каждого участка кольца.

    Для каждого отказа строится сеть без участка (разомкнутое кольцо = дерево)
    и гонится ТОТ ЖЕ сценарный солвер. Возвращает None, если сеть не кольцевая
    по v3 (нечего анализировать).
    """
    from dataclasses import replace as _dc_replace
    from app.calc.fire_hydraulics import (
        FireNetwork, NetworkMode, solve_fire_hydraulics_scenario)

    _mode = mode or NetworkMode.PURE_FIRE
    cyc = find_single_cycle(net)
    if cyc is None:
        return None
    _, loop_segs = cyc
    loop_ids = [s.segment_id for s in loop_segs]

    # штатный режим — кольцо целое (через общий солвер: увязка Кросса)
    normal = solve_fire_hydraulics_scenario(
        net, required_jets, mode=_mode, scenario_filter=scenario_filter)
    if normal.dictating_scenario is None:
        return None
    h0 = normal.required_head_at_source_m

    cases: List[SegmentFailureCase] = []
    for seg_id in loop_ids:
        cut = FireNetwork(
            nodes=dict(net.nodes),
            segments=[s for s in net.segments if s.segment_id != seg_id],
            cabinets=list(net.cabinets),
            source=net.source)
        res = solve_fire_hydraulics_scenario(
            cut, required_jets, mode=_mode, scenario_filter=scenario_filter)
        if res.dictating_scenario is None:
            cases.append(SegmentFailureCase(
                failed_segment_id=seg_id, solved=False,
                required_head_at_source_m=None, head_penalty_m=None,
                available_head_ok=None, needs_pump=None,
                warnings=list(res.warnings)))
            continue
        cases.append(SegmentFailureCase(
            failed_segment_id=seg_id, solved=True,
            required_head_at_source_m=res.required_head_at_source_m,
            head_penalty_m=res.required_head_at_source_m - h0,
            available_head_ok=res.available_head_ok,
            needs_pump=res.needs_pump,
            warnings=list(res.warnings)))

    solved = [c for c in cases if c.solved]
    worst = max(solved, key=lambda c: c.required_head_at_source_m) if solved else None
    all_solved = len(solved) == len(cases) and bool(cases)
    survives: Optional[bool] = None
    survives_by_pump = False
    if worst is not None and worst.available_head_ok is not None:
        # выжила, если все случаи решены и худший держится источником
        # (либо насос закрывает — но тогда это явно отмечается)
        survives_by_pump = (not worst.available_head_ok) and bool(worst.needs_pump)
        survives = all_solved and (worst.available_head_ok or survives_by_pump)

    return RingResilienceReport(
        normal_required_head_m=h0, cases=cases, worst_case=worst,
        all_cases_solved=all_solved, survives_worst_case=survives,
        survives_by_pump=survives_by_pump)


# ============================================================
# ДВА ВВОДА КОЛЬЦА (MultiSource, штатный режим двух активных вводов)
# ============================================================
# Обобщение Кросса на два источника: реальный контур (кольцо) + фиктивный
# контур через разность располагаемых напоров вводов (ΔH = H1 − H2).
# Поправка реального контура увязывает потери по кольцу; поправка фиктивного —
# перераспределяет ПОДАЧУ между вводами до согласования напоров:
#     невязка фиктивного контура = Σh(путь ввод1→ввод2 по кольцу) − (H1 − H2)
# Итерации обоих контуров до сходимости обеих невязок.
#
# MVP-границы: ровно два ввода, оба на узлах одного кольца; ПК на тупиках
# (как v3). Отказ ввода → выключил и решил обычной односорсной задачей.

@dataclass
class TwoSourceLoopProblem:
    """Кольцо с двумя активными вводами."""
    source1_node: str
    source1_head_m: float                # располагаемый напор ввода 1
    source2_node: str
    source2_head_m: float
    loop_nodes: List[str]                # обход кольца
    loop_segments: List[PipeSegment]     # по обходу
    node_demands: Dict[str, float]       # отборы стояков

    def validate(self) -> List[str]:
        pr: List[str] = []
        n = len(self.loop_nodes)
        if n < 3:
            pr.append("кольцо должно иметь ≥3 узла")
        if len(self.loop_segments) != n:
            pr.append("число участков должно равняться числу узлов кольца")
        for s in (self.source1_node, self.source2_node):
            if s not in self.loop_nodes:
                pr.append(f"ввод {s} не на кольце")
        if self.source1_node == self.source2_node:
            pr.append("вводы должны быть в разных узлах")
        total = sum(self.node_demands.get(nd, 0.0) for nd in self.loop_nodes)
        if total <= 0:
            pr.append("суммарный отбор кольца = 0")
        for i, seg in enumerate(self.loop_segments):
            a, b = self.loop_nodes[i], self.loop_nodes[(i + 1) % n]
            if {seg.from_node, seg.to_node} != {a, b}:
                pr.append(f"участок {seg.segment_id} не соединяет {a}–{b}")
        return pr


@dataclass
class TwoSourceSolveResult:
    converged: bool
    iterations: int
    residual_loop_m: float               # невязка реального контура
    residual_pseudo_m: float             # невязка фиктивного контура
    segments: List[RingSegmentFlow] = field(default_factory=list)
    supply1_lps: float = 0.0             # подача ввода 1
    supply2_lps: float = 0.0             # подача ввода 2
    node_head_m: Dict[str, float] = field(default_factory=dict)  # напор в узлах
    warnings: List[str] = field(default_factory=list)


def solve_two_source_loop(
    problem: TwoSourceLoopProblem,
    *,
    tolerance_m: float = 1e-4,
    max_iterations: int = 200,
) -> TwoSourceSolveResult:
    """Увязка кольца с двумя вводами (двухконтурный Кросс).

    Реальный контур: Σ(A·L·Q|Q|) по кольцу → 0.
    Фиктивный: Σh по пути ввод1→ввод2 (по обходу) − (H1−H2) → 0; его поправка
    прикладывается к участкам этого пути (перераспределение подачи вводов).
    """
    probs = problem.validate()
    if probs:
        return TwoSourceSolveResult(False, 0, 0.0, 0.0,
                                    warnings=["невалидная задача: " + "; ".join(probs)])

    nodes = problem.loop_nodes
    segs = problem.loop_segments
    n = len(segs)
    i1 = nodes.index(problem.source1_node)
    i2 = nodes.index(problem.source2_node)
    dH = problem.source1_head_m - problem.source2_head_m
    total = sum(problem.node_demands.get(nd, 0.0) for nd in nodes)

    # путь фиктивного контура: участки от ввода1 до ввода2 по направлению обхода
    pseudo_path = []
    k = i1
    while k != i2:
        pseudo_path.append(k)          # индекс участка nodes[k] → nodes[k+1]
        k = (k + 1) % n

    # начальное распределение: ввод1 подаёт всё (как односорсное), ввод2 — 0;
    # фиктивный контур перераспределит.
    base = SingleLoopProblem(problem.source1_node, nodes, segs, problem.node_demands)
    Q = _initial_distribution(base)

    def _k(i):  # сопротивление участка
        return segs[i].A * segs[i].effective_length_m

    res_loop = res_pseudo = 0.0
    it = 0
    for it in range(1, max_iterations + 1):
        # контур 1 — реальное кольцо
        numer = sum(_k(i) * Q[i] * abs(Q[i]) for i in range(n))
        denom = sum(2.0 * _k(i) * abs(Q[i]) for i in range(n))
        res_loop = abs(numer)
        if denom > 1e-12:
            dQ = -numer / denom
            for i in range(n):
                Q[i] += dQ
        # контур 2 — фиктивный (ввод1 → ввод2), невязка с учётом ΔH
        numer2 = sum(_k(i) * Q[i] * abs(Q[i]) for i in pseudo_path) - dH
        denom2 = sum(2.0 * _k(i) * abs(Q[i]) for i in pseudo_path)
        res_pseudo = abs(numer2)
        if denom2 > 1e-12:
            dQ2 = -numer2 / denom2
            for i in pseudo_path:
                Q[i] += dQ2
        if res_loop < tolerance_m and res_pseudo < tolerance_m:
            break

    # подачи вводов из узловых балансов:
    # в узле ввода: подача = Σ(уход по инцидентным участкам) − Σ(приход) + отбор
    def _supply(idx: int) -> float:
        out_seg = idx                    # участок nodes[idx] → nodes[idx+1]
        in_seg = (idx - 1) % n           # участок nodes[idx-1] → nodes[idx]
        return Q[out_seg] - Q[in_seg] + problem.node_demands.get(nodes[idx], 0.0)

    s1 = _supply(i1)
    s2 = _supply(i2)

    # напоры в узлах: от ввода1 (H1) по обходу с учётом знака потерь
    node_head: Dict[str, float] = {nodes[i1]: problem.source1_head_m}
    cum = problem.source1_head_m
    k = i1
    for _ in range(n):
        hl = _k(k) * Q[k] * abs(Q[k])
        cum -= hl                        # по направлению обхода напор падает на hl
        nxt = nodes[(k + 1) % n]
        node_head.setdefault(nxt, cum)
        k = (k + 1) % n

    seg_flows = [RingSegmentFlow(
        segment_id=segs[i].segment_id, from_node=segs[i].from_node,
        to_node=segs[i].to_node, flow_lps=Q[i], abs_flow_lps=abs(Q[i]),
        head_loss_m=_k(i) * Q[i] * abs(Q[i])) for i in range(n)]

    converged = res_loop < tolerance_m and res_pseudo < tolerance_m
    warns: List[str] = []
    if not converged:
        warns.append(f"двухконтурная увязка не сошлась за {max_iterations} итераций")
    if s1 < -1e-6 or s2 < -1e-6:
        warns.append(f"подача ввода отрицательна (S1={s1:.2f}, S2={s2:.2f}): "
                     "слабый ввод принимает воду — проверьте напоры вводов")
    # контроль: сумма подач = суммарный отбор
    if abs((s1 + s2) - total) > 1e-6:
        warns.append(f"баланс подач нарушен: S1+S2={s1+s2:.3f} ≠ отбор {total:.3f}")

    return TwoSourceSolveResult(
        converged=converged, iterations=it,
        residual_loop_m=res_loop, residual_pseudo_m=res_pseudo,
        segments=seg_flows, supply1_lps=s1, supply2_lps=s2,
        node_head_m=node_head, warnings=warns)


def solve_two_source_loop_with_check_valves(
    problem: TwoSourceLoopProblem,
    *,
    tolerance_m: float = 1e-4,
    max_iterations: int = 200,
) -> TwoSourceSolveResult:
    """Двухвводная увязка с ОБРАТНЫМИ КЛАПАНАМИ на вводах (инженерный режим).

    Реальный ввод не принимает воду обратно в сеть города. Если чистая
    двухвводная увязка даёт отрицательную подачу какого-то ввода — его
    обратный клапан закрывается, и сеть честно пересчитывается как
    ОДНОСОРСНАЯ от оставшегося ввода (с пометкой в warnings).
    """
    res = solve_two_source_loop(problem, tolerance_m=tolerance_m,
                                max_iterations=max_iterations)
    if not res.converged:
        return res
    if res.supply1_lps >= -1e-6 and res.supply2_lps >= -1e-6:
        return res   # оба подают — штатный двухвводный режим

    # реверс: закрываем слабый ввод, решаем односорсно от сильного
    strong = (problem.source1_node if res.supply1_lps > res.supply2_lps
              else problem.source2_node)
    weak = (problem.source2_node if strong == problem.source1_node
            else problem.source1_node)
    single = SingleLoopProblem(strong, problem.loop_nodes,
                               problem.loop_segments, problem.node_demands)
    sres = solve_single_loop(single, tolerance_m=tolerance_m,
                             max_iterations=max_iterations)
    total = sum(problem.node_demands.get(nd, 0.0) for nd in problem.loop_nodes)
    return TwoSourceSolveResult(
        converged=sres.converged, iterations=sres.iterations,
        residual_loop_m=sres.final_residual_m, residual_pseudo_m=0.0,
        segments=sres.segments,
        supply1_lps=(total if strong == problem.source1_node else 0.0),
        supply2_lps=(total if strong == problem.source2_node else 0.0),
        node_head_m={},   # напоры не считаем в одновводном фолбэке (offset в sres)
        warnings=sres.warnings + [
            f"обратный клапан: ввод {weak} закрыт (реверс при чистой увязке), "
            f"сеть питается только от {strong}"])


# ============================================================
# ДВУХВВОДНЫЙ СЦЕНАРИЙ ДЛЯ КОНВЕЙРА (sections-формат)
# ============================================================
# Отличие постановки от одновводной: напоры ОБОИХ вводов заданы (граничные
# условия), поэтому вопрос не «какой напор нужен на вводе», а «ДЕРЖАТ ли
# заданные вводы диктующий ПК»: фактический напор у ПК (напор узла из увязки
# − потери стояка − геодезия) сравнивается с требуемым H_ПК (табл. 7.3).

@dataclass
class TwoSourcePKCheck:
    """Проверка одного ПК при двух активных вводах."""
    cabinet_id: str
    attach_node: str
    node_head_m: float             # напор в узле кольца (из увязки)
    branch_loss_m: float
    geodesic_lift_m: float
    actual_head_at_pk_m: float     # что реально доходит до ПК
    required_head_at_pk_m: float   # H_ПК по табл. 7.3
    ok: bool
    margin_m: float                # запас (+) / дефицит (−)


@dataclass
class TwoSourceScenarioOutcome:
    """Результат двухвводного сценария в формате конвейра."""
    total_flow_lps: float
    supply1_lps: float
    supply2_lps: float
    dictating_cabinet_id: str      # ПК с минимальным запасом
    all_pk_ok: bool
    sections: List[SectionFlow]
    per_pk: List[TwoSourcePKCheck]
    solve: TwoSourceSolveResult
    warnings: List[str] = field(default_factory=list)


def solve_two_source_scenario(
    net,                                        # FireNetwork с second_source
    active_cabinets: List[FireCabinetNode],
    flows_by_cabinet: Dict[str, float],
    heads_by_cabinet: Dict[str, float],
    mode: NetworkMode = NetworkMode.PURE_FIRE,
) -> Optional[TwoSourceScenarioOutcome]:
    """Двухвводный сценарий: разбор сети → двухконтурная увязка (с клапанами)
    → проверка напора у каждого ПК → sections. None, если топология не v3."""
    deco = decompose_ring_network(net, active_cabinets, flows_by_cabinet,
                                  heads_by_cabinet)
    if deco.problems or not deco.loop_nodes:
        return None
    s1, s2 = net.source, net.second_source
    if s2 is None or s2.node_id not in deco.loop_nodes:
        return None
    if s1.available_head_m is None or s2.available_head_m is None:
        return None   # двухвводная постановка требует напоров обоих вводов

    problem = TwoSourceLoopProblem(
        source1_node=s1.node_id, source1_head_m=s1.available_head_m,
        source2_node=s2.node_id, source2_head_m=s2.available_head_m,
        loop_nodes=deco.loop_nodes, loop_segments=deco.loop_segments,
        node_demands=deco.branch_demands_by_node)
    solve = solve_two_source_loop_with_check_valves(problem)
    if not solve.converged:
        return TwoSourceScenarioOutcome(
            0.0, 0.0, 0.0, "", False, [], [], solve,
            warnings=solve.warnings + ["двухвводная увязка не сошлась"])

    src_elev = net.nodes[s1.node_id].elevation_m
    # напоры узлов: в клапанном фолбэке node_head_m пуст — достроим от offset
    node_head = dict(solve.node_head_m)
    if not node_head:
        # односорсный фолбэк: напор узла = H_сильного − потери до узла
        strong = s1 if solve.supply1_lps > 0 else s2
        base = SingleLoopProblem(strong.node_id, deco.loop_nodes,
                                 deco.loop_segments, deco.branch_demands_by_node)
        sres = solve_single_loop(base)
        node_head = {n: strong.available_head_m - off
                     for n, off in sres.node_head_offset_m.items()}

    checks: List[TwoSourcePKCheck] = []
    for b in deco.branches:
        nh = node_head.get(b.attach_node, 0.0)
        bl = sum(seg.A * seg.effective_length_m * (b.flow_lps ** 2)
                 for seg in b.segments)
        dz = b.cabinet_elevation_m - src_elev
        actual = nh - bl - dz
        checks.append(TwoSourcePKCheck(
            cabinet_id=b.cabinet_id, attach_node=b.attach_node,
            node_head_m=nh, branch_loss_m=bl, geodesic_lift_m=dz,
            actual_head_at_pk_m=actual,
            required_head_at_pk_m=b.cabinet_head_m,
            ok=(actual + 1e-9 >= b.cabinet_head_m),
            margin_m=actual - b.cabinet_head_m))

    dictating = min(checks, key=lambda c: c.margin_m) if checks else None
    if dictating is None:
        return None

    # sections в едином формате (как solve_ring_scenario)
    norm_limit = NORMATIVE_VELOCITY_LIMIT_MPS[mode]
    design_limit = DESIGN_VELOCITY_TARGET_MPS[mode]
    seg_by_id = {s.segment_id: s for s in net.segments}
    all_pk = [b.cabinet_id for b in deco.branches]
    sections: List[SectionFlow] = []

    def _mk(seg, q_abs, hl, shared, serving):
        d_in = seg.inner_d_mm()
        v = velocity_mps(q_abs, d_in)
        return SectionFlow(
            segment_id=seg.segment_id, from_node=seg.from_node, to_node=seg.to_node,
            flow_lps=q_abs, effective_length_m=seg.effective_length_m,
            head_loss_m=abs(hl), inner_diameter_mm=d_in, velocity_mps=v,
            velocity_normative_limit_mps=norm_limit,
            velocity_normative_ok=(None if v is None else v <= norm_limit),
            velocity_design_limit_mps=design_limit,
            velocity_design_ok=(None if v is None else v <= design_limit),
            is_shared=shared, serving_cabinets=serving)

    for rf in solve.segments:
        sections.append(_mk(seg_by_id[rf.segment_id], rf.abs_flow_lps,
                            rf.head_loss_m, True, sorted(all_pk)))
    for b in deco.branches:
        for seg in b.segments:
            hl = seg.A * seg.effective_length_m * (b.flow_lps ** 2)
            sections.append(_mk(seg, b.flow_lps, hl, False, [b.cabinet_id]))
    sections.sort(key=lambda s: -s.flow_lps)

    return TwoSourceScenarioOutcome(
        total_flow_lps=sum(flows_by_cabinet.get(c.cabinet_id, 0.0)
                           for c in active_cabinets),
        supply1_lps=solve.supply1_lps, supply2_lps=solve.supply2_lps,
        dictating_cabinet_id=dictating.cabinet_id,
        all_pk_ok=all(c.ok for c in checks),
        sections=sections, per_pk=checks, solve=solve,
        warnings=list(solve.warnings))

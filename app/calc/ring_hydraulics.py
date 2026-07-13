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
    if worst is not None and worst.available_head_ok is not None:
        # выжила, если все случаи решены и худший держится источником
        # (либо насос закрывает — needs_pump=True само по себе не провал)
        survives = all_solved and (worst.available_head_ok or bool(worst.needs_pump))

    return RingResilienceReport(
        normal_required_head_m=h0, cases=cases, worst_case=worst,
        all_cases_solved=all_solved, survives_worst_case=survives)

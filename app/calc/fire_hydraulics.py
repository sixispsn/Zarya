# -*- coding: utf-8 -*-
"""
app/calc/fire_hydraulics.py — гидравлический расчёт сети В2 (слой 4 архитектуры).

Отвечает на вопрос «будет ли из расставленных ПК литься нормативная струя»:
находит диктующий ПК, считает потери по трассе до источника, требуемый напор и
выдаёт вердикт о необходимости повысительной насосной установки.

Инженерные решения (заданы Антоном как ЛПР):
  1. Линейные потери — модель удельного сопротивления участка: h = A·L_eff·Q².
     Darcy-Weisbach НЕ основной метод (оставлен интерфейсом на будущее).
  2. Местные потери — через эквивалентную длину: L_eff = L + L_eq (не % надбавка).
  3. Граф сети задаётся ЯВНО на входе; солвер не строит сеть, только считает.
  4. Диктующий ПК — тот, для которого требуемый напор на источнике максимален:
     H_source,req = H_ПК + Δz + Σh.
  5. Требуемый напор у ПК (H_ПК) — из табл. 7.3 СП 10 (get_nozzle_data),
     не рассчитывается произвольной формулой.

Единицы: длины/напор — метры, расход Q — л/с, удельное сопротивление A — такое,
что A·L·Q² даёт метры (A задаётся пользователем согласованно с размерностью Q).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Protocol, Tuple

from app.data.fire_tables import get_nozzle_data


# перевод давления у клапана ПК (МПа, табл. 7.3) в напор (м вод. ст.)
MPA_TO_M = 1.0e6 / (1000.0 * 9.81)   # ≈ 101.94 м / МПа


# ============================================================
# ВХОДНОЙ ГРАФ СЕТИ В2 (задаётся явно — решение 3)
# ============================================================

@dataclass
class HydraulicNode:
    """Узел сети: id и геодезическая отметка (м)."""
    node_id: str
    elevation_m: float


@dataclass
class PipeSegment:
    """Участок трубопровода между двумя узлами.

    A: удельное сопротивление участка (для h = A·L_eff·Q²).
    length_m: геометрическая длина L.
    equiv_length_m: эквивалентная длина местных сопротивлений L_eq (решение 2).
    diameter_mm: Ду (справочно/для отчёта; на A не влияет — A уже под этот Ду).
    """
    segment_id: str
    from_node: str
    to_node: str
    length_m: float
    A: float
    equiv_length_m: float = 0.0
    diameter_mm: Optional[int] = None

    @property
    def effective_length_m(self) -> float:
        """L_eff = L + L_eq (решение 2)."""
        return self.length_m + self.equiv_length_m


@dataclass
class FireCabinetNode:
    """Пожарный кран, привязанный к узлу сети.

    dn/nozzle_mm/hose_m/jet_m — ключ в табл. 7.3 для требуемого напора/расхода.
    is_design_candidate: участвует ли ПК в поиске диктующего.
    """
    cabinet_id: str
    node_id: str
    dn: int = 50
    nozzle_mm: int = 16
    hose_m: int = 20
    jet_m: int = 6
    is_design_candidate: bool = True


@dataclass
class HydraulicSource:
    """Источник (ввод/выход насосной).

    available_head_m: доступный напор, если известен (для проверки достаточности);
        None — напор неизвестен, считаем только требуемый.
    node_id: узел подключения источника.
    """
    node_id: str
    available_head_m: Optional[float] = None


@dataclass
class FireNetwork:
    """Сеть В2 целиком (явный вход солвера)."""
    nodes: Dict[str, HydraulicNode]
    segments: List[PipeSegment]
    cabinets: List[FireCabinetNode]
    source: HydraulicSource


# ============================================================
# BACKEND ЛИНЕЙНЫХ ПОТЕРЬ (решение 1: основной — A·Leff·Q²)
# ============================================================

class HeadLossBackend(Protocol):
    """Контракт расчёта потерь на участке. Позволяет в будущем добавить
    второй backend (Darcy-Weisbach) без переписывания солвера."""
    def segment_loss(self, seg: PipeSegment, flow_lps: float) -> float:
        ...


@dataclass
class SpecificResistanceBackend:
    """Основной MVP-backend: h = A · L_eff · Q² (решение 1)."""
    def segment_loss(self, seg: PipeSegment, flow_lps: float) -> float:
        return seg.A * seg.effective_length_m * (flow_lps ** 2)


# ============================================================
# ВЫХОДНЫЕ МОДЕЛИ
# ============================================================

@dataclass
class SegmentLossRow:
    """Потери на одном участке пути к диктующему ПК."""
    segment_id: str
    from_node: str
    to_node: str
    effective_length_m: float
    flow_lps: float
    head_loss_m: float


@dataclass
class CabinetHydraulics:
    """Гидравлика одного ПК-кандидата: путь до источника и требуемый напор."""
    cabinet_id: str
    node_id: str
    required_head_at_cabinet_m: float     # H_ПК из табл. 7.3 (переведён в м)
    flow_lps: float                       # расход этого ПК (табл. 7.3)
    geodesic_lift_m: float                # Δz = отметка ПК − отметка источника
    path_head_loss_m: float               # Σh по трассе
    required_head_at_source_m: float      # H_ПК + Δz + Σh (решение 4)
    path: List[SegmentLossRow] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class HydraulicResult:
    """Итог расчёта сети В2."""
    dictating_cabinet_id: Optional[str]
    required_head_at_source_m: float
    available_head_m: Optional[float]
    available_head_ok: Optional[bool]     # None если напор источника неизвестен
    needs_pump: Optional[bool]
    per_cabinet: List[CabinetHydraulics] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ============================================================
# ПОИСК ПУТИ (граф — дерево/сеть, BFS от ПК к источнику)
# ============================================================

def _build_adjacency(net: FireNetwork) -> Dict[str, List[Tuple[str, PipeSegment]]]:
    adj: Dict[str, List[Tuple[str, PipeSegment]]] = {nid: [] for nid in net.nodes}
    for seg in net.segments:
        adj.setdefault(seg.from_node, []).append((seg.to_node, seg))
        adj.setdefault(seg.to_node, []).append((seg.from_node, seg))
    return adj


def _find_path(net: FireNetwork, start: str, goal: str
               ) -> Optional[List[PipeSegment]]:
    """Путь (список участков) от start до goal по графу. BFS — кратчайший по числу
    участков; для дерева путь единственный. Для колец берётся один из путей
    (для MVP достаточно; кольцевую оптимизацию оставляем на будущее)."""
    if start == goal:
        return []
    adj = _build_adjacency(net)
    from collections import deque
    q = deque([start])
    prev: Dict[str, Tuple[str, PipeSegment]] = {}
    seen = {start}
    while q:
        cur = q.popleft()
        for nb, seg in adj.get(cur, []):
            if nb in seen:
                continue
            seen.add(nb)
            prev[nb] = (cur, seg)
            if nb == goal:
                # восстановить путь
                path: List[PipeSegment] = []
                node = goal
                while node != start:
                    p, s = prev[node]
                    path.append(s)
                    node = p
                path.reverse()
                return path
            q.append(nb)
    return None


# ============================================================
# СОЛВЕР
# ============================================================

def _cabinet_required_head_and_flow(cab: FireCabinetNode) -> Tuple[float, float, List[str]]:
    """H_ПК (м) и расход (л/с) из табл. 7.3 (решение 5). При отсутствии ключа —
    ошибка в notes и (0,0), чтобы солвер не выдумывал напор."""
    data = get_nozzle_data(cab.dn, cab.nozzle_mm, cab.hose_m, cab.jet_m)
    if data is None:
        return 0.0, 0.0, [
            f"ПК {cab.cabinet_id}: нет строки в табл. 7.3 для "
            f"(DN{cab.dn}, ствол {cab.nozzle_mm}, рукав {cab.hose_m}, струя {cab.jet_m}). "
            "Требуемый напор не определён — проверьте параметры ПК."]
    head_m = data.p * MPA_TO_M
    return head_m, data.q, []


def solve_fire_hydraulics(
    net: FireNetwork,
    *,
    backend: Optional[HeadLossBackend] = None,
    simultaneous_flow_on_path: bool = True,
) -> HydraulicResult:
    """Гидравлический расчёт сети В2.

    Для каждого ПК-кандидата: находит путь до источника, считает Σh (A·L_eff·Q²),
    Δz и требуемый напор на источнике H_ПК+Δz+Σh. Диктующий — с максимумом (реш.4).

    simultaneous_flow_on_path: если True, по участкам пути к рассматриваемому ПК
    течёт его расход (упрощение MVP — один диктующий путь; совместная работа
    нескольких ПК на общих участках как суммарный расход — расширение на будущее).
    """
    backend = backend or SpecificResistanceBackend()
    warnings: List[str] = []
    src = net.source
    if src.node_id not in net.nodes:
        raise ValueError(f"Источник ссылается на несуществующий узел {src.node_id}")
    src_elev = net.nodes[src.node_id].elevation_m

    per_cab: List[CabinetHydraulics] = []
    candidates = [c for c in net.cabinets if c.is_design_candidate]
    if not candidates:
        warnings.append("нет ПК-кандидатов (is_design_candidate=True)")

    for cab in candidates:
        if cab.node_id not in net.nodes:
            warnings.append(f"ПК {cab.cabinet_id}: узел {cab.node_id} не найден, пропущен")
            continue
        head_cab, flow, notes = _cabinet_required_head_and_flow(cab)
        path = _find_path(net, cab.node_id, src.node_id)
        if path is None:
            warnings.append(f"ПК {cab.cabinet_id}: нет пути до источника {src.node_id}")
            continue

        rows: List[SegmentLossRow] = []
        total_loss = 0.0
        for seg in path:
            q = flow if simultaneous_flow_on_path else flow
            hl = backend.segment_loss(seg, q)
            total_loss += hl
            rows.append(SegmentLossRow(
                segment_id=seg.segment_id, from_node=seg.from_node, to_node=seg.to_node,
                effective_length_m=seg.effective_length_m, flow_lps=q, head_loss_m=hl))

        dz = net.nodes[cab.node_id].elevation_m - src_elev
        req_source = head_cab + dz + total_loss
        per_cab.append(CabinetHydraulics(
            cabinet_id=cab.cabinet_id, node_id=cab.node_id,
            required_head_at_cabinet_m=head_cab, flow_lps=flow,
            geodesic_lift_m=dz, path_head_loss_m=total_loss,
            required_head_at_source_m=req_source, path=rows, notes=notes))
        warnings.extend(notes)

    if not per_cab:
        return HydraulicResult(
            dictating_cabinet_id=None, required_head_at_source_m=0.0,
            available_head_m=src.available_head_m, available_head_ok=None,
            needs_pump=None, per_cabinet=[], warnings=warnings + ["расчёт не выполнен"])

    # диктующий ПК — максимум требуемого напора на источнике (решение 4)
    dictating = max(per_cab, key=lambda c: c.required_head_at_source_m)
    req = dictating.required_head_at_source_m

    available_ok: Optional[bool] = None
    needs_pump: Optional[bool] = None
    if src.available_head_m is not None:
        available_ok = src.available_head_m >= req
        needs_pump = not available_ok

    return HydraulicResult(
        dictating_cabinet_id=dictating.cabinet_id,
        required_head_at_source_m=req,
        available_head_m=src.available_head_m,
        available_head_ok=available_ok,
        needs_pump=needs_pump,
        per_cabinet=per_cab,
        warnings=warnings)


# ============================================================
# СЦЕНАРИЙ СОВМЕСТНОЙ РАБОТЫ ПК (вариант 2: п. 7.6 СП 10)
# ============================================================
# При N расчётных струях по общим участкам (магистраль, низ стояка) течёт
# СУММАРНЫЙ расход, потери там выше. Требуемый напор на источнике для сценария
# = max по активным ПК, где потери КАЖДОГО участка считаются по его реальному
# (агрегированному) расходу в этом сценарии, а не по расходу одного ПК.

from itertools import combinations


@dataclass
class ScenarioCabinet:
    """ПК внутри сценария: требуемый напор на источнике с учётом агрегированных
    расходов по общим участкам."""
    cabinet_id: str
    node_id: str
    required_head_at_cabinet_m: float
    flow_lps: float
    geodesic_lift_m: float
    path_head_loss_m: float
    required_head_at_source_m: float
    path: List[SegmentLossRow] = field(default_factory=list)


@dataclass
class HydraulicScenario:
    """Расчётный сценарий из N одновременно работающих ПК (шаг 1)."""
    active_cabinet_ids: List[str]
    required_head_at_source_m: float          # max по активным ПК (шаг 5)
    total_flow_lps: float                     # суммарный расход сценария
    segment_flows: Dict[str, float] = field(default_factory=dict)  # агрег. расход по участкам
    cabinets: List[ScenarioCabinet] = field(default_factory=list)


@dataclass
class ScenarioResult:
    """Итог сценарного расчёта: худший (диктующий) сценарий из N ПК."""
    dictating_scenario: Optional[HydraulicScenario]
    required_head_at_source_m: float
    available_head_m: Optional[float]
    available_head_ok: Optional[bool]
    needs_pump: Optional[bool]
    evaluated_scenarios: int = 0
    warnings: List[str] = field(default_factory=list)


def _segment_flows_for_scenario(
    net: FireNetwork,
    active: List[FireCabinetNode],
    flows: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, List[PipeSegment]]]:
    """Шаги 2-3: путь каждого активного ПК до источника + агрегация расходов.

    Возвращает (расход по каждому участку, путь по каждому ПК). Расход участка =
    сумма расходов тех активных ПК, чьи пути через него проходят.
    """
    seg_flow: Dict[str, float] = {}
    paths: Dict[str, List[PipeSegment]] = {}
    for cab in active:
        path = _find_path(net, cab.node_id, net.source.node_id)
        if path is None:
            paths[cab.cabinet_id] = []
            continue
        paths[cab.cabinet_id] = path
        for seg in path:
            seg_flow[seg.segment_id] = seg_flow.get(seg.segment_id, 0.0) + flows[cab.cabinet_id]
    return seg_flow, paths


def _evaluate_scenario(
    net: FireNetwork,
    active: List[FireCabinetNode],
    backend: HeadLossBackend,
) -> Optional[HydraulicScenario]:
    """Шаги 3-5: агрегация расходов, потери по агрегированному расходу участка,
    требуемый напор на источнике для каждого активного ПК, max по сценарию."""
    heads: Dict[str, float] = {}
    flows: Dict[str, float] = {}
    for cab in active:
        h, q, _notes = _cabinet_required_head_and_flow(cab)
        heads[cab.cabinet_id] = h
        flows[cab.cabinet_id] = q

    seg_flow, paths = _segment_flows_for_scenario(net, active, flows)
    seg_by_id = {s.segment_id: s for s in net.segments}
    src_elev = net.nodes[net.source.node_id].elevation_m

    scen_cabs: List[ScenarioCabinet] = []
    for cab in active:
        path = paths.get(cab.cabinet_id)
        if not path:
            return None  # один из ПК не связан — сценарий невалиден
        rows: List[SegmentLossRow] = []
        total_loss = 0.0
        for seg in path:
            q_seg = seg_flow[seg.segment_id]           # шаг 4: агрегированный расход участка
            hl = backend.segment_loss(seg, q_seg)
            total_loss += hl
            rows.append(SegmentLossRow(
                segment_id=seg.segment_id, from_node=seg.from_node, to_node=seg.to_node,
                effective_length_m=seg.effective_length_m, flow_lps=q_seg, head_loss_m=hl))
        dz = net.nodes[cab.node_id].elevation_m - src_elev
        req = heads[cab.cabinet_id] + dz + total_loss
        scen_cabs.append(ScenarioCabinet(
            cabinet_id=cab.cabinet_id, node_id=cab.node_id,
            required_head_at_cabinet_m=heads[cab.cabinet_id], flow_lps=flows[cab.cabinet_id],
            geodesic_lift_m=dz, path_head_loss_m=total_loss,
            required_head_at_source_m=req, path=rows))

    req_scenario = max(c.required_head_at_source_m for c in scen_cabs)  # шаг 5
    return HydraulicScenario(
        active_cabinet_ids=[c.cabinet_id for c in active],
        required_head_at_source_m=req_scenario,
        total_flow_lps=sum(flows[c.cabinet_id] for c in active),
        segment_flows=seg_flow, cabinets=scen_cabs)


def solve_fire_hydraulics_scenario(
    net: FireNetwork,
    required_jets: int,
    *,
    backend: Optional[HeadLossBackend] = None,
) -> ScenarioResult:
    """Сценарный расчёт совместной работы N=required_jets ПК (п. 7.6 СП 10).

    Перебирает все допустимые сочетания активных ПК из кандидатов, для каждого
    считает требуемый напор с агрегацией расходов по общим участкам, выбирает
    ХУДШИЙ сценарий (диктующую пару/группу). required_jets=1 сводится к одиночному
    расчёту (одна активная точка).

    Осознанное упрощение MVP: перебор всех C(k, N) сочетаний кандидатов. На
    реальных сетях В2 (десятки ПК, N=2) это подъёмно. Дополнительные нормативные
    фильтры пары (напр. «на разных стояках») можно наложить позже через отбор
    кандидатов до вызова.
    """
    backend = backend or SpecificResistanceBackend()
    warnings: List[str] = []
    if required_jets < 1:
        raise ValueError("required_jets must be >= 1")

    candidates = [c for c in net.cabinets if c.is_design_candidate]
    if len(candidates) < required_jets:
        warnings.append(f"кандидатов {len(candidates)} меньше required_jets={required_jets}; "
                        f"сценарий считается по доступным")
        required_jets = max(1, min(required_jets, len(candidates)))
    if not candidates:
        return ScenarioResult(None, 0.0, net.source.available_head_m, None, None,
                              0, warnings + ["нет ПК-кандидатов"])

    worst: Optional[HydraulicScenario] = None
    count = 0
    for combo in combinations(candidates, required_jets):
        scen = _evaluate_scenario(net, list(combo), backend)
        if scen is None:
            continue
        count += 1
        if worst is None or scen.required_head_at_source_m > worst.required_head_at_source_m:
            worst = scen

    if worst is None:
        return ScenarioResult(None, 0.0, net.source.available_head_m, None, None,
                              0, warnings + ["ни один сценарий не удалось рассчитать (нет путей?)"])

    avail = net.source.available_head_m
    ok = None if avail is None else (avail >= worst.required_head_at_source_m)
    needs_pump = None if ok is None else (not ok)
    return ScenarioResult(
        dictating_scenario=worst,
        required_head_at_source_m=worst.required_head_at_source_m,
        available_head_m=avail, available_head_ok=ok, needs_pump=needs_pump,
        evaluated_scenarios=count, warnings=warnings)


# ============================================================
# ЗАГОТОВКА ВТОРОГО BACKEND (решение 1: интерфейс на будущее)
# ============================================================

@dataclass
class DarcyWeisbachBackend:
    """Заготовка альтернативного backend (Дарси-Вейсбах). Не основной метод MVP;
    реализация оставлена на будущее, интерфейс совместим с солвером."""
    def segment_loss(self, seg: PipeSegment, flow_lps: float) -> float:
        raise NotImplementedError(
            "Darcy-Weisbach backend не реализован в MVP. Основной метод — "
            "SpecificResistanceBackend (h = A·L_eff·Q²).")


def _example() -> None:
    # ввод(0м) → магистраль → стояк вверх → диктующий ПК на 27,5 м
    net = FireNetwork(
        nodes={
            "src": HydraulicNode("src", 0.0),
            "n1": HydraulicNode("n1", 0.0),
            "n2": HydraulicNode("n2", 27.5),
        },
        segments=[
            PipeSegment("mag", "src", "n1", length_m=30.0, A=0.00246, equiv_length_m=8.0, diameter_mm=100),
            PipeSegment("riser", "n1", "n2", length_m=27.5, A=0.0110, equiv_length_m=4.0, diameter_mm=65),
        ],
        cabinets=[FireCabinetNode("PK-1", "n2", dn=50, nozzle_mm=16, hose_m=20, jet_m=6)],
        source=HydraulicSource("src", available_head_m=40.0),
    )
    r = solve_fire_hydraulics(net)
    print(f"диктующий ПК: {r.dictating_cabinet_id}")
    print(f"требуемый напор на источнике: {r.required_head_at_source_m:.1f} м")
    print(f"доступный: {r.available_head_m} м, достаточно: {r.available_head_ok}, "
          f"насос нужен: {r.needs_pump}")
    for c in r.per_cabinet:
        print(f"  {c.cabinet_id}: H_ПК={c.required_head_at_cabinet_m:.1f} + "
              f"Δz={c.geodesic_lift_m:.1f} + Σh={c.path_head_loss_m:.1f} = "
              f"{c.required_head_at_source_m:.1f} м (Q={c.flow_lps} л/с)")


if __name__ == "__main__":
    _example()

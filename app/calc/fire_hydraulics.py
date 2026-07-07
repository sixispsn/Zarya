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
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from app.data.fire_tables import get_nozzle_data


# перевод давления у клапана ПК (МПа, табл. 7.3) в напор (м вод. ст.)
MPA_TO_M = 1.0e6 / (1000.0 * 9.81)   # ≈ 101.94 м / МПа


# внутренний диаметр стальных труб В2 по Ду (мм). Скорость считается по нему,
# а не по номинальному Ду (у стали внутренний заметно отличается).
STEEL_INNER_DIAMETER_MM = {
    50: 53.0, 65: 68.0, 80: 82.5, 100: 106.0, 125: 131.0, 150: 156.0,
}


class NetworkMode(str, Enum):
    """Режим сети для проверки скорости (два уровня: hard-limit + design target)."""
    PURE_FIRE = "pure_fire"            # чистый ВПВ (В2)
    COMBINED_FIRE = "combined_fire"    # объединённый водопровод в пожарном режиме
    DOMESTIC = "domestic"             # хоз-питьевой режим (не fire solver)


# Нормативные жёсткие пределы скорости по режиму (нарушение = ошибка).
NORMATIVE_VELOCITY_LIMIT_MPS = {
    NetworkMode.PURE_FIRE: 10.0,       # чистый ВПВ
    NetworkMode.COMBINED_FIRE: 3.0,    # объединённый в пожарном режиме
    NetworkMode.DOMESTIC: 1.5,         # хоз-питьевой
}

# Проектный целевой предел (нарушение = warning; формально допустимо, но
# гидравлика становится «нервной»: потери растут, насос раздувается).
DESIGN_VELOCITY_TARGET_MPS = {
    NetworkMode.PURE_FIRE: 4.0,
    NetworkMode.COMBINED_FIRE: 3.0,
    NetworkMode.DOMESTIC: 1.5,
}


# ============================================================
# ВХОДНОЙ ГРАФ СЕТИ В2 (задаётся явно — решение 3)
# ============================================================

@dataclass
class HydraulicNode:
    """Узел сети: id и геодезическая отметка (м)."""
    node_id: str
    elevation_m: float


class ValveKind(str, Enum):
    """Тип запорной/защитной арматуры на участке В2 (влияет на L_eq)."""
    GATE = "gate"              # задвижка
    CHECK = "check"            # обратный клапан
    BUTTERFLY = "butterfly"    # дисковый затвор
    BALL = "ball"              # шаровой
    OTHER = "other"


@dataclass
class Valve:
    """Арматура на участке как объект (а не безликое число equiv_length_m).

    equiv_length_m: эквивалентная длина местного сопротивления этого клапана, м.
    На этапе 2.1 клапан ОПИСАТЕЛЬНЫЙ + отдаёт L_eq в расчёт через агрегацию на
    трубе. В 2.3 (увязка кольца) войдёт как полноценный элемент.
    """
    valve_id: str
    kind: ValveKind
    equiv_length_m: float = 0.0


@dataclass
class PipeSegment:
    """Участок трубопровода между двумя узлами.

    A: удельное сопротивление участка (для h = A·L_eff·Q²).
    length_m: геометрическая длина L.
    equiv_length_m: собственная эквивалентная длина участка L_eq (фитинги/повороты).
    valves: арматура на участке; её L_eq добавляется к effective_length_m.
    diameter_mm: Ду (справочно/для отчёта; на A не влияет — A уже под этот Ду).
    """
    segment_id: str
    from_node: str
    to_node: str
    length_m: float
    A: float
    equiv_length_m: float = 0.0
    valves: List[Valve] = field(default_factory=list)
    diameter_mm: Optional[int] = None            # Ду (номинал, для отчёта)
    inner_diameter_mm: Optional[float] = None    # внутренний Ø для скорости

    def inner_d_mm(self) -> Optional[float]:
        """Внутренний диаметр для расчёта скорости: явный inner_diameter_mm, либо
        табличный по Ду (сталь В2), либо Ду как приближение (с оговоркой в отчёте)."""
        if self.inner_diameter_mm is not None:
            return self.inner_diameter_mm
        if self.diameter_mm is not None:
            return STEEL_INNER_DIAMETER_MM.get(int(self.diameter_mm), float(self.diameter_mm))
        return None

    @property
    def valves_equiv_length_m(self) -> float:
        """Суммарная L_eq арматуры на участке."""
        return sum(v.equiv_length_m for v in self.valves)

    @property
    def effective_length_m(self) -> float:
        """L_eff = L + L_eq(участка) + L_eq(арматуры) (решение 2)."""
        return self.length_m + self.equiv_length_m + self.valves_equiv_length_m


@dataclass
class FireCabinetNode:
    """Пожарный кран, привязанный к узлу сети.

    dn/nozzle_mm/hose_m/jet_m — ключ в табл. 7.3 для требуемого напора/расхода.
    is_design_candidate: участвует ли ПК в поиске диктующего.
    riser_id: к какому стояку относится ПК (проектный объект). Источник истины
        для нормативных ограничений типа «разные стояки» (п. 6.2.2). None
        допустим для старых кейсов; при строгом фильтре None → пара недопустима.
    """
    cabinet_id: str
    node_id: str
    dn: int = 50
    nozzle_mm: int = 16
    hose_m: int = 20
    jet_m: int = 6
    is_design_candidate: bool = True
    riser_id: Optional[str] = None


class SourceKind(str, Enum):
    """Тип источника водоснабжения В2.

    CITY_MAIN: городская сеть под напором — даёт H_город (может быть неизвестен).
    RESERVOIR / POND / WELL: напора нет, есть уровень воды; насос забирает со
        всасывающей линии и создаёт весь напор + подъём/потери всаса.
    """
    CITY_MAIN = "city_main"
    RESERVOIR = "reservoir"
    POND = "pond"
    WELL = "well"


@dataclass
class HydraulicSource:
    """Источник водоснабжения В2 (ввод от города или водозабор из резервуара/водоёма).

    node_id: узел подключения источника (для сети — ввод; для резервуара — ось
        насоса / точка нагнетания).
    kind: тип источника (см. SourceKind).

    Для CITY_MAIN:
      available_head_m: гарантированный напор города, м. None → считаем 0
        (город часто не гарантирует напор на пожарный расход — насос на весь H_треб).

    Для RESERVOIR/POND/WELL (напора нет, забор насосом со всаса):
      water_level_m: отметка уровня воды (для резервуара — верхний уровень
        пожарного объёма, п. 12.20; для водоёма — минимальный уровень).
      suction_head_loss_m: потери всасывающей линии, м (упрощённо одним числом на
        этапе 2.1; детальный участок графа — на 2.2).
      Геодезия всаса (подъём от уровня воды до оси насоса) учитывается через
      отметку узла source.node_id относительно water_level_m.
    """
    node_id: str
    kind: SourceKind = SourceKind.CITY_MAIN
    available_head_m: Optional[float] = None
    water_level_m: Optional[float] = None
    suction_head_loss_m: float = 0.0


@dataclass
class FireNetwork:
    """Сеть В2 целиком (явный вход солвера).

    На этапе 2.1 — полноценный граф-объект: валидирует связность и ссылочную
    целостность, даёт доступ к соседям/рёбрам узла. Не импортирует расчётную
    часть — граф описывает сеть, солвер её считает (развязка под будущий вынос
    в hydraulic_graph.py).
    """
    nodes: Dict[str, HydraulicNode]
    segments: List[PipeSegment]
    cabinets: List[FireCabinetNode]
    source: HydraulicSource

    def validate(self) -> List[str]:
        """Проверяет ссылочную целостность и связность. Возвращает список проблем
        (пустой = сеть корректна). Не бросает исключение — диагностика, а не отказ."""
        problems: List[str] = []
        node_ids = set(self.nodes)

        # ссылочная целостность рёбер
        for seg in self.segments:
            if seg.from_node not in node_ids:
                problems.append(f"участок {seg.segment_id}: узел from_node={seg.from_node} не найден")
            if seg.to_node not in node_ids:
                problems.append(f"участок {seg.segment_id}: узел to_node={seg.to_node} не найден")
        # ПК и источник
        for cab in self.cabinets:
            if cab.node_id not in node_ids:
                problems.append(f"ПК {cab.cabinet_id}: узел {cab.node_id} не найден")
        if self.source.node_id not in node_ids:
            problems.append(f"источник: узел {self.source.node_id} не найден")

        # висячие узлы (не участвуют ни в одном ребре)
        used = {n for seg in self.segments for n in (seg.from_node, seg.to_node)}
        for nid in node_ids:
            if nid not in used and nid != self.source.node_id:
                problems.append(f"узел {nid} висячий (не связан ни с одним участком)")

        # связность: все ПК достижимы от источника
        if self.source.node_id in node_ids:
            reachable = self._reachable_from(self.source.node_id)
            for cab in self.cabinets:
                if cab.node_id in node_ids and cab.node_id not in reachable:
                    problems.append(f"ПК {cab.cabinet_id}: недостижим от источника")
        return problems

    def _reachable_from(self, start: str) -> set:
        adj = self.adjacency()
        seen = {start}
        stack = [start]
        while stack:
            cur = stack.pop()
            for nb, _seg in adj.get(cur, []):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        return seen

    def adjacency(self) -> Dict[str, List[Tuple[str, "PipeSegment"]]]:
        """Список смежности: узел → [(сосед, участок)]. Граф неориентированный."""
        adj: Dict[str, List[Tuple[str, PipeSegment]]] = {nid: [] for nid in self.nodes}
        for seg in self.segments:
            adj.setdefault(seg.from_node, []).append((seg.to_node, seg))
            adj.setdefault(seg.to_node, []).append((seg.from_node, seg))
        return adj

    def neighbors(self, node_id: str) -> List[str]:
        """Соседние узлы данного узла."""
        return [nb for nb, _ in self.adjacency().get(node_id, [])]

    def segments_at(self, node_id: str) -> List["PipeSegment"]:
        """Участки, инцидентные узлу."""
        return [seg for seg in self.segments
                if seg.from_node == node_id or seg.to_node == node_id]

    def is_acyclic(self) -> bool:
        """True, если сеть — дерево/лес (нет колец). Этап 2.2 работает только на
        ацикличной сети; кольцо → отдельная увязка (этап 2.3)."""
        # неориентированный граф ацикличен, если рёбер = узлов − компоненты связности
        parent: Dict[str, str] = {n: n for n in self.nodes}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for seg in self.segments:
            if seg.from_node not in parent or seg.to_node not in parent:
                continue  # висячие ссылки ловит validate()
            ra, rb = find(seg.from_node), find(seg.to_node)
            if ra == rb:
                return False  # ребро замыкает цикл
            parent[ra] = rb
        return True


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
class SectionFlow:
    """Section-level результат: расход/скорость/потери по участку в сценарии (2.2).

    Двухуровневая проверка скорости (нормативный hard-limit + проектный target):
      velocity_normative_ok = ошибка при нарушении (по режиму сети);
      velocity_design_ok = warning при нарушении (рекомендуемый потолок).
    """
    segment_id: str
    from_node: str
    to_node: str
    flow_lps: float                       # Q участка (агрегированный)
    effective_length_m: float
    head_loss_m: float
    inner_diameter_mm: Optional[float]
    velocity_mps: Optional[float]
    velocity_normative_limit_mps: float
    velocity_normative_ok: Optional[bool]
    velocity_design_limit_mps: float
    velocity_design_ok: Optional[bool]
    is_shared: bool                       # участок несёт расход >1 активного ПК
    serving_cabinets: List[str] = field(default_factory=list)  # ПК на этом участке
    diameter_is_nominal: bool = False     # скорость по Ду (нет внутреннего Ø)


def velocity_mps(flow_lps: float, inner_diameter_mm: Optional[float]) -> Optional[float]:
    """Скорость воды в трубе, м/с. Q [л/с], d [мм] → v [м/с].
    v = (Q·10⁻³) / (π·(d·10⁻³/2)²)."""
    if inner_diameter_mm is None or inner_diameter_mm <= 0:
        return None
    import math
    area_m2 = math.pi * (inner_diameter_mm * 1e-3 / 2.0) ** 2
    return (flow_lps * 1e-3) / area_m2


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

def _find_path(net: FireNetwork, start: str, goal: str
               ) -> Optional[List[PipeSegment]]:
    """Путь (список участков) от start до goal по графу. BFS — кратчайший по числу
    участков; для дерева путь единственный. Для колец берётся один из путей
    (для MVP достаточно; кольцевую увязку — на этап 2.3)."""
    if start == goal:
        return []
    adj = net.adjacency()
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
    sections: List["SectionFlow"] = field(default_factory=list)  # section-level (2.2)


@dataclass
class PumpDutyPoint:
    """Требуемая рабочая точка повысительного насоса В2 (обратный расчёт).

    required_head_m: напор, который должен развивать насос (недостача до H_треб
        для сети; весь H_треб + подъём/потери всаса для резервуара/водоёма).
    flow_lps: расход в рабочей точке = Q_пож диктующего сценария.
    source_kind: тип источника, от которого считался напор.
    suction_lift_m: геодезический подъём всаса (резервуар/водоём), 0 для сети.
    notes: пояснения к расчёту рабочей точки.
    """
    required_head_m: float
    flow_lps: float
    source_kind: "SourceKind"
    suction_lift_m: float = 0.0
    notes: List[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    """Итог сценарного расчёта: худший (диктующий) сценарий из N ПК."""
    dictating_scenario: Optional[HydraulicScenario]
    required_head_at_source_m: float
    available_head_m: Optional[float]
    available_head_ok: Optional[bool]
    needs_pump: Optional[bool]
    pump_duty: Optional[PumpDutyPoint] = None    # рабочая точка насоса (если нужен)
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


def _build_sections(
    net: FireNetwork,
    seg_flow: Dict[str, float],
    paths: Dict[str, List["PipeSegment"]],
    backend: HeadLossBackend,
    mode: NetworkMode,
) -> List[SectionFlow]:
    """Section-level результат по всем участкам, несущим расход в сценарии.
    Для каждого: Q, v (по внутреннему Ø), потери, две проверки скорости,
    признак общего участка и список обслуживаемых ПК."""
    # какие ПК проходят через каждый участок
    serving: Dict[str, List[str]] = {}
    for cab_id, path in paths.items():
        for seg in path:
            serving.setdefault(seg.segment_id, []).append(cab_id)

    seg_by_id = {s.segment_id: s for s in net.segments}
    norm_limit = NORMATIVE_VELOCITY_LIMIT_MPS[mode]
    design_limit = DESIGN_VELOCITY_TARGET_MPS[mode]

    sections: List[SectionFlow] = []
    for seg_id, q in seg_flow.items():
        seg = seg_by_id[seg_id]
        d_in = seg.inner_d_mm()
        v = velocity_mps(q, d_in)
        cabs = sorted(set(serving.get(seg_id, [])))
        sections.append(SectionFlow(
            segment_id=seg_id, from_node=seg.from_node, to_node=seg.to_node,
            flow_lps=q, effective_length_m=seg.effective_length_m,
            head_loss_m=backend.segment_loss(seg, q),
            inner_diameter_mm=d_in, velocity_mps=v,
            velocity_normative_limit_mps=norm_limit,
            velocity_normative_ok=(None if v is None else v <= norm_limit),
            velocity_design_limit_mps=design_limit,
            velocity_design_ok=(None if v is None else v <= design_limit),
            is_shared=len(cabs) > 1, serving_cabinets=cabs,
            diameter_is_nominal=(seg.inner_diameter_mm is None and seg.diameter_mm is not None
                                 and int(seg.diameter_mm) not in STEEL_INNER_DIAMETER_MM),
        ))
    sections.sort(key=lambda s: -s.flow_lps)   # сначала магистрали (больший расход)
    return sections


def _evaluate_scenario(
    net: FireNetwork,
    active: List[FireCabinetNode],
    backend: HeadLossBackend,
    mode: NetworkMode = NetworkMode.PURE_FIRE,
) -> Optional[HydraulicScenario]:
    """Шаги 3-5: агрегация расходов, потери по агрегированному расходу участка,
    требуемый напор на источнике для каждого активного ПК, max по сценарию.
    Плюс section-level агрегация по всем участкам (этап 2.2)."""
    heads: Dict[str, float] = {}
    flows: Dict[str, float] = {}
    for cab in active:
        h, q, _notes = _cabinet_required_head_and_flow(cab)
        heads[cab.cabinet_id] = h
        flows[cab.cabinet_id] = q

    seg_flow, paths = _segment_flows_for_scenario(net, active, flows)
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
    sections = _build_sections(net, seg_flow, paths, backend, mode)
    return HydraulicScenario(
        active_cabinet_ids=[c.cabinet_id for c in active],
        required_head_at_source_m=req_scenario,
        total_flow_lps=sum(flows[c.cabinet_id] for c in active),
        sections=sections,
        segment_flows=seg_flow, cabinets=scen_cabs)


def solve_fire_hydraulics_scenario(
    net: FireNetwork,
    required_jets: int,
    *,
    backend: Optional[HeadLossBackend] = None,
    scenario_filter: Optional["Callable[[Tuple[FireCabinetNode, ...]], bool]"] = None,
    mode: NetworkMode = NetworkMode.PURE_FIRE,
    require_acyclic: bool = True,
) -> ScenarioResult:
    """Сценарный расчёт совместной работы N=required_jets ПК (п. 7.6 СП 10).

    Перебирает все допустимые сочетания активных ПК из кандидатов, для каждого
    считает требуемый напор с агрегацией расходов по общим участкам, выбирает
    ХУДШИЙ сценарий (диктующую пару/группу). required_jets=1 сводится к одиночному
    расчёту (одна активная точка).

    scenario_filter: внешний предикат допустимости набора ПК. Гидравлика НЕ знает,
    почему набор запрещён — только «считать можно / нельзя». Нормативные правила
    (напр. «разные стояки» по п. 6.2.2) собираются в glue-слое через
    build_scenario_filter и передаются сюда.

    mode: режим сети для проверки скорости (чистый ВПВ / объединённый / хоз).
    require_acyclic: этап 2.2 работает только на дереве. При наличии кольца в сети
        расчёт НЕ выполняется (кольцевую увязку — этап 2.3), а не считается по
        одному произвольному плечу, что было бы полуправдой.

    Осознанное упрощение MVP: перебор всех C(k, N) сочетаний кандидатов. На
    реальных сетях В2 (десятки ПК, N=2) это подъёмно.
    """
    backend = backend or SpecificResistanceBackend()
    warnings: List[str] = []
    if required_jets < 1:
        raise ValueError("required_jets must be >= 1")

    if require_acyclic and not net.is_acyclic():
        return ScenarioResult(
            None, 0.0, net.source.available_head_m, None, None,
            warnings=["сеть содержит кольцо: section-агрегация этапа 2.2 работает "
                      "только на дереве. Кольцевая увязка — этап 2.3. Расчёт не "
                      "выполнен, чтобы не выдавать полуправду по одному плечу."])

    candidates = [c for c in net.cabinets if c.is_design_candidate]
    if len(candidates) < required_jets:
        warnings.append(f"кандидатов {len(candidates)} меньше required_jets={required_jets}; "
                        f"сценарий считается по доступным")
        required_jets = max(1, min(required_jets, len(candidates)))
    if not candidates:
        return ScenarioResult(None, 0.0, net.source.available_head_m, None, None,
                              warnings=warnings + ["нет ПК-кандидатов"])

    worst: Optional[HydraulicScenario] = None
    count = 0
    filtered_out = 0
    for combo in combinations(candidates, required_jets):
        if scenario_filter is not None and not scenario_filter(combo):
            filtered_out += 1
            continue
        scen = _evaluate_scenario(net, list(combo), backend, mode)
        if scen is None:
            continue
        count += 1
        if worst is None or scen.required_head_at_source_m > worst.required_head_at_source_m:
            worst = scen

    if worst is None:
        msg = ("ни один сценарий не удалось рассчитать (нет путей?)"
               if filtered_out == 0 else
               f"все сочетания ПК отсеяны фильтром допустимости ({filtered_out}); "
               "проверьте разнесение ПК по стоякам / заполнение riser_id (п. 6.2.2)")
        return ScenarioResult(None, 0.0, net.source.available_head_m, None, None,
                              warnings=warnings + [msg])

    req_head = worst.required_head_at_source_m
    q_pozh = worst.total_flow_lps
    duty, avail, ok, needs_pump, pump_notes = _compute_pump_duty(net, req_head, q_pozh)
    return ScenarioResult(
        dictating_scenario=worst,
        required_head_at_source_m=req_head,
        available_head_m=avail, available_head_ok=ok, needs_pump=needs_pump,
        pump_duty=duty,
        evaluated_scenarios=count, warnings=warnings + pump_notes)


def _compute_pump_duty(net: FireNetwork, req_head: float, q_pozh: float):
    """Считает рабочую точку насоса по типу источника (обратный расчёт, вариант а).

    Сеть (CITY_MAIN): H_город = available_head_m (None → 0). Насос добирает
      недостачу H_насоса = max(0, H_треб − H_город). Хватает города → насос не нужен.
    Резервуар/водоём/скважина: напора нет, насос создаёт ВЕСЬ H_треб плюс подъём
      воды со всаса (Δz_всас = отметка оси насоса − уровень воды) и потери всаса.
      Насос нужен всегда.

    Возвращает (PumpDutyPoint|None, available_head, ok, needs_pump, notes).
    """
    src = net.source
    notes: List[str] = []

    if src.kind == SourceKind.CITY_MAIN:
        h_city = src.available_head_m if src.available_head_m is not None else 0.0
        if src.available_head_m is None:
            notes.append("напор города неизвестен — принят 0 (уточнить у водоканала); "
                         "насос считается на весь требуемый напор")
        deficit = req_head - h_city
        if deficit <= 1e-9:
            return None, src.available_head_m, True, False, notes  # города хватает
        duty = PumpDutyPoint(
            required_head_m=deficit, flow_lps=q_pozh, source_kind=src.kind,
            notes=[f"насос добирает недостачу: H_треб {req_head:.1f} − H_город "
                   f"{h_city:.1f} = {deficit:.1f} м"])
        return duty, src.available_head_m, False, True, notes

    # резервуар / пруд / скважина — насос создаёт весь напор + всас
    src_elev = net.nodes[src.node_id].elevation_m
    suction_lift = 0.0
    if src.water_level_m is not None:
        suction_lift = src_elev - src.water_level_m  # ось насоса выше воды → подъём
    pump_head = req_head + max(0.0, suction_lift) + src.suction_head_loss_m
    notes.append(f"источник {src.kind.value}: напора нет, насос создаёт весь напор "
                 f"{req_head:.1f} м + всас (подъём {max(0.0, suction_lift):.1f} м + "
                 f"потери {src.suction_head_loss_m:.1f} м) = {pump_head:.1f} м")
    duty = PumpDutyPoint(
        required_head_m=pump_head, flow_lps=q_pozh, source_kind=src.kind,
        suction_lift_m=max(0.0, suction_lift),
        notes=[f"H_насоса = H_треб + подъём всаса + потери всаса = {pump_head:.1f} м"])
    return duty, None, None, True, notes


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

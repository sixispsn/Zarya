"""Гидравлический расчёт диктующего направления В1.

СП 30.13330.2020:
- п. 8.23: расчёт по максимальному секундному расходу;
- п. 8.26: ограничение скорости;
- п. 8.28, формула (15): H_il = i*l*(1+k_l).

Удельные потери i определяются по Darcy-Weisbach с учётом абсолютной
шероховатости трубы. Для турбулентного режима применяется явная формула
Swamee-Jain; для ламинарного - 64/Re.
"""
from collections import Counter
from dataclasses import dataclass, field, replace
import math
from typing import Literal, Optional

from app.calc.water_demand import ConsumerGroup, calculate_water_demand


SectionRole = Literal["internal", "input"]


@dataclass(frozen=True)
class V1SectionInput:
    section_id: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    roughness_mm: float
    role: SectionRole = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""


@dataclass(frozen=True)
class V1SectionResult:
    section_id: str
    role: SectionRole
    material: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    velocity_mps: float
    velocity_limit_mps: float
    velocity_ok: bool
    reynolds: float
    friction_factor: float
    specific_loss_m_per_m: float
    linear_loss_m: float
    local_loss_factor: float
    total_loss_m: float
    from_node: str = ""
    to_node: str = ""


@dataclass(frozen=True)
class V1NodeInput:
    """Узел дерева В1: отметка и подключённые в узле потребители."""
    node_id: str
    elevation_m: float
    consumer_groups: list[tuple[str, int]] = field(default_factory=list)
    direct_demand_lps: float = 0.0
    h_pr_m: float = 20.0


@dataclass(frozen=True)
class V1NetworkSectionInput:
    """Ориентированный участок дерева В1; расход определяется автоматически."""
    section_id: str
    from_node: str
    to_node: str
    length_m: float
    inner_diameter_mm: float
    roughness_mm: float
    role: SectionRole = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""


@dataclass(frozen=True)
class V1NodeHeadCheck:
    node_id: str
    path: list[str]
    elevation_m: float
    demand_lps: float
    h_geom_m: float
    internal_loss_m: float
    input_loss_m: float
    h_pr_m: float
    required_before_common_m: float


@dataclass(frozen=True)
class V1HydraulicResult:
    sections: list[V1SectionResult] = field(default_factory=list)
    internal_loss_m: float = 0.0
    input_loss_m: float = 0.0
    total_loss_m: float = 0.0
    max_velocity_mps: float = 0.0
    all_velocities_ok: bool = True
    dictating_node_id: str = ""
    dictating_path: list[str] = field(default_factory=list)
    node_checks: list[V1NodeHeadCheck] = field(default_factory=list)
    source_flow_lps: float = 0.0


def _friction_factor(reynolds: float, roughness_m: float, diameter_m: float) -> float:
    if reynolds <= 0:
        return 0.0
    if reynolds < 2300:
        return 64.0 / reynolds
    # Swamee-Jain, инженерная явная аппроксимация Colebrook-White.
    term = roughness_m / (3.7 * diameter_m) + 5.74 / (reynolds ** 0.9)
    return 0.25 / (math.log10(term) ** 2)


def calculate_v1_hydraulics(
    sections: list[V1SectionInput],
    *,
    water_temperature_c: float = 10.0,
) -> V1HydraulicResult:
    """Рассчитать потери по последовательным участкам диктующего направления."""
    if not sections:
        raise ValueError("Диктующее направление В1 не содержит участков")
    if not (0.0 < water_temperature_c <= 40.0):
        raise ValueError("Температура воды для расчёта В1 должна быть в диапазоне 0-40 °C")

    # Кинематическая вязкость при 10 °C согласно расчётной постановке СП 30.
    # Для других температур - инженерная аппроксимация в рабочем диапазоне.
    nu = 1.307e-6 * math.exp(-0.0337 * (water_temperature_c - 10.0))
    out: list[V1SectionResult] = []

    for s in sections:
        if not s.section_id.strip():
            raise ValueError("У участка В1 отсутствует обозначение")
        if s.length_m <= 0 or s.inner_diameter_mm <= 0 or s.flow_lps <= 0:
            raise ValueError(f"Участок {s.section_id}: L, dвн и q должны быть > 0")
        if s.roughness_mm < 0:
            raise ValueError(f"Участок {s.section_id}: шероховатость не может быть отрицательной")
        if s.velocity_limit_mps <= 0:
            raise ValueError(f"Участок {s.section_id}: предел скорости должен быть > 0")
        if s.role not in ("internal", "input"):
            raise ValueError(f"Участок {s.section_id}: неизвестная роль {s.role}")

        d = s.inner_diameter_mm / 1000.0
        q = s.flow_lps / 1000.0
        area = math.pi * d * d / 4.0
        velocity = q / area
        reynolds = velocity * d / nu
        friction = _friction_factor(reynolds, s.roughness_mm / 1000.0, d)
        specific = friction * velocity * velocity / (2.0 * 9.80665 * d)
        linear = specific * s.length_m
        # Для хозяйственно-питьевой сети жилых и общественных зданий
        # k_l=0,3 по п. 8.28. Иное значение задаётся участку явно.
        local_factor = 0.3 if s.local_loss_factor is None else s.local_loss_factor
        if local_factor < 0:
            raise ValueError(f"Участок {s.section_id}: k_l не может быть отрицательным")
        total = linear * (1.0 + local_factor)
        out.append(V1SectionResult(
            section_id=s.section_id,
            role=s.role,
            material=s.material,
            length_m=round(s.length_m, 2),
            inner_diameter_mm=round(s.inner_diameter_mm, 2),
            flow_lps=round(s.flow_lps, 3),
            velocity_mps=round(velocity, 3),
            velocity_limit_mps=round(s.velocity_limit_mps, 2),
            velocity_ok=velocity <= s.velocity_limit_mps,
            reynolds=round(reynolds),
            friction_factor=round(friction, 5),
            specific_loss_m_per_m=round(specific, 5),
            linear_loss_m=round(linear, 3),
            local_loss_factor=round(local_factor, 2),
            total_loss_m=round(total, 3),
        ))

    internal = sum(x.total_loss_m for x in out if x.role == "internal")
    input_loss = sum(x.total_loss_m for x in out if x.role == "input")
    return V1HydraulicResult(
        sections=out,
        internal_loss_m=round(internal, 3),
        input_loss_m=round(input_loss, 3),
        total_loss_m=round(internal + input_loss, 3),
        max_velocity_mps=max(x.velocity_mps for x in out),
        all_velocities_ok=all(x.velocity_ok for x in out),
    )


def calculate_v1_network(
    nodes: list[V1NodeInput],
    sections: list[V1NetworkSectionInput],
    source_node: str,
    *,
    flow_kind: Literal["cold", "total"] = "cold",
    water_temperature_c: float = 10.0,
) -> V1HydraulicResult:
    """Распределить расходы по дереву В1 и найти диктующий узел/путь.

    Для каждого участка секундный расход по СП 30 рассчитывается по суммарному
    составу потребителей его поддерева. Пики ветвей не складываются напрямую.
    """
    if flow_kind not in ("cold", "total"):
        raise ValueError("flow_kind должен быть cold или total")
    if not nodes:
        raise ValueError("Топология В1 не содержит узлов")
    if not sections:
        raise ValueError("Топология В1 не содержит участков")

    node_by_id: dict[str, V1NodeInput] = {}
    for node in nodes:
        node_id = node.node_id.strip()
        if not node_id or node_id in node_by_id:
            raise ValueError("Обозначения узлов В1 должны быть непустыми и уникальными")
        if node.direct_demand_lps < 0 or node.h_pr_m < 0:
            raise ValueError(f"Узел {node_id}: расход и Hпр не могут быть отрицательными")
        for code, count in node.consumer_groups:
            if not code or count <= 0:
                raise ValueError(f"Узел {node_id}: код потребителя должен быть задан, количество > 0")
        node_by_id[node_id] = node
    if source_node not in node_by_id:
        raise ValueError(f"Исходный узел В1 '{source_node}' отсутствует")

    section_by_id: dict[str, V1NetworkSectionInput] = {}
    outgoing: dict[str, list[V1NetworkSectionInput]] = {x: [] for x in node_by_id}
    parent_section: dict[str, V1NetworkSectionInput] = {}
    for section in sections:
        sid = section.section_id.strip()
        if not sid or sid in section_by_id:
            raise ValueError("Обозначения участков В1 должны быть непустыми и уникальными")
        if section.from_node not in node_by_id or section.to_node not in node_by_id:
            raise ValueError(f"Участок {sid}: один из узлов отсутствует в топологии")
        if section.from_node == section.to_node:
            raise ValueError(f"Участок {sid}: начало и конец совпадают")
        if section.to_node == source_node:
            raise ValueError(f"Участок {sid}: исходный узел не может иметь родителя")
        if section.to_node in parent_section:
            raise ValueError(f"Узел {section.to_node}: дерево В1 допускает только один входящий участок")
        section_by_id[sid] = section
        outgoing[section.from_node].append(section)
        parent_section[section.to_node] = section

    # Обход одновременно выявляет цикл и недостижимые от источника узлы.
    reachable: set[str] = set()
    active: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in active:
            raise ValueError("Топология В1 содержит цикл; требуется ориентированное дерево")
        if node_id in reachable:
            return
        active.add(node_id)
        for edge in outgoing[node_id]:
            visit(edge.to_node)
        active.remove(node_id)
        reachable.add(node_id)

    visit(source_node)
    missing = sorted(set(node_by_id) - reachable)
    if missing:
        raise ValueError(f"Узлы В1 не достижимы от источника {source_node}: {', '.join(missing)}")
    if len(parent_section) != len(node_by_id) - 1:
        raise ValueError("Топология В1 должна быть связным ориентированным деревом")

    subtree_groups: dict[str, Counter] = {}
    subtree_direct: dict[str, float] = {}

    def collect(node_id: str) -> tuple[Counter, float]:
        node = node_by_id[node_id]
        groups = Counter()
        for code, count in node.consumer_groups:
            groups[code] += count
        direct = node.direct_demand_lps
        for edge in outgoing[node_id]:
            child_groups, child_direct = collect(edge.to_node)
            groups.update(child_groups)
            direct += child_direct
        subtree_groups[node_id] = groups
        subtree_direct[node_id] = direct
        return groups, direct

    collect(source_node)

    def demand_lps(groups: Counter, direct: float) -> float:
        q = 0.0
        if groups:
            result = calculate_water_demand([
                ConsumerGroup(code=code, count=count) for code, count in groups.items()
            ])
            q = result.cold.q_sec if flow_kind == "cold" else result.total.q_sec
        return q + direct

    section_results: list[V1SectionResult] = []
    result_by_id: dict[str, V1SectionResult] = {}
    for section in sections:
        q = demand_lps(subtree_groups[section.to_node], subtree_direct[section.to_node])
        if q <= 0:
            raise ValueError(f"Участок {section.section_id}: в поддереве нет расчётного расхода")
        calculated = calculate_v1_hydraulics([V1SectionInput(
            section_id=section.section_id,
            length_m=section.length_m,
            inner_diameter_mm=section.inner_diameter_mm,
            flow_lps=q,
            roughness_mm=section.roughness_mm,
            role=section.role,
            local_loss_factor=section.local_loss_factor,
            velocity_limit_mps=section.velocity_limit_mps,
            material=section.material,
        )], water_temperature_c=water_temperature_c).sections[0]
        calculated = replace(calculated, from_node=section.from_node, to_node=section.to_node)
        section_results.append(calculated)
        result_by_id[section.section_id] = calculated

    checks: list[V1NodeHeadCheck] = []
    source_elevation = node_by_id[source_node].elevation_m
    for node in nodes:
        own_groups = Counter()
        for code, count in node.consumer_groups:
            own_groups[code] += count
        own_demand = demand_lps(own_groups, node.direct_demand_lps)
        if own_demand <= 0:
            continue
        path_reversed: list[str] = []
        cursor = node.node_id
        while cursor != source_node:
            edge = parent_section[cursor]
            path_reversed.append(edge.section_id)
            cursor = edge.from_node
        path = list(reversed(path_reversed))
        internal = sum(result_by_id[s].total_loss_m for s in path
                       if result_by_id[s].role == "internal")
        input_loss = sum(result_by_id[s].total_loss_m for s in path
                         if result_by_id[s].role == "input")
        h_geom = node.elevation_m - source_elevation
        required = h_geom + internal + input_loss + node.h_pr_m
        checks.append(V1NodeHeadCheck(
            node_id=node.node_id,
            path=path,
            elevation_m=round(node.elevation_m, 2),
            demand_lps=round(own_demand, 3),
            h_geom_m=round(h_geom, 3),
            internal_loss_m=round(internal, 3),
            input_loss_m=round(input_loss, 3),
            h_pr_m=round(node.h_pr_m, 2),
            required_before_common_m=round(required, 3),
        ))
    if not checks:
        raise ValueError("В топологии В1 нет узлов с потребителями или прямым расходом")

    dictating = max(checks, key=lambda x: (x.required_before_common_m, x.node_id))
    return V1HydraulicResult(
        sections=section_results,
        internal_loss_m=dictating.internal_loss_m,
        input_loss_m=dictating.input_loss_m,
        total_loss_m=round(dictating.internal_loss_m + dictating.input_loss_m, 3),
        max_velocity_mps=max(x.velocity_mps for x in section_results),
        all_velocities_ok=all(x.velocity_ok for x in section_results),
        dictating_node_id=dictating.node_id,
        dictating_path=dictating.path,
        node_checks=checks,
        source_flow_lps=round(demand_lps(subtree_groups[source_node],
                                        subtree_direct[source_node]), 3),
    )

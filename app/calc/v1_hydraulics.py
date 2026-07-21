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
    diameter_selection: str = "fixed"
    specific_loss_limit_m_per_m: Optional[float] = None


@dataclass(frozen=True)
class V1NodeInput:
    """Узел дерева В1: отметка и подключённые в узле потребители."""
    node_id: str
    elevation_m: float
    consumer_groups: list[tuple[str, int]] = field(default_factory=list)
    direct_demand_lps: float = 0.0
    h_pr_m: float = 20.0
    max_static_head_m: float = 45.0


@dataclass(frozen=True)
class V1NetworkSectionInput:
    """Ориентированный участок дерева В1; расход определяется автоматически."""
    section_id: str
    from_node: str
    to_node: str
    length_m: float
    inner_diameter_mm: Optional[float]
    roughness_mm: float
    role: SectionRole = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""
    candidate_inner_diameters_mm: list[float] = field(default_factory=list)
    max_specific_loss_m_per_m: Optional[float] = None


@dataclass(frozen=True)
class V1InletInput:
    inlet_id: str
    guaranteed_head_m: float
    maximum_head_m: float
    length_m: float
    inner_diameter_mm: Optional[float]
    roughness_mm: float
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""
    candidate_inner_diameters_mm: list[float] = field(default_factory=list)
    max_specific_loss_m_per_m: Optional[float] = None


@dataclass(frozen=True)
class V1InletCheck:
    inlet_id: str
    guaranteed_head_m: float
    maximum_head_m: float
    flow_lps: float
    inner_diameter_mm: float
    diameter_selection: str
    velocity_mps: float
    velocity_limit_mps: float
    velocity_ok: bool
    loss_m: float
    deficit_index_m: float


@dataclass(frozen=True)
class V1RingScenarioCheck:
    disabled_section_id: str
    dictating_node_id: str
    required_before_common_m: float
    internal_loss_m: float
    max_velocity_mps: float
    all_velocities_ok: bool


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
    max_static_head_m: float
    required_before_common_m: float


@dataclass(frozen=True)
class V1PressureCheck:
    node_id: str
    elevation_m: float
    dynamic_head_m: float
    minimum_head_m: float
    minimum_ok: bool
    static_head_m: Optional[float]
    maximum_static_head_m: float
    maximum_ok: Optional[bool]


@dataclass(frozen=True)
class V1PressureZone:
    zone_id: str
    node_ids: list[str]
    elevation_min_m: float
    elevation_max_m: float
    target_source_head_m: float
    estimated_max_static_head_m: float
    valid: bool


@dataclass(frozen=True)
class V1ZoneRegulator:
    zone_id: str
    required: Optional[bool]
    section_id: str
    install_node: str
    design_flow_lps: float
    outlet_setpoint_m: Optional[float]
    design_pressure_drop_m: Optional[float]
    required_kv_m3h: Optional[float]
    topology_feasible: bool
    hydraulic_reserve_available: Optional[bool]
    note: str


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
    pressure_checks: list[V1PressureCheck] = field(default_factory=list)
    pressure_zones: list[V1PressureZone] = field(default_factory=list)
    zone_regulators: list[V1ZoneRegulator] = field(default_factory=list)
    node_elevations_m: dict[str, float] = field(default_factory=dict)
    source_node_id: str = ""
    inlet_checks: list[V1InletCheck] = field(default_factory=list)
    dictating_inlet_id: str = ""
    all_inlets_100_percent_ok: Optional[bool] = None
    topology_kind: str = "tree"
    ring_section_ids: list[str] = field(default_factory=list)
    ring_converged: Optional[bool] = None
    ring_iterations: int = 0
    ring_residual_m: Optional[float] = None
    ring_normal_sections: list[V1SectionResult] = field(default_factory=list)
    ring_scenarios: list[V1RingScenarioCheck] = field(default_factory=list)
    dictating_outage_section_id: str = ""
    static_source_head_m: Optional[float] = None
    all_minimum_pressures_ok: Optional[bool] = None
    all_maximum_pressures_ok: Optional[bool] = None


def _friction_factor(reynolds: float, roughness_m: float, diameter_m: float) -> float:
    if reynolds <= 0:
        return 0.0
    if reynolds < 2300:
        return 64.0 / reynolds
    if reynolds < 4000:
        # Плавный переход устраняет нефизичный скачок между ламинарной и
        # турбулентной формулами, критичный при увязке малых расходов кольца.
        laminar_at_2300 = 64.0 / 2300.0
        term_at_4000 = (roughness_m / (3.7 * diameter_m)
                        + 5.74 / (4000.0 ** 0.9))
        turbulent_at_4000 = 0.25 / (math.log10(term_at_4000) ** 2)
        weight = (reynolds - 2300.0) / 1700.0
        return laminar_at_2300 + weight * (turbulent_at_4000 - laminar_at_2300)
    # Swamee-Jain, инженерная явная аппроксимация Colebrook-White.
    term = roughness_m / (3.7 * diameter_m) + 5.74 / (reynolds ** 0.9)
    return 0.25 / (math.log10(term) ** 2)


def velocity_mps(flow_lps: float, inner_diameter_mm: float) -> float:
    """Скорость по расходу и фактическому внутреннему диаметру трубы."""
    if flow_lps < 0:
        raise ValueError("Расход не может быть отрицательным")
    if inner_diameter_mm <= 0:
        raise ValueError("Внутренний диаметр должен быть > 0")
    diameter_m = inner_diameter_mm / 1000.0
    return (flow_lps / 1000.0) / (math.pi * diameter_m * diameter_m / 4.0)


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
        velocity = velocity_mps(s.flow_lps, s.inner_diameter_mm)
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


def _calculate_v1_tree_network(
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
        if node.max_static_head_m <= 0:
            raise ValueError(f"Узел {node_id}: максимальный статический напор должен быть > 0")
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
            diameter = section.inner_diameter_mm
            selection = "fixed"
            if diameter is None:
                candidates = sorted(set(section.candidate_inner_diameters_mm))
                if not candidates or any(d <= 0 for d in candidates):
                    raise ValueError(
                        f"Участок {section.section_id}: для автоподбора нужен "
                        "положительный сортамент dвн")
                diameter = candidates[0]
                selection = "auto"
            calculated = V1SectionResult(
                section_id=section.section_id, role=section.role,
                material=section.material, length_m=section.length_m,
                inner_diameter_mm=diameter, flow_lps=0.0, velocity_mps=0.0,
                velocity_limit_mps=section.velocity_limit_mps, velocity_ok=True,
                reynolds=0.0, friction_factor=0.0,
                specific_loss_m_per_m=0.0, linear_loss_m=0.0,
                local_loss_factor=(section.local_loss_factor
                                   if section.local_loss_factor is not None else 0.3),
                total_loss_m=0.0, from_node=section.from_node,
                to_node=section.to_node, diameter_selection=selection,
                specific_loss_limit_m_per_m=section.max_specific_loss_m_per_m,
            )
            section_results.append(calculated)
            result_by_id[section.section_id] = calculated
            continue

        def calculate_at(diameter_mm: float) -> V1SectionResult:
            return calculate_v1_hydraulics([V1SectionInput(
                section_id=section.section_id,
                length_m=section.length_m,
                inner_diameter_mm=diameter_mm,
                flow_lps=q,
                roughness_mm=section.roughness_mm,
                role=section.role,
                local_loss_factor=section.local_loss_factor,
                velocity_limit_mps=section.velocity_limit_mps,
                material=section.material,
            )], water_temperature_c=water_temperature_c).sections[0]

        if section.inner_diameter_mm is not None:
            calculated = calculate_at(section.inner_diameter_mm)
            selection = "fixed"
        else:
            candidates = sorted(set(section.candidate_inner_diameters_mm))
            if not candidates or any(d <= 0 for d in candidates):
                raise ValueError(
                    f"Участок {section.section_id}: для автоподбора нужен положительный сортамент dвн")
            if (section.max_specific_loss_m_per_m is None
                    or section.max_specific_loss_m_per_m <= 0):
                raise ValueError(
                    f"Участок {section.section_id}: для автоподбора задайте iдоп > 0")
            variants = [calculate_at(d) for d in candidates]
            calculated = next((variant for variant in variants
                               if variant.velocity_ok
                               and variant.specific_loss_m_per_m
                               <= section.max_specific_loss_m_per_m), None)
            if calculated is None:
                largest = variants[-1]
                raise ValueError(
                    f"Участок {section.section_id}: сортамент до {candidates[-1]:g} мм "
                    f"не обеспечивает v≤{section.velocity_limit_mps:g} м/с и "
                    f"i≤{section.max_specific_loss_m_per_m:g} м/м "
                    f"(при максимальном dвн: v={largest.velocity_mps:g}, "
                    f"i={largest.specific_loss_m_per_m:g})")
            selection = "auto"
        calculated = replace(
            calculated,
            from_node=section.from_node,
            to_node=section.to_node,
            diameter_selection=selection,
            specific_loss_limit_m_per_m=section.max_specific_loss_m_per_m,
        )
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
            max_static_head_m=round(node.max_static_head_m, 2),
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
        node_elevations_m={node.node_id: round(node.elevation_m, 3) for node in nodes},
        source_node_id=source_node,
    )


def _v1_single_cycle(
    node_ids: set[str], sections: list[V1NetworkSectionInput],
) -> tuple[list[str], list[V1NetworkSectionInput]]:
    """Вернуть единственный контур в порядке обхода либо пустые списки."""
    adjacency: dict[str, list[tuple[str, V1NetworkSectionInput]]] = {
        node_id: [] for node_id in node_ids
    }
    for section in sections:
        adjacency[section.from_node].append((section.to_node, section))
        adjacency[section.to_node].append((section.from_node, section))
    degree = {node_id: len(rows) for node_id, rows in adjacency.items()}
    queue = [node_id for node_id, value in degree.items() if value <= 1]
    removed: set[str] = set()
    while queue:
        node_id = queue.pop()
        if node_id in removed:
            continue
        removed.add(node_id)
        for neighbour, _section in adjacency[node_id]:
            if neighbour not in removed:
                degree[neighbour] -= 1
                if degree[neighbour] == 1:
                    queue.append(neighbour)
    cycle_nodes_set = node_ids - removed
    if len(cycle_nodes_set) < 3:
        return [], []
    start = sorted(cycle_nodes_set)[0]
    nodes_order = [start]
    sections_order: list[V1NetworkSectionInput] = []
    previous = ""
    current = start
    while True:
        choices = [(node, section) for node, section in adjacency[current]
                   if node in cycle_nodes_set and node != previous]
        if not choices:
            return [], []
        next_node, section = next(
            ((node, row) for node, row in choices
             if node == start or node not in nodes_order), choices[0])
        sections_order.append(section)
        if next_node == start:
            break
        nodes_order.append(next_node)
        previous, current = current, next_node
        if len(nodes_order) > len(cycle_nodes_set):
            return [], []
    if len(nodes_order) != len(cycle_nodes_set):
        return [], []
    return nodes_order, sections_order


def _orient_v1_tree(
    node_ids: set[str], sections: list[V1NetworkSectionInput], source_node: str,
) -> list[V1NetworkSectionInput]:
    adjacency: dict[str, list[tuple[str, V1NetworkSectionInput]]] = {
        node_id: [] for node_id in node_ids
    }
    for section in sections:
        adjacency[section.from_node].append((section.to_node, section))
        adjacency[section.to_node].append((section.from_node, section))
    oriented: list[V1NetworkSectionInput] = []
    seen = {source_node}
    queue = [source_node]
    while queue:
        node_id = queue.pop(0)
        for neighbour, section in adjacency[node_id]:
            if neighbour in seen:
                continue
            seen.add(neighbour)
            queue.append(neighbour)
            oriented.append(replace(section, from_node=node_id, to_node=neighbour))
    if seen != node_ids or len(oriented) != len(node_ids) - 1:
        raise ValueError("После отключения участка сеть В1 не является связным деревом")
    return oriented


def _calculate_v1_ring_network(
    nodes: list[V1NodeInput],
    sections: list[V1NetworkSectionInput],
    source_node: str,
    *,
    flow_kind: Literal["cold", "total"],
    water_temperature_c: float,
) -> V1HydraulicResult:
    node_ids = {node.node_id for node in nodes}
    if source_node not in node_ids:
        raise ValueError(f"Исходный узел В1 '{source_node}' отсутствует")
    if any(section.role != "internal" for section in sections):
        raise ValueError("Участки кольцевой внутренней сети В1 должны иметь role=internal")
    cycle_nodes, cycle_sections = _v1_single_cycle(node_ids, sections)
    if not cycle_sections:
        raise ValueError("Не удалось выделить единственное кольцо В1")
    if source_node not in cycle_nodes:
        raise ValueError("Исходный узел В1 должен находиться на кольце")
    for section in cycle_sections:
        if section.inner_diameter_mm is None:
            raise ValueError(
                f"Участок кольца {section.section_id}: для увязки задайте dвн; "
                "автоподбор кольцевых участков выполняется после определения расходов")

    # Начальное потокораспределение получаем размыканием одного участка.
    break_section = cycle_sections[-1]
    base_sections = [section for section in sections
                     if section.section_id != break_section.section_id]
    oriented = _orient_v1_tree(node_ids, base_sections, source_node)
    base = _calculate_v1_tree_network(
        nodes, oriented, source_node, flow_kind=flow_kind,
        water_temperature_c=water_temperature_c)
    base_rows = {row.section_id: row for row in base.sections}

    q_cycle: list[float] = []
    for index, section in enumerate(cycle_sections):
        traversal_from = cycle_nodes[index]
        traversal_to = cycle_nodes[(index + 1) % len(cycle_nodes)]
        row = base_rows.get(section.section_id)
        if row is None:
            q_reference = 0.0
        else:
            q_reference = (row.flow_lps if (row.from_node, row.to_node)
                           == (section.from_node, section.to_node) else -row.flow_lps)
        q_cycle.append(q_reference if (section.from_node, section.to_node)
                       == (traversal_from, traversal_to) else -q_reference)

    def signed_loss(section: V1NetworkSectionInput, flow: float) -> float:
        if abs(flow) < 1e-10:
            return 0.0
        diameter_m = section.inner_diameter_mm / 1000.0
        flow_m3s = abs(flow) / 1000.0
        velocity = flow_m3s / (math.pi * diameter_m ** 2 / 4.0)
        nu = 1.307e-6 * math.exp(-0.0337 * (water_temperature_c - 10.0))
        reynolds = velocity * diameter_m / nu
        friction = _friction_factor(
            reynolds, section.roughness_mm / 1000.0, diameter_m)
        specific = friction * velocity ** 2 / (2.0 * 9.80665 * diameter_m)
        local_factor = (0.3 if section.local_loss_factor is None
                        else section.local_loss_factor)
        loss = specific * section.length_m * (1.0 + local_factor)
        return math.copysign(loss, flow)

    residual = 0.0
    iterations = 0
    for iterations in range(1, 101):
        losses = [signed_loss(section, flow)
                  for section, flow in zip(cycle_sections, q_cycle)]
        residual_signed = sum(losses)
        residual = abs(residual_signed)
        if residual < 1e-4:
            break
        derivative = 0.0
        for section, flow in zip(cycle_sections, q_cycle):
            step = max(abs(flow) * 1e-4, 1e-4)
            derivative += ((signed_loss(section, flow + step)
                            - signed_loss(section, flow - step)) / (2 * step))
        if derivative <= 1e-12:
            break
        correction = -residual_signed / derivative
        q_cycle = [flow + correction for flow in q_cycle]
    converged = residual < 1e-4
    if not converged:
        raise ValueError(
            f"Увязка кольца В1 не сошлась за {iterations} итераций; "
            f"невязка {residual:.4g} м")

    normal_rows = dict(base_rows)
    for index, (section, flow) in enumerate(zip(cycle_sections, q_cycle)):
        traversal = (cycle_nodes[index], cycle_nodes[(index + 1) % len(cycle_nodes)])
        q_reference = flow if (section.from_node, section.to_node) == traversal else -flow
        calculated = calculate_v1_hydraulics([V1SectionInput(
            section.section_id, section.length_m, section.inner_diameter_mm,
            abs(q_reference), section.roughness_mm, role="internal",
            local_loss_factor=section.local_loss_factor,
            velocity_limit_mps=section.velocity_limit_mps,
            material=section.material,
        )], water_temperature_c=water_temperature_c).sections[0]
        normal_rows[section.section_id] = replace(
            calculated,
            from_node=(section.from_node if q_reference >= 0 else section.to_node),
            to_node=(section.to_node if q_reference >= 0 else section.from_node),
        )

    normal_sections = [normal_rows[section.section_id] for section in sections]

    # Каждый одиночный отказ участка кольца превращает сеть в дерево.
    outage_results: list[tuple[str, V1HydraulicResult]] = []
    scenario_checks: list[V1RingScenarioCheck] = []
    for disabled in cycle_sections:
        active = [section for section in sections
                  if section.section_id != disabled.section_id]
        outage = _calculate_v1_tree_network(
            nodes, _orient_v1_tree(node_ids, active, source_node), source_node,
            flow_kind=flow_kind, water_temperature_c=water_temperature_c)
        dictating = next(row for row in outage.node_checks
                         if row.node_id == outage.dictating_node_id)
        outage_results.append((disabled.section_id, outage))
        scenario_checks.append(V1RingScenarioCheck(
            disabled_section_id=disabled.section_id,
            dictating_node_id=outage.dictating_node_id,
            required_before_common_m=dictating.required_before_common_m,
            internal_loss_m=outage.internal_loss_m,
            max_velocity_mps=outage.max_velocity_mps,
            all_velocities_ok=outage.all_velocities_ok,
        ))
    disabled_id, worst = max(
        outage_results,
        key=lambda item: next(row.required_before_common_m
                              for row in item[1].node_checks
                              if row.node_id == item[1].dictating_node_id),
    )
    return replace(
        worst,
        topology_kind="single_ring",
        ring_section_ids=[section.section_id for section in cycle_sections],
        ring_converged=True,
        ring_iterations=iterations,
        ring_residual_m=round(residual, 6),
        ring_normal_sections=normal_sections,
        ring_scenarios=scenario_checks,
        dictating_outage_section_id=disabled_id,
    )


def calculate_v1_network(
    nodes: list[V1NodeInput],
    sections: list[V1NetworkSectionInput],
    source_node: str,
    *,
    flow_kind: Literal["cold", "total"] = "cold",
    water_temperature_c: float = 10.0,
) -> V1HydraulicResult:
    """Рассчитать дерево либо сеть В1 с одним кольцом."""
    node_ids = {node.node_id for node in nodes}
    if not node_ids or not sections:
        return _calculate_v1_tree_network(
            nodes, sections, source_node, flow_kind=flow_kind,
            water_temperature_c=water_temperature_c)
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for section in sections:
        if section.from_node in adjacency and section.to_node in adjacency:
            adjacency[section.from_node].add(section.to_node)
            adjacency[section.to_node].add(section.from_node)
    seen = set()
    stack = [source_node] if source_node in node_ids else []
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency[current] - seen)
    cycle_count = len(sections) - len(node_ids) + 1 if seen == node_ids else -1
    if cycle_count == 0:
        return _calculate_v1_tree_network(
            nodes, sections, source_node, flow_kind=flow_kind,
            water_temperature_c=water_temperature_c)
    if cycle_count == 1:
        return _calculate_v1_ring_network(
            nodes, sections, source_node, flow_kind=flow_kind,
            water_temperature_c=water_temperature_c)
    if cycle_count < 0:
        missing = sorted(node_ids - seen)
        raise ValueError(
            f"Узлы В1 не достижимы от источника {source_node}: {', '.join(missing)}")
    raise ValueError("В1 поддерживает дерево или одно кольцо; многокольцевая сеть не поддержана")


def apply_v1_inlets(
    result: V1HydraulicResult,
    inlets: list[V1InletInput],
    *,
    water_temperature_c: float = 10.0,
) -> V1HydraulicResult:
    """Проверить каждый ввод на 100% расхода и выбрать диктующий сценарий."""
    if not inlets:
        return result
    if any(section.role == "input" for section in result.sections):
        raise ValueError("При явных вводах участки дерева В1 должны иметь role=internal")
    ids = [x.inlet_id.strip() for x in inlets]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("Обозначения вводов В1 должны быть непустыми и уникальными")
    if set(ids) & {x.section_id for x in result.sections}:
        raise ValueError("Обозначение ввода В1 совпадает с обозначением участка сети")

    inlet_rows: list[V1SectionResult] = []
    checks: list[V1InletCheck] = []
    for inlet in inlets:
        if (inlet.guaranteed_head_m <= 0 or inlet.maximum_head_m <= 0
                or inlet.maximum_head_m < inlet.guaranteed_head_m):
            raise ValueError(f"Ввод {inlet.inlet_id}: проверьте Hгар и Hмакс")

        def calculate_at(diameter_mm: float) -> V1SectionResult:
            return calculate_v1_hydraulics([V1SectionInput(
                section_id=inlet.inlet_id,
                length_m=inlet.length_m,
                inner_diameter_mm=diameter_mm,
                flow_lps=result.source_flow_lps,
                roughness_mm=inlet.roughness_mm,
                role="input",
                local_loss_factor=inlet.local_loss_factor,
                velocity_limit_mps=inlet.velocity_limit_mps,
                material=inlet.material,
            )], water_temperature_c=water_temperature_c).sections[0]

        if inlet.inner_diameter_mm is not None:
            row = calculate_at(inlet.inner_diameter_mm)
            selection = "fixed"
        else:
            candidates = sorted(set(inlet.candidate_inner_diameters_mm))
            if not candidates or any(d <= 0 for d in candidates):
                raise ValueError(f"Ввод {inlet.inlet_id}: для автоподбора нужен сортамент dвн")
            if (inlet.max_specific_loss_m_per_m is None
                    or inlet.max_specific_loss_m_per_m <= 0):
                raise ValueError(f"Ввод {inlet.inlet_id}: для автоподбора задайте iдоп > 0")
            variants = [calculate_at(d) for d in candidates]
            row = next((x for x in variants if x.velocity_ok
                        and x.specific_loss_m_per_m
                        <= inlet.max_specific_loss_m_per_m), None)
            if row is None:
                raise ValueError(
                    f"Ввод {inlet.inlet_id}: сортамент до {candidates[-1]:g} мм "
                    "не пропускает 100% расчётного расхода по vдоп и iдоп")
            selection = "auto"
        row = replace(
            row,
            from_node=f"Наружная сеть ({inlet.inlet_id})",
            to_node=result.source_node_id,
            diameter_selection=selection,
            specific_loss_limit_m_per_m=inlet.max_specific_loss_m_per_m,
        )
        inlet_rows.append(row)
        checks.append(V1InletCheck(
            inlet_id=inlet.inlet_id,
            guaranteed_head_m=round(inlet.guaranteed_head_m, 2),
            maximum_head_m=round(inlet.maximum_head_m, 2),
            flow_lps=result.source_flow_lps,
            inner_diameter_mm=row.inner_diameter_mm,
            diameter_selection=selection,
            velocity_mps=row.velocity_mps,
            velocity_limit_mps=row.velocity_limit_mps,
            velocity_ok=row.velocity_ok,
            loss_m=row.total_loss_m,
            deficit_index_m=round(row.total_loss_m - inlet.guaranteed_head_m, 3),
        ))

    dictating_inlet = max(checks, key=lambda x: (x.deficit_index_m, x.inlet_id))
    updated_nodes = [replace(
        node,
        path=[dictating_inlet.inlet_id] + node.path,
        input_loss_m=dictating_inlet.loss_m,
        required_before_common_m=round(
            node.required_before_common_m + dictating_inlet.loss_m, 3),
    ) for node in result.node_checks]
    dictating_node = max(updated_nodes,
                         key=lambda x: (x.required_before_common_m, x.node_id))
    all_sections = inlet_rows + result.sections
    return replace(
        result,
        sections=all_sections,
        input_loss_m=dictating_inlet.loss_m,
        total_loss_m=round(dictating_node.internal_loss_m
                           + dictating_inlet.loss_m, 3),
        max_velocity_mps=max(x.velocity_mps for x in all_sections),
        all_velocities_ok=all(x.velocity_ok for x in all_sections),
        dictating_node_id=dictating_node.node_id,
        dictating_path=dictating_node.path,
        node_checks=updated_nodes,
        inlet_checks=checks,
        dictating_inlet_id=dictating_inlet.inlet_id,
        all_inlets_100_percent_ok=all(x.velocity_ok for x in checks),
    )


def audit_v1_pressures(
    result: V1HydraulicResult,
    *,
    required_source_head_m: float,
    common_dynamic_loss_m: float,
    static_source_head_m: Optional[float],
) -> V1HydraulicResult:
    """Проверить давления в узлах и предложить регулируемые зоны В1.

    Динамический напор считается при расчётном расходе. Статический напор
    проверяется только при наличии максимального напора наружной сети; для
    насосной схемы вызывающий код добавляет напор насоса при Q=0.
    """
    if not result.node_checks:
        raise ValueError("Для зонного расчёта отсутствуют потребляющие узлы В1")
    if required_source_head_m <= 0 or common_dynamic_loss_m < 0:
        raise ValueError("Напор источника должен быть > 0, общие потери неотрицательны")
    if static_source_head_m is not None and static_source_head_m < 0:
        raise ValueError("Статический напор источника не может быть отрицательным")

    checks: list[V1PressureCheck] = []
    for node in result.node_checks:
        dynamic = (required_source_head_m - common_dynamic_loss_m
                   - node.h_geom_m - node.internal_loss_m - node.input_loss_m)
        # Hтр и составляющие ПЗ округляются раздельно; устраняем только
        # микроневязку округления до сантиметра водяного столба.
        if abs(dynamic - node.h_pr_m) <= 0.01:
            dynamic = node.h_pr_m
        static = (None if static_source_head_m is None
                  else static_source_head_m - node.h_geom_m)
        checks.append(V1PressureCheck(
            node_id=node.node_id,
            elevation_m=node.elevation_m,
            dynamic_head_m=round(dynamic, 3),
            minimum_head_m=node.h_pr_m,
            minimum_ok=dynamic >= node.h_pr_m,
            static_head_m=None if static is None else round(static, 3),
            maximum_static_head_m=node.max_static_head_m,
            maximum_ok=(None if static is None
                        else static <= node.max_static_head_m + 0.001),
        ))

    # Концептуальное разбиение на регулируемые зоны. Для каждой зоны на входе
    # принимается минимальная уставка, обеспечивающая её диктующий узел.
    ordered = sorted(result.node_checks, key=lambda x: (x.h_geom_m, x.node_id))
    groups: list[list[V1NodeHeadCheck]] = []
    current: list[V1NodeHeadCheck] = []

    def zone_fits(items: list[V1NodeHeadCheck]) -> bool:
        target = max(x.required_before_common_m + common_dynamic_loss_m for x in items)
        return all(target - x.h_geom_m <= x.max_static_head_m + 0.001 for x in items)

    for node in ordered:
        proposed = current + [node]
        if current and not zone_fits(proposed):
            groups.append(current)
            current = [node]
        else:
            current = proposed
    if current:
        groups.append(current)

    zones: list[V1PressureZone] = []
    for index, items in enumerate(groups, 1):
        target = max(x.required_before_common_m + common_dynamic_loss_m for x in items)
        estimated = max(target - x.h_geom_m for x in items)
        zones.append(V1PressureZone(
            zone_id=f"Зона {index}",
            node_ids=[x.node_id for x in items],
            elevation_min_m=round(min(x.elevation_m for x in items), 2),
            elevation_max_m=round(max(x.elevation_m for x in items), 2),
            target_source_head_m=round(target, 3),
            estimated_max_static_head_m=round(estimated, 3),
            valid=zone_fits(items),
        ))

    section_by_id = {x.section_id: x for x in result.sections}
    node_check_by_id = {x.node_id: x for x in result.node_checks}
    pressure_by_id = {x.node_id: x for x in checks}
    all_paths = {x.node_id: x.path for x in result.node_checks}
    regulators: list[V1ZoneRegulator] = []
    for zone in zones:
        zone_nodes = set(zone.node_ids)
        zone_paths = [all_paths[node_id] for node_id in zone.node_ids]
        common_sections = [
            sid for sid in zone_paths[0]
            if (not result.inlet_checks or section_by_id[sid].role == "internal")
            and all(sid in path for path in zone_paths[1:])
        ]
        outside_paths = [path for node_id, path in all_paths.items()
                         if node_id not in zone_nodes]
        exclusive_sections = [sid for sid in common_sections
                              if not any(sid in path for path in outside_paths)]
        required_values = [pressure_by_id[node_id].maximum_ok for node_id in zone.node_ids]
        required = (None if all(x is None for x in required_values)
                    else any(x is False for x in required_values))
        if not exclusive_sections:
            regulators.append(V1ZoneRegulator(
                zone_id=zone.zone_id,
                required=required,
                section_id="",
                install_node="",
                design_flow_lps=0.0,
                outlet_setpoint_m=None,
                design_pressure_drop_m=None,
                required_kv_m3h=None,
                topology_feasible=False,
                hydraulic_reserve_available=None,
                note="нет эксклюзивной питающей ветви; требуется разделение трасс зон",
            ))
            continue

        section_id = exclusive_sections[0]
        boundary = section_by_id[section_id]
        reference_path = zone_paths[0]
        boundary_index = reference_path.index(section_id)
        prefix = reference_path[:boundary_index]
        prefix_loss = sum(section_by_id[sid].total_loss_m for sid in prefix)
        from_elevation = result.node_elevations_m[boundary.from_node]
        from_h_geom = (from_elevation
                       - result.node_elevations_m[result.source_node_id])
        outlet_requirements = []
        for node_id in zone.node_ids:
            node = node_check_by_id[node_id]
            path = all_paths[node_id]
            start = path.index(section_id)
            downstream_loss = sum(section_by_id[sid].total_loss_m
                                  for sid in path[start:])
            outlet_requirements.append(
                node.h_geom_m - from_h_geom + downstream_loss + node.h_pr_m)
        setpoint = max(outlet_requirements)
        upstream = (required_source_head_m - common_dynamic_loss_m
                    - from_h_geom - prefix_loss)
        pressure_drop = max(upstream - setpoint, 0.0)
        reserve_available = (None if required is not True else pressure_drop > 0.01)
        required_kv = None
        if required and pressure_drop > 0.01:
            delta_p_bar = pressure_drop * 0.0980665
            required_kv = boundary.flow_lps * 3.6 / math.sqrt(delta_p_bar)
        if required and reserve_available:
            note = "установить на начале эксклюзивной ветви; марку проверить по Kv и диапазону настройки"
        elif required:
            note = "нет динамического запаса на потери регулятора; требуется отдельная насосная зона или перерасчёт"
        else:
            note = "эксклюзивная ветвь определена; регулятор по проверке не требуется"
        regulators.append(V1ZoneRegulator(
            zone_id=zone.zone_id,
            required=required,
            section_id=section_id,
            install_node=boundary.from_node,
            design_flow_lps=boundary.flow_lps,
            outlet_setpoint_m=round(setpoint, 3),
            design_pressure_drop_m=round(pressure_drop, 3),
            required_kv_m3h=(None if required_kv is None else round(required_kv, 3)),
            topology_feasible=True,
            hydraulic_reserve_available=reserve_available,
            note=note,
        ))

    maximum_results = [x.maximum_ok for x in checks if x.maximum_ok is not None]
    return replace(
        result,
        pressure_checks=checks,
        pressure_zones=zones,
        zone_regulators=regulators,
        static_source_head_m=(None if static_source_head_m is None
                              else round(static_source_head_m, 3)),
        all_minimum_pressures_ok=all(x.minimum_ok for x in checks),
        all_maximum_pressures_ok=(None if not maximum_results else all(maximum_results)),
    )

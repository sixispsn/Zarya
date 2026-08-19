"""Консервативная пошаговая маршрутизация стоков по направленному графу.

Это первый сетевой слой над :class:`app.calc.sewer_simulation.PipeSection`.
Каждая труба является одной расчётной ячейкой. Поток на шаге ограничивается
локальной характеристикой Шези-Маннинга и свободным объёмом следующего
участка. Непринятый нижним участком объём остаётся в верхнем, поэтому подпор
распространяется против направления графа без создания воды.

Модель является кинематической. Явно заданные внутренние узлы могут
накапливать воду и локализовать аварийный перелив, но уровень между их
отметками не интерполируется: для этого нужна геометрия ёмкости. Модель не
заменяет решение полных уравнений Сен-Венана и не вычисляет наружную сеть.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Optional

from app.calc.sewer_simulation import PipeSection, PipeStatus


class OutletBoundaryKind(str, Enum):
    FREE_OUTFALL = "free_outfall"
    FLOW_LIMIT = "flow_limit"


@dataclass(frozen=True)
class PipeConnection:
    upstream_pipe_id: str
    downstream_pipe_id: str

    def __post_init__(self) -> None:
        if (
            not self.upstream_pipe_id.strip()
            or not self.downstream_pipe_id.strip()
        ):
            raise ValueError("в связи должны быть заданы оба участка")
        if self.upstream_pipe_id == self.downstream_pipe_id:
            raise ValueError("участок не может быть связан сам с собой")


@dataclass(frozen=True)
class HydrographPoint:
    time_seconds: float
    flow_lps: float
    suspended_solids_mg_l: float = 0.0

    def __post_init__(self) -> None:
        if self.time_seconds < 0:
            raise ValueError("время гидрографа не может быть отрицательным")
        if self.flow_lps < 0:
            raise ValueError("расход гидрографа не может быть отрицательным")
        if self.suspended_solids_mg_l < 0:
            raise ValueError("концентрация взвесей не может быть отрицательной")


@dataclass(frozen=True)
class InflowHydrograph:
    """Кусочно-постоянный внешний приток к входу участка."""

    pipe_id: str
    points: tuple[HydrographPoint, ...]
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", tuple(self.points))
        if not self.pipe_id.strip():
            raise ValueError("для гидрографа не задан участок")
        if not self.points:
            raise ValueError("гидрограф должен содержать хотя бы одну точку")
        if self.points[0].time_seconds != 0:
            raise ValueError("гидрограф должен начинаться с t=0")
        times = [row.time_seconds for row in self.points]
        if times != sorted(set(times)):
            raise ValueError("время гидрографа должно строго возрастать")
        if not self.source.strip():
            raise ValueError("для гидрографа нужен источник")

    def value_at(self, time_seconds: float) -> HydrographPoint:
        if time_seconds < 0:
            raise ValueError("время не может быть отрицательным")
        current = self.points[0]
        for point in self.points[1:]:
            if point.time_seconds > time_seconds:
                break
            current = point
        return current


@dataclass(frozen=True)
class OutletBoundary:
    pipe_id: str
    kind: OutletBoundaryKind
    source: str
    maximum_flow_lps: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.pipe_id.strip():
            raise ValueError("для выходной границы не задан участок")
        if not self.source.strip():
            raise ValueError("для выходной границы нужен источник")
        if self.kind is OutletBoundaryKind.FLOW_LIMIT:
            if self.maximum_flow_lps is None or self.maximum_flow_lps < 0:
                raise ValueError(
                    "для ограниченной границы нужен неотрицательный расход"
                )
        elif self.maximum_flow_lps is not None:
            raise ValueError(
                "для свободного выпуска maximum_flow_lps задавать не следует"
            )

    def accepted_volume_m3(
        self,
        desired_volume_m3: float,
        dt_seconds: float,
    ) -> float:
        if self.kind is OutletBoundaryKind.FREE_OUTFALL:
            return desired_volume_m3
        limit_m3 = (self.maximum_flow_lps or 0.0) / 1000.0 * dt_seconds
        return min(desired_volume_m3, limit_m3)


@dataclass(frozen=True)
class NetworkSedimentModel:
    """Параметры осаждения; концентрация приходит из гидрографа."""

    sediment_bulk_density_kg_m3: float
    capture_efficiency_at_zero_velocity: float
    velocity_deficit_exponent: float
    source: str

    def __post_init__(self) -> None:
        if self.sediment_bulk_density_kg_m3 <= 0:
            raise ValueError("объёмная плотность осадка должна быть больше 0")
        if not 0 <= self.capture_efficiency_at_zero_velocity <= 1:
            raise ValueError("эффективность улавливания должна быть от 0 до 1")
        if self.velocity_deficit_exponent <= 0:
            raise ValueError("показатель дефицита скорости должен быть больше 0")
        if not self.source.strip():
            raise ValueError("для модели осадка нужен источник или калибровка")


class NodeStatus(str, Enum):
    EMPTY = "empty"
    STORING = "storing"
    OVERFLOW = "overflow"


@dataclass(frozen=True)
class NetworkStorageNodeConfig:
    """Явно заданный внутренний узел приёма, накопления и перелива.

    Узел перехватывает все связи и внешние притоки у входа
    ``downstream_pipe_id``. Объём хранения и отметка перелива являются
    исходными данными; движок не выводит их из высоты этажа или DN трубы.
    """

    node_id: str
    downstream_pipe_id: str
    upstream_pipe_ids: tuple[str, ...]
    invert_absolute_elevation_m: float
    overflow_absolute_elevation_m: float
    storage_volume_m3: float
    overflow_location: str
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "upstream_pipe_ids", tuple(self.upstream_pipe_ids)
        )
        if not self.node_id.strip():
            raise ValueError("для внутреннего узла не задан ID")
        if not self.downstream_pipe_id.strip():
            raise ValueError(f"{self.node_id}: не задан нижний участок")
        if len(set(self.upstream_pipe_ids)) != len(self.upstream_pipe_ids):
            raise ValueError(f"{self.node_id}: верхний участок задан повторно")
        if any(not row.strip() for row in self.upstream_pipe_ids):
            raise ValueError(f"{self.node_id}: пустой ID верхнего участка")
        if (
            self.overflow_absolute_elevation_m
            <= self.invert_absolute_elevation_m
        ):
            raise ValueError(
                f"{self.node_id}: отметка перелива должна быть выше лотка"
            )
        if self.storage_volume_m3 <= 0:
            raise ValueError(f"{self.node_id}: объём хранения должен быть > 0")
        if not self.overflow_location.strip():
            raise ValueError(
                f"{self.node_id}: не задано место аварийного выхода"
            )
        if not self.source.strip():
            raise ValueError(f"{self.node_id}: не задан источник геометрии")


@dataclass
class NetworkStorageNodeState:
    stored_water_m3: float = 0.0
    suspended_solids_kg: float = 0.0
    flooded_volume_m3: float = 0.0

    def __post_init__(self) -> None:
        if min(
            self.stored_water_m3,
            self.suspended_solids_kg,
            self.flooded_volume_m3,
        ) < 0:
            raise ValueError(
                "состояние внутреннего узла не может быть отрицательным"
            )


@dataclass
class NetworkStorageNode:
    config: NetworkStorageNodeConfig
    state: NetworkStorageNodeState

    def __post_init__(self) -> None:
        if self.state.stored_water_m3 > self.config.storage_volume_m3 + 1e-12:
            raise ValueError(
                f"{self.config.node_id}: начальный объём больше объёма хранения"
            )
        if (
            self.state.suspended_solids_kg > 0
            and self.state.stored_water_m3 == 0
        ):
            raise ValueError(
                f"{self.config.node_id}: взвеси заданы без объёма воды"
            )


@dataclass(frozen=True)
class PipeStepSnapshot:
    time_seconds: float
    pipe_id: str
    inflow_lps: float
    outflow_lps: float
    representative_flow_lps: float
    velocity_mps: float
    free_flow_velocity_mps: float
    fill_ratio_h_d: float
    available_fill_ratio: float
    stored_water_m3: float
    available_storage_m3: float
    suspended_solids_kg: float
    sediment_depth_mm: float
    deposited_mass_kg: float
    flooded_volume_m3: float
    cumulative_flooded_volume_m3: float
    downstream_rejected_lps: float
    free_flow_capacity_lps: float
    maximum_gravity_capacity_lps: float
    full_section_capacity_lps: float
    capacity_exceeded: bool
    status: PipeStatus
    active_flags: tuple[PipeStatus, ...]


@dataclass(frozen=True)
class NodeStepSnapshot:
    time_seconds: float
    node_id: str
    downstream_pipe_id: str
    invert_absolute_elevation_m: float
    overflow_absolute_elevation_m: float
    inflow_lps: float
    outflow_lps: float
    stored_water_m3: float
    storage_volume_m3: float
    fill_ratio: float
    suspended_solids_kg: float
    flooded_volume_m3: float
    cumulative_flooded_volume_m3: float
    status: NodeStatus
    overflow_location: str


@dataclass(frozen=True)
class NetworkStepSnapshot:
    time_seconds: float
    dt_seconds: float
    pipes: tuple[PipeStepSnapshot, ...]
    nodes: tuple[NodeStepSnapshot, ...]
    external_inflow_m3: float
    outlet_discharge_m3: float
    flooded_volume_m3: float
    deposited_mass_kg: float
    water_balance_error_m3: float
    solids_balance_error_kg: float

    def by_pipe(self, pipe_id: str) -> PipeStepSnapshot:
        for row in self.pipes:
            if row.pipe_id == pipe_id:
                return row
        raise KeyError(pipe_id)

    def by_node(self, node_id: str) -> NodeStepSnapshot:
        for row in self.nodes:
            if row.node_id == node_id:
                return row
        raise KeyError(node_id)


class SewerNetworkSimulator:
    """Пошаговый расчёт сети без ветвления потока и без циклов."""

    def __init__(
        self,
        *,
        pipes: Iterable[PipeSection],
        connections: Iterable[PipeConnection],
        inflows: Iterable[InflowHydrograph],
        outlets: Iterable[OutletBoundary],
        nodes: Iterable[NetworkStorageNode] = (),
        sediment_models: Optional[Mapping[str, NetworkSedimentModel]] = None,
    ) -> None:
        pipe_rows = list(pipes)
        self.pipes = {row.config.section_id: row for row in pipe_rows}
        if not self.pipes:
            raise ValueError("для симуляции не задано ни одного участка")
        if len(self.pipes) != len(pipe_rows):
            raise ValueError("обозначения участков должны быть уникальными")
        for pipe in pipe_rows:
            state = pipe.state
            if state.suspended_solids_kg > 0 and state.stored_water_m3 == 0:
                raise ValueError(
                    f"{pipe.config.section_id}: взвеси заданы без объёма воды"
                )

        self.downstream: dict[str, str] = {}
        self.upstreams: dict[str, list[str]] = {
            pipe_id: [] for pipe_id in self.pipes
        }
        seen_connections: set[tuple[str, str]] = set()
        for edge in connections:
            pair = (edge.upstream_pipe_id, edge.downstream_pipe_id)
            if pair in seen_connections:
                raise ValueError(f"повторная связь {pair[0]} -> {pair[1]}")
            seen_connections.add(pair)
            if pair[0] not in self.pipes or pair[1] not in self.pipes:
                raise ValueError(
                    f"связь {pair[0]} -> {pair[1]} содержит неизвестный участок"
                )
            if pair[0] in self.downstream:
                raise ValueError(
                    f"{pair[0]}: разделение потока на несколько труб пока не поддерживается"
                )
            self.downstream[pair[0]] = pair[1]
            self.upstreams[pair[1]].append(pair[0])

        self.topological_order = self._build_topological_order()
        terminals = {
            pipe_id for pipe_id in self.pipes
            if pipe_id not in self.downstream
        }
        outlet_rows = list(outlets)
        self.outlets = {row.pipe_id: row for row in outlet_rows}
        if len(self.outlets) != len(outlet_rows):
            raise ValueError("выходная граница участка задана повторно")
        if set(self.outlets) != terminals:
            missing = sorted(terminals - set(self.outlets))
            extra = sorted(set(self.outlets) - terminals)
            raise ValueError(
                "выходные границы должны совпадать с конечными участками; "
                f"не заданы: {missing or 'нет'}, лишние: {extra or 'нет'}"
            )

        self.inflows_by_pipe: dict[str, list[InflowHydrograph]] = {
            pipe_id: [] for pipe_id in self.pipes
        }
        for hydrograph in inflows:
            if hydrograph.pipe_id not in self.pipes:
                raise ValueError(
                    f"гидрограф ссылается на неизвестный участок {hydrograph.pipe_id}"
                )
            self.inflows_by_pipe[hydrograph.pipe_id].append(hydrograph)

        node_rows = list(nodes)
        self.nodes = {row.config.node_id: row for row in node_rows}
        if len(self.nodes) != len(node_rows):
            raise ValueError("ID внутренних узлов должны быть уникальными")
        self.node_by_downstream_pipe: dict[str, NetworkStorageNode] = {}
        for node in node_rows:
            config = node.config
            if config.downstream_pipe_id not in self.pipes:
                raise ValueError(
                    f"{config.node_id}: неизвестный нижний участок "
                    f"{config.downstream_pipe_id}"
                )
            if config.downstream_pipe_id in self.node_by_downstream_pipe:
                raise ValueError(
                    f"{config.downstream_pipe_id}: у входа задано несколько узлов"
                )
            expected = set(self.upstreams[config.downstream_pipe_id])
            actual = set(config.upstream_pipe_ids)
            if actual != expected:
                raise ValueError(
                    f"{config.node_id}: верхние участки не совпадают с графом; "
                    f"ожидались {sorted(expected)}, заданы {sorted(actual)}"
                )
            self.node_by_downstream_pipe[config.downstream_pipe_id] = node

        self.sediment_models = dict(sediment_models or {})
        unknown_models = set(self.sediment_models) - set(self.pipes)
        if unknown_models:
            raise ValueError(
                "модель осадка ссылается на неизвестные участки: "
                + ", ".join(sorted(unknown_models))
            )
        self.time_seconds = 0.0

    def step(self, dt_seconds: float) -> NetworkStepSnapshot:
        if dt_seconds <= 0:
            raise ValueError("шаг времени должен быть больше 0")

        ids = self.topological_order
        old_volume = {
            pipe_id: self.pipes[pipe_id].state.stored_water_m3
            for pipe_id in ids
        }
        old_solids = {
            pipe_id: self.pipes[pipe_id].state.suspended_solids_kg
            for pipe_id in ids
        }
        old_total_volume = sum(old_volume.values())
        old_total_solids = sum(old_solids.values())
        old_node_volume = {
            node_id: node.state.stored_water_m3
            for node_id, node in self.nodes.items()
        }
        old_node_solids = {
            node_id: node.state.suspended_solids_kg
            for node_id, node in self.nodes.items()
        }
        old_total_volume += sum(old_node_volume.values())
        old_total_solids += sum(old_node_solids.values())

        external_volume: dict[str, float] = {}
        external_solids: dict[str, float] = {}
        for pipe_id in ids:
            volume_m3 = 0.0
            mass_kg = 0.0
            for hydrograph in self.inflows_by_pipe[pipe_id]:
                point = hydrograph.value_at(self.time_seconds)
                row_volume = point.flow_lps / 1000.0 * dt_seconds
                volume_m3 += row_volume
                mass_kg += row_volume * point.suspended_solids_mg_l * 0.001
            external_volume[pipe_id] = volume_m3
            external_solids[pipe_id] = mass_kg

        node_external_volume = {node_id: 0.0 for node_id in self.nodes}
        node_external_solids = {node_id: 0.0 for node_id in self.nodes}
        for pipe_id, node in self.node_by_downstream_pipe.items():
            node_external_volume[node.config.node_id] = external_volume[pipe_id]
            node_external_solids[node.config.node_id] = external_solids[pipe_id]
            external_volume[pipe_id] = 0.0
            external_solids[pipe_id] = 0.0

        desired_out: dict[str, float] = {}
        for pipe_id in ids:
            pipe = self.pipes[pipe_id]
            geometry = pipe.geometry_for_stored_volume(old_volume[pipe_id])
            if geometry is None:
                desired_out[pipe_id] = 0.0
                continue
            capacity_lps, velocity_mps, _ = pipe.capacity_at_water_surface(
                geometry.water_surface_from_original_invert_m
            )
            courant = velocity_mps * dt_seconds / pipe.config.length_m
            if courant > 1.0 + 1e-12:
                maximum_dt = pipe.config.length_m / velocity_mps
                raise ValueError(
                    f"{pipe_id}: нарушено условие Куранта C={courant:.3f}; "
                    f"шаг должен быть не более {maximum_dt:.3f} с либо участок "
                    "нужно разделить на расчётные ячейки"
                )
            desired_out[pipe_id] = min(
                old_volume[pipe_id],
                capacity_lps / 1000.0 * dt_seconds,
            )

        actual_out: dict[str, float] = {}
        for pipe_id, boundary in self.outlets.items():
            actual_out[pipe_id] = boundary.accepted_volume_m3(
                desired_out[pipe_id],
                dt_seconds,
            )

        rejected_out = {pipe_id: 0.0 for pipe_id in ids}
        for downstream_id in reversed(ids):
            upstream_ids = self.upstreams[downstream_id]
            if not upstream_ids:
                continue
            if downstream_id in self.node_by_downstream_pipe:
                for upstream_id in upstream_ids:
                    actual_out[upstream_id] = desired_out[upstream_id]
                continue
            base_volume = (
                old_volume[downstream_id]
                - actual_out[downstream_id]
                + external_volume[downstream_id]
            )
            room = max(
                0.0,
                self.pipes[downstream_id].available_storage_m3 - base_volume,
            )
            attempted = sum(desired_out[row] for row in upstream_ids)
            ratio = 1.0 if attempted <= room or attempted == 0 else room / attempted
            for upstream_id in upstream_ids:
                accepted = desired_out[upstream_id] * ratio
                actual_out[upstream_id] = accepted
                rejected_out[upstream_id] = desired_out[upstream_id] - accepted

        incoming_internal = {pipe_id: 0.0 for pipe_id in ids}
        for upstream_id, downstream_id in self.downstream.items():
            if downstream_id not in self.node_by_downstream_pipe:
                incoming_internal[downstream_id] += actual_out[upstream_id]

        outgoing_solids: dict[str, float] = {}
        for pipe_id in ids:
            if old_volume[pipe_id] <= 0:
                outgoing_solids[pipe_id] = 0.0
            else:
                outgoing_solids[pipe_id] = (
                    old_solids[pipe_id]
                    * actual_out[pipe_id]
                    / old_volume[pipe_id]
                )

        incoming_internal_solids = {pipe_id: 0.0 for pipe_id in ids}
        for upstream_id, downstream_id in self.downstream.items():
            if downstream_id not in self.node_by_downstream_pipe:
                incoming_internal_solids[downstream_id] += (
                    outgoing_solids[upstream_id]
                )

        node_out_volume: dict[str, float] = {}
        node_out_solids: dict[str, float] = {}
        node_in_volume: dict[str, float] = {}
        node_flooded_volume: dict[str, float] = {}
        node_flooded_solids: dict[str, float] = {}
        for node_id, node in self.nodes.items():
            config = node.config
            upstream_volume = sum(
                actual_out[row] for row in config.upstream_pipe_ids
            )
            upstream_solids = sum(
                outgoing_solids[row] for row in config.upstream_pipe_ids
            )
            incoming = node_external_volume[node_id] + upstream_volume
            incoming_solids = node_external_solids[node_id] + upstream_solids
            node_in_volume[node_id] = incoming
            available_for_node = max(
                0.0,
                self.pipes[config.downstream_pipe_id].available_storage_m3
                - (
                    old_volume[config.downstream_pipe_id]
                    - actual_out[config.downstream_pipe_id]
                    + external_volume[config.downstream_pipe_id]
                    + incoming_internal[config.downstream_pipe_id]
                ),
            )
            mixed_volume = old_node_volume[node_id] + incoming
            mixed_solids = old_node_solids[node_id] + incoming_solids
            passed = min(mixed_volume, available_for_node)
            passed_fraction = passed / mixed_volume if mixed_volume > 0 else 0.0
            passed_solids = mixed_solids * passed_fraction
            remaining = mixed_volume - passed
            remaining_solids = mixed_solids - passed_solids
            overflow = max(0.0, remaining - config.storage_volume_m3)
            overflow_fraction = overflow / remaining if remaining > 0 else 0.0
            overflow_solids = remaining_solids * overflow_fraction
            node.state.stored_water_m3 = min(remaining, config.storage_volume_m3)
            node.state.suspended_solids_kg = max(
                0.0, remaining_solids - overflow_solids
            )
            node.state.flooded_volume_m3 += overflow
            node_out_volume[node_id] = passed
            node_out_solids[node_id] = passed_solids
            node_flooded_volume[node_id] = overflow
            node_flooded_solids[node_id] = overflow_solids
            incoming_internal[config.downstream_pipe_id] += passed
            incoming_internal_solids[config.downstream_pipe_id] += passed_solids

        new_volume: dict[str, float] = {}
        new_solids: dict[str, float] = {}
        flooded_volume = {pipe_id: 0.0 for pipe_id in ids}
        flooded_solids = {pipe_id: 0.0 for pipe_id in ids}
        retained_incoming_fraction = {pipe_id: 1.0 for pipe_id in ids}
        for pipe_id in ids:
            volume = (
                old_volume[pipe_id]
                - actual_out[pipe_id]
                + external_volume[pipe_id]
                + incoming_internal[pipe_id]
            )
            solids = (
                old_solids[pipe_id]
                - outgoing_solids[pipe_id]
                + external_solids[pipe_id]
                + incoming_internal_solids[pipe_id]
            )
            capacity = self.pipes[pipe_id].available_storage_m3
            if volume > capacity + 1e-12:
                overflow = volume - capacity
                overflow_fraction = overflow / volume
                overflow_solids = solids * overflow_fraction
                flooded_volume[pipe_id] += overflow
                flooded_solids[pipe_id] += overflow_solids
                volume = capacity
                solids -= overflow_solids
                retained_incoming_fraction[pipe_id] = 1.0 - overflow_fraction
            new_volume[pipe_id] = max(0.0, volume)
            new_solids[pipe_id] = max(0.0, solids)

        deposited_mass = {pipe_id: 0.0 for pipe_id in ids}
        for pipe_id in ids:
            pipe = self.pipes[pipe_id]
            pipe.state.stored_water_m3 = new_volume[pipe_id]
            pipe.state.suspended_solids_kg = new_solids[pipe_id]
            model = self.sediment_models.get(pipe_id)
            geometry = pipe.geometry_for_stored_volume(new_volume[pipe_id])
            if model is None or geometry is None:
                continue

            inflow_volume = external_volume[pipe_id] + incoming_internal[pipe_id]
            outflow_volume = actual_out[pipe_id]
            through_flow_lps = outflow_volume / dt_seconds * 1000.0
            velocity_mps = (
                through_flow_lps / 1000.0 / geometry.water_area_m2
            )
            deficit = max(
                0.0,
                1.0 - velocity_mps / pipe.config.critical_velocity_mps,
            )
            capture_fraction = (
                model.capture_efficiency_at_zero_velocity
                * deficit ** model.velocity_deficit_exponent
            )
            incoming_mass = (
                external_solids[pipe_id] + incoming_internal_solids[pipe_id]
            ) * retained_incoming_fraction[pipe_id]
            requested_mass = min(
                pipe.state.suspended_solids_kg,
                incoming_mass * capture_fraction,
            )
            deposit = pipe.deposit_suspended_mass(
                deposited_mass_kg=requested_mass,
                sediment_bulk_density_kg_m3=model.sediment_bulk_density_kg_m3,
                capture_fraction=capture_fraction,
            )
            deposited_mass[pipe_id] = deposit.deposited_mass_kg
            pipe.state.suspended_solids_kg -= deposit.deposited_mass_kg

            # Осадок уменьшает доступный объём. Если вода больше нового
            # сечения, лишний объём фиксируется как затопление этого шага.
            if pipe.state.stored_water_m3 > pipe.available_storage_m3 + 1e-12:
                overflow = pipe.state.stored_water_m3 - pipe.available_storage_m3
                overflow_fraction = overflow / pipe.state.stored_water_m3
                overflow_solids = (
                    pipe.state.suspended_solids_kg * overflow_fraction
                )
                pipe.state.stored_water_m3 = pipe.available_storage_m3
                pipe.state.suspended_solids_kg -= overflow_solids
                flooded_volume[pipe_id] += overflow
                flooded_solids[pipe_id] += overflow_solids

        rows: list[PipeStepSnapshot] = []
        for pipe_id in ids:
            pipe = self.pipes[pipe_id]
            pipe.state.flooded_volume_m3 += flooded_volume[pipe_id]
            geometry = pipe.geometry_for_stored_volume(pipe.state.stored_water_m3)
            inflow_volume = external_volume[pipe_id] + incoming_internal[pipe_id]
            inflow_lps = inflow_volume / dt_seconds * 1000.0
            outflow_lps = actual_out[pipe_id] / dt_seconds * 1000.0
            representative_flow_lps = (inflow_lps + outflow_lps) / 2.0
            if geometry is None:
                velocity_mps = 0.0
                current_free_velocity = 0.0
                fill_ratio = 0.0
                available_fill = 0.0
                free_capacity = 0.0
            else:
                velocity_mps = (
                    outflow_lps / 1000.0 / geometry.water_area_m2
                )
                free_capacity, current_free_velocity, _ = (
                    pipe.capacity_at_water_surface(
                        geometry.water_surface_from_original_invert_m
                    )
                )
                fill_ratio = geometry.fill_ratio_h_d
                available_fill = geometry.available_fill_ratio
            maximum_capacity = pipe.maximum_gravity_capacity_lps
            full_capacity = pipe.full_section_capacity_lps
            capacity_exceeded = inflow_lps > maximum_capacity + 1e-12

            flags: list[PipeStatus] = []
            if (
                geometry is not None
                and velocity_mps < pipe.config.critical_velocity_mps
            ):
                flags.append(PipeStatus.SILTING)
            if (
                geometry is not None
                and available_fill + 1e-12 >= pipe.config.critical_fill_ratio
            ) or rejected_out[pipe_id] > 1e-12 or capacity_exceeded:
                flags.append(PipeStatus.CRITICAL_FILL)
            if flooded_volume[pipe_id] > 1e-12:
                flags.append(PipeStatus.FLOODING)
            status = (
                PipeStatus.FLOODING
                if PipeStatus.FLOODING in flags
                else PipeStatus.CRITICAL_FILL
                if PipeStatus.CRITICAL_FILL in flags
                else PipeStatus.SILTING
                if PipeStatus.SILTING in flags
                else PipeStatus.NORMAL
            )
            rows.append(PipeStepSnapshot(
                time_seconds=self.time_seconds + dt_seconds,
                pipe_id=pipe_id,
                inflow_lps=inflow_lps,
                outflow_lps=outflow_lps,
                representative_flow_lps=representative_flow_lps,
                velocity_mps=velocity_mps,
                free_flow_velocity_mps=current_free_velocity,
                fill_ratio_h_d=fill_ratio,
                available_fill_ratio=available_fill,
                stored_water_m3=pipe.state.stored_water_m3,
                available_storage_m3=pipe.available_storage_m3,
                suspended_solids_kg=pipe.state.suspended_solids_kg,
                sediment_depth_mm=pipe.state.sediment_depth_mm,
                deposited_mass_kg=deposited_mass[pipe_id],
                flooded_volume_m3=flooded_volume[pipe_id],
                cumulative_flooded_volume_m3=pipe.state.flooded_volume_m3,
                downstream_rejected_lps=(
                    rejected_out[pipe_id] / dt_seconds * 1000.0
                ),
                free_flow_capacity_lps=free_capacity,
                maximum_gravity_capacity_lps=maximum_capacity,
                full_section_capacity_lps=full_capacity,
                capacity_exceeded=capacity_exceeded,
                status=status,
                active_flags=tuple(flags),
            ))

        node_rows: list[NodeStepSnapshot] = []
        for node_id, node in self.nodes.items():
            config = node.config
            flooded = node_flooded_volume[node_id]
            if flooded > 1e-12:
                status = NodeStatus.OVERFLOW
            elif node.state.stored_water_m3 > 1e-12:
                status = NodeStatus.STORING
            else:
                status = NodeStatus.EMPTY
            node_rows.append(NodeStepSnapshot(
                time_seconds=self.time_seconds + dt_seconds,
                node_id=node_id,
                downstream_pipe_id=config.downstream_pipe_id,
                invert_absolute_elevation_m=config.invert_absolute_elevation_m,
                overflow_absolute_elevation_m=(
                    config.overflow_absolute_elevation_m
                ),
                inflow_lps=node_in_volume[node_id] / dt_seconds * 1000.0,
                outflow_lps=node_out_volume[node_id] / dt_seconds * 1000.0,
                stored_water_m3=node.state.stored_water_m3,
                storage_volume_m3=config.storage_volume_m3,
                fill_ratio=(
                    node.state.stored_water_m3 / config.storage_volume_m3
                ),
                suspended_solids_kg=node.state.suspended_solids_kg,
                flooded_volume_m3=flooded,
                cumulative_flooded_volume_m3=node.state.flooded_volume_m3,
                status=status,
                overflow_location=config.overflow_location,
            ))

        external_total = (
            sum(external_volume.values()) + sum(node_external_volume.values())
        )
        outlet_total = sum(actual_out[row] for row in self.outlets)
        flood_total = (
            sum(flooded_volume.values()) + sum(node_flooded_volume.values())
        )
        new_total_volume = sum(
            pipe.state.stored_water_m3 for pipe in self.pipes.values()
        ) + sum(node.state.stored_water_m3 for node in self.nodes.values())
        water_error = (
            old_total_volume + external_total
            - new_total_volume - outlet_total - flood_total
        )

        external_mass_total = (
            sum(external_solids.values()) + sum(node_external_solids.values())
        )
        outlet_mass_total = sum(outgoing_solids[row] for row in self.outlets)
        flooded_mass_total = (
            sum(flooded_solids.values()) + sum(node_flooded_solids.values())
        )
        deposited_mass_total = sum(deposited_mass.values())
        new_total_solids = sum(
            pipe.state.suspended_solids_kg for pipe in self.pipes.values()
        ) + sum(node.state.suspended_solids_kg for node in self.nodes.values())
        solids_error = (
            old_total_solids + external_mass_total
            - new_total_solids
            - outlet_mass_total
            - flooded_mass_total
            - deposited_mass_total
        )
        if abs(water_error) > 1e-9:
            raise RuntimeError(f"нарушен баланс воды: {water_error:.12g} м³")
        if abs(solids_error) > 1e-9:
            raise RuntimeError(f"нарушен баланс взвесей: {solids_error:.12g} кг")

        self.time_seconds += dt_seconds
        return NetworkStepSnapshot(
            time_seconds=self.time_seconds,
            dt_seconds=dt_seconds,
            pipes=tuple(rows),
            nodes=tuple(node_rows),
            external_inflow_m3=external_total,
            outlet_discharge_m3=outlet_total,
            flooded_volume_m3=flood_total,
            deposited_mass_kg=deposited_mass_total,
            water_balance_error_m3=water_error,
            solids_balance_error_kg=solids_error,
        )

    def run(
        self,
        *,
        duration_seconds: float,
        dt_seconds: float,
    ) -> tuple[NetworkStepSnapshot, ...]:
        if duration_seconds <= 0:
            raise ValueError("продолжительность расчёта должна быть больше 0")
        if dt_seconds <= 0:
            raise ValueError("шаг времени должен быть больше 0")
        elapsed = 0.0
        result: list[NetworkStepSnapshot] = []
        while elapsed < duration_seconds - 1e-12:
            step_dt = min(dt_seconds, duration_seconds - elapsed)
            result.append(self.step(step_dt))
            elapsed += step_dt
        return tuple(result)

    def _build_topological_order(self) -> tuple[str, ...]:
        indegree = {
            pipe_id: len(self.upstreams[pipe_id]) for pipe_id in self.pipes
        }
        queue = sorted(
            pipe_id for pipe_id, degree in indegree.items() if degree == 0
        )
        result: list[str] = []
        while queue:
            pipe_id = queue.pop(0)
            result.append(pipe_id)
            downstream_id = self.downstream.get(pipe_id)
            if downstream_id is None:
                continue
            indegree[downstream_id] -= 1
            if indegree[downstream_id] == 0:
                queue.append(downstream_id)
                queue.sort()
        if len(result) != len(self.pipes):
            raise ValueError("граф самотечной сети содержит цикл")
        return tuple(result)

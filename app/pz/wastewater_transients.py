"""Связка реестра приборов с временной симуляцией внутренних сетей К1.

Топология и состав приборов читаются из ``Project.sewage``. Время, расход и
длительность каждого сброса остаются явными исходными данными. Модуль не
назначает вероятность одновременности и не моделирует наружную сеть.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.calc.sewer_network_simulation import (
    HydrographPoint,
    InflowHydrograph,
    NetworkStepSnapshot,
    OutletBoundary,
    OutletBoundaryKind,
    PipeConnection,
    SewerNetworkSimulator,
)
from app.calc.sewer_simulation import (
    PipeSection,
    PipeSectionConfig,
    PipeSectionState,
    PipeStatus,
)
from app.calc.sewer_stack_pressure import (
    DischargeEvent,
    StackPressureInput,
    StackPressureTimeline,
    StackVentilationMode,
    calculate_pressure_timeline,
)
from app.pz.project import (
    Project,
    SewerDischargeEventSpec,
    SewerElementSpec,
    SewerPipeSpec,
    SewageRiserSpec,
)
from app.pz.wastewater_topology import (
    GRAVITY_SOURCE_KINDS,
    SewerBranch,
    build_wastewater_topology,
)


@dataclass(frozen=True)
class ResolvedFixtureDischarge:
    event_id: str
    fixture_id: str
    fixture_name: str
    fixture_kind: str
    floor: int
    instance_no: int
    branch_section_id: str
    riser_id: str
    route_section_ids: Tuple[str, ...]
    start_seconds: float
    duration_seconds: float
    flow_lps: float
    source: str
    suspended_solids_mg_l: Optional[float]
    suspended_solids_source: str

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds

    def is_active(self, time_seconds: float) -> bool:
        return self.start_seconds <= time_seconds < self.end_seconds


@dataclass(frozen=True)
class TransientFlowPoint:
    time_seconds: float
    active_event_ids: Tuple[str, ...]
    total_flow_lps: float
    riser_flows_lps: Dict[str, float]
    section_flows_lps: Dict[str, float]


@dataclass(frozen=True)
class StackTransientCheck:
    riser_id: str
    design_flow_lps: float
    peak_scenario_flow_lps: float
    design_flow_ok: bool
    pressure_timeline: Optional[StackPressureTimeline]
    peak_vacuum_mm_water: Optional[float]
    allowable_vacuum_mm_water: Optional[float]
    vacuum_ok: Optional[bool]
    status: str
    note: str


@dataclass(frozen=True)
class NetworkTransientSummary:
    section_id: str
    peak_inflow_lps: float
    peak_outflow_lps: float
    peak_fill_ratio_h_d: float
    minimum_wet_velocity_mps: Optional[float]
    flooded_volume_m3: float
    final_stored_water_m3: float
    final_sediment_depth_mm: float
    status: PipeStatus


@dataclass
class WastewaterTransientAssessment:
    events: Tuple[ResolvedFixtureDischarge, ...] = ()
    points: Tuple[TransientFlowPoint, ...] = ()
    stack_checks: Tuple[StackTransientCheck, ...] = ()
    network_inflows: Tuple[InflowHydrograph, ...] = ()
    network_steps: Tuple[NetworkStepSnapshot, ...] = ()
    network_summaries: Tuple[NetworkTransientSummary, ...] = ()
    step_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    sediment_data_complete: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.events and self.points) and not self.errors

    @property
    def peak_total_flow_lps(self) -> float:
        return max((row.total_flow_lps for row in self.points), default=0.0)

    @property
    def report_points(self) -> Tuple[TransientFlowPoint, ...]:
        """Только моменты изменения состояния плюс конечная нулевая точка."""
        selected: List[TransientFlowPoint] = []
        previous = None
        for row in self.points:
            signature = (
                row.active_event_ids,
                tuple(row.riser_flows_lps.items()),
                tuple(row.section_flows_lps.items()),
            )
            if signature != previous:
                selected.append(row)
                previous = signature
        if self.points and selected[-1] is not self.points[-1]:
            selected.append(self.points[-1])
        return tuple(selected)


_VENTILATION_MODES = {
    "ventilated": StackVentilationMode.VENTILATED,
    "unventilated": StackVentilationMode.UNVENTILATED,
    "vacuum_valve": StackVentilationMode.AIR_ADMITTANCE_VALVE,
}


def _event_times(step_seconds: float, end_seconds: float) -> Tuple[float, ...]:
    count = int(round(end_seconds / step_seconds))
    return tuple(round(index * step_seconds, 9) for index in range(count + 1))


def _fixture_instance_error(
    event: SewerDischargeEventSpec,
    fixture: SewerElementSpec,
) -> Optional[str]:
    floor_to = fixture.floor_to if fixture.floor_to is not None else fixture.floor_from
    if not fixture.floor_from <= event.floor <= floor_to:
        return (
            f"{event.event_id}: этаж {event.floor} вне диапазона прибора "
            f"{fixture.element_id} "
            f"({fixture.floor_from}--{floor_to})"
        )
    if fixture.typical_quantity is None:
        return (
            f"{event.event_id}: у {fixture.element_id} не задано количество "
            "экземпляров на этаже"
        )
    if event.instance_no > fixture.typical_quantity:
        return (
            f"{event.event_id}: экземпляр {event.instance_no} превышает "
            f"количество {fixture.typical_quantity} на этаже"
        )
    ordinal = (
        (event.floor - fixture.floor_from) * fixture.typical_quantity
        + event.instance_no
    )
    if ordinal > fixture.quantity:
        return (
            f"{event.event_id}: выбранный экземпляр выходит за общее "
            f"количество {fixture.quantity}"
        )
    return None


def _main_route(
    riser_id: str,
    mains: Tuple[SewerPipeSpec, ...],
) -> Tuple[Tuple[str, ...], Optional[str]]:
    outgoing: Dict[str, List[SewerPipeSpec]] = {}
    for pipe in mains:
        if pipe.system == "K1":
            outgoing.setdefault(pipe.from_node, []).append(pipe)
    route: List[str] = []
    visited = set()
    node = riser_id
    while node in outgoing:
        if node in visited:
            return (), f"{riser_id}: цикл в маршруте временного сценария"
        visited.add(node)
        choices = outgoing[node]
        if len(choices) != 1:
            return (), (
                f"{node}: временной расход нельзя распределить между "
                f"{len(choices)} участками без явных долей"
            )
        pipe = choices[0]
        route.append(pipe.section_id)
        node = pipe.to_node
    if not route:
        return (), f"{riser_id}: не найден горизонтальный путь до выпуска"
    return tuple(route), None


def _resolve_events(
    project: Project,
    result: WastewaterTransientAssessment,
) -> Tuple[ResolvedFixtureDischarge, ...]:
    topology = build_wastewater_topology(project)
    if topology.errors:
        result.errors.extend(
            "топология: " + row for row in topology.errors
        )
        return ()
    fixture_index = {
        element.element_id: element
        for element in project.sewage.elements
        if element.system == "K1" and element.kind in GRAVITY_SOURCE_KINDS
    }
    branch_index: Dict[str, SewerBranch] = {
        element.element_id: branch
        for branch in topology.branches
        if branch.pipe.system == "K1"
        for element in branch.elements
        if element.kind in GRAVITY_SOURCE_KINDS
    }
    routes: Dict[str, Tuple[str, ...]] = {}
    for riser_id in {
        branch.riser_id for branch in topology.branches
        if branch.pipe.system == "K1"
    }:
        route, error = _main_route(riser_id, tuple(topology.mains))
        if error:
            result.errors.append(error)
        else:
            routes[riser_id] = route
    if result.errors:
        return ()

    rows: List[ResolvedFixtureDischarge] = []
    for event in project.sewage.discharge_events:
        fixture = fixture_index.get(event.fixture_id)
        if fixture is None:
            result.errors.append(
                f"{event.event_id}: прибор {event.fixture_id} отсутствует "
                "в реестре приёмников К1"
            )
            continue
        branch = branch_index.get(event.fixture_id)
        if branch is None:
            result.errors.append(
                f"{event.event_id}: для {event.fixture_id} не найдена "
                "этажная ветвь"
            )
            continue
        instance_error = _fixture_instance_error(event, fixture)
        if instance_error:
            result.errors.append(instance_error)
            continue
        main_route = routes.get(branch.riser_id)
        if not main_route:
            result.errors.append(
                f"{event.event_id}: для стояка {branch.riser_id} нет "
                "маршрута до выпуска"
            )
            continue
        rows.append(ResolvedFixtureDischarge(
            event_id=event.event_id,
            fixture_id=fixture.element_id,
            fixture_name=fixture.name,
            fixture_kind=fixture.kind,
            floor=event.floor,
            instance_no=event.instance_no,
            branch_section_id=branch.pipe.section_id,
            riser_id=branch.riser_id,
            route_section_ids=(
                branch.pipe.section_id,
                branch.riser_id,
                *main_route,
            ),
            start_seconds=event.start_seconds,
            duration_seconds=event.duration_seconds,
            flow_lps=event.flow_lps,
            source=event.source,
            suspended_solids_mg_l=event.suspended_solids_mg_l,
            suspended_solids_source=event.suspended_solids_source,
        ))

    by_instance: Dict[Tuple[str, int, int], List[ResolvedFixtureDischarge]] = {}
    for row in rows:
        by_instance.setdefault(
            (row.fixture_id, row.floor, row.instance_no), []
        ).append(row)
    for key, instance_events in by_instance.items():
        ordered = sorted(instance_events, key=lambda row: row.start_seconds)
        for previous, current in zip(ordered, ordered[1:]):
            if current.start_seconds < previous.end_seconds:
                result.errors.append(
                    f"{previous.event_id}/{current.event_id}: один экземпляр "
                    f"{key[0]}, этаж {key[1]}, № {key[2]} не может выполнять "
                    "перекрывающиеся сбросы"
                )
    return tuple(sorted(rows, key=lambda row: (row.start_seconds, row.event_id)))


def _build_flow_points(
    events: Tuple[ResolvedFixtureDischarge, ...],
    times: Tuple[float, ...],
) -> Tuple[TransientFlowPoint, ...]:
    points: List[TransientFlowPoint] = []
    for time_seconds in times:
        active = tuple(row for row in events if row.is_active(time_seconds))
        riser_flows: Dict[str, float] = {}
        section_flows: Dict[str, float] = {}
        for event in active:
            riser_flows[event.riser_id] = (
                riser_flows.get(event.riser_id, 0.0) + event.flow_lps
            )
            for section_id in event.route_section_ids:
                section_flows[section_id] = (
                    section_flows.get(section_id, 0.0) + event.flow_lps
                )
        points.append(TransientFlowPoint(
            time_seconds=time_seconds,
            active_event_ids=tuple(row.event_id for row in active),
            total_flow_lps=round(sum(row.flow_lps for row in active), 9),
            riser_flows_lps={
                key: round(value, 9) for key, value in sorted(riser_flows.items())
            },
            section_flows_lps={
                key: round(value, 9) for key, value in sorted(section_flows.items())
            },
        ))
    return tuple(points)


def _stack_input_missing(riser: SewageRiserSpec) -> Tuple[str, ...]:
    missing = []
    for name, value in (
        ("рабочая высота", riser.working_height_m),
        ("внутренний диаметр стояка", riser.inner_diameter_mm),
        ("внутренний диаметр отвода", riser.branch_inner_diameter_mm),
        ("минимальный гидрозатвор", riser.minimum_trap_seal_mm),
    ):
        if value is None:
            missing.append(name)
    if not riser.pressure_input_source.strip():
        missing.append("источник исходных данных давления")
    if riser.ventilation == "vacuum_valve":
        if riser.air_valve_free_area_mm2 is None:
            missing.append("площадь живого сечения воздушного клапана")
        if not riser.air_valve_source.strip():
            missing.append("паспорт воздушного клапана")
    return tuple(missing)


def _build_stack_checks(
    project: Project,
    events: Tuple[ResolvedFixtureDischarge, ...],
    times: Tuple[float, ...],
) -> Tuple[StackTransientCheck, ...]:
    specs = {row.riser_id: row for row in project.sewage.risers}
    checks: List[StackTransientCheck] = []
    for riser_id in sorted({row.riser_id for row in events}):
        riser = specs.get(riser_id)
        riser_events = tuple(row for row in events if row.riser_id == riser_id)
        peak_flow = max(
            sum(row.flow_lps for row in riser_events if row.is_active(time))
            for time in times
        )
        if riser is None:
            checks.append(StackTransientCheck(
                riser_id=riser_id,
                design_flow_lps=0.0,
                peak_scenario_flow_lps=peak_flow,
                design_flow_ok=False,
                pressure_timeline=None,
                peak_vacuum_mm_water=None,
                allowable_vacuum_mm_water=None,
                vacuum_ok=None,
                status="data_required",
                note="не задан расчётный узел стояка",
            ))
            continue
        design_ok = peak_flow <= riser.design_flow_lps + 1e-12
        missing = _stack_input_missing(riser)
        if missing:
            checks.append(StackTransientCheck(
                riser_id=riser_id,
                design_flow_lps=riser.design_flow_lps,
                peak_scenario_flow_lps=peak_flow,
                design_flow_ok=design_ok,
                pressure_timeline=None,
                peak_vacuum_mm_water=None,
                allowable_vacuum_mm_water=None,
                vacuum_ok=None,
                status="data_required" if design_ok else "critical",
                note="не хватает: " + ", ".join(missing),
            ))
            continue
        pressure_input = StackPressureInput(
            stack_id=riser.riser_id,
            ventilation_mode=_VENTILATION_MODES[riser.ventilation],
            inner_diameter_mm=float(riser.inner_diameter_mm),
            branch_inner_diameter_mm=float(riser.branch_inner_diameter_mm),
            branch_angle_deg=riser.branch_angle_deg,
            working_height_m=float(riser.working_height_m),
            minimum_trap_seal_mm=float(riser.minimum_trap_seal_mm),
            source=riser.pressure_input_source,
            air_valve_free_area_mm2=riser.air_valve_free_area_mm2,
            air_valve_source=riser.air_valve_source or None,
        )
        timeline = calculate_pressure_timeline(
            pressure_input,
            events=(
                DischargeEvent(
                    event_id=row.event_id,
                    start_seconds=row.start_seconds,
                    duration_seconds=row.duration_seconds,
                    flow_lps=row.flow_lps,
                    source=row.source,
                )
                for row in riser_events
            ),
            times_seconds=times,
        )
        peak_vacuum = max(row.vacuum_mm_water for row in timeline.points)
        vacuum_ok = all(row.vacuum_within_limit for row in timeline.points)
        status = "verified" if design_ok and vacuum_ok else "critical"
        notes = []
        if not design_ok:
            notes.append("пик сценария превышает расчётный расход стояка")
        if not vacuum_ok:
            notes.append("разрежение превышает 0,9 hз")
        if not notes:
            notes.append("расход и разрежение сценария допустимы")
        checks.append(StackTransientCheck(
            riser_id=riser_id,
            design_flow_lps=riser.design_flow_lps,
            peak_scenario_flow_lps=peak_flow,
            design_flow_ok=design_ok,
            pressure_timeline=timeline,
            peak_vacuum_mm_water=peak_vacuum,
            allowable_vacuum_mm_water=pressure_input.allowable_vacuum_mm_water,
            vacuum_ok=vacuum_ok,
            status=status,
            note="; ".join(notes),
        ))
    return tuple(checks)


def _build_network_inflows(
    events: Tuple[ResolvedFixtureDischarge, ...],
    points: Tuple[TransientFlowPoint, ...],
    mains: Tuple[SewerPipeSpec, ...],
    result: WastewaterTransientAssessment,
) -> Tuple[InflowHydrograph, ...]:
    main_ids = {row.section_id for row in mains if row.system == "K1"}
    by_injection: Dict[str, List[ResolvedFixtureDischarge]] = {}
    for event in events:
        main_route = [
            section_id for section_id in event.route_section_ids
            if section_id in main_ids
        ]
        if not main_route:
            result.errors.append(
                f"{event.event_id}: отсутствует точка ввода в горизонтальную сеть"
            )
            continue
        by_injection.setdefault(main_route[0], []).append(event)

    all_solids_known = all(
        row.suspended_solids_mg_l is not None for row in events
    )
    if not all_solids_known:
        result.warnings.append(
            "концентрация взвешенных веществ задана не для всех событий: "
            "гидрограф пригоден для гидравлики, но прогноз осадка отключён"
        )
    result.sediment_data_complete = all_solids_known
    inflows: List[InflowHydrograph] = []
    for pipe_id, rows in sorted(by_injection.items()):
        hydro_points: List[HydrographPoint] = []
        for point in points:
            active = [row for row in rows if row.is_active(point.time_seconds)]
            flow = sum(row.flow_lps for row in active)
            if flow > 0 and all(
                row.suspended_solids_mg_l is not None for row in active
            ):
                concentration = sum(
                    row.flow_lps * float(row.suspended_solids_mg_l)
                    for row in active
                ) / flow
            else:
                concentration = 0.0
            hydro_points.append(HydrographPoint(
                time_seconds=point.time_seconds,
                flow_lps=flow,
                suspended_solids_mg_l=concentration,
            ))
        inflows.append(InflowHydrograph(
            pipe_id=pipe_id,
            points=tuple(hydro_points),
            source="; ".join(dict.fromkeys(row.source for row in rows)),
        ))
    return tuple(inflows)


def _network_missing(pipe: SewerPipeSpec) -> Tuple[str, ...]:
    missing = []
    if pipe.calculation_length_m is None:
        missing.append("расчётная длина")
    if pipe.slope_per_mille is None or pipe.slope_per_mille <= 0:
        missing.append("положительный уклон")
    if pipe.manning_n is None:
        missing.append("коэффициент Маннинга")
    if not pipe.hydraulic_source.strip():
        missing.append("источник шероховатости")
    if pipe.critical_velocity_mps is None:
        missing.append("критическая скорость")
    if not pipe.critical_velocity_source.strip():
        missing.append("источник критической скорости")
    if pipe.critical_fill_ratio is None:
        missing.append("порог критического наполнения")
    return tuple(missing)


def _run_network(
    mains: Tuple[SewerPipeSpec, ...],
    inflows: Tuple[InflowHydrograph, ...],
    step_seconds: float,
    end_seconds: float,
    result: WastewaterTransientAssessment,
) -> None:
    k1_mains = tuple(row for row in mains if row.system == "K1")
    for pipe in k1_mains:
        missing = _network_missing(pipe)
        if missing:
            result.warnings.append(
                f"{pipe.section_id}: динамическая сеть не рассчитана; "
                "не хватает: " + ", ".join(missing)
            )
    if any(_network_missing(pipe) for pipe in k1_mains):
        return

    sections = [PipeSection(
        PipeSectionConfig(
            section_id=pipe.section_id,
            length_m=float(pipe.calculation_length_m),
            inner_diameter_mm=pipe.inner_diameter_mm,
            slope_per_mille=float(pipe.slope_per_mille),
            material=pipe.material,
            manning_n=float(pipe.manning_n),
            roughness_source=pipe.hydraulic_source,
            critical_velocity_mps=float(pipe.critical_velocity_mps),
            critical_velocity_source=pipe.critical_velocity_source,
            critical_fill_ratio=float(pipe.critical_fill_ratio),
        ),
        PipeSectionState(),
    ) for pipe in k1_mains]
    by_from: Dict[str, List[SewerPipeSpec]] = {}
    for pipe in k1_mains:
        by_from.setdefault(pipe.from_node, []).append(pipe)
    connections = []
    for pipe in k1_mains:
        choices = by_from.get(pipe.to_node, [])
        if len(choices) > 1:
            result.errors.append(
                f"{pipe.to_node}: сетевой симулятор не поддерживает "
                "разделение потока без заданных долей"
            )
            return
        if choices:
            downstream = choices[0]
            connections.append(PipeConnection(
                upstream_pipe_id=pipe.section_id,
                downstream_pipe_id=downstream.section_id,
            ))
    upstream_ids = {row.upstream_pipe_id for row in connections}
    terminal_ids = {
        pipe.section_id for pipe in k1_mains
        if pipe.section_id not in upstream_ids
    }
    outlets = tuple(OutletBoundary(
        pipe_id=pipe_id,
        kind=OutletBoundaryKind.FREE_OUTFALL,
        source=(
            "граница внутренней системы у первого колодца; "
            "наружная сеть не моделируется"
        ),
    ) for pipe_id in sorted(terminal_ids))
    try:
        simulator = SewerNetworkSimulator(
            pipes=sections,
            connections=connections,
            inflows=inflows,
            outlets=outlets,
        )
        steps: List[NetworkStepSnapshot] = []
        for _ in range(int(round(end_seconds / step_seconds))):
            steps.append(simulator.step(step_seconds))
    except (ValueError, RuntimeError) as exc:
        result.warnings.append(
            "динамическая сеть не рассчитана: " + str(exc)
        )
        return
    result.network_steps = tuple(steps)

    summaries: List[NetworkTransientSummary] = []
    for pipe in k1_mains:
        rows = [step.by_pipe(pipe.section_id) for step in steps]
        wet_velocities = [
            row.velocity_mps for row in rows if row.outflow_lps > 1e-12
        ]
        status = PipeStatus.NORMAL
        for candidate in (
            PipeStatus.SILTING,
            PipeStatus.CRITICAL_FILL,
            PipeStatus.FLOODING,
        ):
            if any(candidate in row.active_flags for row in rows):
                status = candidate
        summaries.append(NetworkTransientSummary(
            section_id=pipe.section_id,
            peak_inflow_lps=max((row.inflow_lps for row in rows), default=0.0),
            peak_outflow_lps=max((row.outflow_lps for row in rows), default=0.0),
            peak_fill_ratio_h_d=max(
                (row.fill_ratio_h_d for row in rows), default=0.0
            ),
            minimum_wet_velocity_mps=(
                min(wet_velocities) if wet_velocities else None
            ),
            flooded_volume_m3=sum(row.flooded_volume_m3 for row in rows),
            final_stored_water_m3=(
                rows[-1].stored_water_m3 if rows else 0.0
            ),
            final_sediment_depth_mm=(
                rows[-1].sediment_depth_mm if rows else 0.0
            ),
            status=status,
        ))
    result.network_summaries = tuple(summaries)


def assess_wastewater_transients(project: Project) -> WastewaterTransientAssessment:
    """Рассчитать единый детерминированный сценарий внутренних систем К1."""
    result = WastewaterTransientAssessment(
        step_seconds=project.sewage.transient_step_seconds,
    )
    if not project.sewage.discharge_events:
        result.warnings.append(
            "сценарные сбросы не заданы; нормативный расчёт qₛ сохраняется, "
            "временная симуляция не выполняется"
        )
        return result
    step = project.sewage.transient_step_seconds
    if step is None or step <= 0:
        result.errors.append("для временного сценария нужен положительный шаг")
        return result
    events = _resolve_events(project, result)
    result.events = events
    if result.errors or not events:
        return result
    for event in events:
        for field_name, value in (
            ("начало", event.start_seconds),
            ("длительность", event.duration_seconds),
        ):
            ratio = value / step
            if abs(ratio - round(ratio)) > 1e-9:
                result.errors.append(
                    f"{event.event_id}: {field_name} {value:g} с не кратно "
                    f"шагу {step:g} с"
                )
    if result.errors:
        return result

    last_event_end = max(row.end_seconds for row in events)
    explicit_duration = project.sewage.transient_duration_seconds
    if explicit_duration is not None and explicit_duration < last_event_end:
        result.errors.append(
            "горизонт симуляции меньше окончания последнего события"
        )
        return result
    end_seconds = explicit_duration or last_event_end
    ratio = end_seconds / step
    if abs(ratio - round(ratio)) > 1e-9:
        result.errors.append(
            f"горизонт {end_seconds:g} с не кратен шагу {step:g} с"
        )
        return result
    result.duration_seconds = end_seconds
    if project.sewage.transient_duration_seconds is None:
        result.warnings.append(
            "горизонт симуляции не задан: расчёт остановлен в момент "
            "окончания последнего сброса, последующее опорожнение не проверено"
        )
    times = _event_times(step, end_seconds)
    result.points = _build_flow_points(events, times)
    result.stack_checks = _build_stack_checks(project, events, times)

    topology = build_wastewater_topology(project)
    mains = tuple(topology.mains)
    result.network_inflows = _build_network_inflows(
        events,
        result.points,
        mains,
        result,
    )
    if not result.errors:
        _run_network(
            mains,
            result.network_inflows,
            step,
            end_seconds,
            result,
        )
    if (
        project.sewage.result is not None
        and result.peak_total_flow_lps
        > project.sewage.result.total.q_sewage_lps + 1e-12
    ):
        result.warnings.append(
            "пик временного сценария превышает нормативный расчётный "
            "расход системы qₛ"
        )
    return result

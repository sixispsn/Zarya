"""Strict project inputs for the separate gravity K3 principle scheme.

K3 is intentionally kept outside the combined K1/K2 drawing.  This resolver
filters the common wastewater register to the production-wastewater system,
validates its directed gravity graph and exposes only confirmed rows to the
drawing layer.  A pressure main or a sewage pump is a separate hydraulic
regime and therefore blocks this gravity sheet instead of being sketched as a
continuation of it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_project_inputs import (
    BuildingPipeProjectInput,
    BuildingTransitionProjectInput,
    _building_pipe_input,
    _is_horizontal_building_edge,
    _is_riser_pipe,
    _order_linear_system_chain,
    _section,
    _select_outlet_pipe,
    _system,
    _validate_building_pipe,
    _validate_transition_topology,
)
from app.pz.wastewater_topology import SewerBranch, build_wastewater_topology


@dataclass(frozen=True)
class K3BranchProjectInput:
    """One explicit gravity branch from a production receiver to a riser."""

    pipe: BuildingPipeProjectInput
    riser_id: str
    elements: tuple[SewerElementSpec, ...]
    floor_from: int
    floor_to: int
    room_number: str
    room_name: str
    connection_elbow_element_id: str
    connection_junction_element_id: str

    def applies_to_floor(self, floor_no: int) -> bool:
        return self.floor_from <= floor_no <= self.floor_to


@dataclass(frozen=True)
class K3RiserProjectInput:
    """One K3 riser with its branches and confirmed service fittings."""

    pipe: BuildingPipeProjectInput
    branches: tuple[K3BranchProjectInput, ...]
    revision_elements: tuple[SewerElementSpec, ...]
    fire_collar_element_ids: tuple[str, ...]
    lower_elbow_element_ids: tuple[str, ...]
    lower_cleanout_element_ids: tuple[str, ...]
    lower_junction_element_ids: tuple[str, ...]

    @property
    def riser_id(self) -> str:
        return self.pipe.section_id

    @property
    def riser_dn_mm(self) -> int:
        return self.pipe.dn_mm


@dataclass(frozen=True)
class WastewaterK3ProjectInputs:
    """Complete confirmed contract for a separate gravity K3 drawing."""

    applicable: bool
    floors_above: int
    floor_height_m: float | None
    basement_floor_elevation_m: float | None
    risers: tuple[K3RiserProjectInput, ...]
    collectors: tuple[BuildingPipeProjectInput, ...]
    outlet: BuildingPipeProjectInput | None
    transitions: tuple[BuildingTransitionProjectInput, ...]
    discharge_point: str
    treatment_element_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]

    @property
    def characteristic_floors(self) -> tuple[int, ...]:
        floors = {
            value
            for riser in self.risers
            for branch in riser.branches
            for value in (branch.floor_from, branch.floor_to)
            if value > 0
        }
        floors.update(
            row.floor_from
            for riser in self.risers
            for row in riser.revision_elements
            if row.floor_from > 0
        )
        return tuple(sorted(floors, reverse=True))

    @property
    def complete(self) -> bool:
        return (
            self.applicable
            and self.floors_above > 0
            and self.floor_height_m is not None
            and self.floor_height_m > 0
            and self.basement_floor_elevation_m is not None
            and bool(self.risers)
            and all(row.branches for row in self.risers)
            and self.outlet is not None
            and bool(self.discharge_point)
            and not self.diagnostics
        )


def k3_is_applicable(project: Project) -> bool:
    """Return whether project intent or the register declares a K3 system."""
    return bool(
        any(_system(row.system) == "K3" for row in project.sewage.pipes)
        or any(_system(row.system) == "K3" for row in project.sewage.elements)
        or project.sewage.discharge_point_k3.strip()
        or project.sewage.k3_max_hourly_m3h is not None
        or project.sewage.k3_min_hourly_m3h is not None
        or project.grease_trap.preparation_type != "none"
    )


def _filtered_k3_project(project: Project) -> Project:
    return replace(
        project,
        sewage=replace(
            project.sewage,
            pipes=[
                row for row in project.sewage.pipes
                if _system(row.system) == "K3"
            ],
            elements=[
                row for row in project.sewage.elements
                if _system(row.system) == "K3"
            ],
        ),
    )


def _branch_input(
    project: Project,
    branch: SewerBranch,
    diagnostics: list[str],
) -> K3BranchProjectInput | None:
    pipe = branch.pipe
    if not _validate_building_pipe(
        pipe,
        label=f"Ветвь К3 {pipe.section_id}",
        require_slope=True,
        diagnostics=diagnostics,
    ):
        return None
    if not branch.elements:
        diagnostics.append(
            f"Ветвь К3 {pipe.section_id}: не задан приёмник производственных стоков."
        )
        return None
    if any(row.dn_mm is None or row.dn_mm <= 0 for row in branch.elements):
        diagnostics.append(
            f"Ветвь К3 {pipe.section_id}: для каждого элемента нужен положительный DN."
        )
    elbows = [
        row for row in project.sewage.elements
        if _system(row.system) == "K3"
        and row.kind == "elbow"
        and _section(row.section_id) == _section(pipe.section_id)
        and _section(row.connects_to) == _section(branch.riser_id)
        and row.quantity == 1
        and "45" in row.type_mark
        and row.element_id.strip()
    ]
    junctions = [
        row for row in project.sewage.elements
        if _system(row.system) == "K3"
        and row.kind in {"tee", "junction"}
        and _section(row.section_id) == _section(pipe.section_id)
        and _section(row.connects_to) == _section(branch.riser_id)
        and row.quantity == 1
        and "45" in row.type_mark
        and row.element_id.strip()
    ]
    if len(elbows) != 1 or len(junctions) != 1:
        diagnostics.append(
            f"Ветвь К3 {pipe.section_id}: присоединение к стояку должно быть "
            "подтверждено одним отводом 45° и одним косым тройником/крестовиной 45°."
        )
    return K3BranchProjectInput(
        pipe=_building_pipe_input(pipe),
        riser_id=branch.riser_id,
        elements=branch.elements,
        floor_from=branch.floor_from,
        floor_to=branch.floor_to,
        room_number=branch.room_number,
        room_name=branch.room_name,
        connection_elbow_element_id=(
            elbows[0].element_id.strip() if len(elbows) == 1 else ""
        ),
        connection_junction_element_id=(
            junctions[0].element_id.strip() if len(junctions) == 1 else ""
        ),
    )


def _lower_node_inputs(
    project: Project,
    pipe: SewerPipeSpec,
    diagnostics: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    elements = project.sewage.elements
    incoming = [
        row for row in project.sewage.pipes
        if _system(row.system) == "K3"
        and _is_horizontal_building_edge(row)
        and _section(row.to_node) == _section(pipe.section_id)
    ]
    outgoing = [
        row for row in project.sewage.pipes
        if _system(row.system) == "K3"
        and _is_horizontal_building_edge(row)
        and _section(row.from_node) == _section(pipe.section_id)
    ]
    elbows = tuple(
        row.element_id.strip()
        for row in elements
        if _system(row.system) == "K3"
        and row.kind == "elbow"
        and _section(row.section_id) == _section(pipe.section_id)
        and row.quantity == 1
        and "45" in row.type_mark
        and row.element_id.strip()
    )
    cleanouts = tuple(
        row.element_id.strip()
        for row in elements
        if _system(row.system) == "K3"
        and row.kind == "cleanout"
        and _section(row.connects_to) == _section(pipe.section_id)
        and len(outgoing) == 1
        and _section(row.section_id) == _section(outgoing[0].section_id)
        and row.service_direction in {"downstream", "both"}
        and row.service_fitting == "wye_45"
        and row.accessible
        and row.element_id.strip()
    )
    junctions = tuple(
        row.element_id.strip()
        for row in elements
        if _system(row.system) == "K3"
        and row.kind in {"tee", "junction"}
        and _section(row.connects_to) == _section(pipe.section_id)
        and len(outgoing) == 1
        and _section(row.section_id) == _section(outgoing[0].section_id)
        and "45" in row.type_mark
        and (
            "без заглуш" in row.type_mark.casefold()
            or "заглуш" not in row.type_mark.casefold()
        )
        and row.element_id.strip()
    )
    lower_revisions = [
        row for row in elements
        if _system(row.system) == "K3"
        and row.kind == "revision"
        and _section(row.section_id) == _section(pipe.section_id)
        and row.floor_from <= 1
        and row.service_direction in {"downstream", "both"}
        and row.service_fitting == "revision_opening"
        and row.accessible
    ]
    if len(elbows) != 1:
        diagnostics.append(
            f"Для нижнего поворота {pipe.section_id} нужна одна строка "
            "реестра с одним отводом 45°."
        )
    if len(outgoing) != 1:
        diagnostics.append(
            f"Стояк {pipe.section_id}: нижний узел должен иметь ровно одну "
            "выходящую горизонтальную магистраль."
        )
    if incoming:
        if cleanouts:
            diagnostics.append(
                f"Стояк {pipe.section_id}: заглушённая прочистка недопустима — "
                f"в узел входит магистраль {incoming[0].section_id}."
            )
        if len(junctions) != 1:
            diagnostics.append(
                f"Для проточного узла {pipe.section_id} нужен один косой "
                "тройник/крестовина 45° без заглушки."
            )
        if len(lower_revisions) != 1:
            diagnostics.append(
                f"Для проточного нижнего узла {pipe.section_id} нужна одна "
                "доступная ревизия на стояке."
            )
    else:
        if len(cleanouts) != 1:
            diagnostics.append(
                f"Для начального нижнего поворота {pipe.section_id} нужна одна "
                "прочистка с соосным заглушённым концом."
            )
        if junctions:
            diagnostics.append(
                f"Стояк {pipe.section_id}: терминальная прочистка и проходной "
                "тройник не могут занимать один нижний узел."
            )
    return elbows, cleanouts, junctions


def resolve_wastewater_k3_project_inputs(
    project: Project,
) -> WastewaterK3ProjectInputs:
    """Resolve a standalone gravity K3 sheet without generated defaults."""
    applicable = k3_is_applicable(project)
    diagnostics: list[str] = []
    if not applicable:
        return WastewaterK3ProjectInputs(
            applicable=False,
            floors_above=project.building.floors_above,
            floor_height_m=project.sewage.floor_height_m,
            basement_floor_elevation_m=project.sewage.basement_floor_elevation_m,
            risers=(),
            collectors=(),
            outlet=None,
            transitions=(),
            discharge_point="",
            treatment_element_ids=(),
            diagnostics=(),
        )

    k3_project = _filtered_k3_project(project)
    if not k3_project.sewage.pipes:
        diagnostics.append("Для К3 не заполнен реестр трубопроводных участков.")
    if not k3_project.sewage.elements:
        diagnostics.append("Для К3 не заполнен реестр приборов и фасонных частей.")
    if project.building.floors_above <= 0:
        diagnostics.append("В проекте не задано положительное число этажей.")
    if project.sewage.floor_height_m is None:
        diagnostics.append("Не задана точная высота этажа по архитектурным данным.")
    elif project.sewage.floor_height_m <= 0:
        diagnostics.append("Высота этажа должна быть положительной.")
    if project.sewage.basement_floor_elevation_m is None:
        diagnostics.append("Не задана относительная отметка чистого пола подвала.")

    pressure_pipes = [
        row.section_id for row in k3_project.sewage.pipes
        if row.pressure_rated is True
    ]
    pumps = [
        row.element_id for row in k3_project.sewage.elements
        if row.kind == "pump"
    ]
    if pressure_pipes or pumps or project.sewage.pump_required:
        diagnostics.append(
            "К3 содержит насос или напорный участок; требуется отдельная "
            "схема напорной канализации с подтверждённой рабочей точкой."
        )

    topology = build_wastewater_topology(k3_project)
    diagnostics.extend(topology.errors)
    riser_pipes = [
        row for row in k3_project.sewage.pipes if _is_riser_pipe(row)
    ]
    riser_ids = tuple(row.section_id.strip() for row in riser_pipes)
    if not riser_pipes:
        diagnostics.append("В реестре труб не найдено ни одного стояка К3.")

    branches_by_riser: dict[str, list[K3BranchProjectInput]] = {}
    for branch in topology.branches:
        if _system(branch.pipe.system) != "K3":
            continue
        resolved = _branch_input(k3_project, branch, diagnostics)
        if resolved is not None:
            branches_by_riser.setdefault(_section(branch.riser_id), []).append(
                resolved
            )

    risers: list[K3RiserProjectInput] = []
    for pipe in riser_pipes:
        _validate_building_pipe(
            pipe,
            label=f"Стояк К3 {pipe.section_id}",
            require_slope=False,
            diagnostics=diagnostics,
        )
        branches = tuple(branches_by_riser.get(_section(pipe.section_id), ()))
        if not branches:
            diagnostics.append(
                f"К стояку {pipe.section_id} не привязано ни одной ветви К3."
            )
        revisions = tuple(sorted(
            (
                row for row in k3_project.sewage.elements
                if row.kind == "revision"
                and _section(row.section_id) == _section(pipe.section_id)
            ),
            key=lambda row: (row.floor_from, row.element_id),
        ))
        used_floors = sorted({
            value
            for branch in branches
            for value in (branch.floor_from, branch.floor_to)
        })
        revision_floors = sorted({row.floor_from for row in revisions})
        if used_floors:
            required_ends = {used_floors[0], used_floors[-1]}
            if not required_ends.issubset(revision_floors):
                diagnostics.append(
                    f"Стояк {pipe.section_id}: ревизии должны включать нижний "
                    f"и верхний обслуживаемые этажи {used_floors[0]} и "
                    f"{used_floors[-1]}."
                )
            if used_floors[-1] >= 5 and any(
                b - a > 3 for a, b in zip(revision_floors, revision_floors[1:])
            ):
                diagnostics.append(
                    f"Стояк {pipe.section_id}: интервал между ревизиями "
                    "превышает три этажа."
                )
        if any(not row.accessible for row in revisions):
            diagnostics.append(
                f"Стояк {pipe.section_id}: все ревизии должны быть доступны."
            )
        elbows, cleanouts, junctions = _lower_node_inputs(
            k3_project, pipe, diagnostics
        )
        collars = tuple(
            row.element_id.strip()
            for row in k3_project.sewage.elements
            if row.kind == "fire_collar"
            and _section(row.section_id) == _section(pipe.section_id)
            and row.element_id.strip()
        )
        risers.append(K3RiserProjectInput(
            pipe=_building_pipe_input(pipe),
            branches=branches,
            revision_elements=revisions,
            fire_collar_element_ids=collars,
            lower_elbow_element_ids=elbows,
            lower_cleanout_element_ids=cleanouts,
            lower_junction_element_ids=junctions,
        ))

    outlet_pipe, _, outlet_diagnostics = _select_outlet_pipe(
        k3_project,
        system="K3",
    )
    diagnostics.extend(outlet_diagnostics)
    outlet: BuildingPipeProjectInput | None = None
    if outlet_pipe is not None and _validate_building_pipe(
        outlet_pipe,
        label=f"Выпуск К3 {outlet_pipe.section_id}",
        require_slope=True,
        diagnostics=diagnostics,
    ):
        outlet = _building_pipe_input(outlet_pipe)

    collector_pipes = [
        row for row in k3_project.sewage.pipes
        if row not in riser_pipes
        and row is not outlet_pipe
        and "магистраль" in row.purpose.strip().casefold()
    ]
    collectors = tuple(
        _building_pipe_input(row)
        for row in collector_pipes
        if _validate_building_pipe(
            row,
            label=f"Магистраль К3 {row.section_id}",
            require_slope=True,
            diagnostics=diagnostics,
        )
    )
    if len(collectors) != max(0, len(riser_pipes) - 1):
        diagnostics.append(
            "Количество подтверждённых магистралей К3 между стояками не "
            "соответствует линейной схеме здания."
        )
    riser_ids, collectors = _order_linear_system_chain(
        system_mark="К3",
        riser_ids=riser_ids,
        collectors=collectors,
        outlet=outlet,
        diagnostics=diagnostics,
    )
    riser_by_id = {_section(row.riser_id): row for row in risers}
    if all(_section(row) in riser_by_id for row in riser_ids):
        risers = [riser_by_id[_section(row)] for row in riser_ids]

    transitions = _validate_transition_topology(
        k3_project,
        systems=("K3",),
        diagnostics=diagnostics,
    )
    discharge_point = project.sewage.discharge_point_k3.strip()
    if not discharge_point:
        diagnostics.append("Не задана подтверждённая точка сброса К3.")
    elif outlet is not None and _section(discharge_point) != _section(outlet.to_node):
        diagnostics.append(
            f"Точка сброса К3 {discharge_point} не совпадает с конечным узлом "
            f"выпуска {outlet.to_node}."
        )

    treatment_rows = tuple(
        row.element_id.strip()
        for row in k3_project.sewage.elements
        if row.kind == "grease_trap" and row.element_id.strip()
    )
    if project.grease_trap.required and not treatment_rows:
        diagnostics.append(
            "Для требуемой предварительной очистки К3 не зарегистрирован "
            "жироуловитель."
        )
    if project.sewage.treatment_required:
        if not project.sewage.treatment_type.strip():
            diagnostics.append("Не задан тип локальной очистки К3.")
        if not project.sewage.treatment_location.strip():
            diagnostics.append("Не задано размещение локальной очистки К3.")
        if not project.sewage.treatment_technology.strip():
            diagnostics.append("Не задана технология локальной очистки К3.")
        if (
            project.sewage.treatment_capacity_lps is None
            and project.sewage.treatment_capacity_m3_day is None
        ):
            diagnostics.append("Не задана производительность локальной очистки К3.")
        if not treatment_rows:
            diagnostics.append(
                "Локальная очистка К3 указана в решениях, но отсутствует в "
                "реестре элементов схемы."
            )

    return WastewaterK3ProjectInputs(
        applicable=True,
        floors_above=project.building.floors_above,
        floor_height_m=project.sewage.floor_height_m,
        basement_floor_elevation_m=project.sewage.basement_floor_elevation_m,
        risers=tuple(risers),
        collectors=collectors,
        outlet=outlet,
        transitions=transitions,
        discharge_point=discharge_point,
        treatment_element_ids=treatment_rows,
        diagnostics=tuple(dict.fromkeys(row for row in diagnostics if row)),
    )

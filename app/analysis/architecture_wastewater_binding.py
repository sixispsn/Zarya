"""Подтверждённая привязка К1/К2 к архитектурному разрезу.

Модуль не выводит приборы из наименований помещений и не выбирает стояк по
близости. Каждая координата, связь и отметка приходят из отдельной строки,
подтверждённой проектировщиком. Реестр проекта остаётся источником инженерной
топологии; архитектурная привязка задаёт только положение её узлов.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Mapping

from app.analysis.architecture_confirmation import (
    ConfirmedArchitectureSectionInput,
    build_confirmed_architecture_section,
)
from app.pz.architecture_section_engine import (
    ArchitectureSectionModel,
    SectionRoomCell,
    architecture_section_to_wastewater_layout,
)
from app.pz.project import Project
from app.pz.wastewater_layout import (
    PointMm,
    WastewaterElementPlacement,
    WastewaterLayoutSource,
    WastewaterNodePlacement,
    WastewaterRoutePlacement,
    WastewaterSchemeLayout,
)
from app.pz.wastewater_topology import build_wastewater_topology


@dataclass(frozen=True)
class WastewaterReceiverDefinition:
    kind: str
    label: str
    system: str
    minimum_dn_mm: int


RECEIVER_DEFINITIONS: Mapping[str, WastewaterReceiverDefinition] = {
    row.kind: row
    for row in (
        WastewaterReceiverDefinition("sink", "Мойка", "K1", 50),
        WastewaterReceiverDefinition("washbasin", "Умывальник", "K1", 50),
        WastewaterReceiverDefinition("bath", "Ванна", "K1", 50),
        WastewaterReceiverDefinition("shower", "Душевой поддон", "K1", 50),
        WastewaterReceiverDefinition("floor_drain", "Трап", "K1", 50),
        WastewaterReceiverDefinition("toilet", "Унитаз", "K1", 100),
        WastewaterReceiverDefinition(
            "washing_machine", "Стиральная машина", "K1", 50
        ),
        WastewaterReceiverDefinition(
            "dishwasher", "Посудомоечная машина", "K1", 50
        ),
        WastewaterReceiverDefinition(
            "roof_funnel", "Водосточная воронка", "K2", 100
        ),
    )
}


@dataclass(frozen=True)
class ConfirmedRiserFloorPlacement:
    placement_id: str
    riser_id: str
    system: str
    floor: int
    shaft_cell_id: str
    station_m: float
    dn_mm: int
    source_ref: str
    offset_from_below_confirmed: bool = False


@dataclass(frozen=True)
class ConfirmedReceiverPlacement:
    placement_id: str
    element_id: str
    kind: str
    system: str
    floor: int
    room_cell_id: str
    station_m: float
    connection_height_m: float
    quantity: int
    dn_mm: int
    riser_id: str
    source_ref: str


@dataclass(frozen=True)
class ConfirmedArchitectureWastewaterBinding:
    plan_id: str
    cut_id: str
    architecture_source_sha256: str
    risers: tuple[ConfirmedRiserFloorPlacement, ...] = ()
    receivers: tuple[ConfirmedReceiverPlacement, ...] = ()


@dataclass(frozen=True)
class ArchitectureWastewaterBindingIssue:
    code: str
    message: str
    severity: str = "error"


def _floor_cells(
    model: ArchitectureSectionModel,
) -> dict[int, dict[str, SectionRoomCell]]:
    return {
        floor.floor: {cell.room_id: cell for cell in floor.cells}
        for floor in model.floors
    }


def audit_architecture_wastewater_binding(
    architecture: ConfirmedArchitectureSectionInput,
    binding: ConfirmedArchitectureWastewaterBinding,
    *,
    project: Project | None = None,
    station_tolerance_m: float = 0.01,
    riser_alignment_tolerance_m: float = 0.03,
) -> tuple[ArchitectureWastewaterBindingIssue, ...]:
    """Проверить привязки без восстановления отсутствующих решений."""
    issues: list[ArchitectureWastewaterBindingIssue] = []

    def add(code: str, message: str, severity: str = "error") -> None:
        issues.append(ArchitectureWastewaterBindingIssue(code, message, severity))

    if station_tolerance_m <= 0 or riser_alignment_tolerance_m <= 0:
        raise ValueError("binding tolerances must be positive")
    model = build_confirmed_architecture_section(architecture)
    if binding.plan_id != architecture.plan_id or binding.cut_id != architecture.cut_id:
        add("identity.mismatch", "привязка относится к другому плану или разрезу")
    if binding.architecture_source_sha256 != architecture.source_sha256:
        add("source.mismatch", "контрольная сумма архитектурного PDF изменилась")
    cells = _floor_cells(model)
    floor_heights = {row.floor: row.clear_height_m for row in model.floors}

    placement_ids = [row.placement_id for row in binding.risers] + [
        row.placement_id for row in binding.receivers
    ]
    for duplicate in sorted({row for row in placement_ids if placement_ids.count(row) > 1}):
        add("placement.duplicate", f"идентификатор размещения {duplicate} повторяется")

    riser_keys: set[tuple[str, int]] = set()
    risers_by_id: dict[str, list[ConfirmedRiserFloorPlacement]] = {}
    for row in binding.risers:
        prefix = row.placement_id or row.riser_id or "стояк"
        if not row.placement_id.strip() or not row.riser_id.strip():
            add("riser.label", f"{prefix}: нужны ID размещения и обозначение стояка")
        if row.system not in {"K1", "K2", "K3"}:
            add("riser.system", f"{prefix}: неизвестная система {row.system!r}")
        if row.dn_mm <= 0:
            add("riser.dn", f"{prefix}: DN должен быть положительным")
        if not isfinite(row.station_m):
            add("riser.station", f"{prefix}: координата должна быть конечной")
        if not row.source_ref.strip():
            add("riser.source", f"{prefix}: не указано основание привязки")
        key = (row.riser_id, row.floor)
        if key in riser_keys:
            add(
                "riser.floor_duplicate",
                f"{row.riser_id}: на этаже {row.floor} задано два положения",
            )
        riser_keys.add(key)
        floor_cells = cells.get(row.floor)
        if floor_cells is None:
            add("riser.floor", f"{prefix}: этаж {row.floor} отсутствует в разрезе")
            continue
        cell = floor_cells.get(row.shaft_cell_id)
        if cell is None:
            add(
                "riser.cell",
                f"{prefix}: ячейка {row.shaft_cell_id!r} отсутствует на этаже {row.floor}",
            )
            continue
        if cell.kind != "shaft":
            add(
                "riser.shaft",
                f"{prefix}: стояк должен быть привязан к подтверждённой шахте, "
                f"а {cell.room_id} имеет тип {cell.kind!r}",
            )
        if not (
            cell.start_m - station_tolerance_m
            <= row.station_m
            <= cell.end_m + station_tolerance_m
        ):
            add(
                "riser.station",
                f"{prefix}: координата {row.station_m:g} м находится вне "
                f"шахты {cell.room_id} ({cell.start_m:g}-{cell.end_m:g} м)",
            )
        risers_by_id.setdefault(row.riser_id, []).append(row)

    for riser_id, rows in risers_by_id.items():
        systems = {row.system for row in rows}
        if len(systems) > 1:
            add("riser.system_mismatch", f"{riser_id}: система различается по этажам")
        ordered = sorted(rows, key=lambda item: item.floor)
        for below, above in zip(ordered, ordered[1:]):
            shift = abs(above.station_m - below.station_m)
            if (
                shift > riser_alignment_tolerance_m
                and not above.offset_from_below_confirmed
            ):
                add(
                    "riser.offset_unconfirmed",
                    f"{riser_id}: смещение {shift:.3f} м между этажами "
                    f"{below.floor} и {above.floor} не подтверждено",
                )

    receiver_keys: set[tuple[str, int]] = set()
    for row in binding.receivers:
        prefix = row.placement_id or row.element_id or "прибор"
        if not row.placement_id.strip() or not row.element_id.strip():
            add("receiver.label", f"{prefix}: нужны ID размещения и элемента")
        definition = RECEIVER_DEFINITIONS.get(row.kind)
        if definition is None:
            add("receiver.kind", f"{prefix}: неподдерживаемый вид {row.kind!r}")
        else:
            if row.system != definition.system:
                add(
                    "receiver.system",
                    f"{prefix}: {row.kind} относится к {definition.system}, а не {row.system}",
                )
            if row.dn_mm < definition.minimum_dn_mm:
                add(
                    "receiver.dn",
                    f"{prefix}: для {definition.label.lower()} требуется не менее "
                    f"DN{definition.minimum_dn_mm}",
                )
        if row.quantity < 1:
            add("receiver.quantity", f"{prefix}: количество должно быть не меньше 1")
        if not isfinite(row.station_m) or not isfinite(row.connection_height_m):
            add("receiver.coordinate", f"{prefix}: координаты должны быть конечными")
        if not row.source_ref.strip():
            add("receiver.source", f"{prefix}: не указано основание привязки")
        key = (row.element_id, row.floor)
        if key in receiver_keys:
            add(
                "receiver.floor_duplicate",
                f"{row.element_id}: на этаже {row.floor} задан дважды",
            )
        receiver_keys.add(key)
        floor_cells = cells.get(row.floor)
        if floor_cells is None:
            add("receiver.floor", f"{prefix}: этаж {row.floor} отсутствует в разрезе")
            continue
        cell = floor_cells.get(row.room_cell_id)
        if cell is None:
            add(
                "receiver.cell",
                f"{prefix}: помещение {row.room_cell_id!r} отсутствует на этаже {row.floor}",
            )
            continue
        if cell.kind == "shaft":
            add("receiver.room", f"{prefix}: санитарный прибор не размещается в шахте")
        if not (
            cell.start_m - station_tolerance_m
            <= row.station_m
            <= cell.end_m + station_tolerance_m
        ):
            add(
                "receiver.station",
                f"{prefix}: координата {row.station_m:g} м находится вне "
                f"помещения {cell.room_id} ({cell.start_m:g}-{cell.end_m:g} м)",
            )
        clear_height = floor_heights[row.floor]
        if not 0 <= row.connection_height_m <= clear_height:
            add(
                "receiver.height",
                f"{prefix}: высота подключения должна быть от 0 до {clear_height:g} м",
            )
        riser = next(
            (
                candidate
                for candidate in binding.risers
                if candidate.riser_id == row.riser_id
                and candidate.floor == row.floor
            ),
            None,
        )
        if riser is None:
            add(
                "receiver.riser",
                f"{prefix}: стояк {row.riser_id!r} не размещён на этаже {row.floor}",
            )
        elif riser.system != row.system:
            add(
                "receiver.riser_system",
                f"{prefix}: система прибора не совпадает со стояком {row.riser_id}",
            )

    if project is not None:
        project_elements = {row.element_id: row for row in project.sewage.elements}
        project_pipes = {row.section_id: row for row in project.sewage.pipes}
        project_risers = {row.riser_id for row in project.sewage.risers}
        for row in binding.risers:
            pipe = project_pipes.get(row.riser_id)
            if row.riser_id not in project_risers and pipe is None:
                add("riser.registry", f"{row.riser_id}: стояк отсутствует в проекте")
            if pipe is not None and pipe.system != row.system:
                add("riser.registry_system", f"{row.riser_id}: система не совпадает с проектом")
        for row in binding.receivers:
            element = project_elements.get(row.element_id)
            if element is None:
                add("receiver.registry", f"{row.element_id}: элемент отсутствует в проекте")
                continue
            if element.kind != row.kind or element.system != row.system:
                add(
                    "receiver.registry_kind",
                    f"{row.element_id}: вид или система не совпадают с проектным реестром",
                )
            floor_to = element.floor_to if element.floor_to is not None else element.floor_from
            if not element.floor_from <= row.floor <= floor_to:
                add(
                    "receiver.registry_floor",
                    f"{row.element_id}: элемент не применяется на этаже {row.floor}",
                )
            if element.connects_to and element.connects_to != row.riser_id:
                # Промежуточная связь с другим прибором допустима; точную цепь
                # далее проверяет build_wastewater_topology.
                target = project_elements.get(element.connects_to)
                if target is None:
                    add(
                        "receiver.registry_target",
                        f"{row.element_id}: связь {element.connects_to!r} отсутствует в реестре",
                    )

    if not binding.risers:
        add("riser.missing", "не подтверждено ни одного положения стояка", "warning")
    if not binding.receivers:
        add("receiver.missing", "не подтверждено ни одного приёмника стоков", "warning")
    return tuple(issues)


def _sheet_x(model: ArchitectureSectionModel, station_m: float) -> float:
    return 80.0 + 600.0 * station_m / model.cut_length_m


def build_bound_wastewater_layout(
    architecture: ConfirmedArchitectureSectionInput,
    binding: ConfirmedArchitectureWastewaterBinding,
    project: Project,
) -> WastewaterSchemeLayout:
    """Наложить подтверждённые координаты на явный граф проекта."""
    issues = audit_architecture_wastewater_binding(
        architecture,
        binding,
        project=project,
    )
    errors = [row.message for row in issues if row.severity == "error"]
    if errors:
        raise ValueError("привязка К1/К2 не прошла проверку: " + "; ".join(errors))
    model = build_confirmed_architecture_section(architecture)
    required_floors = {
        row.floor for row in binding.risers
    } | {row.floor for row in binding.receivers}
    layout = architecture_section_to_wastewater_layout(
        model,
        required_floor_numbers=required_floors,
    )
    floor_groups = {
        group.floors[0]: group
        for group in layout.floor_groups
        if len(group.floors) == 1
    }
    spaces = {}
    for space in layout.spaces:
        floor = int(space.group_id.rsplit("-", 1)[-1])
        prefix = f"section-{floor}-"
        room_id = space.space_id.removeprefix(prefix)
        spaces[(floor, room_id)] = space
    riser_points: dict[tuple[str, int], PointMm] = {}
    for row in binding.risers:
        space = spaces[(row.floor, row.shaft_cell_id)]
        point = PointMm(_sheet_x(model, row.station_m), space.frame.y2)
        riser_points[(row.riser_id, row.floor)] = point

    receiver_points: dict[tuple[str, int], PointMm] = {}
    receiver_by_key = {
        (row.element_id, row.floor): row for row in binding.receivers
    }
    model_floors = {row.floor: row for row in model.floors}
    for row in binding.receivers:
        space = spaces[(row.floor, row.room_cell_id)]
        clear_height = model_floors[row.floor].clear_height_m
        y = space.frame.y2 - space.frame.height * row.connection_height_m / clear_height
        point = PointMm(_sheet_x(model, row.station_m), y)
        receiver_points[(row.element_id, row.floor)] = point
        layout.elements.append(WastewaterElementPlacement(
            placement_id=row.placement_id,
            element_id=row.element_id,
            point=point,
            group_id=floor_groups[row.floor].group_id,
            source=WastewaterLayoutSource.MANUAL_CONFIRMED,
            source_ref=row.source_ref,
        ))

    topology = build_wastewater_topology(project)
    if topology.errors:
        raise ValueError("граф К1/К2 не готов: " + "; ".join(topology.errors))

    for branch in topology.branches:
        active_floors = sorted(
            floor
            for element in branch.elements
            for element_id, floor in receiver_by_key
            if element_id == element.element_id
            and branch.floor_from <= floor <= branch.floor_to
        )
        for floor in sorted(set(active_floors)):
            ordered = [
                receiver_points.get((element.element_id, floor))
                for element in branch.elements
            ]
            if any(point is None for point in ordered):
                raise ValueError(
                    f"{branch.pipe.section_id}, этаж {floor}: подтверждены не все "
                    "приборы непрерывной цепи до стояка"
                )
            riser_point = riser_points.get((branch.riser_id, floor))
            if riser_point is None:
                raise ValueError(
                    f"{branch.pipe.section_id}, этаж {floor}: нет положения стояка "
                    f"{branch.riser_id}"
                )
            points = tuple(ordered) + (riser_point,)
            start_id = f"binding-{floor}-{branch.pipe.section_id}-start"
            end_id = f"binding-{floor}-{branch.pipe.section_id}-riser"
            group_id = floor_groups[floor].group_id
            layout.nodes.extend((
                WastewaterNodePlacement(
                    placement_id=start_id,
                    node_id=branch.pipe.from_node,
                    system=branch.pipe.system,
                    point=points[0],
                    group_id=group_id,
                    kind="fixture_source",
                    source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                    source_ref=(
                        f"{receiver_by_key[(branch.pipe.from_node, floor)].source_ref}; "
                        f"sewage.pipes:{branch.pipe.section_id}.from_node"
                    ),
                ),
                WastewaterNodePlacement(
                    placement_id=end_id,
                    node_id=branch.riser_id,
                    system=branch.pipe.system,
                    point=riser_point,
                    group_id=group_id,
                    kind="riser",
                    source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                    source_ref=(
                        f"sewage.pipes:{branch.pipe.section_id}.to_node; "
                        "подтверждённое положение стояка"
                    ),
                ),
            ))
            layout.routes.append(WastewaterRoutePlacement(
                route_id=f"binding-{floor}-{branch.pipe.section_id}",
                section_id=branch.pipe.section_id,
                system=branch.pipe.system,
                from_placement_id=start_id,
                to_placement_id=end_id,
                points=points,
                group_id=group_id,
                source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                source_ref=(
                    f"sewage.pipes:{branch.pipe.section_id}; "
                    "координаты приборов и стояка подтверждены по АР"
                ),
            ))

    riser_bindings: dict[str, list[ConfirmedRiserFloorPlacement]] = {}
    for row in binding.risers:
        riser_bindings.setdefault(row.riser_id, []).append(row)
    for riser_id, rows in riser_bindings.items():
        pipe = topology.risers.get(riser_id)
        if pipe is None:
            continue
        ordered = sorted(
            rows,
            key=lambda row: floor_groups[row.floor].y_mm,
        )
        highest = ordered[0]
        lowest = ordered[-1]
        highest_space = spaces[(highest.floor, highest.shaft_cell_id)]
        lowest_space = spaces[(lowest.floor, lowest.shaft_cell_id)]
        points = (
            PointMm(_sheet_x(model, highest.station_m), highest_space.frame.y),
            *(
                riser_points[(row.riser_id, row.floor)]
                for row in ordered
            ),
        )
        if points[-1] != PointMm(
            _sheet_x(model, lowest.station_m),
            lowest_space.frame.y2,
        ):
            points = points + (
                PointMm(
                    _sheet_x(model, lowest.station_m),
                    lowest_space.frame.y2,
                ),
            )
        start_id = f"binding-{riser_id}-vent"
        end_id = f"binding-{riser_id}-base"
        layout.nodes.extend((
            WastewaterNodePlacement(
                placement_id=start_id,
                node_id=pipe.from_node,
                system=pipe.system,
                point=points[0],
                group_id=floor_groups[highest.floor].group_id,
                kind="vent",
                source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                source_ref=(
                    f"sewage.pipes:{pipe.section_id}.from_node; "
                    "ось стояка подтверждена по АР"
                ),
            ),
            WastewaterNodePlacement(
                placement_id=end_id,
                node_id=pipe.to_node,
                system=pipe.system,
                point=points[-1],
                group_id=floor_groups[lowest.floor].group_id,
                kind="riser_base",
                source=WastewaterLayoutSource.MANUAL_CONFIRMED,
                source_ref=(
                    f"sewage.pipes:{pipe.section_id}.to_node; "
                    "ось стояка подтверждена по АР"
                ),
            ),
        ))
        layout.routes.append(WastewaterRoutePlacement(
            route_id=f"binding-{riser_id}-vertical",
            section_id=pipe.section_id,
            system=pipe.system,
            from_placement_id=start_id,
            to_placement_id=end_id,
            points=points,
            source=WastewaterLayoutSource.MANUAL_CONFIRMED,
            source_ref=(
                f"sewage.pipes:{pipe.section_id}; положения по этажам "
                "подтверждены в шахтах АР"
            ),
        ))
    return layout


def architecture_wastewater_binding_to_mapping(
    value: ConfirmedArchitectureWastewaterBinding,
) -> dict:
    return asdict(value)


def architecture_wastewater_binding_from_mapping(
    value: Mapping,
) -> ConfirmedArchitectureWastewaterBinding:
    return ConfirmedArchitectureWastewaterBinding(
        plan_id=str(value.get("plan_id", "")),
        cut_id=str(value.get("cut_id", "")),
        architecture_source_sha256=str(
            value.get("architecture_source_sha256", "")
        ),
        risers=tuple(
            ConfirmedRiserFloorPlacement(
                placement_id=str(row.get("placement_id", "")),
                riser_id=str(row.get("riser_id", "")),
                system=str(row.get("system", "")),
                floor=int(row.get("floor", 0)),
                shaft_cell_id=str(row.get("shaft_cell_id", "")),
                station_m=float(row.get("station_m", 0)),
                dn_mm=int(row.get("dn_mm", 0)),
                source_ref=str(row.get("source_ref", "")),
                offset_from_below_confirmed=bool(
                    row.get("offset_from_below_confirmed", False)
                ),
            )
            for row in value.get("risers", ())
        ),
        receivers=tuple(
            ConfirmedReceiverPlacement(
                placement_id=str(row.get("placement_id", "")),
                element_id=str(row.get("element_id", "")),
                kind=str(row.get("kind", "")),
                system=str(row.get("system", "")),
                floor=int(row.get("floor", 0)),
                room_cell_id=str(row.get("room_cell_id", "")),
                station_m=float(row.get("station_m", 0)),
                connection_height_m=float(row.get("connection_height_m", 0)),
                quantity=int(row.get("quantity", 0)),
                dn_mm=int(row.get("dn_mm", 0)),
                riser_id=str(row.get("riser_id", "")),
                source_ref=str(row.get("source_ref", "")),
            )
            for row in value.get("receivers", ())
        ),
    )

"""Явная направленная топология принципиальной схемы К1/К2/К3.

Самотечная сеть строится только по направлению движения стоков: от подтверждённого
приёмника стоков через этажную ветвь, стояк и магистраль к выпуску. Модуль не
достраивает линии по близости координат и отклоняет ветви без источника, циклы,
подъём самотечного участка и тупики, не достигающие выпуска.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec


GRAVITY_SOURCE_KINDS: Set[str] = {
    "toilet",
    "washbasin",
    "sink",
    "bath",
    "shower",
    "floor_drain",
    "washing_machine",
    "dishwasher",
}
# Жироуловитель не создаёт сток, но может быть промежуточным узлом между
# прибором и стояком. Отдельный сифон также не считается началом трубопровода.
BRANCH_FLOW_KINDS: Set[str] = GRAVITY_SOURCE_KINDS | {"grease_trap"}
# Обратная совместимость для импортов, где под FIXTURE_KINDS понимались именно
# приёмники стоков, а не все фасонные части и устройства К1.
FIXTURE_KINDS = GRAVITY_SOURCE_KINDS


@dataclass(frozen=True)
class SewerBranch:
    pipe: SewerPipeSpec
    riser_id: str
    elements: tuple[SewerElementSpec, ...]
    room_number: str
    room_name: str
    floor_from: int
    floor_to: int

    @property
    def source_element_id(self) -> str:
        """Первый подтверждённый приёмник стоков по направлению потока."""
        return self.elements[0].element_id if self.elements else ""

    @property
    def has_toilet(self) -> bool:
        return any(row.kind == "toilet" for row in self.elements)


@dataclass
class WastewaterTopology:
    risers: Dict[str, SewerPipeSpec] = field(default_factory=dict)
    branches: List[SewerBranch] = field(default_factory=list)
    mains: List[SewerPipeSpec] = field(default_factory=list)
    elements_by_section: Dict[str, List[SewerElementSpec]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.risers and self.mains) and not self.errors


def _is_riser(pipe: SewerPipeSpec) -> bool:
    purpose = (pipe.purpose or "").strip().lower()
    return purpose.startswith((
        "стояк",
        "канализационный стояк",
        "водосточный стояк",
        "вертикаль",
        "вертикальный участок",
    ))


def _is_declared_branch(pipe: SewerPipeSpec) -> bool:
    purpose = (pipe.purpose or "").lower()
    return any(word in purpose for word in ("ответвлен", "ветвь", "подключен"))


def _has_explicit_pump(pipe: SewerPipeSpec, elements: List[SewerElementSpec]) -> bool:
    """Напорный режим допустим только при насосе, привязанном к участку."""
    return any(
        row.kind == "pump" and row.section_id == pipe.section_id
        for row in elements
    )


def _order_branch_elements(
    section_id: str,
    riser_id: str,
    elements: List[SewerElementSpec],
    errors: List[str],
) -> Tuple[SewerElementSpec, ...]:
    """Проверить и вернуть единственную цепочку «прибор -> ... -> стояк»."""
    by_id = {row.element_id: row for row in elements}
    targets: Dict[str, str] = {}
    malformed = False
    for row in elements:
        target = (row.connects_to or "").strip()
        if not target:
            errors.append(
                f"{row.element_id}: не задан следующий узел по движению стоков"
            )
            malformed = True
            continue
        if target == row.element_id:
            errors.append(f"{row.element_id}: элемент замкнут сам на себя")
            malformed = True
            continue
        if target != riser_id and target not in by_id:
            errors.append(
                f"{row.element_id}: связь {target} не принадлежит ветви "
                f"{section_id} и не является стояком {riser_id}"
            )
            malformed = True
            continue
        targets[row.element_id] = target
    if malformed:
        return ()

    downstream_elements = {target for target in targets.values() if target in by_id}
    sources = [
        row for row in elements
        if row.element_id not in downstream_elements
        and row.kind in GRAVITY_SOURCE_KINDS
    ]
    if len(sources) != 1:
        errors.append(
            f"{section_id}: этажная ветвь должна начинаться ровно от одного "
            f"приёмника стоков; найдено {len(sources)}"
        )
        return ()

    ordered: List[SewerElementSpec] = []
    visited: Set[str] = set()
    current = sources[0].element_id
    while current != riser_id:
        if current in visited:
            errors.append(f"{section_id}: цикл в цепочке приборов у {current}")
            return ()
        row = by_id.get(current)
        if row is None:
            errors.append(
                f"{section_id}: цепочка стоков оборвана перед узлом {current}"
            )
            return ()
        visited.add(current)
        ordered.append(row)
        current = targets[current]

    if visited != set(by_id):
        detached = ", ".join(sorted(set(by_id) - visited))
        errors.append(
            f"{section_id}: элементы {detached} не входят в непрерывный путь "
            f"от прибора до стояка {riser_id}"
        )
        return ()

    toilets = [row for row in ordered if row.kind == "toilet"]
    toilet_order_invalid = False
    if toilets:
        for toilet in toilets:
            if targets[toilet.element_id] != riser_id:
                errors.append(
                    f"{toilet.element_id}: унитаз должен быть последним прибором "
                    f"перед стояком {riser_id}"
                )
                toilet_order_invalid = True
        if ordered[-1].kind != "toilet":
            errors.append(
                f"{section_id}: при наличии унитаза ближайшим к стояку "
                "должен быть унитаз"
            )
            toilet_order_invalid = True
    if toilet_order_invalid:
        return ()
    return tuple(ordered)


def _check_gravity_pipe(
    pipe: SewerPipeSpec,
    elements: List[SewerElementSpec],
    errors: List[str],
) -> None:
    """Проверить направление отметок самотечного участка без расчёта РД."""
    if _has_explicit_pump(pipe, elements):
        return
    if pipe.elevation_start_m is None or pipe.elevation_end_m is None:
        errors.append(
            f"{pipe.section_id}: для самотечного участка нужны отметки начала "
            "и конца по движению стоков"
        )
        return
    if pipe.elevation_start_m <= pipe.elevation_end_m:
        errors.append(
            f"{pipe.section_id}: самотечный участок должен понижаться от "
            f"{pipe.elevation_start_m:g} до {pipe.elevation_end_m:g} м; "
            "подъём допустим только при явно заданном насосе"
        )
    if not _is_riser(pipe) and (
        pipe.slope_per_mille is None or pipe.slope_per_mille <= 0
    ):
        errors.append(
            f"{pipe.section_id}: горизонтальному самотечному участку нужен "
            "положительный уклон по направлению стоков"
        )


def build_wastewater_topology(project: Project) -> WastewaterTopology:
    pipes = list(project.sewage.pipes or [])
    elements = list(project.sewage.elements or [])
    result = WastewaterTopology()
    result.risers = {
        pipe.section_id: pipe for pipe in pipes if pipe.section_id and _is_riser(pipe)
    }
    if not result.risers:
        result.errors.append("не заданы стояки с явными обозначениями участков")

    for element in elements:
        if element.section_id:
            result.elements_by_section.setdefault(element.section_id, []).append(element)

    riser_ids = set(result.risers)
    branch_ids: Set[str] = set()
    for pipe in pipes:
        if pipe.section_id in riser_ids:
            continue
        attached = {pipe.from_node, pipe.to_node} & riser_ids
        fixture_elements = [
            row for row in result.elements_by_section.get(pipe.section_id, [])
            if row.kind in BRANCH_FLOW_KINDS
        ]
        is_branch = _is_declared_branch(pipe) or bool(attached and fixture_elements)
        if not is_branch:
            result.mains.append(pipe)
            continue
        branch_error_count = len(result.errors)
        branch_ids.add(pipe.section_id)
        if len(attached) != 1:
            result.errors.append(
                f"{pipe.section_id}: этажное ответвление должно быть связано "
                "ровно с одним стояком"
            )
            continue
        if not fixture_elements:
            result.errors.append(
                f"{pipe.section_id}: к этажному ответвлению не привязаны приборы"
            )
            continue
        riser_id = next(iter(attached))
        ordered_elements = _order_branch_elements(
            pipe.section_id,
            riser_id,
            fixture_elements,
            result.errors,
        )
        if not ordered_elements:
            continue
        if pipe.from_node != ordered_elements[0].element_id:
            result.errors.append(
                f"{pipe.section_id}: from_node должен совпадать с первым "
                f"приёмником стоков {ordered_elements[0].element_id}, а не "
                f"{pipe.from_node or 'пустым узлом'}"
            )
        if pipe.to_node != riser_id:
            result.errors.append(
                f"{pipe.section_id}: to_node должен быть стояком {riser_id} "
                "по направлению самотёка"
            )
        rooms = {
            (row.room_number.strip(), row.room_name.strip())
            for row in fixture_elements
        }
        if len(rooms) != 1:
            result.errors.append(
                f"{pipe.section_id}: одно ответвление содержит приборы разных "
                "помещений; разделите участки"
            )
        room_number, room_name = sorted(rooms)[0]
        if not room_number or not room_name:
            result.errors.append(
                f"{pipe.section_id}: для помещения нужны номер и наименование"
            )
        floors_from = [row.floor_from for row in fixture_elements]
        floors_to = [
            row.floor_to if row.floor_to is not None else row.floor_from
            for row in fixture_elements
        ]
        for row in fixture_elements:
            if row.typical_quantity is None:
                result.errors.append(
                    f"{row.element_id}: не задано количество в типовом помещении"
                )
            if row.elevation_m is None:
                result.errors.append(
                    f"{row.element_id}: не задана относительная отметка прибора"
                )
        if len(result.errors) > branch_error_count:
            continue
        result.branches.append(SewerBranch(
            pipe=pipe,
            riser_id=riser_id,
            elements=ordered_elements,
            room_number=room_number,
            room_name=room_name,
            floor_from=min(floors_from),
            floor_to=max(floors_to),
        ))

    for row in elements:
        if row.kind in GRAVITY_SOURCE_KINDS and row.section_id not in branch_ids:
            result.errors.append(
                f"{row.element_id}: прибор должен быть привязан к отдельному "
                "этажному ответвлению, а не непосредственно к стояку"
            )

    for pipe in result.mains:
        if not pipe.from_node or not pipe.to_node:
            result.errors.append(
                f"{pipe.section_id}: для магистрали/выпуска нужны from_node и to_node"
            )

    # Кровельная воронка является подтверждённым источником К2: стояк не может
    # начинаться произвольной линией над кровлей.
    for riser_id, riser in result.risers.items():
        if riser.system != "K2":
            continue
        funnels = [
            row for row in result.elements_by_section.get(riser_id, [])
            if row.kind == "roof_funnel"
        ]
        if not funnels:
            result.errors.append(
                f"{riser_id}: водосточный стояк должен начинаться от воронки"
            )
            continue
        if riser.from_node not in {row.element_id for row in funnels}:
            result.errors.append(
                f"{riser_id}: from_node водосточного стояка должен совпадать "
                "с обозначением кровельной воронки"
            )
        for funnel in funnels:
            if funnel.connects_to != riser_id:
                result.errors.append(
                    f"{funnel.element_id}: воронка должна быть направленно "
                    f"связана со стояком {riser_id}"
                )

    for riser_id, riser in result.risers.items():
        if not any(
            riser_id in {pipe.from_node, pipe.to_node}
            for pipe in result.mains
            if pipe.system == riser.system
        ):
            result.errors.append(
                f"{riser_id}: стояк не связан с магистралью полями from_node/to_node"
            )

    # Все трубы в реестре считаются самотечными, пока на конкретном участке не
    # зарегистрирован насос. Проверяется только направление отметок и наличие
    # уклона; фиктивная гидравлика без аксонометрии не выполняется.
    for pipe in pipes:
        _check_gravity_pipe(pipe, elements, result.errors)

    outlet_sections = {
        row.section_id for row in elements if row.kind == "outlet" and row.section_id
    }
    for section_id in outlet_sections:
        pipe = next((row for row in result.mains if row.section_id == section_id), None)
        if pipe is None:
            result.errors.append(
                f"{section_id}: элемент выпуска не связан с трубопроводным участком"
            )
            continue
        if (
            pipe.elevation_start_m is None
            or pipe.elevation_end_m is None
            or pipe.absolute_elevation_start_m is None
            or pipe.absolute_elevation_end_m is None
        ):
            result.errors.append(
                f"{section_id}: для выпуска нужны относительные и абсолютные "
                "отметки начала и конца"
            )

    # Направленный граф магистралей обязан вести каждый стояк к подтверждённому
    # выпуску. Одновременно это запрещает циклы, висящие тупики и участки,
    # начинающиеся в произвольной точке без притока от стояка.
    mains_by_system: Dict[str, List[SewerPipeSpec]] = {}
    for pipe in result.mains:
        mains_by_system.setdefault(pipe.system, []).append(pipe)
    outlet_by_system: Dict[str, Set[str]] = {}
    for pipe in result.mains:
        if pipe.section_id in outlet_sections:
            outlet_by_system.setdefault(pipe.system, set()).add(pipe.to_node)

    graph_systems = {
        row.system for row in list(result.risers.values()) + result.mains
    }
    for system, system_risers in (
        (name, [row for row in result.risers.values() if row.system == name])
        for name in sorted(graph_systems)
    ):
        system_mains = mains_by_system.get(system, [])
        if system_mains and not system_risers:
            result.errors.append(
                f"{system}: магистрали не получают стоки ни от одного стояка"
            )
            continue
        terminals = outlet_by_system.get(system, set())
        if not terminals:
            result.errors.append(
                f"{system}: не задан подтверждённый выпуск в наружную сеть"
            )
            continue
        adjacency: Dict[str, List[SewerPipeSpec]] = {}
        for pipe in system_mains:
            adjacency.setdefault(pipe.from_node, []).append(pipe)
        reached_sections: Set[str] = set()
        reported_dead_ends: Set[str] = set()
        reported_cycles: Set[str] = set()

        def reaches_outlet(node: str, path: Set[str]) -> bool:
            if node in terminals:
                return True
            if node in path:
                if node not in reported_cycles:
                    result.errors.append(
                        f"{system}: цикл самотечной сети обнаружен в узле {node}"
                    )
                    reported_cycles.add(node)
                return False
            next_path = path | {node}
            outgoing = adjacency.get(node, [])
            if not outgoing:
                if node not in reported_dead_ends:
                    result.errors.append(
                        f"{system}: тупик самотечной сети в узле {node}; "
                        "стоки не достигают подтверждённого выпуска"
                    )
                    reported_dead_ends.add(node)
                return False
            reached = True
            for edge in outgoing:
                reached_sections.add(edge.section_id)
                reached = reaches_outlet(edge.to_node, next_path) and reached
            return reached

        for riser in system_risers:
            if not reaches_outlet(riser.section_id, set()):
                result.errors.append(
                    f"{riser.section_id}: по направлению стоков нет непрерывного "
                    "пути до выпуска в наружную сеть"
                )
        floating = {
            pipe.section_id for pipe in system_mains
            if pipe.section_id not in reached_sections
        }
        if floating:
            result.errors.append(
                f"{system}: участки {', '.join(sorted(floating))} не получают "
                "стоки ни от одного стояка"
            )

    known_sections = {pipe.section_id for pipe in pipes}
    for row in elements:
        if row.section_id and row.section_id not in known_sections:
            result.errors.append(
                f"{row.element_id}: неизвестный участок {row.section_id}"
            )

    result.branches.sort(key=lambda row: (
        row.pipe.system, row.riser_id, row.pipe.section_id,
    ))
    result.mains.sort(key=lambda row: (row.system, row.section_id))
    return result

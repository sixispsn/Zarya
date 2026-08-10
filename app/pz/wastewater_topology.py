"""Явная топология принципиальной схемы К1/К2/К3.

Модуль ничего не достраивает по этажности или количеству приборов. Он связывает
подтверждённые трубы и элементы в граф и отклоняет косметические соединения,
которые не подтверждены полями ``from_node``/``to_node``/``section_id``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec


FIXTURE_KINDS: Set[str] = {
    "toilet", "washbasin", "sink", "bath", "shower", "floor_drain", "trap",
}


@dataclass(frozen=True)
class SewerBranch:
    pipe: SewerPipeSpec
    riser_id: str
    elements: tuple[SewerElementSpec, ...]
    room_number: str
    room_name: str
    floor_from: int
    floor_to: int


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
    purpose = (pipe.purpose or "").lower()
    return "стояк" in purpose or "вертикаль" in purpose


def _is_declared_branch(pipe: SewerPipeSpec) -> bool:
    purpose = (pipe.purpose or "").lower()
    return any(word in purpose for word in ("ответвлен", "ветвь", "подключен"))


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
            if row.kind in FIXTURE_KINDS
        ]
        is_branch = _is_declared_branch(pipe) or bool(attached and fixture_elements)
        if not is_branch:
            result.mains.append(pipe)
            continue
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
        result.branches.append(SewerBranch(
            pipe=pipe,
            riser_id=next(iter(attached)),
            elements=tuple(sorted(fixture_elements, key=lambda row: (row.layout_column, row.element_id))),
            room_number=room_number,
            room_name=room_name,
            floor_from=min(floors_from),
            floor_to=max(floors_to),
        ))

    for row in elements:
        if row.kind in FIXTURE_KINDS and row.section_id not in branch_ids:
            result.errors.append(
                f"{row.element_id}: прибор должен быть привязан к отдельному "
                "этажному ответвлению, а не непосредственно к стояку"
            )

    for pipe in result.mains:
        if not pipe.from_node or not pipe.to_node:
            result.errors.append(
                f"{pipe.section_id}: для магистрали/выпуска нужны from_node и to_node"
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

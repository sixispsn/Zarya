"""Нормативный аудит монтажной топологии К1/К2 по СП 30.13330.2020.

Проверка не достраивает отсутствующие фасонные части и точки обслуживания.
Она сопоставляет явный реестр проекта с требованиями СП и сообщает, какие
решения подтверждены, а какие ещё требуют данных стадии Р/архитектурной
подложки.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec


@dataclass
class WastewaterSP30Audit:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    revision_floors: Dict[str, List[int]] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not self.errors


def _is_riser(pipe: SewerPipeSpec) -> bool:
    purpose = (pipe.purpose or "").lower()
    return "стояк" in purpose or "вертикаль" in purpose


def _services_turn(
    element: SewerElementSpec,
    riser: SewerPipeSpec,
    connected_main_ids: set[str],
) -> bool:
    if element.system != riser.system or element.kind not in {"revision", "cleanout"}:
        return False
    if element.section_id == riser.section_id:
        return True
    return (
        element.section_id in connected_main_ids
        and element.connects_to == riser.section_id
    )


def _compound_bend_quantity(
    elements: List[SewerElementSpec],
    riser: SewerPipeSpec,
    connected_main_ids: set[str],
) -> int:
    return sum(
        row.quantity
        for row in elements
        if row.system == riser.system
        and row.kind == "elbow"
        and (
            row.section_id == riser.section_id
            or (
                row.section_id in connected_main_ids
                and row.connects_to == riser.section_id
            )
        )
    )


def audit_wastewater_sp30(project: Project) -> WastewaterSP30Audit:
    """Проверить доступ для обслуживания и нижние повороты стояков.

    Контролируются требования:
    - 18.4: переход К1 из стояка в горизонталь не одним отводом 87,5°;
    - 18.26: нижний/верхний этажи и шаг ревизий не более трёх этажей;
    - 18.26: обслуживаемость поворотов К1;
    - 21.10: ревизия или прочистка на поворотах стояков К2.
    """
    result = WastewaterSP30Audit()
    elements = list(project.sewage.elements or [])
    pipes = list(project.sewage.pipes or [])
    floors = max(1, int(project.building.floors_above or 1))
    risers = [row for row in pipes if _is_riser(row)]
    mains = [row for row in pipes if not _is_riser(row)]

    for riser in risers:
        connected_mains = [
            row for row in mains
            if row.system == riser.system
            and riser.section_id in {row.from_node, row.to_node}
        ]
        connected_main_ids = {row.section_id for row in connected_mains}
        if not connected_mains:
            continue

        turn_service = [
            row for row in elements
            if _services_turn(row, riser, connected_main_ids)
        ]
        if riser.system == "K2" and not turn_service:
            result.errors.append(
                f"{riser.section_id}: на повороте стояка К2 нет ревизии/прочистки "
                "(СП 30.13330.2020, п. 21.10)"
            )
        elif riser.system == "K1" and not turn_service:
            result.warnings.append(
                f"{riser.section_id}: не подтверждён доступ к повороту К1; "
                "проверить необходимость прочистки по п. 18.26 СП 30.13330.2020"
            )

        if riser.system != "K1":
            continue

        revision_floors = sorted({
            row.floor_from
            for row in elements
            if row.system == "K1"
            and row.kind == "revision"
            and row.section_id == riser.section_id
            and 1 <= row.floor_from <= floors
        })
        result.revision_floors[riser.section_id] = revision_floors
        if 1 not in revision_floors:
            result.errors.append(
                f"{riser.section_id}: отсутствует ревизия на нижнем этаже "
                "(СП 30.13330.2020, п. 18.26)"
            )
        if floors not in revision_floors:
            result.errors.append(
                f"{riser.section_id}: отсутствует ревизия на верхнем этаже "
                "(СП 30.13330.2020, п. 18.26)"
            )
        if floors >= 5 and revision_floors:
            for lower, upper in zip(revision_floors, revision_floors[1:]):
                if upper - lower > 3:
                    result.errors.append(
                        f"{riser.section_id}: между ревизиями на этажах {lower} и "
                        f"{upper} более трёх этажей (п. 18.26 СП 30.13330.2020)"
                    )

        if _compound_bend_quantity(elements, riser, connected_main_ids) < 2:
            result.errors.append(
                f"{riser.section_id}: нижний поворот не подтверждён минимум двумя "
                "фасонными частями; одиночный отвод 87,5° запрещён "
                "(СП 30.13330.2020, п. 18.4)"
            )

    result.notes.extend((
        "СП 30.13330.2020, п. 18.30: расстояния между ревизиями/прочистками "
        "на горизонтальных участках требуют линейных привязок точек обслуживания",
        "СП 30.13330.2020, п. 18.26: доступ в начале ветвей с тремя и более "
        "приборами требует подтверждения по планам/аксонометрии",
    ))
    return result

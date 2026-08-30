"""Нормативный аудит монтажной топологии К1/К2 по СП 30.13330.2020.

Проверка не достраивает отсутствующие фасонные части и точки обслуживания.
Она сопоставляет подтверждённые данные проекта с требованиями СП и сообщает, какие
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
    purpose = (pipe.purpose or "").strip().lower()
    return purpose.startswith((
        "стояк",
        "канализационный стояк",
        "водосточный стояк",
        "вертикаль",
        "вертикальный участок",
    ))


def _services_turn(
    element: SewerElementSpec,
    riser: SewerPipeSpec,
    connected_main_ids: set[str],
) -> bool:
    if element.system != riser.system or element.kind not in {"revision", "cleanout"}:
        return False
    if not element.accessible:
        return False
    if element.kind == "revision":
        return (
            element.section_id == riser.section_id
            and element.floor_from <= 1
            and element.service_direction in {"downstream", "both"}
            and element.service_fitting == "revision_opening"
        )
    return (
        element.section_id in connected_main_ids
        and element.connects_to == riser.section_id
        and element.service_direction in {"downstream", "both"}
        and element.service_fitting == "wye_45"
    )


def _compound_bend_quantity(
    elements: List[SewerElementSpec],
    riser: SewerPipeSpec,
    connected_main_ids: set[str],
) -> int:
    elbows = sum(
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
    # Принятая пользователем геометрия логика1.pdf использует косой тройник
    # как вторую фасонную часть поворота. Это не скрывает буквальное отличие
    # от формулировки п. 18.4 про два отвода: оно отдельно выводится в аудите.
    wye_substitution = any(
        row.system == riser.system
        and row.kind in {"cleanout", "tee"}
        and row.section_id in connected_main_ids
        and row.connects_to == riser.section_id
        and "45" in row.type_mark
        and (
            row.kind == "tee"
            or (
                row.service_direction in {"downstream", "both"}
                and row.service_fitting == "wye_45"
                and row.accessible
            )
        )
        for row in elements
    )
    return elbows + int(wye_substitution)


def audit_wastewater_sp30(project: Project) -> WastewaterSP30Audit:
    """Проверить доступ для обслуживания и нижние повороты стояков.

    Контролируются требования:
    - 18.4: переход К1 из стояка в горизонталь не одним отводом 87,5°;
    - 18.26: нижний/верхний этажи и шаг ревизий не более трёх этажей;
    - 18.26: обслуживаемость поворотов К1;
    - 21.8: сеть внутренних водостоков должна быть доступна для прочистки;
    - 21.15: ревизии К2 в нижнем этаже, далее с шагом не более 40 м;
    - 21.2–21.3: К2 не соединяется с К1, кроме явно заданного зимнего
      отвода талых вод при открытом выпуске;
    - 21.13–21.14: К2 рассчитывается на гидростатическое давление и
      выполняется напорными трубами (кроме зданий высотой до 10 м).
    """
    result = WastewaterSP30Audit()
    elements = list(project.sewage.elements or [])
    pipes = list(project.sewage.pipes or [])
    floors = max(1, int(project.building.floors_above or 1))
    risers = [row for row in pipes if _is_riser(row)]
    mains = [
        row for row in pipes
        if not _is_riser(row)
        and any(
            mark in (row.purpose or "").strip().casefold()
            for mark in ("магистраль", "выпуск")
        )
    ]
    wye_substitution_risers: list[str] = []

    k1_pipes = [row for row in pipes if row.system == "K1"]
    k2_pipes = [row for row in pipes if row.system == "K2"]
    k1_outgoing_nodes = {row.from_node for row in k1_pipes if row.from_node}
    k1_terminal_nodes = {
        row.to_node
        for row in k1_pipes
        if row.to_node and row.to_node not in k1_outgoing_nodes
    }
    k1_internal_nodes = {
        node
        for row in k1_pipes
        for node in (row.from_node, row.to_node, row.section_id)
        if node and node not in k1_terminal_nodes
    }
    for pipe in k2_pipes:
        if pipe.from_node in k1_internal_nodes or pipe.to_node in k1_internal_nodes:
            result.errors.append(
                f"{pipe.section_id}: внутренний участок К2 присоединён к узлу К1; "
                "отведение воды из внутренних водостоков в бытовую канализацию "
                "не допускается (СП 30.13330.2020, п. 21.2)"
            )
    for element in elements:
        if (
            element.system == "K2"
            and element.connects_to in k1_internal_nodes
        ):
            result.errors.append(
                f"{element.element_id}: элемент К2 присоединён к внутреннему узлу "
                "К1 (СП 30.13330.2020, п. 21.2)"
            )

    network_type = (project.sewage.existing_network_type or "").casefold()
    k1_discharge = (project.sewage.discharge_point_k1 or "").strip()
    k2_discharge = (project.sewage.discharge_point_k2 or "").strip()
    if "раздель" in network_type and k1_discharge and k1_discharge == k2_discharge:
        result.errors.append(
            "К1 и К2 направлены в одну точку при заявленной раздельной наружной "
            "сети; требуется раздельная трассировка выпусков (пп. 21.1–21.3 "
            "СП 30.13330.2020)"
        )

    k2_elevations = [
        value
        for pipe in k2_pipes
        for value in (pipe.elevation_start_m, pipe.elevation_end_m)
        if value is not None
    ]
    k2_hydrostatic_bar = None
    if k2_elevations:
        k2_hydrostatic_bar = (max(k2_elevations) - min(k2_elevations)) * 0.0980665
    if project.building.height_m > 10 and k2_pipes:
        for pipe in k2_pipes:
            if pipe.pressure_rated is not True:
                result.errors.append(
                    f"{pipe.section_id}: для К2 здания высотой более 10 м не "
                    "подтверждена напорная труба (СП 30.13330.2020, п. 21.14)"
                )
                continue
            if pipe.pressure_class_bar is None:
                result.errors.append(
                    f"{pipe.section_id}: не задан класс давления напорной трубы "
                    "К2 для проверки гидростатического давления при засоре "
                    "(п. 21.13 СП 30.13330.2020)"
                )
            elif (
                k2_hydrostatic_bar is not None
                and pipe.pressure_class_bar + 1e-9 < k2_hydrostatic_bar
            ):
                result.errors.append(
                    f"{pipe.section_id}: класс давления {pipe.pressure_class_bar:g} "
                    f"бар меньше гидростатического столба {k2_hydrostatic_bar:.2f} "
                    "бар при засоре (п. 21.13 СП 30.13330.2020)"
                )

    for riser in risers:
        connected_mains = [
            row for row in mains
            if row.system == riser.system
            and riser.section_id in {row.from_node, row.to_node}
        ]
        connected_main_ids = {row.section_id for row in connected_mains}
        incoming_mains = [
            row for row in connected_mains if row.to_node == riser.section_id
        ]
        invalid_through_cleanouts = [
            row for row in elements
            if row.system == riser.system
            and row.kind == "cleanout"
            and row.connects_to == riser.section_id
            and row.service_fitting == "wye_45"
            and incoming_mains
        ]
        for cleanout in invalid_through_cleanouts:
            result.errors.append(
                f"{cleanout.element_id}: заглушённая прочистка недопустима в "
                f"проточном узле {riser.section_id}; входящая магистраль "
                f"{incoming_mains[0].section_id}: заглушка перекрыла бы поток"
            )
        if not connected_mains:
            continue

        turn_service = [
            row for row in elements
            if _services_turn(row, riser, connected_main_ids)
            and row not in invalid_through_cleanouts
        ]
        if any(
            row.kind in {"cleanout", "tee"}
            and "45" in row.type_mark
            and row.section_id in connected_main_ids
            and row.connects_to == riser.section_id
            for row in elements
        ):
            if riser.system == "K1":
                wye_substitution_risers.append(riser.section_id)
        if riser.system == "K2" and not turn_service:
            result.errors.append(
                f"{riser.section_id}: на повороте стояка К2 нет ревизии/прочистки "
                "(СП 30.13330.2020, п. 21.8 с учётом раздела 18)"
            )
        elif riser.system == "K1" and not turn_service:
            result.warnings.append(
                f"{riser.section_id}: не подтверждён доступ к повороту К1; "
                "проверить необходимость прочистки по п. 18.26 СП 30.13330.2020"
            )

        if riser.system == "K2":
            k2_revisions = [
                row for row in elements
                if row.system == "K2"
                and row.kind == "revision"
                and row.section_id == riser.section_id
                and row.accessible
                and row.service_fitting == "revision_opening"
            ]
            revision_floors = sorted({row.floor_from for row in k2_revisions})
            result.revision_floors[riser.section_id] = revision_floors
            if not any(row.floor_from <= 1 for row in k2_revisions):
                result.errors.append(
                    f"{riser.section_id}: отсутствует ревизия К2 в нижнем этаже "
                    "(СП 30.13330.2020, п. 21.15)"
                )
            missing_elevations = [
                row.element_id for row in k2_revisions if row.elevation_m is None
            ]
            if missing_elevations:
                result.errors.append(
                    f"{riser.section_id}: для ревизий {', '.join(missing_elevations)} "
                    "не заданы отметки; шаг 40 м по п. 21.15 не проверяется"
                )
            elif (
                riser.elevation_start_m is not None
                and riser.elevation_end_m is not None
                and k2_revisions
            ):
                lower = min(riser.elevation_start_m, riser.elevation_end_m)
                upper = max(riser.elevation_start_m, riser.elevation_end_m)
                points = sorted(
                    row.elevation_m for row in k2_revisions
                    if row.elevation_m is not None
                    and lower <= row.elevation_m <= upper
                )
                spans = [
                    right - left
                    for left, right in zip(
                        [lower, *points],
                        [*points, upper],
                    )
                ]
                if spans and max(spans) > 40.0 + 1e-9:
                    result.errors.append(
                        f"{riser.section_id}: максимальный вертикальный интервал "
                        f"между ревизиями К2 {max(spans):.1f} м превышает 40 м "
                        "(СП 30.13330.2020, п. 21.15)"
                    )
            continue

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

    if wye_substitution_risers:
        result.warnings.append(
            "Узлы " + ", ".join(wye_substitution_risers)
            + ": по логика1.pdf косой тройник заменяет второй полуотвод; "
            "буквальный п. 18.4 СП 30.13330.2020 называет два отвода 45°. "
            "Монтажное решение требует подтверждения проектировщиком."
        )

    result.notes.extend((
        "СП 30.13330.2020, п. 18.30, таблица 18.1: К1 DN50 — ревизии "
        "не более 12 м, прочистки не более 8 м; К1 DN100–150 — 15/10 м",
        "СП 30.13330.2020, п. 18.30, таблица 18.1: К2 DN50 — ревизии "
        "не более 15 м, прочистки не более 10 м; К2 DN100–150 — 20/15 м",
        "СП 30.13330.2020, п. 18.26: доступ в начале ветвей с тремя и более "
        "приборами требует подтверждения по планам/аксонометрии",
        "СП 30.13330.2020, п. 21.2: постоянный либо автоматический перепуск "
        "К2 в К1 запрещён. Примечание к п. 21.3 допускает зимний отвод талых "
        "вод в К1 только при открытом выпуске, с запорной арматурой/обратным "
        "клапаном и гидравлическим затвором; это не обязательное решение",
        "СП 30.13330.2020, п. 21.13: расчёт креплений К2 на гидростатическое "
        "давление требует узлов крепления и нагрузок стадии Р",
    ))
    return result

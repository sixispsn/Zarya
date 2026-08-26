"""Resolve confirmed project inputs for the K1 basement schematic.

The resolver deliberately refuses to choose between several plausible
outlets.  A missing or ambiguous registry remains a visible incompleteness;
it is never replaced with a generated elevation, slope or outlet mark.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec
from app.pz.wastewater_floor_drafting import FloorFixtureInput


_FLOOR_FIXTURE_KINDS = {
    "sink",
    "washbasin",
    "bath",
    "shower",
    "floor_drain",
    "toilet",
}


@dataclass(frozen=True)
class WastewaterBasementProjectInputs:
    """Confirmed values and selection diagnostics for one K1 outlet."""

    basement_floor_elevation_m: float | None
    outlet_invert_elevation_m: float | None
    collector_slope_per_mille: float | None
    outlet_dn_mm: int | None
    outlet_id: str
    selected_section_id: str
    selection_status: str
    diagnostics: tuple[str, ...]

    @property
    def missing_project_inputs(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.basement_floor_elevation_m is None:
            missing.append("basement_floor_elevation_m")
        if not self.outlet_id:
            missing.append("outlet_id")
        if self.outlet_dn_mm is None:
            missing.append("outlet_dn_mm")
        if self.outlet_invert_elevation_m is None:
            missing.append("outlet_invert_elevation_m")
        if self.collector_slope_per_mille is None:
            missing.append("collector_slope_per_mille")
        return tuple(missing)

    @property
    def complete(self) -> bool:
        return not self.missing_project_inputs


@dataclass(frozen=True)
class WastewaterStackProjectInputs:
    """Registry-backed inputs for one complete K1 riser control drawing."""

    riser_id: str
    riser_dn_mm: int | None
    floors_above: int
    fixtures_by_floor_rows: tuple[tuple[int, tuple[FloorFixtureInput, ...]], ...]
    slope_dn50: float | None
    slope_dn100: float | None
    basement: WastewaterBasementProjectInputs
    selection_status: str
    diagnostics: tuple[str, ...]

    @property
    def fixtures_by_floor(self) -> dict[int, tuple[FloorFixtureInput, ...]]:
        return dict(self.fixtures_by_floor_rows)

    @property
    def missing_project_inputs(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.riser_id:
            missing.append("riser_id")
        if self.riser_dn_mm is None:
            missing.append("riser_dn_mm")
        if self.floors_above < 1:
            missing.append("floors_above")
        if not self.fixtures_by_floor_rows:
            missing.append("fixtures_by_floor")
        if self.slope_dn50 is None:
            missing.append("slope_dn50")
        if self.slope_dn100 is None:
            missing.append("slope_dn100")
        missing.extend(self.basement.missing_project_inputs)
        return tuple(dict.fromkeys(missing))

    @property
    def complete(self) -> bool:
        return not self.missing_project_inputs and not self.diagnostics


def _system(value: str) -> str:
    return value.strip().upper()


def _section(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _select_outlet_pipe(project: Project) -> tuple[SewerPipeSpec | None, str, list[str]]:
    diagnostics: list[str] = []
    k1_pipes = [row for row in project.sewage.pipes if _system(row.system) == "K1"]
    linked_section_ids = {
        _section(row.section_id): row.section_id.strip()
        for row in project.sewage.elements
        if _system(row.system) == "K1"
        and row.kind == "outlet"
        and row.section_id.strip()
    }

    if len(linked_section_ids) > 1:
        diagnostics.append(
            "В реестре элементов К1 несколько выпусков; для листа стояка "
            "нужен однозначный участок выпуска."
        )
        return None, "ambiguous", diagnostics

    if len(linked_section_ids) == 1:
        section_key, display_id = next(iter(linked_section_ids.items()))
        matches = [row for row in k1_pipes if _section(row.section_id) == section_key]
        if len(matches) == 1:
            return matches[0], "linked", diagnostics
        if len(matches) > 1:
            diagnostics.append(
                f"Участок выпуска {display_id} повторяется в реестре труб К1."
            )
            return None, "ambiguous", diagnostics
        diagnostics.append(
            f"Элемент выпуска ссылается на участок {display_id}, которого нет "
            "в реестре труб К1."
        )
        return None, "missing", diagnostics

    purpose_matches = [
        row for row in k1_pipes if "выпуск" in row.purpose.strip().casefold()
    ]
    if len(purpose_matches) == 1:
        diagnostics.append(
            "Выпуск выбран по единственной трубе К1 с назначением «выпуск»; "
            "рекомендуется связать её с элементом типа «выпуск»."
        )
        return purpose_matches[0], "purpose", diagnostics
    if len(purpose_matches) > 1:
        diagnostics.append(
            "Найдено несколько труб К1 с назначением «выпуск»; выбор не выполнен."
        )
        return None, "ambiguous", diagnostics

    diagnostics.append(
        "Выпуск К1 не найден: добавьте элемент типа «выпуск» и свяжите его "
        "с участком трубы."
    )
    return None, "missing", diagnostics


def resolve_wastewater_basement_project_inputs(
    project: Project,
) -> WastewaterBasementProjectInputs:
    """Resolve only project-confirmed basement values from the K1 registry."""
    pipe, selection_status, diagnostics = _select_outlet_pipe(project)
    basement_floor = project.sewage.basement_floor_elevation_m

    if basement_floor is None:
        diagnostics.append("Не задана относительная отметка чистого пола подвала.")

    if pipe is None:
        return WastewaterBasementProjectInputs(
            basement_floor_elevation_m=basement_floor,
            outlet_invert_elevation_m=None,
            collector_slope_per_mille=None,
            outlet_dn_mm=None,
            outlet_id="",
            selected_section_id="",
            selection_status=selection_status,
            diagnostics=tuple(diagnostics),
        )

    if pipe.elevation_end_m is None:
        diagnostics.append(
            f"Для выпуска {pipe.section_id} не задана относительная отметка конца."
        )
    if pipe.slope_per_mille is None:
        diagnostics.append(f"Для выпуска {pipe.section_id} не задан уклон.")
    if pipe.nominal_diameter_mm is None:
        diagnostics.append(
            f"Для выпуска {pipe.section_id} не задан номинальный диаметр."
        )

    missing_value = (
        basement_floor is None
        or pipe.elevation_end_m is None
        or pipe.slope_per_mille is None
        or pipe.nominal_diameter_mm is None
        or not pipe.section_id.strip()
    )
    status = "partial" if missing_value else "resolved"
    return WastewaterBasementProjectInputs(
        basement_floor_elevation_m=basement_floor,
        outlet_invert_elevation_m=pipe.elevation_end_m,
        collector_slope_per_mille=pipe.slope_per_mille,
        outlet_dn_mm=pipe.nominal_diameter_mm,
        outlet_id=pipe.section_id.strip(),
        selected_section_id=pipe.section_id.strip(),
        selection_status=status,
        diagnostics=tuple(diagnostics),
    )


def _fixture_dn_group(dn_mm: int) -> int | None:
    if dn_mm == 50:
        return 50
    if dn_mm >= 100:
        return 100
    return None


def _room_label(element: SewerElementSpec) -> str:
    parts = [element.room_number.strip(), element.room_name.strip()]
    return " - ".join(part for part in parts if part)


def resolve_wastewater_stack_project_inputs(
    project: Project,
    *,
    riser_id: str,
) -> WastewaterStackProjectInputs:
    """Resolve every floor fixture for one K1 riser without typical defaults."""
    diagnostics: list[str] = []
    requested_riser_id = riser_id.strip()
    floors_above = project.building.floors_above
    basement = resolve_wastewater_basement_project_inputs(project)
    if floors_above < 1:
        diagnostics.append("В проекте не задано положительное число этажей.")
    if not requested_riser_id:
        diagnostics.append("Не задано обозначение стояка К1.")

    riser_key = _section(requested_riser_id)
    riser_matches = [
        row
        for row in project.sewage.pipes
        if _system(row.system) == "K1"
        and _section(row.section_id) == riser_key
        and "стояк" in row.purpose.strip().casefold()
    ]
    if len(riser_matches) != 1:
        diagnostics.append(
            f"Стояк {requested_riser_id or 'К1'} должен быть задан ровно одной "
            "трубой К1 с назначением «стояк»."
        )
        riser = None
    else:
        riser = riser_matches[0]
        if riser.nominal_diameter_mm is None:
            diagnostics.append(
                f"Для стояка {riser.section_id} не задан номинальный диаметр."
            )

    k1_elements = [
        row for row in project.sewage.elements if _system(row.system) == "K1"
    ]
    elements_by_section: dict[str, list[SewerElementSpec]] = {}
    for element in k1_elements:
        if element.section_id.strip():
            elements_by_section.setdefault(_section(element.section_id), []).append(
                element
            )

    branch_rows: list[tuple[SewerPipeSpec, list[SewerElementSpec]]] = []
    for pipe in project.sewage.pipes:
        if (
            _system(pipe.system) != "K1"
            or _section(pipe.section_id) == riser_key
            or _section(pipe.to_node) != riser_key
        ):
            continue
        fixture_elements = [
            row
            for row in elements_by_section.get(_section(pipe.section_id), [])
            if row.kind in _FLOOR_FIXTURE_KINDS
        ]
        if fixture_elements:
            branch_rows.append((pipe, fixture_elements))

    if not branch_rows:
        diagnostics.append(
            f"К стояку {requested_riser_id or 'К1'} не привязано ни одного "
            "этажного ответвления с приборами."
        )

    selected_elements = [
        element for _, elements in branch_rows for element in elements
    ]
    element_keys = [_section(row.element_id) for row in selected_elements]
    if len(element_keys) != len(set(element_keys)):
        diagnostics.append(
            f"В ветвях стояка {requested_riser_id} повторяются обозначения приборов."
        )
    elements_by_id = {
        _section(row.element_id): row for row in selected_elements if row.element_id.strip()
    }

    for pipe, elements in branch_rows:
        if not pipe.section_id.strip():
            diagnostics.append("У этажного ответвления не задано обозначение.")
        if _section(pipe.from_node) not in {
            _section(row.element_id) for row in elements
        }:
            diagnostics.append(
                f"{pipe.section_id}: from_node должен быть прибором этой ветви."
            )
        if pipe.nominal_diameter_mm is None:
            diagnostics.append(f"{pipe.section_id}: не задан DN этажной ветви.")
        elif _fixture_dn_group(pipe.nominal_diameter_mm) is None:
            diagnostics.append(
                f"{pipe.section_id}: DN{pipe.nominal_diameter_mm} пока не "
                "поддерживается поэтажным модулем."
            )
        if pipe.slope_per_mille is None or pipe.slope_per_mille <= 0:
            diagnostics.append(
                f"{pipe.section_id}: не задан положительный уклон этажной ветви."
            )

    for element in selected_elements:
        if not element.element_id.strip():
            diagnostics.append("У прибора К1 не задано обозначение.")
            continue
        target = _section(element.connects_to)
        if not target:
            diagnostics.append(
                f"{element.element_id}: не задан следующий узел по движению стоков."
            )
            continue
        visited: set[str] = set()
        current = _section(element.element_id)
        while current != riser_key:
            if current in visited:
                diagnostics.append(
                    f"{element.element_id}: цикл в связях приборов до стояка."
                )
                break
            visited.add(current)
            current_element = elements_by_id.get(current)
            if current_element is None:
                diagnostics.append(
                    f"{element.element_id}: связь обрывается до стояка "
                    f"{requested_riser_id}."
                )
                break
            current = _section(current_element.connects_to)

        floor_to = element.floor_to if element.floor_to is not None else element.floor_from
        if element.floor_from < 1 or floor_to > floors_above or floor_to < element.floor_from:
            diagnostics.append(
                f"{element.element_id}: диапазон этажей {element.floor_from}-{floor_to} "
                f"не входит в 1-{floors_above}."
            )
        if element.typical_quantity is None or element.typical_quantity < 1:
            diagnostics.append(
                f"{element.element_id}: не задано положительное количество "
                "в типовом помещении."
            )
        else:
            expected_total = element.typical_quantity * (
                floor_to - element.floor_from + 1
            )
            if element.quantity != expected_total:
                diagnostics.append(
                    f"{element.element_id}: всего {element.quantity} шт., но "
                    f"{element.typical_quantity} шт. x "
                    f"{floor_to - element.floor_from + 1} этажей = "
                    f"{expected_total} шт."
                )
        if element.dn_mm is None:
            diagnostics.append(f"{element.element_id}: не задан DN прибора.")
        elif _fixture_dn_group(element.dn_mm) is None:
            diagnostics.append(
                f"{element.element_id}: DN{element.dn_mm} пока не "
                "поддерживается поэтажным модулем."
            )
        if element.slope_per_mille is None or element.slope_per_mille <= 0:
            diagnostics.append(
                f"{element.element_id}: не задан положительный уклон подключения."
            )
        if not _room_label(element):
            diagnostics.append(
                f"{element.element_id}: не задано помещение прибора."
            )

    slopes: dict[int, set[float]] = {50: set(), 100: set()}
    for pipe, _ in branch_rows:
        if pipe.nominal_diameter_mm is not None and pipe.slope_per_mille is not None:
            group = _fixture_dn_group(pipe.nominal_diameter_mm)
            if group is not None and pipe.slope_per_mille > 0:
                slopes[group].add(round(pipe.slope_per_mille / 1000.0, 6))
    for element in selected_elements:
        if element.dn_mm is not None and element.slope_per_mille is not None:
            group = _fixture_dn_group(element.dn_mm)
            if group is not None and element.slope_per_mille > 0:
                slopes[group].add(round(element.slope_per_mille / 1000.0, 6))

    resolved_slopes: dict[int, float | None] = {50: None, 100: None}
    for group, values in slopes.items():
        if len(values) == 1:
            resolved_slopes[group] = next(iter(values))
        elif not values:
            diagnostics.append(
                f"Для ветвей DN{group} стояка {requested_riser_id} не задан уклон."
            )
        else:
            diagnostics.append(
                f"Для ветвей DN{group} стояка {requested_riser_id} заданы "
                f"разные уклоны: {', '.join(f'{value:.3f}' for value in sorted(values))}."
            )

    fixture_rows: list[tuple[int, tuple[FloorFixtureInput, ...]]] = []
    if floors_above > 0:
        for floor_no in range(1, floors_above + 1):
            floor_elements = []
            for element in selected_elements:
                floor_to = (
                    element.floor_to
                    if element.floor_to is not None
                    else element.floor_from
                )
                if element.floor_from <= floor_no <= floor_to:
                    floor_elements.append(element)
            toilets = [row for row in floor_elements if row.kind == "toilet"]
            if len(floor_elements) < 3:
                diagnostics.append(
                    f"Этаж {floor_no}: для стояка {requested_riser_id} нужно "
                    "не менее трёх подтверждённых типов приборов."
                )
                continue
            if len(toilets) != 1:
                diagnostics.append(
                    f"Этаж {floor_no}: должен быть один тип унитаза у стояка "
                    f"{requested_riser_id}; найдено {len(toilets)}."
                )
                continue
            if any(
                row.dn_mm is None
                or row.typical_quantity is None
                or row.typical_quantity < 1
                for row in floor_elements
            ):
                continue
            fixtures = tuple(
                FloorFixtureInput(
                    fixture_id=row.element_id,
                    kind=row.kind,
                    room_label=_room_label(row),
                    dn_mm=row.dn_mm,
                    quantity=row.typical_quantity or 1,
                )
                for row in floor_elements
            )
            fixture_rows.append((floor_no, fixtures))

    all_floors_resolved = (
        floors_above > 0 and len(fixture_rows) == floors_above
    )
    if not all_floors_resolved:
        fixture_rows = []

    riser_dn = riser.nominal_diameter_mm if riser is not None else None
    diagnostics.extend(basement.diagnostics)
    status = "resolved" if (
        not diagnostics
        and basement.complete
        and riser_dn is not None
        and all_floors_resolved
        and resolved_slopes[50] is not None
        and resolved_slopes[100] is not None
    ) else "partial"
    return WastewaterStackProjectInputs(
        riser_id=requested_riser_id,
        riser_dn_mm=riser_dn,
        floors_above=floors_above,
        fixtures_by_floor_rows=tuple(fixture_rows),
        slope_dn50=resolved_slopes[50],
        slope_dn100=resolved_slopes[100],
        basement=basement,
        selection_status=status,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )

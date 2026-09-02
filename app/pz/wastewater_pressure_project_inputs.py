"""Strict confirmed inputs for a separate internal pressure-sewer sheet.

The resolver never selects a pump and never invents a pressure main.  It only
checks a designer-supplied pump curve, a designer-supplied system duty point,
the registered pressure-pipe chain and the registered fittings.  K2 pressure
rainwater pipes are deliberately outside this contour.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from app.pz.project import Project, SewerElementSpec, SewerPipeSpec


_SYSTEMS = {"K1", "K3"}
_MODES = {"local_fixture_unit", "internal_station"}
_TOLERANCE = 0.10


def _system(value: str) -> str:
    return (value or "").strip().upper().replace("К", "K")


def _section(value: str) -> str:
    return (value or "").strip()


@dataclass(frozen=True)
class PressureWorkingPoint:
    q_m3h: float
    pump_head_m: float
    system_head_m: float


@dataclass(frozen=True)
class WastewaterPressureProjectInputs:
    applicable: bool
    system: str
    mode: str
    pressure_pipes: tuple[SewerPipeSpec, ...]
    pump_element: SewerElementSpec | None
    check_valve_element: SewerElementSpec | None
    isolation_valve_element: SewerElementSpec | None
    sump_element: SewerElementSpec | None
    pressure_break_loop_element: SewerElementSpec | None
    receiving_gravity_pipe: SewerPipeSpec | None
    working_point: PressureWorkingPoint | None
    system_curve_k: float | None
    diagnostics: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.applicable and bool(self.pressure_pipes) and not self.diagnostics


def pressure_sewer_is_applicable(project: Project) -> bool:
    """Return whether an internal pressure K1/K3 system is explicitly declared."""
    sewage = project.sewage
    return bool(
        sewage.pump_required
        or _system(sewage.pump_system) in _SYSTEMS
        or any(
            row.pressure_rated is True and _system(row.system) in _SYSTEMS
            for row in sewage.pipes
        )
        or any(
            row.kind == "pump" and _system(row.system) in _SYSTEMS
            for row in sewage.elements
        )
    )


def _order_pressure_chain(
    pipes: list[SewerPipeSpec], diagnostics: list[str]
) -> tuple[SewerPipeSpec, ...]:
    if not pipes:
        return ()
    by_from: dict[str, list[SewerPipeSpec]] = {}
    incoming: dict[str, int] = {}
    for row in pipes:
        by_from.setdefault(_section(row.from_node), []).append(row)
        incoming[_section(row.to_node)] = incoming.get(_section(row.to_node), 0) + 1
    if any(len(rows) > 1 for rows in by_from.values()):
        diagnostics.append(
            "Напорная сеть разветвляется; для выпуска требуется отдельная "
            "подтверждённая рабочая точка каждой ветви."
        )
        return tuple(pipes)
    if any(value > 1 for value in incoming.values()):
        diagnostics.append("Напорная сеть имеет неподтверждённое слияние участков.")
        return tuple(pipes)
    starts = [row for row in pipes if incoming.get(_section(row.from_node), 0) == 0]
    if len(starts) != 1:
        diagnostics.append(
            "Напорные участки должны образовывать одну направленную цепь от насоса."
        )
        return tuple(pipes)
    ordered: list[SewerPipeSpec] = []
    seen: set[str] = set()
    current = starts[0]
    while current.section_id not in seen:
        ordered.append(current)
        seen.add(current.section_id)
        next_rows = by_from.get(_section(current.to_node), [])
        if not next_rows:
            break
        current = next_rows[0]
    if len(ordered) != len(pipes):
        diagnostics.append("Напорная цепь разорвана либо содержит цикл.")
    return tuple(ordered)


def _curve_intersection(
    curve: list[tuple[float, float]],
    *,
    static_head_m: float,
    dynamic_loss_m: float,
    design_q_m3h: float,
) -> tuple[PressureWorkingPoint | None, float | None]:
    if design_q_m3h <= 0:
        return None, None
    k = dynamic_loss_m / design_q_m3h ** 2
    candidates: list[PressureWorkingPoint] = []
    for (q1, h1), (q2, h2) in zip(curve, curve[1:]):
        slope = (h2 - h1) / (q2 - q1)
        intercept = h1 - slope * q1
        roots: list[float] = []
        if abs(k) < 1e-12:
            if abs(slope) > 1e-12:
                roots.append((static_head_m - intercept) / slope)
        else:
            discriminant = slope ** 2 - 4.0 * k * (static_head_m - intercept)
            if discriminant >= 0:
                roots.extend((
                    (slope - sqrt(discriminant)) / (2.0 * k),
                    (slope + sqrt(discriminant)) / (2.0 * k),
                ))
        for q_value in roots:
            if q1 - 1e-9 <= q_value <= q2 + 1e-9:
                pump_head = intercept + slope * q_value
                system_head = static_head_m + k * q_value ** 2
                candidates.append(PressureWorkingPoint(
                    q_m3h=q_value,
                    pump_head_m=pump_head,
                    system_head_m=system_head,
                ))
    unique: list[PressureWorkingPoint] = []
    for row in sorted(candidates, key=lambda item: item.q_m3h):
        if not unique or abs(row.q_m3h - unique[-1].q_m3h) > 1e-7:
            unique.append(row)
    return (unique[0] if len(unique) == 1 else None), k


def _single_element(
    elements: list[SewerElementSpec],
    *,
    kind: str,
    system: str,
    label: str,
    diagnostics: list[str],
    required: bool = True,
) -> SewerElementSpec | None:
    rows = [row for row in elements if row.kind == kind and _system(row.system) == system]
    if not rows and required:
        diagnostics.append(f"{label}: элемент не зарегистрирован.")
        return None
    if len(rows) > 1:
        diagnostics.append(f"{label}: найдено несколько элементов; нужен один точный узел.")
        return None
    row = rows[0] if rows else None
    if row is not None and (not row.element_id.strip() or row.quantity <= 0):
        diagnostics.append(f"{label}: нужны ID и положительное количество.")
    return row


def resolve_wastewater_pressure_project_inputs(
    project: Project,
) -> WastewaterPressureProjectInputs:
    sewage = project.sewage
    applicable = pressure_sewer_is_applicable(project)
    if not applicable:
        return WastewaterPressureProjectInputs(
            applicable=False,
            system="",
            mode="not_set",
            pressure_pipes=(),
            pump_element=None,
            check_valve_element=None,
            isolation_valve_element=None,
            sump_element=None,
            pressure_break_loop_element=None,
            receiving_gravity_pipe=None,
            working_point=None,
            system_curve_k=None,
            diagnostics=(),
        )

    diagnostics: list[str] = []
    system = _system(sewage.pump_system)
    mode = sewage.pump_mode
    if system not in _SYSTEMS:
        diagnostics.append("Для напорной канализации выберите систему К1 или К3.")
    if mode not in _MODES:
        diagnostics.append(
            "Выберите режим: малогабаритная установка по п. 18.32 СП 30 "
            "или внутренняя насосная станция по п. 18.31."
        )
    if not sewage.pump_required:
        diagnostics.append("Признак «предусмотрена КНС» не установлен.")

    pressure_rows = [
        row for row in sewage.pipes
        if row.pressure_rated is True and _system(row.system) in _SYSTEMS
    ]
    if system in _SYSTEMS:
        foreign = [row.section_id for row in pressure_rows if _system(row.system) != system]
        if foreign:
            diagnostics.append(
                "Напорный реестр смешивает системы: " + ", ".join(foreign)
            )
        pressure_rows = [row for row in pressure_rows if _system(row.system) == system]
    if not pressure_rows:
        diagnostics.append("Не зарегистрированы напорные участки К1/К3.")
    section_ids = [row.section_id.strip() for row in pressure_rows]
    if any(not value for value in section_ids) or len(set(section_ids)) != len(section_ids):
        diagnostics.append("Напорным участкам нужны уникальные непустые ID.")
    for row in pressure_rows:
        label = row.section_id or "без ID"
        if not row.from_node.strip() or not row.to_node.strip():
            diagnostics.append(f"Участок {label}: нужны начальный и конечный узлы.")
        if (
            row.outer_diameter_mm <= 0
            or row.wall_thickness_mm <= 0
            or row.inner_diameter_mm <= 0
            or not row.nominal_diameter_mm
        ):
            diagnostics.append(f"Участок {label}: нужны точные DN, Dнар и толщина стенки.")
        if row.length_m <= 0 or not row.calculation_length_m or row.calculation_length_m <= 0:
            diagnostics.append(f"Участок {label}: нужны монтажная и расчётная длины.")
        if not row.material.strip() or not row.standard.strip() or not row.room.strip():
            diagnostics.append(f"Участок {label}: нужны материал, стандарт и помещение.")
        if not row.design_flow_lps or row.design_flow_lps <= 0:
            diagnostics.append(f"Участок {label}: нужен расчётный расход.")
        if not row.hydraulic_source.strip():
            diagnostics.append(f"Участок {label}: нужен источник гидравлических потерь.")
        if not row.pressure_class_bar or row.pressure_class_bar <= 0:
            diagnostics.append(f"Участок {label}: нужен подтверждённый класс давления PN.")
        if row.elevation_start_m is None or row.elevation_end_m is None:
            diagnostics.append(f"Участок {label}: нужны отметки начала и конца.")
    ordered = _order_pressure_chain(pressure_rows, diagnostics)

    pump = _single_element(
        sewage.elements, kind="pump", system=system, label="Насос", diagnostics=diagnostics
    )
    check_valve = _single_element(
        sewage.elements,
        kind="check_valve",
        system=system,
        label="Обратный клапан",
        diagnostics=diagnostics,
    )
    isolation_valve = _single_element(
        sewage.elements,
        kind="ball_valve",
        system=system,
        label="Запорная арматура",
        diagnostics=diagnostics,
    )
    sump = _single_element(
        sewage.elements,
        kind="sump",
        system=system,
        label="Приёмный резервуар",
        diagnostics=diagnostics,
        required=mode == "internal_station",
    )
    break_loop = _single_element(
        sewage.elements,
        kind="pressure_break_loop",
        system=system,
        label="Петля гашения напора",
        diagnostics=diagnostics,
        required=mode == "local_fixture_unit",
    )

    if ordered:
        first_id = ordered[0].section_id.strip()
        for element, label in (
            (pump, "Насос"),
            (check_valve, "Обратный клапан"),
            (isolation_valve, "Запорная арматура"),
        ):
            if element is not None and _section(element.section_id) != first_id:
                diagnostics.append(f"{label}: привяжите к первому участку {first_id}.")
        if break_loop is not None and _section(break_loop.section_id) != ordered[-1].section_id:
            diagnostics.append(
                f"Петля гашения напора: привяжите к конечному участку "
                f"{ordered[-1].section_id}."
            )

    discharge_node = sewage.pump_discharge_node.strip()
    if not discharge_node:
        diagnostics.append("Не задан узел присоединения напорной линии к самотечной сети.")
    if ordered and discharge_node and ordered[-1].to_node.strip() != discharge_node:
        diagnostics.append(
            "Конечный узел напорной цепи не совпадает с заданным узлом присоединения."
        )
    gravity_rows = [
        row for row in sewage.pipes
        if _system(row.system) == system and row.pressure_rated is not True
        and discharge_node
        and row.section_id.strip() == discharge_node
    ]
    if not gravity_rows:
        gravity_rows = [
            row for row in sewage.pipes
            if _system(row.system) == system and row.pressure_rated is not True
            and discharge_node
            and discharge_node in {row.from_node.strip(), row.to_node.strip()}
        ]
    receiving_gravity_pipe = gravity_rows[0] if len(gravity_rows) == 1 else None
    if discharge_node and not gravity_rows:
        diagnostics.append(
            f"Узел {discharge_node}: не найдена принимающая самотечная труба {system}."
        )
    elif len(gravity_rows) > 1:
        diagnostics.append(
            f"Узел {discharge_node}: принимающая самотечная труба задана неоднозначно."
        )
    if (
        break_loop is not None
        and discharge_node
        and _section(break_loop.connects_to) != discharge_node
    ):
        diagnostics.append(
            "Петля гашения напора должна быть связана с заданным принимающим узлом."
        )

    if mode == "local_fixture_unit" and not (
        sewage.pump_fixture_count is not None and 2 <= sewage.pump_fixture_count <= 4
    ):
        diagnostics.append(
            "Для малогабаритной установки укажите от 2 до 4 приборов "
            "(п. 18.32 СП 30.13330.2020)."
        )
    if mode == "internal_station":
        if not sewage.pump_receiver_useful_volume_m3 or sewage.pump_receiver_useful_volume_m3 <= 0:
            diagnostics.append("Для насосной станции нужен полезный объём приёмной части.")
        if not sewage.pump_emergency_volume_m3 or sewage.pump_emergency_volume_m3 <= 0:
            diagnostics.append("Для насосной станции нужен подтверждённый аварийный объём.")
        if not sewage.pump_emergency_runtime_min or sewage.pump_emergency_runtime_min <= 0:
            diagnostics.append("Для насосной станции нужно расчётное время реагирования.")

    required_values = (
        (sewage.pump_q_m3h, "расход насоса Q"),
        (sewage.pump_head_m, "напор насоса H"),
        (sewage.pump_power_kw, "мощность насоса"),
        (sewage.pump_static_head_m, "статическая составляющая напора"),
        (sewage.pump_dynamic_loss_m, "динамические потери"),
    )
    zero_allowed = {"статическая составляющая напора", "динамические потери"}
    for value, label in required_values:
        if value is None or value < 0 or (label not in zero_allowed and value == 0):
            diagnostics.append(f"Не задано положительное значение: {label}.")
    if not sewage.pump_model.strip() or not sewage.pump_location.strip():
        diagnostics.append("Для насоса нужны точные модель/тип и размещение.")
    if not sewage.pump_curve_source.strip() or not sewage.pump_hydraulic_source.strip():
        diagnostics.append("Нужны источники Q-H кривой и гидравлического расчёта.")
    if sewage.pump_working_units is None or sewage.pump_working_units <= 0:
        diagnostics.append("Укажите число рабочих насосов.")
    if sewage.pump_reserve_units is None or sewage.pump_reserve_units < 0:
        diagnostics.append("Укажите число резервных насосов, включая 0 при отсутствии.")
    if not sewage.pump_reserve_note.strip() or not sewage.pump_power_category.strip():
        diagnostics.append("Нужны решения по резервированию и категории электроснабжения.")
    if not sewage.pump_automation_note.strip() or not sewage.pump_emergency_note.strip():
        diagnostics.append("Нужны решения по автоматизации и аварийной сигнализации.")
    if (
        pump is not None
        and sewage.pump_working_units is not None
        and sewage.pump_reserve_units is not None
        and pump.quantity != sewage.pump_working_units + sewage.pump_reserve_units
    ):
        diagnostics.append(
            "Количество насосов в реестре не совпадает с числом рабочих и резервных."
        )

    curve = [(float(q), float(h)) for q, h in sewage.pump_curve]
    curve_valid = bool(
        len(curve) >= 3
        and all(q >= 0 and h > 0 for q, h in curve)
        and all(q2 > q1 and h2 <= h1 for (q1, h1), (q2, h2) in zip(curve, curve[1:]))
    )
    if len(curve) < 3:
        diagnostics.append("Для проверки рабочей точки нужны минимум три точки Q-H.")
    elif not curve_valid:
        diagnostics.append(
            "Q-H кривая требует Q ≥ 0, H > 0, возрастающий Q и невозрастающий H."
        )

    working_point = None
    k_value = None
    q_design = sewage.pump_q_m3h
    static = sewage.pump_static_head_m
    dynamic = sewage.pump_dynamic_loss_m
    if (
        curve_valid
        and q_design
        and static is not None
        and static >= 0
        and dynamic is not None
        and dynamic >= 0
    ):
        working_point, k_value = _curve_intersection(
            curve,
            static_head_m=static,
            dynamic_loss_m=dynamic,
            design_q_m3h=q_design,
        )
        required_head = static + dynamic
        if sewage.pump_head_m is not None and abs(sewage.pump_head_m - required_head) > _TOLERANCE:
            diagnostics.append(
                "Заданный напор насоса не равен сумме статической составляющей "
                "и подтверждённых динамических потерь."
            )
        if working_point is None:
            diagnostics.append("Q-H кривая насоса не даёт единственной рабочей точки с кривой системы.")
        elif (
            abs(working_point.q_m3h - q_design) > _TOLERANCE
            or sewage.pump_head_m is None
            or abs(working_point.pump_head_m - sewage.pump_head_m) > _TOLERANCE
        ):
            diagnostics.append(
                "Расчётное пересечение Q-H и кривой системы не совпадает с принятой рабочей точкой."
            )
    if q_design:
        expected_lps = q_design / 3.6
        for row in pressure_rows:
            if row.design_flow_lps and abs(row.design_flow_lps - expected_lps) > 0.03:
                diagnostics.append(
                    f"Участок {row.section_id}: расход не совпадает с Q принятого насоса."
                )

    return WastewaterPressureProjectInputs(
        applicable=True,
        system=system,
        mode=mode,
        pressure_pipes=ordered,
        pump_element=pump,
        check_valve_element=check_valve,
        isolation_valve_element=isolation_valve,
        sump_element=sump,
        pressure_break_loop_element=break_loop,
        receiving_gravity_pipe=receiving_gravity_pipe,
        working_point=working_point,
        system_curve_k=k_value,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


__all__ = [
    "PressureWorkingPoint",
    "WastewaterPressureProjectInputs",
    "pressure_sewer_is_applicable",
    "resolve_wastewater_pressure_project_inputs",
]

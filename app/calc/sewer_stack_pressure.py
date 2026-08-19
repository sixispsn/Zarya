"""Разрежение в канализационном стояке по СП 30.13330.2020.

Модуль буквально реализует формулы (34)--(39) раздела 19. Он не моделирует
наружную сеть и не назначает одновременность сбросов: каждый сброс должен быть
передан явным событием с расходом и источником.

Для гидрозатворов высотой 50--60 мм формульный результат не заменяет подбор
стояка по таблицам К.1--К.8. Такое ограничение возвращается в результате.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import cos, pi, radians, sqrt
from typing import Iterable, Optional

from app.calc.sewer_fixture_safety import (
    AirPressurePoint,
    TrapPressureHydrograph,
)


MM_WATER_TO_PA = 9.80665
_ZERO_TOLERANCE = 1e-12


class StackVentilationMode(str, Enum):
    VENTILATED = "Вентилируемый стояк"
    UNVENTILATED = "Невентилируемый стояк"
    AIR_ADMITTANCE_VALVE = "Стояк с воздушным клапаном"


@dataclass(frozen=True)
class StackPressureInput:
    """Явные исходные данные одного канализационного стояка."""

    stack_id: str
    ventilation_mode: StackVentilationMode
    inner_diameter_mm: float
    branch_inner_diameter_mm: float
    branch_angle_deg: float
    working_height_m: float
    minimum_trap_seal_mm: float
    source: str
    air_valve_free_area_mm2: Optional[float] = None
    air_valve_source: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.stack_id.strip():
            raise ValueError("обозначение стояка не задано")
        if self.inner_diameter_mm <= 0:
            raise ValueError("внутренний диаметр стояка должен быть больше 0")
        if self.branch_inner_diameter_mm <= 0:
            raise ValueError("внутренний диаметр отвода должен быть больше 0")
        if self.branch_inner_diameter_mm > self.inner_diameter_mm:
            raise ValueError("диаметр поэтажного отвода больше диаметра стояка")
        if not 0 < self.branch_angle_deg < 180:
            raise ValueError("угол присоединения должен быть от 0 до 180 градусов")
        if 1.0 + cos(radians(self.branch_angle_deg)) <= _ZERO_TOLERANCE:
            raise ValueError("для заданного угла формулы СП неприменимы")
        if self.working_height_m <= 0:
            raise ValueError("рабочая высота стояка должна быть больше 0")
        if self.minimum_trap_seal_mm <= 0:
            raise ValueError("высота наименьшего гидрозатвора должна быть больше 0")
        if not self.source.strip():
            raise ValueError("для геометрии стояка нужен источник")

        has_valve_area = self.air_valve_free_area_mm2 is not None
        if self.ventilation_mode is StackVentilationMode.AIR_ADMITTANCE_VALVE:
            if not has_valve_area or self.air_valve_free_area_mm2 <= 0:
                raise ValueError(
                    "для воздушного клапана нужна положительная площадь живого сечения"
                )
            if not self.air_valve_source or not self.air_valve_source.strip():
                raise ValueError("для площади воздушного клапана нужен источник")
        elif has_valve_area or self.air_valve_source:
            raise ValueError(
                "параметры воздушного клапана допустимы только для режима с клапаном"
            )

    @property
    def inner_diameter_m(self) -> float:
        return self.inner_diameter_mm / 1000.0

    @property
    def branch_inner_diameter_m(self) -> float:
        return self.branch_inner_diameter_mm / 1000.0

    @property
    def allowable_vacuum_mm_water(self) -> float:
        """Предел по п. 19.2: Δp <= 0,9 hз."""
        return 0.9 * self.minimum_trap_seal_mm

    @property
    def requires_appendix_k_check(self) -> bool:
        return 50.0 <= self.minimum_trap_seal_mm <= 60.0


@dataclass(frozen=True)
class StackPressureResult:
    stack_id: str
    ventilation_mode: StackVentilationMode
    wastewater_flow_lps: float
    vacuum_mm_water: float
    sewer_air_pressure_pa: float
    allowable_vacuum_mm_water: float
    vacuum_within_limit: bool
    appendix_k_check_required: bool
    formula_reference: str
    induced_air_flow_m3s: Optional[float] = None
    mixture_velocity_mps: Optional[float] = None
    equivalent_valve_diameter_mm: Optional[float] = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DischargeEvent:
    """Прямоугольный импульс притока с явно заданным расходом."""

    event_id: str
    start_seconds: float
    duration_seconds: float
    flow_lps: float
    source: str

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("обозначение события сброса не задано")
        if self.start_seconds < 0:
            raise ValueError("начало сброса не может быть отрицательным")
        if self.duration_seconds <= 0:
            raise ValueError("длительность сброса должна быть больше 0")
        if self.flow_lps < 0:
            raise ValueError("расход сброса не может быть отрицательным")
        if not self.source.strip():
            raise ValueError("для расхода события нужен источник")

    def is_active(self, time_seconds: float) -> bool:
        return (
            self.start_seconds <= time_seconds
            and time_seconds < self.start_seconds + self.duration_seconds
        )


@dataclass(frozen=True)
class StackPressurePoint:
    time_seconds: float
    wastewater_flow_lps: float
    vacuum_mm_water: float
    sewer_air_pressure_pa: float
    active_event_ids: tuple[str, ...]
    vacuum_within_limit: bool


@dataclass(frozen=True)
class StackPressureTimeline:
    stack_id: str
    points: tuple[StackPressurePoint, ...]
    source: str


def _validate_flow_lps(flow_lps: float) -> float:
    if flow_lps < 0:
        raise ValueError("расход сточных вод не может быть отрицательным")
    return flow_lps / 1000.0


def _angle_factor(data: StackPressureInput) -> float:
    return 1.0 + cos(radians(data.branch_angle_deg))


def _ventilated_calculation_height_m(data: StackPressureInput) -> float:
    """Ограничение Lст=90Dст при Lст>=90Dст по п. 19.5."""
    return min(data.working_height_m, 90.0 * data.inner_diameter_m)


def ventilated_capacity_lps(
    data: StackPressureInput,
    vacuum_mm_water: Optional[float] = None,
) -> float:
    """Максимальный расход по формуле (34), без табличной подмены."""
    if data.ventilation_mode is not StackVentilationMode.VENTILATED:
        raise ValueError("формула (34) относится к вентилируемому стояку")
    pressure = (
        data.allowable_vacuum_mm_water
        if vacuum_mm_water is None
        else vacuum_mm_water
    )
    if pressure < 0:
        raise ValueError("разрежение не может быть отрицательным")
    if pressure == 0:
        return 0.0
    diameter = data.inner_diameter_m
    branch_diameter = data.branch_inner_diameter_m
    height = _ventilated_calculation_height_m(data)
    flow_m3s = (
        0.0297
        * pressure ** 0.596
        * _angle_factor(data)
        * diameter ** 2
        * (90.0 * diameter / height) ** 0.298
        * (diameter / branch_diameter) ** 0.423
    )
    return flow_m3s * 1000.0


def _ventilated_vacuum_mm(
    data: StackPressureInput,
    flow_m3s: float,
) -> float:
    """Разрежение по формуле (35)."""
    if flow_m3s == 0:
        return 0.0
    diameter = data.inner_diameter_m
    height = _ventilated_calculation_height_m(data)
    numerator = 366.0 * (
        flow_m3s / (_angle_factor(data) * diameter ** 2)
    ) ** 1.677
    denominator = (
        (diameter / data.branch_inner_diameter_m) ** 0.71
        * (90.0 * diameter / height) ** 0.5
    )
    return numerator / denominator


def _unventilated_vacuum(
    data: StackPressureInput,
    flow_m3s: float,
) -> tuple[float, float, float]:
    """Формулы (36)--(38): Δp, Qв и Vсм."""
    if flow_m3s == 0:
        return 0.0, 0.0, 0.0
    diameter = data.inner_diameter_m
    branch_diameter = data.branch_inner_diameter_m
    height_factor = (90.0 * diameter / data.working_height_m) ** 0.5
    induced_air_flow = (
        13.8
        * flow_m3s ** 0.333
        * diameter ** 1.75
        * (diameter / branch_diameter) ** 0.12
        / (_angle_factor(data) ** 0.177 * height_factor)
    )
    section_area = pi * diameter ** 2 / 4.0
    mixture_velocity = (induced_air_flow + flow_m3s) / section_area
    vacuum = 0.31 * mixture_velocity ** 4.3
    return vacuum, induced_air_flow, mixture_velocity


def _equivalent_valve_diameter_m(data: StackPressureInput) -> float:
    if data.air_valve_free_area_mm2 is None:
        raise ValueError("не задана площадь живого сечения воздушного клапана")
    valve_area_m2 = data.air_valve_free_area_mm2 / 1_000_000.0
    return sqrt(valve_area_m2 / 0.785)


def air_valve_capacity_lps(
    data: StackPressureInput,
    vacuum_mm_water: Optional[float] = None,
) -> float:
    """Расход стояка с воздушным клапаном по формуле (39)."""
    if data.ventilation_mode is not StackVentilationMode.AIR_ADMITTANCE_VALVE:
        raise ValueError("формула (39) относится к стояку с воздушным клапаном")
    pressure = (
        data.allowable_vacuum_mm_water
        if vacuum_mm_water is None
        else vacuum_mm_water
    )
    if pressure < 0:
        raise ValueError("разрежение не может быть отрицательным")
    if pressure == 0:
        return 0.0
    diameter = data.inner_diameter_m
    valve_diameter = _equivalent_valve_diameter_m(data)
    flow_m3s = (
        0.034
        * pressure ** 0.596
        * (90.0 * diameter / data.working_height_m) ** 0.298
        * (diameter / data.branch_inner_diameter_m) ** 0.423
        * _angle_factor(data)
        * diameter ** 2
        / (diameter / valve_diameter) ** 0.596
    )
    return flow_m3s * 1000.0


def _air_valve_vacuum_mm(
    data: StackPressureInput,
    flow_m3s: float,
) -> tuple[float, float]:
    """Формула (39), разрешённая относительно Δp."""
    valve_diameter = _equivalent_valve_diameter_m(data)
    if flow_m3s == 0:
        return 0.0, valve_diameter
    diameter = data.inner_diameter_m
    factor_without_pressure = (
        0.034
        * (90.0 * diameter / data.working_height_m) ** 0.298
        * (diameter / data.branch_inner_diameter_m) ** 0.423
        * _angle_factor(data)
        * diameter ** 2
        / (diameter / valve_diameter) ** 0.596
    )
    vacuum = (flow_m3s / factor_without_pressure) ** (1.0 / 0.596)
    return vacuum, valve_diameter


def calculate_stack_pressure(
    data: StackPressureInput,
    wastewater_flow_lps: float,
) -> StackPressureResult:
    """Рассчитать разрежение стояка при одном заданном расходе."""
    flow_m3s = _validate_flow_lps(wastewater_flow_lps)
    induced_air_flow: Optional[float] = None
    mixture_velocity: Optional[float] = None
    equivalent_valve_diameter_mm: Optional[float] = None

    if data.ventilation_mode is StackVentilationMode.VENTILATED:
        vacuum = _ventilated_vacuum_mm(data, flow_m3s)
        formula_reference = "СП 30.13330.2020, п. 19.4, формула (35)"
    elif data.ventilation_mode is StackVentilationMode.UNVENTILATED:
        vacuum, induced_air_flow, mixture_velocity = _unventilated_vacuum(
            data,
            flow_m3s,
        )
        formula_reference = "СП 30.13330.2020, п. 19.6, формулы (36)--(38)"
    else:
        vacuum, valve_diameter = _air_valve_vacuum_mm(data, flow_m3s)
        equivalent_valve_diameter_mm = valve_diameter * 1000.0
        formula_reference = "СП 30.13330.2020, п. 19.9, формула (39)"

    notes: list[str] = []
    if data.requires_appendix_k_check:
        notes.append(
            "для гидрозатвора 50--60 мм диаметр и пропускную способность "
            "дополнительно проверяют по таблицам приложения К без интерполяции"
        )
    within_limit = vacuum <= data.allowable_vacuum_mm_water + _ZERO_TOLERANCE
    if not within_limit:
        notes.append("разрежение превышает предел 0,9 hз по п. 19.2")

    return StackPressureResult(
        stack_id=data.stack_id,
        ventilation_mode=data.ventilation_mode,
        wastewater_flow_lps=wastewater_flow_lps,
        vacuum_mm_water=vacuum,
        sewer_air_pressure_pa=-vacuum * MM_WATER_TO_PA,
        allowable_vacuum_mm_water=data.allowable_vacuum_mm_water,
        vacuum_within_limit=within_limit,
        appendix_k_check_required=data.requires_appendix_k_check,
        formula_reference=formula_reference,
        induced_air_flow_m3s=induced_air_flow,
        mixture_velocity_mps=mixture_velocity,
        equivalent_valve_diameter_mm=equivalent_valve_diameter_mm,
        notes=tuple(notes),
    )


def calculate_pressure_timeline(
    data: StackPressureInput,
    events: Iterable[DischargeEvent],
    times_seconds: Iterable[float],
) -> StackPressureTimeline:
    """Суммировать только явно заданные одновременные сбросы и найти Δp(t)."""
    event_rows = tuple(events)
    if len({event.event_id for event in event_rows}) != len(event_rows):
        raise ValueError("обозначения событий сброса должны быть уникальны")
    times = tuple(float(value) for value in times_seconds)
    if not times:
        raise ValueError("не заданы моменты расчёта давления")
    if times[0] != 0:
        raise ValueError("график давления должен начинаться с t=0")
    if times != tuple(sorted(set(times))):
        raise ValueError("моменты расчёта должны строго возрастать")
    if times[0] < 0:
        raise ValueError("время не может быть отрицательным")

    points: list[StackPressurePoint] = []
    for time_seconds in times:
        active = tuple(
            event for event in event_rows if event.is_active(time_seconds)
        )
        flow_lps = sum(event.flow_lps for event in active)
        result = calculate_stack_pressure(data, flow_lps)
        points.append(StackPressurePoint(
            time_seconds=time_seconds,
            wastewater_flow_lps=flow_lps,
            vacuum_mm_water=result.vacuum_mm_water,
            sewer_air_pressure_pa=result.sewer_air_pressure_pa,
            active_event_ids=tuple(event.event_id for event in active),
            vacuum_within_limit=result.vacuum_within_limit,
        ))

    sources = "; ".join(dict.fromkeys(event.source for event in event_rows))
    return StackPressureTimeline(
        stack_id=data.stack_id,
        points=tuple(points),
        source=sources or "нулевой сценарий без событий сброса",
    )


def timeline_to_trap_pressure(
    timeline: StackPressureTimeline,
    fixture_id: str,
) -> TrapPressureHydrograph:
    """Передать рассчитанное давление в проверку конкретного гидрозатвора."""
    if not fixture_id.strip():
        raise ValueError("обозначение прибора не задано")
    return TrapPressureHydrograph(
        fixture_id=fixture_id,
        points=tuple(
            AirPressurePoint(
                time_seconds=point.time_seconds,
                sewer_air_pressure_pa=point.sewer_air_pressure_pa,
            )
            for point in timeline.points
        ),
        source=(
            f"расчёт стояка {timeline.stack_id} по СП 30.13330.2020; "
            f"события: {timeline.source}"
        ),
    )

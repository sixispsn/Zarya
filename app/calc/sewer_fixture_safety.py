"""Подпор, подтопление и срыв гидрозатворов внутренних приборов.

Первый наружный колодец здесь является только граничной отметкой. Наружная
сеть не рассчитывается. Статическая проверка сравнивает уровень воды в первом
колодце с абсолютными отметками подключения и перелива внутреннего прибора.

Срыв гидрозатвора проверяется по эквивалентному водяному столбу
``Δh = Δp / (rho * g)``. Давление воздуха должно приходить из отдельного
расчёта/измерения. Если его нет, модуль не объявляет гидрозатвор безопасным.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Optional

from app.calc.sewer_network_simulation import NetworkStepSnapshot
from app.calc.sewer_simulation import PipeStatus


WATER_DENSITY_KG_M3 = 1000.0
STANDARD_GRAVITY_M_S2 = 9.80665


class BackwaterStatus(str, Enum):
    CLEAR = "Подпор отсутствует"
    BACKWATER = "Подпор к прибору"
    FLOODING = "Подтопление через прибор"


class TrapSealStatus(str, Enum):
    VERIFIED = "Гидрозатвор сохранён"
    CRITICAL = "Критический остаток гидрозатвора"
    SIPHONED = "Сифонный срыв гидрозатвора"
    BLOWN = "Выдавливание гидрозатвора"
    DATA_REQUIRED = "Требуется перепад давления"


class FixtureSafetyStatus(str, Enum):
    NORMAL = "Норма"
    DATA_REQUIRED = "Требуются данные"
    CRITICAL = "Критическое состояние"
    BACKWATER = "Подпор"
    FLOODING = "Подтопление"


@dataclass(frozen=True)
class FixtureSafetyInput:
    """Высотная и гидравлическая привязка открытого приёмника стоков."""

    fixture_id: str
    pipe_id: str
    name: str
    connection_elevation_m: float
    overflow_elevation_m: float
    trap_seal_depth_mm: float
    minimum_residual_seal_mm: float
    source: str

    def __post_init__(self) -> None:
        if not self.fixture_id.strip():
            raise ValueError("обозначение прибора не задано")
        if not self.pipe_id.strip():
            raise ValueError("прибор не привязан к участку")
        if not self.name.strip():
            raise ValueError("наименование прибора не задано")
        if self.overflow_elevation_m <= self.connection_elevation_m:
            raise ValueError(
                "отметка перелива должна быть выше отметки подключения"
            )
        if self.trap_seal_depth_mm <= 0:
            raise ValueError("глубина гидрозатвора должна быть больше 0")
        if not 0 <= self.minimum_residual_seal_mm < self.trap_seal_depth_mm:
            raise ValueError(
                "минимальный остаток должен быть от 0 до глубины гидрозатвора"
            )
        if not self.source.strip():
            raise ValueError("для отметок и гидрозатвора нужен источник")


@dataclass(frozen=True)
class BoundaryLevelPoint:
    time_seconds: float
    water_level_elevation_m: float

    def __post_init__(self) -> None:
        if self.time_seconds < 0:
            raise ValueError("время уровня не может быть отрицательным")


@dataclass(frozen=True)
class FirstManholeBoundary:
    """Известный уровень первого колодца без расчёта наружной сети."""

    manhole_id: str
    invert_elevation_m: float
    levels: tuple[BoundaryLevelPoint, ...]
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "levels", tuple(self.levels))
        if not self.manhole_id.strip():
            raise ValueError("обозначение первого колодца не задано")
        if not self.levels:
            raise ValueError("для первого колодца не задан уровень воды")
        if self.levels[0].time_seconds != 0:
            raise ValueError("график уровня должен начинаться с t=0")
        times = [row.time_seconds for row in self.levels]
        if times != sorted(set(times)):
            raise ValueError("время уровня должно строго возрастать")
        if any(
            row.water_level_elevation_m < self.invert_elevation_m
            for row in self.levels
        ):
            raise ValueError("уровень воды не может быть ниже лотка колодца")
        if not self.source.strip():
            raise ValueError("для отметок первого колодца нужен источник")

    def level_at(self, time_seconds: float) -> float:
        if time_seconds < 0:
            raise ValueError("время не может быть отрицательным")
        current = self.levels[0]
        for point in self.levels[1:]:
            if point.time_seconds > time_seconds:
                break
            current = point
        return current.water_level_elevation_m


@dataclass(frozen=True)
class AirPressurePoint:
    time_seconds: float
    sewer_air_pressure_pa: float

    def __post_init__(self) -> None:
        if self.time_seconds < 0:
            raise ValueError("время давления не может быть отрицательным")


@dataclass(frozen=True)
class TrapPressureHydrograph:
    """Давление со стороны канализации относительно атмосферы."""

    fixture_id: str
    points: tuple[AirPressurePoint, ...]
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", tuple(self.points))
        if not self.fixture_id.strip():
            raise ValueError("график давления не привязан к прибору")
        if not self.points:
            raise ValueError("график давления не содержит точек")
        if self.points[0].time_seconds != 0:
            raise ValueError("график давления должен начинаться с t=0")
        times = [row.time_seconds for row in self.points]
        if times != sorted(set(times)):
            raise ValueError("время давления должно строго возрастать")
        if not self.source.strip():
            raise ValueError("для перепада давления нужен источник")

    def pressure_at(self, time_seconds: float) -> float:
        if time_seconds < 0:
            raise ValueError("время не может быть отрицательным")
        current = self.points[0]
        for point in self.points[1:]:
            if point.time_seconds > time_seconds:
                break
            current = point
        return current.sewer_air_pressure_pa


@dataclass(frozen=True)
class FixtureSafetySnapshot:
    time_seconds: float
    fixture_id: str
    manhole_water_level_elevation_m: float
    connection_elevation_m: float
    overflow_elevation_m: float
    level_margin_to_overflow_m: float
    backwater_head_above_connection_m: float
    flood_depth_above_overflow_m: float
    sewer_air_pressure_pa: Optional[float]
    hydrostatic_pressure_pa: float
    combined_pressure_pa: Optional[float]
    equivalent_pressure_head_mm: Optional[float]
    remaining_trap_seal_mm: Optional[float]
    backwater_status: BackwaterStatus
    trap_status: TrapSealStatus
    internal_pipe_status: Optional[PipeStatus]
    status: FixtureSafetyStatus
    notes: tuple[str, ...]


def evaluate_fixture_safety(
    *,
    fixture: FixtureSafetyInput,
    first_manhole: FirstManholeBoundary,
    time_seconds: float,
    pressure: Optional[TrapPressureHydrograph] = None,
    network_step: Optional[NetworkStepSnapshot] = None,
) -> FixtureSafetySnapshot:
    """Проверить один прибор на подпор, подтопление и срыв затвора."""
    if time_seconds < 0:
        raise ValueError("время не может быть отрицательным")
    if pressure is not None and pressure.fixture_id != fixture.fixture_id:
        raise ValueError("график давления относится к другому прибору")

    boundary_level = first_manhole.level_at(time_seconds)
    margin_to_overflow = fixture.overflow_elevation_m - boundary_level
    backwater_head = max(
        0.0,
        boundary_level - fixture.connection_elevation_m,
    )
    flood_depth = max(
        0.0,
        boundary_level - fixture.overflow_elevation_m,
    )
    if margin_to_overflow <= 1e-12:
        backwater_status = BackwaterStatus.FLOODING
    elif backwater_head > 0:
        backwater_status = BackwaterStatus.BACKWATER
    else:
        backwater_status = BackwaterStatus.CLEAR

    hydrostatic_pressure = (
        WATER_DENSITY_KG_M3 * STANDARD_GRAVITY_M_S2 * backwater_head
    )
    air_pressure = pressure.pressure_at(time_seconds) if pressure else None
    combined_pressure = (
        hydrostatic_pressure + air_pressure
        if air_pressure is not None
        else None
    )
    equivalent_head_mm: Optional[float] = None
    remaining_seal_mm: Optional[float] = None
    notes: list[str] = []

    # Даже без воздушного расчёта известный гидростатический подпор может быть
    # достаточен для гарантированного выдавливания затвора.
    hydrostatic_head_mm = backwater_head * 1000.0
    if combined_pressure is None:
        if hydrostatic_head_mm + 1e-12 >= fixture.trap_seal_depth_mm:
            equivalent_head_mm = hydrostatic_head_mm
            remaining_seal_mm = 0.0
            trap_status = TrapSealStatus.BLOWN
            notes.append(
                "гидростатический подпор превышает глубину гидрозатвора"
            )
        else:
            trap_status = TrapSealStatus.DATA_REQUIRED
            notes.append(
                "для проверки сифонного срыва/выдавливания нужен перепад "
                "воздушного давления у гидрозатвора"
            )
    else:
        signed_head_mm = (
            combined_pressure
            / (WATER_DENSITY_KG_M3 * STANDARD_GRAVITY_M_S2)
            * 1000.0
        )
        equivalent_head_mm = signed_head_mm
        remaining_seal_mm = max(
            0.0,
            fixture.trap_seal_depth_mm - abs(signed_head_mm),
        )
        if signed_head_mm <= -fixture.trap_seal_depth_mm:
            trap_status = TrapSealStatus.SIPHONED
            notes.append("отрицательное давление вызывает сифонный срыв")
        elif signed_head_mm >= fixture.trap_seal_depth_mm:
            trap_status = TrapSealStatus.BLOWN
            notes.append("положительное давление выдавливает гидрозатвор")
        elif remaining_seal_mm < fixture.minimum_residual_seal_mm:
            trap_status = TrapSealStatus.CRITICAL
            notes.append("остаточная глубина гидрозатвора меньше заданного минимума")
        else:
            trap_status = TrapSealStatus.VERIFIED

    internal_pipe_status: Optional[PipeStatus] = None
    if network_step is not None:
        try:
            internal_pipe_status = network_step.by_pipe(fixture.pipe_id).status
        except KeyError as exc:
            raise ValueError(
                f"в сетевом шаге нет участка прибора {fixture.pipe_id}"
            ) from exc
        if internal_pipe_status is PipeStatus.FLOODING:
            notes.append(
                "внутренний участок перегружен; точное место выхода воды "
                "требует геометрии узла"
            )
        elif internal_pipe_status is PipeStatus.CRITICAL_FILL:
            notes.append("внутренний участок имеет критическое наполнение")

    if backwater_status is BackwaterStatus.FLOODING:
        status = FixtureSafetyStatus.FLOODING
        notes.append("уровень первого колодца достиг отметки перелива прибора")
    elif backwater_status is BackwaterStatus.BACKWATER:
        status = FixtureSafetyStatus.BACKWATER
        notes.append("уровень первого колодца выше отметки подключения прибора")
    elif trap_status in {
        TrapSealStatus.SIPHONED,
        TrapSealStatus.BLOWN,
        TrapSealStatus.CRITICAL,
    } or internal_pipe_status in {
        PipeStatus.FLOODING,
        PipeStatus.CRITICAL_FILL,
    }:
        status = FixtureSafetyStatus.CRITICAL
    elif trap_status is TrapSealStatus.DATA_REQUIRED:
        status = FixtureSafetyStatus.DATA_REQUIRED
    else:
        status = FixtureSafetyStatus.NORMAL

    return FixtureSafetySnapshot(
        time_seconds=time_seconds,
        fixture_id=fixture.fixture_id,
        manhole_water_level_elevation_m=boundary_level,
        connection_elevation_m=fixture.connection_elevation_m,
        overflow_elevation_m=fixture.overflow_elevation_m,
        level_margin_to_overflow_m=margin_to_overflow,
        backwater_head_above_connection_m=backwater_head,
        flood_depth_above_overflow_m=flood_depth,
        sewer_air_pressure_pa=air_pressure,
        hydrostatic_pressure_pa=hydrostatic_pressure,
        combined_pressure_pa=combined_pressure,
        equivalent_pressure_head_mm=equivalent_head_mm,
        remaining_trap_seal_mm=remaining_seal_mm,
        backwater_status=backwater_status,
        trap_status=trap_status,
        internal_pipe_status=internal_pipe_status,
        status=status,
        notes=tuple(notes),
    )


def evaluate_all_fixtures(
    *,
    fixtures: Iterable[FixtureSafetyInput],
    first_manhole: FirstManholeBoundary,
    time_seconds: float,
    pressures: Optional[Mapping[str, TrapPressureHydrograph]] = None,
    network_step: Optional[NetworkStepSnapshot] = None,
) -> tuple[FixtureSafetySnapshot, ...]:
    """Проверить список приборов; нижний опасный прибор выявится по отметкам."""
    pressure_map = dict(pressures or {})
    fixture_rows = list(fixtures)
    fixture_ids = {row.fixture_id for row in fixture_rows}
    unknown = set(pressure_map) - fixture_ids
    if unknown:
        raise ValueError(
            "графики давления заданы для неизвестных приборов: "
            + ", ".join(sorted(unknown))
        )
    return tuple(
        evaluate_fixture_safety(
            fixture=fixture,
            first_manhole=first_manhole,
            time_seconds=time_seconds,
            pressure=pressure_map.get(fixture.fixture_id),
            network_step=network_step,
        )
        for fixture in fixture_rows
    )

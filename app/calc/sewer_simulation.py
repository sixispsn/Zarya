"""Базовые сущности пошаговой симуляции самотечной канализации.

Модуль отделяет две разные задачи:

* гидравлика участка рассчитывается по уравнению Шези в форме Маннинга с
  геометрией частично наполненной круглой трубы;
* рост осадка является сценарной моделью баланса массы взвешенных веществ и
  требует явной калибровки. Нормативного коэффициента ``мм/ч`` модуль не
  придумывает.

Таблицы Шевелева не оцифрованы в проекте, поэтому текущий метод нельзя
маркировать как табличный расчёт «по Шевелеву». Использован разрешённый
пользователем вариант через гидравлический радиус и коэффициент Шези. При
нулевом осадке результат совпадает с :mod:`app.calc.sewer_hydraulics`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import acos, pi, sin, sqrt
from typing import Optional


class PipeStatus(str, Enum):
    """Основной статус участка на текущем шаге времени."""

    NORMAL = "Норма"
    SILTING = "Заиливание"
    CRITICAL_FILL = "Критическое наполнение"
    FLOODING = "Затопление"


@dataclass(frozen=True)
class PipeSectionConfig:
    """Неизменяемые исходные данные одного расчётного участка.

    ``critical_fill_ratio`` является порогом сценарной сигнализации, а не
    нормативной константой. Поэтому он задаётся проектировщиком явно.
    """

    section_id: str
    length_m: float
    inner_diameter_mm: float
    slope_per_mille: float
    material: str
    manning_n: float
    roughness_source: str
    critical_velocity_mps: float
    critical_velocity_source: str
    critical_fill_ratio: float

    def __post_init__(self) -> None:
        if not self.section_id.strip():
            raise ValueError("обозначение участка не задано")
        if self.length_m <= 0:
            raise ValueError("длина участка должна быть больше 0")
        if self.inner_diameter_mm <= 0:
            raise ValueError("внутренний диаметр должен быть больше 0")
        if self.slope_per_mille <= 0:
            raise ValueError("уклон самотечного участка должен быть больше 0")
        if not self.material.strip():
            raise ValueError("материал трубы не задан")
        if self.manning_n <= 0:
            raise ValueError("коэффициент Маннинга n должен быть больше 0")
        if not self.roughness_source.strip():
            raise ValueError("для коэффициента шероховатости нужен источник")
        if self.critical_velocity_mps <= 0:
            raise ValueError("критическая скорость должна быть больше 0")
        if not self.critical_velocity_source.strip():
            raise ValueError("для критической скорости нужен источник")
        if not 0 < self.critical_fill_ratio <= 1:
            raise ValueError("порог критического наполнения должен быть в (0; 1]")


@dataclass(frozen=True)
class SedimentCalibration:
    """Калибровка переноса взвесей для одного сценария.

    Интенсивность осаждения считается по массе поступивших взвесей. Доля
    осевшей массы линейно или нелинейно зависит от относительного дефицита
    скорости. Все величины, влияющие на толщину слоя, заданы явно.
    """

    suspended_solids_mg_l: float
    sediment_bulk_density_kg_m3: float
    capture_efficiency_at_zero_velocity: float
    velocity_deficit_exponent: float
    source: str

    def __post_init__(self) -> None:
        if self.suspended_solids_mg_l < 0:
            raise ValueError("концентрация взвесей не может быть отрицательной")
        if self.sediment_bulk_density_kg_m3 <= 0:
            raise ValueError("объёмная плотность осадка должна быть больше 0")
        if not 0 <= self.capture_efficiency_at_zero_velocity <= 1:
            raise ValueError("эффективность улавливания должна быть от 0 до 1")
        if self.velocity_deficit_exponent <= 0:
            raise ValueError("показатель дефицита скорости должен быть больше 0")
        if not self.source.strip():
            raise ValueError("для модели осадка нужен источник или калибровка")


@dataclass(frozen=True)
class SedimentStepResult:
    deposited_mass_kg: float
    deposited_volume_m3: float
    sediment_increment_mm: float
    sediment_depth_mm: float
    capture_fraction: float


@dataclass(frozen=True)
class FlowGeometry:
    """Живое сечение над горизонтальным слоем осадка."""

    water_surface_from_original_invert_m: float
    water_depth_m: float
    water_area_m2: float
    wetted_perimeter_m: float
    hydraulic_radius_m: float
    fill_ratio_h_d: float
    available_fill_ratio: float


@dataclass(frozen=True)
class PipeHydraulicState:
    section_id: str
    inflow_lps: float
    velocity_mps: float
    fill_ratio_h_d: float
    available_fill_ratio: float
    water_depth_m: float
    wetted_area_m2: float
    hydraulic_radius_m: float
    sediment_depth_mm: float
    available_cross_section_m2: float
    maximum_gravity_capacity_lps: float
    full_section_capacity_lps: float
    status: PipeStatus
    active_flags: tuple[PipeStatus, ...]
    capacity_exceeded: bool


@dataclass
class PipeSectionState:
    """Изменяемое состояние участка между шагами симуляции."""

    sediment_depth_mm: float = 0.0
    stored_water_m3: float = 0.0
    flooded_volume_m3: float = 0.0


@dataclass
class PipeSection:
    """Базовый класс участка трубы для будущего сетевого движка.

    Класс решает локальную задачу нормальной глубины и хранит осадок/воду.
    Передачу потока по графу, подпор и граничные условия выполняет отдельный
    ``SewerNetworkSimulator``; его контракт описан в архитектурном документе.
    """

    config: PipeSectionConfig
    state: PipeSectionState = field(default_factory=PipeSectionState)

    def __post_init__(self) -> None:
        if self.state.sediment_depth_mm < 0:
            raise ValueError("толщина осадка не может быть отрицательной")
        if self.state.sediment_depth_mm >= self.config.inner_diameter_mm:
            raise ValueError("осадок не может перекрывать всё сечение трубы")
        if self.state.stored_water_m3 < 0 or self.state.flooded_volume_m3 < 0:
            raise ValueError("объём воды не может быть отрицательным")

    @property
    def diameter_m(self) -> float:
        return self.config.inner_diameter_mm / 1000.0

    @property
    def sediment_depth_m(self) -> float:
        return self.state.sediment_depth_mm / 1000.0

    @property
    def gross_cross_section_m2(self) -> float:
        return pi * self.diameter_m**2 / 4.0

    @property
    def sediment_cross_section_m2(self) -> float:
        return _circle_segment(self.diameter_m, self.sediment_depth_m)[0]

    @property
    def available_cross_section_m2(self) -> float:
        return self.gross_cross_section_m2 - self.sediment_cross_section_m2

    @property
    def available_storage_m3(self) -> float:
        return self.available_cross_section_m2 * self.config.length_m

    def geometry_at_water_surface(self, water_surface_m: float) -> FlowGeometry:
        """Вернуть точную геометрию воды над плоским слоем осадка."""
        diameter = self.diameter_m
        sediment = self.sediment_depth_m
        if not sediment < water_surface_m <= diameter:
            raise ValueError(
                "уровень воды должен быть выше осадка и не выше верха трубы"
            )
        surface_area, surface_arc, _ = _circle_segment(diameter, water_surface_m)
        sediment_area, sediment_arc, sediment_chord = _circle_segment(
            diameter, sediment
        )
        water_area = surface_area - sediment_area
        # В смоченный периметр входит стенка трубы между верхом осадка и
        # зеркалом воды, а также граница «вода - осадок».
        wetted_perimeter = surface_arc - sediment_arc + sediment_chord
        hydraulic_radius = water_area / wetted_perimeter
        water_depth = water_surface_m - sediment
        available_depth = diameter - sediment
        return FlowGeometry(
            water_surface_from_original_invert_m=water_surface_m,
            water_depth_m=water_depth,
            water_area_m2=water_area,
            wetted_perimeter_m=wetted_perimeter,
            hydraulic_radius_m=hydraulic_radius,
            fill_ratio_h_d=water_depth / diameter,
            available_fill_ratio=water_depth / available_depth,
        )

    def capacity_at_water_surface(
        self,
        water_surface_m: float,
    ) -> tuple[float, float, FlowGeometry]:
        """Вернуть ``Q, V, geometry`` по Шези-Маннингу для уровня воды."""
        geometry = self.geometry_at_water_surface(water_surface_m)
        slope = self.config.slope_per_mille / 1000.0
        velocity = (
            geometry.hydraulic_radius_m ** (2.0 / 3.0)
            * sqrt(slope)
            / self.config.manning_n
        )
        flow_lps = geometry.water_area_m2 * velocity * 1000.0
        return flow_lps, velocity, geometry

    def calculate_hydraulics(self, inflow_lps: float) -> PipeHydraulicState:
        """Рассчитать локальный безнапорный режим при текущем осадке.

        Ищется первый корень расходной характеристики по мере роста глубины.
        Если расход превышает максимум свободной поверхности, возвращается
        флаг превышения пропускной способности. Само затопление устанавливает
        сетевой шаг после проверки накопленного объёма, а не этот steady-state
        решатель.
        """
        if inflow_lps < 0:
            raise ValueError("входящий расход не может быть отрицательным")

        peak_level, maximum_capacity = self._peak_capacity()
        full_capacity, _, _ = self.capacity_at_water_surface(self.diameter_m)
        if inflow_lps == 0:
            flags: tuple[PipeStatus, ...] = ()
            return PipeHydraulicState(
                section_id=self.config.section_id,
                inflow_lps=0.0,
                velocity_mps=0.0,
                fill_ratio_h_d=0.0,
                available_fill_ratio=0.0,
                water_depth_m=0.0,
                wetted_area_m2=0.0,
                hydraulic_radius_m=0.0,
                sediment_depth_mm=self.state.sediment_depth_mm,
                available_cross_section_m2=self.available_cross_section_m2,
                maximum_gravity_capacity_lps=maximum_capacity,
                full_section_capacity_lps=full_capacity,
                status=PipeStatus.NORMAL,
                active_flags=flags,
                capacity_exceeded=False,
            )

        capacity_exceeded = inflow_lps > maximum_capacity + 1e-12
        if capacity_exceeded:
            # Для диагностического состояния показывается вершина безнапорной
            # расходной характеристики. Избыточный объём обработает сеть.
            flow_lps, velocity, geometry = self.capacity_at_water_surface(peak_level)
        else:
            lower = self.sediment_depth_m + self.diameter_m * 1e-12
            upper = peak_level
            for _ in range(80):
                middle = (lower + upper) / 2.0
                flow_lps, _, _ = self.capacity_at_water_surface(middle)
                if flow_lps < inflow_lps:
                    lower = middle
                else:
                    upper = middle
            level = (lower + upper) / 2.0
            flow_lps, velocity, geometry = self.capacity_at_water_surface(level)

        flags_list: list[PipeStatus] = []
        if velocity + 1e-12 < self.config.critical_velocity_mps:
            flags_list.append(PipeStatus.SILTING)
        if (
            capacity_exceeded
            or geometry.available_fill_ratio + 1e-12
            >= self.config.critical_fill_ratio
        ):
            flags_list.append(PipeStatus.CRITICAL_FILL)
        if self.state.flooded_volume_m3 > 0:
            flags_list.append(PipeStatus.FLOODING)

        status = (
            PipeStatus.FLOODING
            if PipeStatus.FLOODING in flags_list
            else PipeStatus.CRITICAL_FILL
            if PipeStatus.CRITICAL_FILL in flags_list
            else PipeStatus.SILTING
            if PipeStatus.SILTING in flags_list
            else PipeStatus.NORMAL
        )
        return PipeHydraulicState(
            section_id=self.config.section_id,
            inflow_lps=inflow_lps,
            velocity_mps=velocity,
            fill_ratio_h_d=geometry.fill_ratio_h_d,
            available_fill_ratio=geometry.available_fill_ratio,
            water_depth_m=geometry.water_depth_m,
            wetted_area_m2=geometry.water_area_m2,
            hydraulic_radius_m=geometry.hydraulic_radius_m,
            sediment_depth_mm=self.state.sediment_depth_mm,
            available_cross_section_m2=self.available_cross_section_m2,
            maximum_gravity_capacity_lps=maximum_capacity,
            full_section_capacity_lps=full_capacity,
            status=status,
            active_flags=tuple(flags_list),
            capacity_exceeded=capacity_exceeded,
        )

    def apply_sediment_step(
        self,
        *,
        dt_seconds: float,
        inflow_lps: float,
        hydraulic_state: PipeHydraulicState,
        calibration: SedimentCalibration,
    ) -> SedimentStepResult:
        """Увеличить слой осадка по балансу массы за один шаг ``dt``.

        При ``V >= V_min`` отложение равно нулю. Эрозия уже накопленного слоя
        пока намеренно не моделируется: для неё нужны отдельные параметры
        критического касательного напряжения и гранулометрии.
        """
        if dt_seconds <= 0:
            raise ValueError("шаг времени должен быть больше 0")
        if inflow_lps < 0:
            raise ValueError("входящий расход не может быть отрицательным")
        if hydraulic_state.section_id != self.config.section_id:
            raise ValueError("гидравлическое состояние относится к другому участку")
        if abs(hydraulic_state.inflow_lps - inflow_lps) > 1e-9:
            raise ValueError(
                "расход шага не совпадает с расходом гидравлического состояния"
            )

        velocity_deficit = max(
            0.0,
            1.0 - hydraulic_state.velocity_mps / self.config.critical_velocity_mps,
        )
        capture_fraction = (
            calibration.capture_efficiency_at_zero_velocity
            * velocity_deficit ** calibration.velocity_deficit_exponent
        )
        if inflow_lps == 0 or capture_fraction == 0:
            return SedimentStepResult(
                deposited_mass_kg=0.0,
                deposited_volume_m3=0.0,
                sediment_increment_mm=0.0,
                sediment_depth_mm=self.state.sediment_depth_mm,
                capture_fraction=capture_fraction,
            )

        water_volume_m3 = inflow_lps / 1000.0 * dt_seconds
        # 1 мг/л = 0,001 кг/м³.
        suspended_mass_kg = (
            water_volume_m3 * calibration.suspended_solids_mg_l * 0.001
        )
        deposited_mass_kg = suspended_mass_kg * capture_fraction
        deposited_volume_m3 = (
            deposited_mass_kg / calibration.sediment_bulk_density_kg_m3
        )
        new_sediment_area = (
            self.sediment_cross_section_m2
            + deposited_volume_m3 / self.config.length_m
        )
        maximum_area = self.gross_cross_section_m2 * (1.0 - 1e-9)
        new_sediment_area = min(new_sediment_area, maximum_area)
        new_depth_m = _depth_for_segment_area(
            self.diameter_m,
            new_sediment_area,
        )
        previous_depth_mm = self.state.sediment_depth_mm
        self.state.sediment_depth_mm = new_depth_m * 1000.0
        return SedimentStepResult(
            deposited_mass_kg=deposited_mass_kg,
            deposited_volume_m3=deposited_volume_m3,
            sediment_increment_mm=self.state.sediment_depth_mm - previous_depth_mm,
            sediment_depth_mm=self.state.sediment_depth_mm,
            capture_fraction=capture_fraction,
        )

    def _peak_capacity(self) -> tuple[float, float]:
        """Найти максимум расходной характеристики свободной поверхности."""
        lower = self.sediment_depth_m + self.diameter_m * 1e-12
        upper = self.diameter_m
        for _ in range(64):
            third = (upper - lower) / 3.0
            first = lower + third
            second = upper - third
            first_capacity = self.capacity_at_water_surface(first)[0]
            second_capacity = self.capacity_at_water_surface(second)[0]
            if first_capacity < second_capacity:
                lower = first
            else:
                upper = second
        level = (lower + upper) / 2.0
        return level, self.capacity_at_water_surface(level)[0]


def base_critical_velocity_mps(inner_diameter_mm: float) -> Optional[float]:
    """Вернуть только явно заданные пользователем базовые значения ``V_min``.

    Для остальных диаметров функция возвращает ``None``: интерполяция и
    придумывание значения запрещены.
    """
    if 100 <= inner_diameter_mm <= 110:
        return 0.6
    if 150 <= inner_diameter_mm <= 200:
        return 0.7
    return None


def _circle_segment(
    diameter_m: float,
    depth_m: float,
) -> tuple[float, float, float]:
    """Площадь сегмента от низа, длина дуги и хорда на его верхней границе."""
    if diameter_m <= 0:
        raise ValueError("диаметр должен быть больше 0")
    if not 0 <= depth_m <= diameter_m:
        raise ValueError("глубина сегмента должна быть от 0 до диаметра")
    if depth_m == 0:
        return 0.0, 0.0, 0.0
    radius = diameter_m / 2.0
    if depth_m == diameter_m:
        return pi * radius**2, 2.0 * pi * radius, 0.0
    angle = 2.0 * acos(1.0 - 2.0 * depth_m / diameter_m)
    area = radius**2 * (angle - sin(angle)) / 2.0
    arc = radius * angle
    chord = 2.0 * sqrt(max(0.0, 2.0 * radius * depth_m - depth_m**2))
    return area, arc, chord


def _depth_for_segment_area(diameter_m: float, target_area_m2: float) -> float:
    full_area = pi * diameter_m**2 / 4.0
    if not 0 <= target_area_m2 < full_area:
        raise ValueError("площадь осадка должна быть меньше площади трубы")
    lower, upper = 0.0, diameter_m
    for _ in range(80):
        middle = (lower + upper) / 2.0
        if _circle_segment(diameter_m, middle)[0] < target_area_m2:
            lower = middle
        else:
            upper = middle
    return (lower + upper) / 2.0

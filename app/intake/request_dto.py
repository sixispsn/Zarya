# -*- coding: utf-8 -*-
"""
app/intake/request_dto.py — входное намерение проектировщика (Request DTO).

Слой 1 цепочки ввода:
    Wizard / IFC / Excel / YAML / REST / CLI
            ↓  отдают НАМЕРЕНИЕ, не Project
       Request DTO   (этот модуль)
            ↓
      Project Builder (app/intake/project_builder.py)
            ↓
         Project → design_ios2()

DTO описывает объект в терминах ПРОЕКТИРОВЩИКА (тип здания, этажи, коридор,
стояки), а не в терминах модели (BuildingPurpose, FireNetworkSpec, dataclass'ы).
Форма и любые будущие входы не знают про Project вообще — они собирают этот DTO.

Здесь НЕТ логики сборки Project и НЕТ расчётов — только данные намерения
и их первичная валидация (типы, диапазоны, обязательность).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── справочники значений (строки — то, что придёт из формы/YAML/API) ────────

BUILDING_TYPES = ("residential", "public", "industrial")
FIRE_MODES = ("auto", "not_required", "manual")
FIRE_CATEGORIES = (
    "residential_f13",
    "office_public",
    "hospital_f11",
    "theatre_f21",
    "library_sport",
    "museum_trade",
    "dormitory_f12",  # legacy-значение; в Изм. № 1 относится к строке 2
)
ROOF_TYPES = ("not_set", "flat", "sloped")
WASTEWATER_ROOF_KINDS = (
    "unknown",
    "flat_non_accessible",
    "flat_accessible",
    "pitched",
    "collecting_vent_shaft",
)
CATERING_TYPES = ("none", "semi_finished", "raw", "school")
APPLICABILITY_ANSWERS = ("unknown", "yes", "no")
GREASE_TRAP_LOCATIONS = (
    "unknown", "under_sink", "technical_room", "outside_building", "stage_r",
)
SOURCE_KINDS = ("city_main", "reservoir", "pond", "well")
SPACE_KINDS = ("corridor", "room", "hall", "storage")
PLACEMENT_MODES = ("one_side", "two_opposite_sides")
SEWAGE_MATERIALS = ("pvc", "pp", "cast_iron_socket", "sml")
SEWAGE_VENTILATION = ("ventilated", "vacuum_valve", "unventilated")
SEWER_ELEMENT_KINDS = (
    "toilet", "washbasin", "sink", "bath", "shower", "floor_drain",
    "washing_machine", "dishwasher", "grease_trap",
    "roof_funnel", "revision", "cleanout", "fire_collar", "trap",
    "pump", "sump", "ball_valve", "check_valve", "pressure_break_loop",
    "junction", "outlet",
    "tee", "elbow", "transition", "other",
)
WASTEWATER_PUMP_SYSTEMS = ("", "K1", "K3")
WASTEWATER_PUMP_MODES = ("not_set", "local_fixture_unit", "internal_station")


@dataclass
class DocumentRequest:
    """Кто/что/шифр — реквизиты комплекта."""
    cipher: str
    object_name: str
    organization: str
    object_address: str = ""
    object_part: str = ""
    stage: str = "П"
    developer: str = ""
    inspector: str = ""
    dept_head: str = ""
    gip: str = ""
    norm_control: str = ""


@dataclass
class SourceDataRequest:
    """Исходные данные проектирования: заказчик, основание, ТУ на подключение.
    Всё — то, что проектировщик получает НА ВХОДЕ (не считает сам)."""
    customer: str = ""                 # заказчик
    designer_org: str = ""             # проектная организация (генпроектировщик)
    basis: str = ""                    # основание (договор №, дата)
    design_stage: str = "Проектная документация (П)"
    source_description: str = ""       # существующая централизованная сеть
    water_protection_note: str = ""    # подтверждение по ГПЗУ/ИОС1
    reserve_water_note: str = ""       # решение по резервированию воды
    # ТУ на подключение к водопроводу
    tu_org: str = ""                   # кто выдал ТУ (водоканал)
    tu_number: str = ""
    tu_date: str = ""
    connection_point: str = ""         # точка подключения
    guaranteed_head_m: Optional[float] = None   # гарантированный напор, м
    maximum_head_m: Optional[float] = None      # максимальный статический напор по ТУ, м
    tu_limit_q_day: Optional[float] = None      # лимит, м³/сут
    tu_fire_outdoor_l_s: Optional[float] = None # наружное пожаротушение, л/с
    water_main_dn: int = 0             # диаметр городского водовода
    # Расчёт требуемого напора В1 (формула (14) п. 8.27 СП 30.13330.2020).
    # Это исходные/расчётные величины проектировщика; Builder их не придумывает.
    elev_header_m: Optional[float] = None   # отметка оси ввода/напорного коллектора
    elev_fixture_m: Optional[float] = None  # отметка излива диктующего прибора
    h_geom_m: Optional[float] = None        # Hgeom напрямую, если отметок нет
    il_dict_m: Optional[float] = None       # i*l внутренней сети до учёта местных потерь
    h_il_m: Optional[float] = None          # готовая сумма потерь внутренней сети
    network_kind: str = "domestic"         # domestic / combined / fire
    h_pr_m: float = 20.0                    # свободный напор перед прибором
    h_tepl_m: float = 0.0                   # потери в теплообменнике/ИТП
    h_apartment_c_meter_m: Optional[float] = None
    h_apartment_h_meter_m: Optional[float] = None
    hws_heater_in_scope: bool = False
    il_vvod_m: Optional[float] = None       # i*L ввода до коэффициента 1,1
    h_vvod_m: Optional[float] = None        # готовые потери на вводе
    water_use_period_h: float = 24.0        # период водопотребления для водомера
    inputs_count: int = 1                   # число вводов водопровода
    npsh_available_m: Optional[float] = None  # располагаемый кавитационный запас

@dataclass
class RoomRequest:
    """Помещение, где расставляются ПК (в терминах проектировщика)."""
    name: str
    length_m: float
    width_m: float
    height_m: float
    space_kind: str = "corridor"                 # SPACE_KINDS
    placement: str = "two_opposite_sides"        # PLACEMENT_MODES


@dataclass
class RiserRequest:
    """Стояк В2: где стоит и куда поднимается."""
    name: str                     # "СТ-В2-1"
    at_node: str                  # узел магистрали
    height_m: float               # длина стояка (подъём)
    cabinet_elevation_m: float    # отметка ПК
    dn: int = 65
    equiv_length_m: float = 0.0
    A: float = 0.011
    repair_section_id: str = ""   # ремонтная секция кольца


@dataclass
class MainRunRequest:
    """Участок магистрали между узлами."""
    from_node: str
    to_node: str
    length_m: float
    dn: int = 100
    equiv_length_m: float = 0.0
    A: float = 0.0023
    repair_section_id: str = ""       # секция между запорными устройствами


@dataclass
class NetworkRequest:
    """Сеть В2: узлы перечисляются неявно (из участков), кольцо/дерево — по факту."""
    runs: List[MainRunRequest] = field(default_factory=list)
    risers: List[RiserRequest] = field(default_factory=list)
    source_node: str = ""
    source_kind: str = "city_main"               # SOURCE_KINDS
    available_head_m: Optional[float] = None     # напор города (None → 0, уточнить)
    second_source_node: str = ""                 # второй ввод (пусто = один ввод)
    second_available_head_m: Optional[float] = None
    water_level_m: Optional[float] = None        # для резервуара/водоёма
    suction_head_loss_m: float = 0.0
    node_elevations: dict = field(default_factory=dict)   # {узел: отметка}, дефолт 0


@dataclass
class ConsumerGroupRequest:
    """Группа водопотребителей для расчёта расходов В1/Т3 (СП 30, табл. А.2)."""
    code: str                          # код типа потребителя (residential_central_hw и т.п.)
    count: int                         # число потребителей (жителей/мест/...)
    name: str = ""                    # функциональная часть объекта (для интерфейса/ТЗ)


@dataclass
class V1SectionRequest:
    """Участок диктующего направления хозяйственно-питьевого водопровода."""
    section_id: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    roughness_mm: float
    role: str = "internal"            # internal / input
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""


@dataclass
class V1NodeRequest:
    """Узел дерева В1 с отметкой и подключёнными потребителями."""
    node_id: str
    elevation_m: float
    consumers: List[ConsumerGroupRequest] = field(default_factory=list)
    direct_demand_lps: float = 0.0
    h_pr_m: float = 20.0
    max_static_head_m: float = 45.0


@dataclass
class V1NetworkSectionRequest:
    """Ориентированный участок В1; расход определяется по поддереву."""
    section_id: str
    from_node: str
    to_node: str
    length_m: float
    inner_diameter_mm: Optional[float]
    roughness_mm: float
    role: str = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""
    candidate_inner_diameters_mm: List[float] = field(default_factory=list)
    max_specific_loss_m_per_m: Optional[float] = None


@dataclass
class V1InletRequest:
    """Отдельный ввод В1, проверяемый на 100% расхода при отказе второго."""
    inlet_id: str
    guaranteed_head_m: float
    maximum_head_m: float
    length_m: float
    inner_diameter_mm: Optional[float]
    roughness_mm: float
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""
    candidate_inner_diameters_mm: List[float] = field(default_factory=list)
    max_specific_loss_m_per_m: Optional[float] = None


@dataclass
class V1NetworkRequest:
    source_node: str
    nodes: List[V1NodeRequest] = field(default_factory=list)
    sections: List[V1NetworkSectionRequest] = field(default_factory=list)
    inlets: List[V1InletRequest] = field(default_factory=list)


@dataclass
class SewageRiserRequest:
    """Явный расчётный узел стояка К1 по приложению К СП 30."""
    riser_id: str
    design_flow_lps: float
    material: str
    ventilation: str
    riser_dn_mm: int
    branch_dn_mm: int
    branch_angle_deg: float
    has_toilet: bool = True
    working_height_m: Optional[float] = None
    inner_diameter_mm: Optional[float] = None
    branch_inner_diameter_mm: Optional[float] = None
    minimum_trap_seal_mm: Optional[float] = None
    pressure_input_source: str = ""
    air_valve_free_area_mm2: Optional[float] = None
    air_valve_source: str = ""


@dataclass
class SewerPipeRequest:
    """Явно посчитанная труба К1/К2 для спецификации стадии П.

    Наружный диаметр и толщина стенки задаются отдельно, чтобы ПЗ и
    спецификация не подменяли фактическую геометрию условным DN.
    """
    system: str
    section_id: str
    purpose: str
    material: str
    standard: str
    outer_diameter_mm: float
    wall_thickness_mm: float
    length_m: float
    calculation_length_m: Optional[float] = None
    nominal_diameter_mm: Optional[int] = None
    design_flow_lps: Optional[float] = None
    manning_n: Optional[float] = None
    hydraulic_source: str = ""
    critical_velocity_mps: Optional[float] = None
    critical_velocity_source: str = ""
    critical_fill_ratio: Optional[float] = None
    slope_per_mille: Optional[float] = None
    fill_ratio: Optional[float] = None
    from_node: str = ""
    to_node: str = ""
    room: str = ""
    elevation_start_m: Optional[float] = None
    elevation_end_m: Optional[float] = None
    absolute_elevation_start_m: Optional[float] = None
    absolute_elevation_end_m: Optional[float] = None
    insulated: bool = False
    # Для К2 выше 10 м СП 30.13330.2020, пп. 21.13–21.14 требуют
    # напорные трубы, рассчитанные на гидростатическое давление при засоре.
    # Признак и класс давления задаются явно, а не выводятся из названия ГОСТ.
    pressure_rated: Optional[bool] = None
    pressure_class_bar: Optional[float] = None

    @property
    def inner_diameter_mm(self) -> float:
        return self.outer_diameter_mm - 2.0 * self.wall_thickness_mm


@dataclass
class SewerElementRequest:
    """Элемент реестра К1/К2/К3 — источник схемы и спецификации.

    Количество и этажность вводятся проектировщиком либо импортируются из
    модели. Builder не создаёт приборы, арматуру и фасонные части по
    косвенным данным, чтобы стадия П не выглядела фиктивно точной.
    """
    element_id: str
    system: str
    kind: str
    name: str
    quantity: int = 1
    typical_quantity: Optional[int] = None
    floor_from: int = 1
    floor_to: Optional[int] = None
    room_number: str = ""
    room_name: str = ""
    elevation_m: Optional[float] = None
    dn_mm: Optional[int] = None
    slope_per_mille: Optional[float] = None
    section_id: str = ""
    connects_to: str = ""
    type_mark: str = ""
    standard: str = ""
    manufacturer: str = "по проекту"
    unit: str = "шт."
    include_in_spec: bool = True
    note: str = ""
    layout_column: int = 0
    service_direction: str = ""
    service_fitting: str = ""
    accessible: bool = True
    service_chainage_m: Optional[float] = None


@dataclass
class SewerDischargeEventRequest:
    """Сценарный сброс; время и расход не выводятся из количества приборов."""
    event_id: str
    fixture_id: str
    floor: int
    instance_no: int
    start_seconds: float
    duration_seconds: float
    flow_lps: float
    source: str
    suspended_solids_mg_l: Optional[float] = None
    suspended_solids_source: str = ""


@dataclass
class SewerFixtureSafetyRequest:
    """Абсолютные отметки конкретного прибора; ничего не выводится из этажности."""
    fixture_id: str
    floor: int
    instance_no: int
    connection_absolute_elevation_m: float
    overflow_absolute_elevation_m: float
    trap_seal_depth_mm: float
    minimum_residual_seal_mm: float
    source: str


@dataclass
class SewerBoundaryLevelRequest:
    time_seconds: float
    water_level_absolute_elevation_m: float


@dataclass
class SewerFirstManholeRequest:
    """Первый колодец как заданная граничная отметка, не наружная модель."""
    manhole_id: str
    outlet_section_id: str
    invert_absolute_elevation_m: float
    levels: List[SewerBoundaryLevelRequest] = field(default_factory=list)
    source: str = ""


@dataclass
class SewerInternalNodeRequest:
    """Внутренний узел К1: отметки и объём задаются, а не вычисляются."""
    node_id: str
    downstream_section_id: str
    upstream_section_ids: List[str]
    invert_absolute_elevation_m: float
    overflow_absolute_elevation_m: float
    storage_volume_m3: float
    overflow_location: str
    source: str


@dataclass
class IOS2Request:
    """Полное намерение: «спроектируй мне ИОС2 для такого объекта»."""
    document: DocumentRequest
    building_type: str                            # BUILDING_TYPES
    floors: int
    building_height_m: float
    total_area_m2: float = 0.0
    hws_type: str = "central"                    # central / local / none
    risers_v1: int = 0
    risers_t3: int = 0
    risers_t4: int = 0
    insulation_location: str = "room_hot"
    insulation_t_room_manual: float = 5.0
    insulation_humidity: int = 60
    insulation_hvs_water_temp: float = 10.0
    insulation_gvs_water_temp: float = 60.0
    # ВПВ
    fire_mode: str = "auto"                       # auto / not_required / manual
    fire_height_m: Optional[float] = None          # пожарно-техническая высота
    fire_category: str = ""                        # строка табл. 7.1 СП 10, Изм. № 1
    fire_hall_seats: Optional[int] = None           # для Ф2.1
    fire_area_m2: Optional[float] = None            # площадь расчётной части
    fire_geometry_confirmed: bool = True            # геометрия явно введена/импортирована
    streams: Optional[int] = None                  # только ручной override
    q_per_stream_lps: float = 2.6
    hose_length_m: int = 20
    cabinet_dn: int = 50
    nozzle_mm: int = 13
    compact_jet_m: int = 12
    fire_topology: str = "auto"               # auto/combined/separate/pre_meter_branch
    fire_topology_basis: str = ""
    fire_branch_electric_valves: bool = False
    rooms: List[RoomRequest] = field(default_factory=list)
    network: Optional[NetworkRequest] = None
    # прочее
    zones: int = 1
    needs_booster_pumps: bool = True
    source_data: Optional[SourceDataRequest] = None
    consumers: List[ConsumerGroupRequest] = field(default_factory=list)
    v1_sections: List[V1SectionRequest] = field(default_factory=list)
    v1_network: Optional[V1NetworkRequest] = None
    sewage_max_fixture_lps: float = 1.6  # q_0s по таблице А.1 СП 30, л/с
    sewage_risers: List[SewageRiserRequest] = field(default_factory=list)
    sewer_pipes: List[SewerPipeRequest] = field(default_factory=list)
    sewer_elements: List[SewerElementRequest] = field(default_factory=list)
    sewer_discharge_events: List[SewerDischargeEventRequest] = field(default_factory=list)
    sewer_fixture_safety_inputs: List[SewerFixtureSafetyRequest] = field(default_factory=list)
    sewer_first_manholes: List[SewerFirstManholeRequest] = field(default_factory=list)
    sewer_internal_nodes: List[SewerInternalNodeRequest] = field(default_factory=list)
    sewer_transient_step_seconds: Optional[float] = None
    sewer_transient_duration_seconds: Optional[float] = None
    sewage_outlets_count: int = 0
    wastewater_basement_floor_elevation_m: Optional[float] = None
    # Точные входы графического генератора. Высота этажа не выводится из
    # общей высоты здания, а вид кровли не подменяется общим roof_type:
    # оба значения влияют на отметки и высоту вентиляционной части стояка.
    wastewater_floor_height_m: Optional[float] = None
    wastewater_roof_kind: str = "unknown"
    wastewater_design_assignment_ref: str = ""
    wastewater_survey_ref: str = ""
    wastewater_service_life_years: Optional[int] = None
    wastewater_overhaul_period_years: Optional[int] = None
    wastewater_disposal_mode: str = "not_set"
    wastewater_tu_org: str = ""
    wastewater_tu_number: str = ""
    wastewater_tu_date: str = ""
    wastewater_discharge_standard_ref: str = ""
    wastewater_water_body_characteristics_note: str = ""
    wastewater_existing_network_type: str = ""
    wastewater_existing_network_material: str = ""
    wastewater_existing_network_standard: str = ""
    wastewater_existing_network_outer_diameter_mm: Optional[float] = None
    wastewater_existing_network_wall_thickness_mm: Optional[float] = None
    wastewater_discharge_point_k1: str = ""
    wastewater_discharge_point_k2: str = ""
    wastewater_discharge_point_k3: str = ""
    wastewater_k1_min_hourly_m3h: Optional[float] = None
    wastewater_k3_max_hourly_m3h: Optional[float] = None
    wastewater_k3_min_hourly_m3h: Optional[float] = None
    wastewater_quality_indicators_note: str = ""
    wastewater_laying_method: str = ""
    wastewater_fire_barrier_note: str = ""
    wastewater_deformation_joint_note: str = ""
    wastewater_waste_handling_note: str = ""
    wastewater_external_network_in_scope: bool = False
    wastewater_external_network_design_note: str = ""
    wastewater_external_scheme_source: str = ""
    wastewater_site_plan_source: str = ""
    wastewater_pump_required: bool = False
    wastewater_pump_location: str = ""
    wastewater_pump_model: str = ""
    wastewater_pump_q_m3h: Optional[float] = None
    wastewater_pump_head_m: Optional[float] = None
    wastewater_pump_power_kw: Optional[float] = None
    wastewater_pump_reserve_note: str = ""
    wastewater_pump_power_category: str = ""
    wastewater_pump_automation_note: str = ""
    wastewater_pump_system: str = ""
    wastewater_pump_mode: str = "not_set"
    wastewater_pump_fixture_count: Optional[int] = None
    wastewater_pump_static_head_m: Optional[float] = None
    wastewater_pump_dynamic_loss_m: Optional[float] = None
    wastewater_pump_curve: List[tuple[float, float]] = field(default_factory=list)
    wastewater_pump_curve_source: str = ""
    wastewater_pump_hydraulic_source: str = ""
    wastewater_pump_working_units: Optional[int] = None
    wastewater_pump_reserve_units: Optional[int] = None
    wastewater_pump_discharge_node: str = ""
    wastewater_pump_receiver_useful_volume_m3: Optional[float] = None
    wastewater_pump_emergency_volume_m3: Optional[float] = None
    wastewater_pump_emergency_runtime_min: Optional[float] = None
    wastewater_pump_emergency_note: str = ""
    wastewater_treatment_required: bool = False
    wastewater_treatment_location: str = ""
    wastewater_treatment_type: str = ""
    wastewater_treatment_capacity_lps: Optional[float] = None
    wastewater_treatment_capacity_m3_day: Optional[float] = None
    wastewater_treatment_technology: str = ""
    storm_city: str = ""           # город для расчёта дождевого стока (К2)
    apartments: int = 0
    owner_groups_count: int = 1
    roof_type: str = "not_set"
    storm_roof_area_m2: float = 0.0
    storm_walls_area_m2: float = 0.0
    storm_period_years: int = 1
    storm_roof_sections: int = 0
    storm_funnels_count: int = 0
    storm_sectional_residential_single_funnel: bool = False
    storm_max_funnel_spacing_m: Optional[float] = None
    storm_selected_funnel_capacity_lps: Optional[float] = None
    storm_max_funnel_flow_lps: Optional[float] = None
    storm_risers_count: int = 0
    storm_selected_riser_dn_mm: int = 0
    storm_max_riser_flow_lps: Optional[float] = None
    storm_funnels_on_different_levels: bool = False
    storm_design_m3_day: Optional[float] = None
    storm_annual_m3: Optional[float] = None
    storm_melt_m3h: Optional[float] = None
    storm_melt_m3_day: Optional[float] = None
    storm_melt_m3_year: Optional[float] = None
    storm_treatment_volume_m3: Optional[float] = None
    storm_storage_volume_m3: Optional[float] = None
    catering_type: str = "none"
    catering_seats: int = 0
    catering_conditional_dishes: int = 0
    school_grease_by_assignment: bool = False
    # Технологическая анкета. Эти ответы управляют полнотой исходных данных,
    # но сами по себе не заменяют строки таблицы А.2 и расчёт legacy.
    group_showers_answer: str = "unknown"
    group_showers_count: int = 0
    food_service_answer: str = "unknown"
    grease_wastewater_answer: str = "unknown"
    grease_trap_location: str = "unknown"

    def validate(self) -> List[str]:
        """Первичная валидация намерения (типы/диапазоны/обязательность).
        Возвращает список проблем; пустой = вход пригоден для Builder."""
        p: List[str] = []
        if self.fire_topology not in ("auto", "combined", "separate", "pre_meter_branch"):
            p.append("fire_topology должен быть auto, combined, separate или pre_meter_branch")
        if self.hws_type not in ("central", "local", "none"):
            p.append("hws_type должен быть central, local или none")
        if self.building_type not in BUILDING_TYPES:
            p.append(f"building_type '{self.building_type}' не из {BUILDING_TYPES}")
        if self.floors <= 0:
            p.append("floors должно быть > 0")
        if self.building_height_m <= 0:
            p.append("building_height_m должно быть > 0 (нужно для Rk п. 7.15)")
        if self.total_area_m2 < 0:
            p.append("total_area_m2 не может быть отрицательной")
        if min(self.risers_v1, self.risers_t3, self.risers_t4) < 0:
            p.append("число стояков В1/Т3/Т4 не может быть отрицательным")
        if self.insulation_location not in ("room_hot", "room_cold", "parking"):
            p.append("insulation_location должен быть room_hot, room_cold или parking")
        if self.insulation_humidity not in (40, 50, 60, 70, 80, 90):
            p.append("insulation_humidity должна быть 40, 50, 60, 70, 80 или 90")
        if self.fire_mode not in FIRE_MODES:
            p.append(f"fire_mode '{self.fire_mode}' не из {FIRE_MODES}")
        if self.fire_category and self.fire_category not in FIRE_CATEGORIES:
            p.append(
                f"fire_category '{self.fire_category}' не из {FIRE_CATEGORIES}"
            )
        if self.fire_mode == "auto":
            if self.fire_height_m is None or self.fire_height_m <= 0:
                p.append(
                    "fire_height_m должна быть > 0 для автоматической проверки "
                    "ВПВ по СП 10 (укажите пожарно-техническую высоту)"
                )
            if self.building_type == "industrial":
                p.append(
                    "автомат В2 для производственного здания требует категории, "
                    "степени огнестойкости, класса и объёма; используйте ручной режим"
                )
            if self.building_type == "public" and not self.fire_category:
                p.append(
                    "для общественного здания выберите функциональную категорию "
                    "В2 по строке таблицы 7.1 СП 10"
                )
            has_public_part = any(
                group.code and not group.code.startswith("residential_")
                for group in self.consumers
            )
            if (
                self.building_type == "residential"
                and has_public_part
                and not self.fire_category
            ):
                p.append(
                    "для смешанного жилого здания явно выберите диктующую "
                    "функциональную категорию В2"
                )
            if (
                self.fire_category == "theatre_f21"
                and (self.fire_hall_seats is None or self.fire_hall_seats <= 0)
            ):
                p.append(
                    "для объекта Ф2.1 строки 5 задайте вместимость зала"
                )
            if (
                self.fire_category in ("library_sport", "museum_trade")
                and (self.fire_area_m2 or self.total_area_m2) <= 0
            ):
                p.append(
                    "для выбранной строки таблицы 7.1 задайте площадь расчётной части"
                )
        if self.fire_hall_seats is not None and self.fire_hall_seats <= 0:
            p.append("fire_hall_seats должен быть > 0")
        if self.fire_area_m2 is not None and self.fire_area_m2 <= 0:
            p.append("fire_area_m2 должен быть > 0")
        if (self.rooms or self.network is not None) and not self.fire_geometry_confirmed:
            p.append(
                "геометрия В2 должна быть явно подтверждена как введённая "
                "по плану/расчётной схеме"
            )
        if self.fire_mode == "manual" and self.streams not in (1, 2, 3, 4):
            p.append("для ручного режима В2 задайте streams от 1 до 4")
        if self.streams is not None and self.streams not in (1, 2, 3, 4):
            p.append(f"streams={self.streams}: поддерживается диапазон 1–4")
        if self.nozzle_mm not in (13, 16, 19):
            p.append("nozzle_mm должен быть 13, 16 или 19")
        if self.compact_jet_m not in (6, 8, 10, 12, 14, 16, 18, 20):
            p.append("compact_jet_m должен быть 6, 8, 10, 12, 14, 16, 18 или 20")
        if self.sewage_max_fixture_lps < 0:
            p.append("sewage_max_fixture_lps не может быть отрицательным")
        if self.sewage_outlets_count < 0:
            p.append("sewage_outlets_count не может быть отрицательным")
        if (
            self.wastewater_floor_height_m is not None
            and self.wastewater_floor_height_m <= 0
        ):
            p.append("wastewater_floor_height_m должен быть > 0")
        if self.wastewater_roof_kind not in WASTEWATER_ROOF_KINDS:
            p.append(
                "wastewater_roof_kind должен быть одним из "
                f"{WASTEWATER_ROOF_KINDS}"
            )
        seen_sewage_risers = set()
        for i, riser in enumerate(self.sewage_risers):
            if not riser.riser_id or riser.riser_id in seen_sewage_risers:
                p.append(
                    f"sewage_risers[{i}]: марка пустая или повторяется"
                )
            seen_sewage_risers.add(riser.riser_id)
            if riser.design_flow_lps <= 0:
                p.append(
                    f"sewage_risers[{i}].design_flow_lps должен быть > 0"
                )
            if min(riser.riser_dn_mm, riser.branch_dn_mm) <= 0:
                p.append(f"sewage_risers[{i}]: диаметры должны быть > 0")
            if riser.material not in SEWAGE_MATERIALS:
                p.append(
                    f"sewage_risers[{i}].material должен быть одним из "
                    f"{SEWAGE_MATERIALS}"
                )
            if riser.ventilation not in SEWAGE_VENTILATION:
                p.append(
                    f"sewage_risers[{i}].ventilation должен быть одним из "
                    f"{SEWAGE_VENTILATION}"
                )
            if riser.branch_angle_deg not in (45.0, 60.0, 87.5):
                p.append(
                    f"sewage_risers[{i}].branch_angle_deg должен быть "
                    "45, 60 или 87,5"
                )
            if riser.working_height_m is not None and riser.working_height_m <= 0:
                p.append(
                    f"sewage_risers[{i}].working_height_m должен быть > 0"
                )
            for field_name, value in (
                ("inner_diameter_mm", riser.inner_diameter_mm),
                ("branch_inner_diameter_mm", riser.branch_inner_diameter_mm),
                ("minimum_trap_seal_mm", riser.minimum_trap_seal_mm),
                ("air_valve_free_area_mm2", riser.air_valve_free_area_mm2),
            ):
                if value is not None and value <= 0:
                    p.append(f"sewage_risers[{i}].{field_name} должен быть > 0")
            if (
                riser.branch_inner_diameter_mm is not None
                and riser.inner_diameter_mm is not None
                and riser.branch_inner_diameter_mm > riser.inner_diameter_mm
            ):
                p.append(
                    f"sewage_risers[{i}]: внутренний диаметр отвода "
                    "не может быть больше внутреннего диаметра стояка"
                )
            if riser.air_valve_free_area_mm2 is not None:
                if riser.ventilation != "vacuum_valve":
                    p.append(
                        f"sewage_risers[{i}].air_valve_free_area_mm2 допустима "
                        "только для стояка с воздушным клапаном"
                    )
                if not riser.air_valve_source.strip():
                    p.append(
                        f"sewage_risers[{i}].air_valve_source обязателен "
                        "для площади клапана"
                    )
        seen_sewer_sections = set()
        for i, pipe in enumerate(self.sewer_pipes):
            if pipe.system not in ("K1", "K2", "K3"):
                p.append(f"sewer_pipes[{i}].system должен быть K1, K2 или K3")
            if not pipe.section_id or pipe.section_id in seen_sewer_sections:
                p.append(
                    f"sewer_pipes[{i}]: обозначение пустое или повторяется"
                )
            seen_sewer_sections.add(pipe.section_id)
            if min(
                pipe.outer_diameter_mm,
                pipe.wall_thickness_mm,
                pipe.length_m,
            ) <= 0:
                p.append(
                    f"sewer_pipes[{i}]: наружный диаметр, стенка и длина "
                    "должны быть > 0"
                )
            if pipe.inner_diameter_mm <= 0:
                p.append(
                    f"sewer_pipes[{i}]: толщина стенки исключает проходное "
                    "сечение"
                )
            if (
                pipe.nominal_diameter_mm is not None
                and pipe.nominal_diameter_mm <= 0
            ):
                p.append(
                    f"sewer_pipes[{i}].nominal_diameter_mm должен быть > 0"
                )
            if pipe.design_flow_lps is not None and pipe.design_flow_lps <= 0:
                p.append(
                    f"sewer_pipes[{i}].design_flow_lps должен быть > 0"
                )
            if (
                pipe.calculation_length_m is not None
                and pipe.calculation_length_m <= 0
            ):
                p.append(
                    f"sewer_pipes[{i}].calculation_length_m должен быть > 0"
                )
            if pipe.manning_n is not None and pipe.manning_n <= 0:
                p.append(f"sewer_pipes[{i}].manning_n должен быть > 0")
            if pipe.manning_n is not None and not pipe.hydraulic_source.strip():
                p.append(
                    f"sewer_pipes[{i}].hydraulic_source обязателен при manning_n"
                )
            if (
                pipe.critical_velocity_mps is not None
                and pipe.critical_velocity_mps <= 0
            ):
                p.append(
                    f"sewer_pipes[{i}].critical_velocity_mps должен быть > 0"
                )
            if (
                pipe.critical_velocity_mps is not None
                and not pipe.critical_velocity_source.strip()
            ):
                p.append(
                    f"sewer_pipes[{i}].critical_velocity_source обязателен"
                )
            if (
                pipe.critical_fill_ratio is not None
                and not 0 < pipe.critical_fill_ratio <= 1
            ):
                p.append(
                    f"sewer_pipes[{i}].critical_fill_ratio должен быть в (0; 1]"
                )
            if not pipe.material.strip() or not pipe.standard.strip():
                p.append(
                    f"sewer_pipes[{i}]: материал и стандарт/ТУ обязательны "
                    "для точной спецификации"
                )
            if pipe.slope_per_mille is not None and pipe.slope_per_mille < 0:
                p.append(f"sewer_pipes[{i}].slope_per_mille не может быть отрицательным")
            if pipe.fill_ratio is not None and not 0 <= pipe.fill_ratio <= 1:
                p.append(f"sewer_pipes[{i}].fill_ratio должен быть от 0 до 1")
            if (
                pipe.pressure_class_bar is not None
                and pipe.pressure_class_bar <= 0
            ):
                p.append(
                    f"sewer_pipes[{i}].pressure_class_bar должен быть > 0"
                )
            if pipe.pressure_class_bar is not None and pipe.pressure_rated is not True:
                p.append(
                    f"sewer_pipes[{i}].pressure_class_bar допустим только "
                    "для явно напорной трубы"
                )
            if ((pipe.elevation_start_m is None)
                    != (pipe.elevation_end_m is None)):
                p.append(
                    f"sewer_pipes[{i}]: начальная и конечная отметки задаются парой"
                )
            if ((pipe.absolute_elevation_start_m is None)
                    != (pipe.absolute_elevation_end_m is None)):
                p.append(
                    f"sewer_pipes[{i}]: абсолютные начальная и конечная "
                    "отметки задаются парой"
                )
        seen_sewer_elements = set()
        sewer_nodes = {
            node
            for pipe in self.sewer_pipes
            for node in (pipe.from_node, pipe.to_node)
            if node
        }
        for i, element in enumerate(self.sewer_elements):
            if not element.element_id or element.element_id in seen_sewer_elements:
                p.append(
                    f"sewer_elements[{i}]: обозначение пустое или повторяется"
                )
            seen_sewer_elements.add(element.element_id)
            if element.system not in ("K1", "K2", "K3"):
                p.append(f"sewer_elements[{i}].system должен быть K1, K2 или K3")
            if element.kind not in SEWER_ELEMENT_KINDS:
                p.append(
                    f"sewer_elements[{i}].kind должен быть одним из "
                    f"{SEWER_ELEMENT_KINDS}"
                )
            if not element.name.strip():
                p.append(f"sewer_elements[{i}].name не может быть пустым")
            if element.quantity <= 0:
                p.append(f"sewer_elements[{i}].quantity должен быть > 0")
            if (
                element.typical_quantity is not None
                and element.typical_quantity <= 0
            ):
                p.append(
                    f"sewer_elements[{i}].typical_quantity должен быть > 0"
                )
            if element.floor_to is not None and element.floor_to < element.floor_from:
                p.append(
                    f"sewer_elements[{i}].floor_to не может быть ниже floor_from"
                )
            if element.dn_mm is not None and element.dn_mm <= 0:
                p.append(f"sewer_elements[{i}].dn_mm должен быть > 0")
            if (
                element.slope_per_mille is not None
                and element.slope_per_mille < 0
            ):
                p.append(
                    f"sewer_elements[{i}].slope_per_mille не может быть отрицательным"
                )
            if element.layout_column < 0:
                p.append(f"sewer_elements[{i}].layout_column не может быть < 0")
            if element.service_direction not in (
                "", "downstream", "upstream", "both",
            ):
                p.append(
                    f"sewer_elements[{i}].service_direction должен быть "
                    "downstream, upstream или both"
                )
            if element.service_fitting not in (
                "", "wye_45", "revision_opening",
            ):
                p.append(
                    f"sewer_elements[{i}].service_fitting должен быть "
                    "wye_45 или revision_opening"
                )
            if (
                element.service_chainage_m is not None
                and element.service_chainage_m < 0
            ):
                p.append(
                    f"sewer_elements[{i}].service_chainage_m не может быть < 0"
                )
            if element.include_in_spec and not element.unit.strip():
                p.append(
                    f"sewer_elements[{i}].unit обязателен для спецификации"
                )
            if element.section_id and element.section_id not in seen_sewer_sections:
                p.append(
                    f"sewer_elements[{i}].section_id ссылается на неизвестный "
                    f"участок '{element.section_id}'"
                )
        sewer_section_systems = {
            pipe.section_id: pipe.system
            for pipe in self.sewer_pipes
            if pipe.section_id
        }
        valid_connections = seen_sewer_elements | sewer_nodes | seen_sewer_sections
        for i, element in enumerate(self.sewer_elements):
            if (
                element.section_id
                and element.section_id in sewer_section_systems
                and sewer_section_systems[element.section_id] != element.system
            ):
                p.append(
                    f"sewer_elements[{i}]: система {element.system} не совпадает "
                    f"с системой участка {element.section_id}"
                )
            if element.connects_to and element.connects_to not in valid_connections:
                p.append(
                    f"sewer_elements[{i}].connects_to ссылается на неизвестный "
                    f"элемент или узел '{element.connects_to}'"
                )
        if (
            self.sewer_transient_step_seconds is not None
            and self.sewer_transient_step_seconds <= 0
        ):
            p.append("sewer_transient_step_seconds должен быть > 0")
        if (
            self.sewer_transient_duration_seconds is not None
            and self.sewer_transient_duration_seconds <= 0
        ):
            p.append("sewer_transient_duration_seconds должен быть > 0")
        if self.sewer_discharge_events and self.sewer_transient_step_seconds is None:
            p.append(
                "для sewer_discharge_events требуется "
                "sewer_transient_step_seconds"
            )
        elements_by_id = {
            row.element_id: row for row in self.sewer_elements if row.element_id
        }
        seen_discharge_events = set()
        for i, event in enumerate(self.sewer_discharge_events):
            if not event.event_id or event.event_id in seen_discharge_events:
                p.append(
                    f"sewer_discharge_events[{i}]: ID пустой или повторяется"
                )
            seen_discharge_events.add(event.event_id)
            fixture = elements_by_id.get(event.fixture_id)
            if fixture is None:
                p.append(
                    f"sewer_discharge_events[{i}].fixture_id ссылается "
                    f"на неизвестный прибор '{event.fixture_id}'"
                )
            elif fixture.system != "K1" or fixture.kind not in {
                "toilet", "washbasin", "sink", "bath", "shower",
                "floor_drain", "washing_machine", "dishwasher",
            }:
                p.append(
                    f"sewer_discharge_events[{i}].fixture_id должен "
                    "ссылаться на приёмник стоков К1"
                )
            if event.floor < 1:
                p.append(f"sewer_discharge_events[{i}].floor должен быть >= 1")
            if event.instance_no < 1:
                p.append(
                    f"sewer_discharge_events[{i}].instance_no должен быть >= 1"
                )
            if event.start_seconds < 0:
                p.append(
                    f"sewer_discharge_events[{i}].start_seconds не может быть < 0"
                )
            if event.duration_seconds <= 0:
                p.append(
                    f"sewer_discharge_events[{i}].duration_seconds должен быть > 0"
                )
            if event.flow_lps <= 0:
                p.append(
                    f"sewer_discharge_events[{i}].flow_lps должен быть > 0"
                )
            if not event.source.strip():
                p.append(f"sewer_discharge_events[{i}].source обязателен")
            if (
                event.suspended_solids_mg_l is not None
                and event.suspended_solids_mg_l < 0
            ):
                p.append(
                    f"sewer_discharge_events[{i}].suspended_solids_mg_l "
                    "не может быть < 0"
                )
            if (
                event.suspended_solids_mg_l is not None
                and not event.suspended_solids_source.strip()
            ):
                p.append(
                    f"sewer_discharge_events[{i}].suspended_solids_source "
                    "обязателен при заданной концентрации"
                )
            step = self.sewer_transient_step_seconds
            if step is not None and step > 0:
                for field_name, value in (
                    ("start_seconds", event.start_seconds),
                    ("end_seconds", event.start_seconds + event.duration_seconds),
                ):
                    quotient = value / step
                    if abs(quotient - round(quotient)) > 1e-9:
                        p.append(
                            f"sewer_discharge_events[{i}].{field_name} "
                            f"должно быть кратно шагу {step:g} с"
                        )
        if self.sewer_discharge_events:
            last_event_end = max(
                row.start_seconds + row.duration_seconds
                for row in self.sewer_discharge_events
            )
            duration = self.sewer_transient_duration_seconds
            if duration is not None and duration < last_event_end:
                p.append(
                    "sewer_transient_duration_seconds не может быть меньше "
                    f"конца последнего события ({last_event_end:g} с)"
                )
            step = self.sewer_transient_step_seconds
            if duration is not None and step is not None and step > 0:
                quotient = duration / step
                if abs(quotient - round(quotient)) > 1e-9:
                    p.append(
                        "sewer_transient_duration_seconds должно быть "
                        f"кратно шагу {step:g} с"
                    )

        seen_fixture_safety = set()
        for i, row in enumerate(self.sewer_fixture_safety_inputs):
            key = (row.fixture_id, row.floor, row.instance_no)
            if key in seen_fixture_safety:
                p.append(
                    f"sewer_fixture_safety_inputs[{i}]: привязка {key} "
                    "задана повторно"
                )
            seen_fixture_safety.add(key)
            fixture = elements_by_id.get(row.fixture_id)
            if fixture is None:
                p.append(
                    f"sewer_fixture_safety_inputs[{i}].fixture_id ссылается "
                    f"на неизвестный прибор '{row.fixture_id}'"
                )
            elif fixture.system != "K1" or fixture.kind not in {
                "toilet", "washbasin", "sink", "bath", "shower",
                "floor_drain", "washing_machine", "dishwasher",
            }:
                p.append(
                    f"sewer_fixture_safety_inputs[{i}].fixture_id должен "
                    "ссылаться на приёмник стоков К1"
                )
            else:
                floor_to = (
                    fixture.floor_to
                    if fixture.floor_to is not None else fixture.floor_from
                )
                if not fixture.floor_from <= row.floor <= floor_to:
                    p.append(
                        f"sewer_fixture_safety_inputs[{i}].floor вне "
                        f"диапазона {fixture.floor_from}--{floor_to}"
                    )
                if fixture.typical_quantity is None:
                    p.append(
                        f"sewer_fixture_safety_inputs[{i}]: у прибора не "
                        "задано количество экземпляров на этаже"
                    )
                elif not 1 <= row.instance_no <= fixture.typical_quantity:
                    p.append(
                        f"sewer_fixture_safety_inputs[{i}].instance_no должен "
                        f"быть от 1 до {fixture.typical_quantity}"
                    )
            if row.floor < 1:
                p.append(
                    f"sewer_fixture_safety_inputs[{i}].floor должен быть >= 1"
                )
            if row.instance_no < 1:
                p.append(
                    f"sewer_fixture_safety_inputs[{i}].instance_no должен быть >= 1"
                )
            if (
                row.overflow_absolute_elevation_m
                <= row.connection_absolute_elevation_m
            ):
                p.append(
                    f"sewer_fixture_safety_inputs[{i}]: абсолютная отметка "
                    "перелива должна быть выше отметки подключения"
                )
            if row.trap_seal_depth_mm <= 0:
                p.append(
                    f"sewer_fixture_safety_inputs[{i}].trap_seal_depth_mm "
                    "должен быть > 0"
                )
            if not (
                0 <= row.minimum_residual_seal_mm < row.trap_seal_depth_mm
            ):
                p.append(
                    f"sewer_fixture_safety_inputs[{i}].minimum_residual_seal_mm "
                    "должен быть от 0 до глубины гидрозатвора"
                )
            if not row.source.strip():
                p.append(f"sewer_fixture_safety_inputs[{i}].source обязателен")

        pipe_by_id = {
            row.section_id: row for row in self.sewer_pipes if row.section_id
        }
        seen_internal_nodes = set()
        seen_internal_downstream = set()
        for i, row in enumerate(self.sewer_internal_nodes):
            prefix = f"sewer_internal_nodes[{i}]"
            if not row.node_id or row.node_id in seen_internal_nodes:
                p.append(f"{prefix}: ID пустой или повторяется")
            seen_internal_nodes.add(row.node_id)
            if (
                not row.downstream_section_id
                or row.downstream_section_id in seen_internal_downstream
            ):
                p.append(f"{prefix}: нижний участок пустой или повторяется")
            seen_internal_downstream.add(row.downstream_section_id)
            downstream = pipe_by_id.get(row.downstream_section_id)
            if downstream is None or downstream.system != "K1":
                p.append(
                    f"{prefix}.downstream_section_id должен ссылаться на К1"
                )
            else:
                if downstream.from_node != row.node_id:
                    p.append(
                        f"{prefix}: участок {row.downstream_section_id} "
                        f"начинается в '{downstream.from_node}', а не "
                        f"в '{row.node_id}'"
                    )
                if (
                    downstream.absolute_elevation_start_m is not None
                    and abs(
                        downstream.absolute_elevation_start_m
                        - row.invert_absolute_elevation_m
                    ) > 0.001
                ):
                    p.append(
                        f"{prefix}: отметка лотка не совпадает с началом "
                        "нижнего участка"
                    )
            if (
                len(set(row.upstream_section_ids))
                != len(row.upstream_section_ids)
            ):
                p.append(f"{prefix}: верхний участок задан повторно")
            for upstream_id in row.upstream_section_ids:
                upstream = pipe_by_id.get(upstream_id)
                if upstream is None or upstream.system != "K1":
                    p.append(
                        f"{prefix}.upstream_section_ids содержит не К1 "
                        f"'{upstream_id}'"
                    )
                elif upstream.to_node != row.node_id:
                    p.append(
                        f"{prefix}: участок {upstream_id} заканчивается в "
                        f"'{upstream.to_node}', а не в '{row.node_id}'"
                    )
            if (
                row.overflow_absolute_elevation_m
                <= row.invert_absolute_elevation_m
            ):
                p.append(f"{prefix}: отметка перелива должна быть выше лотка")
            if row.storage_volume_m3 <= 0:
                p.append(f"{prefix}.storage_volume_m3 должен быть > 0")
            if not row.overflow_location.strip():
                p.append(f"{prefix}.overflow_location обязателен")
            if not row.source.strip():
                p.append(f"{prefix}.source обязателен")
        seen_manholes = set()
        seen_manhole_outlets = set()
        for i, row in enumerate(self.sewer_first_manholes):
            if not row.manhole_id or row.manhole_id in seen_manholes:
                p.append(
                    f"sewer_first_manholes[{i}]: ID пустой или повторяется"
                )
            seen_manholes.add(row.manhole_id)
            if (
                not row.outlet_section_id
                or row.outlet_section_id in seen_manhole_outlets
            ):
                p.append(
                    f"sewer_first_manholes[{i}]: выпуск пустой или повторяется"
                )
            seen_manhole_outlets.add(row.outlet_section_id)
            outlet = pipe_by_id.get(row.outlet_section_id)
            if outlet is None or outlet.system != "K1":
                p.append(
                    f"sewer_first_manholes[{i}].outlet_section_id должен "
                    "ссылаться на выпуск К1"
                )
            else:
                if outlet.to_node != row.manhole_id:
                    p.append(
                        f"sewer_first_manholes[{i}]: выпуск "
                        f"{row.outlet_section_id} заканчивается в "
                        f"'{outlet.to_node}', а не в '{row.manhole_id}'"
                    )
                if outlet.absolute_elevation_end_m is None:
                    p.append(
                        f"sewer_first_manholes[{i}]: у выпуска нужна "
                        "абсолютная отметка конца"
                    )
                elif abs(
                    outlet.absolute_elevation_end_m
                    - row.invert_absolute_elevation_m
                ) > 0.001:
                    p.append(
                        f"sewer_first_manholes[{i}]: отметка лотка не "
                        "совпадает с отметкой конца выпуска"
                    )
            if not row.levels:
                p.append(
                    f"sewer_first_manholes[{i}]: нужен хотя бы один уровень"
                )
            else:
                times = [point.time_seconds for point in row.levels]
                if times[0] != 0 or times != sorted(set(times)):
                    p.append(
                        f"sewer_first_manholes[{i}]: уровни должны начинаться "
                        "с t=0 и иметь строго возрастающее время"
                    )
                for j, point in enumerate(row.levels):
                    if point.time_seconds < 0:
                        p.append(
                            f"sewer_first_manholes[{i}].levels[{j}].time_seconds "
                            "не может быть < 0"
                        )
                    if (
                        point.water_level_absolute_elevation_m
                        < row.invert_absolute_elevation_m
                    ):
                        p.append(
                            f"sewer_first_manholes[{i}].levels[{j}]: уровень "
                            "не может быть ниже лотка"
                        )
                    step = self.sewer_transient_step_seconds
                    if step is not None and step > 0:
                        quotient = point.time_seconds / step
                        if abs(quotient - round(quotient)) > 1e-9:
                            p.append(
                                f"sewer_first_manholes[{i}].levels[{j}]."
                                f"time_seconds должно быть кратно шагу {step:g} с"
                            )
            if not row.source.strip():
                p.append(f"sewer_first_manholes[{i}].source обязателен")
        if self.wastewater_disposal_mode not in (
            "not_set", "centralized", "local", "water_body",
        ):
            p.append(
                "wastewater_disposal_mode должен быть not_set, centralized, "
                "local или water_body"
            )
        if self.wastewater_pump_system not in WASTEWATER_PUMP_SYSTEMS:
            p.append(
                "wastewater_pump_system должен быть пустым, K1 или K3"
            )
        if self.wastewater_pump_mode not in WASTEWATER_PUMP_MODES:
            p.append(
                "wastewater_pump_mode должен быть not_set, "
                "local_fixture_unit или internal_station"
            )
        for name, value in {
            "wastewater_service_life_years": self.wastewater_service_life_years,
            "wastewater_overhaul_period_years": self.wastewater_overhaul_period_years,
            "wastewater_existing_network_outer_diameter_mm": self.wastewater_existing_network_outer_diameter_mm,
            "wastewater_existing_network_wall_thickness_mm": self.wastewater_existing_network_wall_thickness_mm,
            "wastewater_k1_min_hourly_m3h": self.wastewater_k1_min_hourly_m3h,
            "wastewater_k3_max_hourly_m3h": self.wastewater_k3_max_hourly_m3h,
            "wastewater_k3_min_hourly_m3h": self.wastewater_k3_min_hourly_m3h,
            "wastewater_pump_q_m3h": self.wastewater_pump_q_m3h,
            "wastewater_pump_head_m": self.wastewater_pump_head_m,
            "wastewater_pump_power_kw": self.wastewater_pump_power_kw,
            "wastewater_pump_static_head_m": self.wastewater_pump_static_head_m,
            "wastewater_pump_dynamic_loss_m": self.wastewater_pump_dynamic_loss_m,
            "wastewater_pump_receiver_useful_volume_m3": self.wastewater_pump_receiver_useful_volume_m3,
            "wastewater_pump_emergency_volume_m3": self.wastewater_pump_emergency_volume_m3,
            "wastewater_pump_emergency_runtime_min": self.wastewater_pump_emergency_runtime_min,
            "wastewater_treatment_capacity_lps": self.wastewater_treatment_capacity_lps,
            "wastewater_treatment_capacity_m3_day": self.wastewater_treatment_capacity_m3_day,
            "storm_design_m3_day": self.storm_design_m3_day,
            "storm_annual_m3": self.storm_annual_m3,
            "storm_melt_m3h": self.storm_melt_m3h,
            "storm_melt_m3_day": self.storm_melt_m3_day,
            "storm_melt_m3_year": self.storm_melt_m3_year,
            "storm_treatment_volume_m3": self.storm_treatment_volume_m3,
            "storm_storage_volume_m3": self.storm_storage_volume_m3,
        }.items():
            if value is not None and value < 0:
                p.append(f"{name} не может быть отрицательным")
        for name, value in {
            "wastewater_pump_fixture_count": self.wastewater_pump_fixture_count,
            "wastewater_pump_working_units": self.wastewater_pump_working_units,
            "wastewater_pump_reserve_units": self.wastewater_pump_reserve_units,
        }.items():
            if value is not None and value < 0:
                p.append(f"{name} не может быть отрицательным")
        if self.wastewater_pump_curve:
            malformed_curve = any(
                not isinstance(point, (list, tuple)) or len(point) != 2
                for point in self.wastewater_pump_curve
            )
            if malformed_curve:
                p.append(
                    "wastewater_pump_curve должна содержать пары [Q, H]"
                )
            else:
                curve = [
                    (float(point[0]), float(point[1]))
                    for point in self.wastewater_pump_curve
                ]
                if any(q < 0 or h <= 0 for q, h in curve):
                    p.append(
                        "точки wastewater_pump_curve требуют Q >= 0 и H > 0"
                    )
                if any(right[0] <= left[0] for left, right in zip(curve, curve[1:])):
                    p.append(
                        "Q в wastewater_pump_curve должен строго возрастать"
                    )
                if any(right[1] > left[1] for left, right in zip(curve, curve[1:])):
                    p.append(
                        "H в wastewater_pump_curve не должен возрастать"
                    )
        if self.apartments < 0:
            p.append("apartments не может быть отрицательным")
        if self.owner_groups_count < 1:
            p.append("owner_groups_count должно быть не менее 1")
        if self.roof_type not in ROOF_TYPES:
            p.append(f"roof_type '{self.roof_type}' не из {ROOF_TYPES}")
        if min(self.storm_roof_area_m2, self.storm_walls_area_m2) < 0:
            p.append("площади кровли и примыкающих стен не могут быть отрицательными")
        if self.storm_period_years not in (1, 2, 3, 5, 10):
            p.append("storm_period_years должен быть 1, 2, 3, 5 или 10")
        if min(
            self.storm_roof_sections,
            self.storm_funnels_count,
            self.storm_risers_count,
            self.storm_selected_riser_dn_mm,
        ) < 0:
            p.append(
                "число секций, воронок, стояков и DN К2 не может быть "
                "отрицательным"
            )
        if (
            self.storm_sectional_residential_single_funnel
            and self.building_type != "residential"
        ):
            p.append(
                "исключение «одна воронка на секцию» применимо только "
                "к секционному жилому зданию"
            )
        for name, value in (
            ("storm_max_funnel_spacing_m", self.storm_max_funnel_spacing_m),
            (
                "storm_selected_funnel_capacity_lps",
                self.storm_selected_funnel_capacity_lps,
            ),
            ("storm_max_funnel_flow_lps", self.storm_max_funnel_flow_lps),
            ("storm_max_riser_flow_lps", self.storm_max_riser_flow_lps),
        ):
            if value is not None and value <= 0:
                p.append(f"{name} должен быть > 0")
        if self.catering_type not in CATERING_TYPES:
            p.append(f"catering_type '{self.catering_type}' не из {CATERING_TYPES}")
        if min(self.catering_seats, self.catering_conditional_dishes) < 0:
            p.append("число мест и условных блюд не может быть отрицательным")
        for name, value in (
            ("group_showers_answer", self.group_showers_answer),
            ("food_service_answer", self.food_service_answer),
            ("grease_wastewater_answer", self.grease_wastewater_answer),
        ):
            if value not in APPLICABILITY_ANSWERS:
                p.append(f"{name} '{value}' не из {APPLICABILITY_ANSWERS}")
        if self.group_showers_count < 0:
            p.append("group_showers_count не может быть отрицательным")
        if self.group_showers_answer == "yes" and self.group_showers_count <= 0:
            p.append(
                "для групповых душевых задайте число душевых сеток больше нуля"
            )
        if self.food_service_answer == "yes" and self.catering_type == "none":
            p.append("для предприятия питания задайте тип приготовления пищи")
        if self.food_service_answer == "no" and self.catering_type != "none":
            p.append(
                "тип общепита задан, хотя предприятие питания отмечено как отсутствующее"
            )
        if self.grease_wastewater_answer == "yes" and self.food_service_answer == "no":
            p.append(
                "жиросодержащие стоки не могут быть подтверждены при отсутствии общепита"
            )
        if self.grease_trap_location not in GREASE_TRAP_LOCATIONS:
            p.append(
                f"grease_trap_location '{self.grease_trap_location}' не из "
                f"{GREASE_TRAP_LOCATIONS}"
            )
        # Триггер только задаёт вопрос; ответ всегда принимает проектировщик.
        # Локальный импорт сохраняет одно направление зависимости DTO → rules.
        from app.intake.applicability import infer_applicability_scope
        applicability = infer_applicability_scope(
            self.consumers,
            group_showers_answer=self.group_showers_answer,
            food_service_answer=self.food_service_answer,
            catering_type=self.catering_type,
        )
        if applicability.group_showers and self.group_showers_answer == "unknown":
            p.append(
                "подтвердите наличие групповых душевых по технологической анкете"
            )
        if (
            applicability.food_service
            and self.food_service_answer == "unknown"
            and self.catering_type == "none"
        ):
            p.append(
                "подтвердите наличие предприятия питания по технологической анкете"
            )
        if (
            self.food_service_answer == "yes"
            and self.grease_wastewater_answer == "unknown"
        ):
            p.append(
                "подтвердите наличие жиросодержащих производственных стоков"
            )
        if (
            self.grease_wastewater_answer == "yes"
            and self.grease_trap_location == "unknown"
        ):
            p.append(
                "для жиросодержащих стоков выберите место жироуловителя "
                "либо явно укажите уточнение на стадии Р"
            )
        seen_v1 = set()
        for i, s in enumerate(self.v1_sections):
            if not s.section_id or s.section_id in seen_v1:
                p.append(f"v1_sections[{i}]: обозначение пустое или повторяется")
            seen_v1.add(s.section_id)
            if min(s.length_m, s.inner_diameter_mm, s.flow_lps, s.velocity_limit_mps) <= 0:
                p.append(f"v1_sections[{i}]: L, dвн, q и предел скорости должны быть > 0")
            if s.roughness_mm < 0 or (s.local_loss_factor is not None and s.local_loss_factor < 0):
                p.append(f"v1_sections[{i}]: шероховатость и k_l не могут быть отрицательными")
            if s.role not in ("internal", "input"):
                p.append(f"v1_sections[{i}].role должен быть internal или input")
        vn = self.v1_network
        if vn is not None:
            node_ids = [n.node_id for n in vn.nodes]
            if not vn.source_node:
                p.append("v1_network.source_node обязателен")
            if not vn.nodes:
                p.append("v1_network.nodes пуст")
            if not vn.sections:
                p.append("v1_network.sections пуст")
            if len(set(node_ids)) != len(node_ids) or any(not x for x in node_ids):
                p.append("v1_network: обозначения узлов должны быть непустыми и уникальными")
            if vn.source_node and vn.source_node not in node_ids:
                p.append(f"v1_network.source_node '{vn.source_node}' отсутствует в узлах")
            for i, node in enumerate(vn.nodes):
                if node.direct_demand_lps < 0 or node.h_pr_m < 0:
                    p.append(f"v1_network.nodes[{i}]: расход и Hпр не могут быть отрицательными")
                if node.max_static_head_m <= 0:
                    p.append(f"v1_network.nodes[{i}].max_static_head_m должен быть > 0")
                for j, group in enumerate(node.consumers):
                    if not group.code or group.count <= 0:
                        p.append(f"v1_network.nodes[{i}].consumers[{j}]: нужен код и количество > 0")
            section_ids = set()
            for i, section in enumerate(vn.sections):
                if not section.section_id or section.section_id in section_ids:
                    p.append(f"v1_network.sections[{i}]: обозначение пустое или повторяется")
                section_ids.add(section.section_id)
                if section.from_node not in node_ids or section.to_node not in node_ids:
                    p.append(f"v1_network.sections[{i}]: начальный или конечный узел отсутствует")
                if section.from_node == section.to_node:
                    p.append(f"v1_network.sections[{i}]: начало и конец совпадают")
                if min(section.length_m, section.velocity_limit_mps) <= 0:
                    p.append(f"v1_network.sections[{i}]: L и предел скорости должны быть > 0")
                if section.inner_diameter_mm is not None and section.inner_diameter_mm <= 0:
                    p.append(f"v1_network.sections[{i}].inner_diameter_mm должен быть > 0")
                if section.inner_diameter_mm is None:
                    if (not section.candidate_inner_diameters_mm
                            or any(d <= 0 for d in section.candidate_inner_diameters_mm)):
                        p.append(f"v1_network.sections[{i}]: для автоподбора нужен положительный сортамент dвн")
                    if (section.max_specific_loss_m_per_m is None
                            or section.max_specific_loss_m_per_m <= 0):
                        p.append(f"v1_network.sections[{i}]: для автоподбора нужен iдоп > 0")
                if (section.roughness_mm < 0 or
                        (section.local_loss_factor is not None and section.local_loss_factor < 0)):
                    p.append(f"v1_network.sections[{i}]: шероховатость и k_l не могут быть отрицательными")
                if (section.max_specific_loss_m_per_m is not None
                        and section.max_specific_loss_m_per_m <= 0):
                    p.append(f"v1_network.sections[{i}].max_specific_loss_m_per_m должен быть > 0")
                if section.role not in ("internal", "input"):
                    p.append(f"v1_network.sections[{i}].role должен быть internal или input")
            if vn.inlets and any(section.role == "input" for section in vn.sections):
                p.append("v1_network: при явных inlets участки дерева должны иметь role=internal")
            inlet_ids = set()
            for i, inlet in enumerate(vn.inlets):
                if not inlet.inlet_id or inlet.inlet_id in inlet_ids:
                    p.append(f"v1_network.inlets[{i}]: обозначение пустое или повторяется")
                inlet_ids.add(inlet.inlet_id)
                if inlet.inlet_id in section_ids:
                    p.append(f"v1_network.inlets[{i}]: обозначение совпадает с участком сети")
                if min(inlet.guaranteed_head_m, inlet.maximum_head_m,
                       inlet.length_m, inlet.velocity_limit_mps) <= 0:
                    p.append(f"v1_network.inlets[{i}]: напоры, L и предел скорости должны быть > 0")
                if inlet.maximum_head_m < inlet.guaranteed_head_m:
                    p.append(f"v1_network.inlets[{i}]: Hмакс не может быть меньше Hгар")
                if inlet.inner_diameter_mm is not None and inlet.inner_diameter_mm <= 0:
                    p.append(f"v1_network.inlets[{i}].inner_diameter_mm должен быть > 0")
                if inlet.inner_diameter_mm is None:
                    if (not inlet.candidate_inner_diameters_mm
                            or any(d <= 0 for d in inlet.candidate_inner_diameters_mm)):
                        p.append(f"v1_network.inlets[{i}]: для автоподбора нужен положительный сортамент dвн")
                    if (inlet.max_specific_loss_m_per_m is None
                            or inlet.max_specific_loss_m_per_m <= 0):
                        p.append(f"v1_network.inlets[{i}]: для автоподбора нужен iдоп > 0")
                if (inlet.roughness_mm < 0 or
                        (inlet.local_loss_factor is not None and inlet.local_loss_factor < 0)):
                    p.append(f"v1_network.inlets[{i}]: шероховатость и k_l не могут быть отрицательными")
        sd = self.source_data
        if sd is not None:
            if (sd.elev_header_m is None) != (sd.elev_fixture_m is None):
                p.append("source_data: отметки elev_header_m и elev_fixture_m задаются парой")
            if (sd.elev_header_m is not None and sd.elev_fixture_m is not None
                    and sd.elev_fixture_m < sd.elev_header_m):
                p.append("source_data: отметка диктующего прибора ниже отметки ввода")
            if sd.network_kind not in ("domestic", "combined", "fire"):
                p.append("source_data.network_kind должен быть domestic, combined или fire")
            if sd.water_use_period_h <= 0:
                p.append("source_data.water_use_period_h должно быть > 0")
            if sd.inputs_count <= 0:
                p.append("source_data.inputs_count должно быть > 0")
            nonnegative = {
                "h_geom_m": sd.h_geom_m, "il_dict_m": sd.il_dict_m,
                "h_il_m": sd.h_il_m, "h_pr_m": sd.h_pr_m,
                "h_tepl_m": sd.h_tepl_m, "il_vvod_m": sd.il_vvod_m,
                "h_apartment_c_meter_m": sd.h_apartment_c_meter_m,
                "h_apartment_h_meter_m": sd.h_apartment_h_meter_m,
                "h_vvod_m": sd.h_vvod_m, "npsh_available_m": sd.npsh_available_m,
                "guaranteed_head_m": sd.guaranteed_head_m,
                "maximum_head_m": sd.maximum_head_m,
            }
            for name, value in nonnegative.items():
                if value is not None and value < 0:
                    p.append(f"source_data.{name} не может быть отрицательным")
            if (sd.guaranteed_head_m is not None and sd.maximum_head_m is not None
                    and sd.maximum_head_m < sd.guaranteed_head_m):
                p.append("source_data.maximum_head_m не может быть меньше guaranteed_head_m")
        for i, r in enumerate(self.rooms):
            if r.space_kind not in SPACE_KINDS:
                p.append(f"rooms[{i}].space_kind '{r.space_kind}' не из {SPACE_KINDS}")
            if r.placement not in PLACEMENT_MODES:
                p.append(f"rooms[{i}].placement '{r.placement}' не из {PLACEMENT_MODES}")
            if min(r.length_m, r.width_m, r.height_m) <= 0:
                p.append(f"rooms[{i}]: размеры должны быть > 0")
        n = self.network
        if n is not None:
            if n.source_kind not in SOURCE_KINDS:
                p.append(f"network.source_kind '{n.source_kind}' не из {SOURCE_KINDS}")
            if not n.source_node:
                p.append("network.source_node обязателен")
            if not n.runs:
                p.append("network.runs пуст — нет магистрали")
            if not n.risers:
                p.append("network.risers пуст — нет стояков с ПК")
            run_nodes = {x for r in n.runs for x in (r.from_node, r.to_node)}
            if n.source_node and n.source_node not in run_nodes:
                p.append(f"source_node '{n.source_node}' не встречается в участках магистрали")
            for i, r in enumerate(n.risers):
                if r.at_node not in run_nodes:
                    p.append(f"risers[{i}] '{r.name}': узел '{r.at_node}' не в магистрали")
            if n.second_source_node:
                if n.second_source_node not in run_nodes:
                    p.append(f"второй ввод '{n.second_source_node}' не в магистрали")
                if n.second_source_node == n.source_node:
                    p.append("второй ввод совпадает с первым — уберите или переставьте")
                if n.second_available_head_m is None:
                    p.append("для второго ввода нужен его напор (second_available_head_m)")
            # ── связность: вся магистраль достижима от источника (BFS) ──
            if n.source_node in run_nodes and n.runs:
                adj: dict = {}
                for r in n.runs:
                    adj.setdefault(r.from_node, set()).add(r.to_node)
                    adj.setdefault(r.to_node, set()).add(r.from_node)
                seen = {n.source_node}
                stack = [n.source_node]
                while stack:
                    for nb in adj.get(stack.pop(), ()):
                        if nb not in seen:
                            seen.add(nb)
                            stack.append(nb)
                orphans = sorted(run_nodes - seen)
                if orphans:
                    p.append(f"магистраль разорвана: узлы {', '.join(orphans)} не связаны "
                             f"с источником '{n.source_node}' — проверьте участки (runs)")
                for r in n.risers:
                    if r.at_node in run_nodes and r.at_node not in seen:
                        p.append(f"стояк '{r.name}' висит на недостижимом узле "
                                 f"'{r.at_node}' — вода до него не дойдёт")
            # ── дубли ──
            pairs = [frozenset((r.from_node, r.to_node)) for r in n.runs]
            if len(set(pairs)) < len(pairs):
                p.append("в магистрали есть дублирующиеся участки (одна и та же пара узлов)")
            names = [r.name for r in n.risers]
            if len(set(names)) < len(names):
                p.append("имена стояков повторяются — должны быть уникальны")
        return p

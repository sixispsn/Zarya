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
    "dormitory_f12",
)
ROOF_TYPES = ("not_set", "flat", "sloped")
CATERING_TYPES = ("none", "semi_finished", "raw", "school")
SOURCE_KINDS = ("city_main", "reservoir", "pond", "well")
SPACE_KINDS = ("corridor", "room", "hall", "storage")
PLACEMENT_MODES = ("one_side", "two_opposite_sides")
SEWAGE_MATERIALS = ("pvc", "pp", "cast_iron_socket", "sml")
SEWAGE_VENTILATION = ("ventilated", "vacuum_valve", "unventilated")
SEWER_ELEMENT_KINDS = (
    "toilet", "washbasin", "sink", "bath", "shower", "floor_drain",
    "washing_machine", "dishwasher", "grease_trap",
    "roof_funnel", "revision", "cleanout", "fire_collar", "trap",
    "pump", "sump", "ball_valve", "check_valve", "junction", "outlet",
    "tee", "elbow", "transition", "other",
)


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
    fire_category: str = ""                        # строка таблицы 7.1 СП 10
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
    sewage_outlets_count: int = 0
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
                    "для театра/кино/клуба Ф2.1 задайте вместимость зала"
                )
            if (
                self.fire_category == "library_sport"
                and (self.fire_area_m2 or self.total_area_m2) <= 0
            ):
                p.append(
                    "для библиотеки/архива/спортивной части задайте её площадь"
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
        if self.fire_mode == "manual" and self.streams not in (1, 2):
            p.append("для ручного режима В2 задайте streams=1 или 2")
        if self.streams is not None and self.streams not in (1, 2):
            p.append(f"streams={self.streams}: поддерживается 1 или 2")
        if self.nozzle_mm not in (13, 16, 19):
            p.append("nozzle_mm должен быть 13, 16 или 19")
        if self.compact_jet_m not in (6, 8, 10, 12, 14, 16, 18, 20):
            p.append("compact_jet_m должен быть 6, 8, 10, 12, 14, 16, 18 или 20")
        if self.sewage_max_fixture_lps < 0:
            p.append("sewage_max_fixture_lps не может быть отрицательным")
        if self.sewage_outlets_count < 0:
            p.append("sewage_outlets_count не может быть отрицательным")
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
            if not pipe.material.strip() or not pipe.standard.strip():
                p.append(
                    f"sewer_pipes[{i}]: материал и стандарт/ТУ обязательны "
                    "для точной спецификации"
                )
            if pipe.slope_per_mille is not None and pipe.slope_per_mille < 0:
                p.append(f"sewer_pipes[{i}].slope_per_mille не может быть отрицательным")
            if pipe.fill_ratio is not None and not 0 <= pipe.fill_ratio <= 1:
                p.append(f"sewer_pipes[{i}].fill_ratio должен быть от 0 до 1")
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
        if self.wastewater_disposal_mode not in (
            "not_set", "centralized", "local", "water_body",
        ):
            p.append(
                "wastewater_disposal_mode должен быть not_set, centralized, "
                "local или water_body"
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

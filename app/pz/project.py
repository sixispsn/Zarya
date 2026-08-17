"""
Модель данных "Проект" — всё, что нужно для генерации пояснительных записок
ИОС2 (водоснабжение) и ИОС3 (водоотведение) согласно ПП-87, пп. 17–18.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class BuildingPurpose(str, Enum):
    RESIDENTIAL = "residential"
    PUBLIC = "public"
    INDUSTRIAL = "industrial"


class HwsType(str, Enum):
    CENTRAL = "central"
    LOCAL = "local"
    NONE = "none"


class Stage(str, Enum):
    P = "П"
    R = "Р"


@dataclass(frozen=True)
class DigitalPassportInfo:
    """Ссылка на неизменяемый снимок конкретного выпуска документов."""
    passport_id: str
    url: str
    qr_data_uri: str


@dataclass
class DocumentInfo:
    cipher: str = ""
    object_name: str = ""
    object_address: str = ""
    object_part: str = ""          # наименование части/здания ("Конференц зал")
    stage: Stage = Stage.P
    sheet_title: str = "Текстовая часть"
    organization: str = ""
    gip_name: str = ""
    developer_name: str = ""
    inspector_name: str = ""
    dept_head_name: str = ""       # Нач. отдела
    norm_control_name: str = ""
    sheet_no: str = "1"
    sheet_total: str = "—"

    @property
    def stage_label(self) -> str:
        value = getattr(self.stage, "value", self.stage)
        return str(value or "П")


@dataclass
class WaterSource:
    description: str = ""
    water_protection_note: str = ""
    reserve_water_note: str = ""
    connection_point: str = ""
    tu_number: str = ""
    tu_date: str = ""
    guaranteed_head_m: Optional[float] = None
    maximum_head_m: Optional[float] = None
    pressure_note: str = ""
    # --- составляющие требуемого напора Hтр по формуле (14) п.8.27 СП 30.13330.2020 ---
    # Hтр = Hgeom + ∑Hil + Hпр + ∑Hвод + Hтепл + Hlввод
    # Hgeom — авто из отметок: elev_fixture_m − elev_header_m (ось коллектора насоса
    # или ось ввода). Если отметки не заданы — берётся прямое h_geom_m.
    elev_header_m: Optional[float] = None   # отметка оси напорного коллектора насоса / ввода, м
    elev_fixture_m: Optional[float] = None  # отметка излива диктующего прибора, м
    h_geom_m: Optional[float] = None        # Hgeom напрямую (если отметки не заданы)
    # ∑Hil = i·l·(1+kм): il_dict_m — линейные потери i·l по диктующему направлению,
    # kм добавляется автоматически по network_kind. h_il_m — готовая сумма (запасной путь).
    il_dict_m: Optional[float] = None       # линейные i·l внутренней сети, м
    h_il_m: Optional[float] = None          # ∑Hil готовой суммой (если задан — используется как есть)
    network_kind: str = "domestic"          # тип сети для kм: domestic 0,3 / combined 0,2 / fire 0,1
    h_pr_m: float = 20.0                # Hпр — напор перед прибором, п.8.21 (минимум 20 м)
    h_vod_m: Optional[float] = None     # ∑Hвод — потери в узлах учёта (12.15); обычно из расчёта счётчика
    h_tepl_m: float = 0.0               # Hтепл — потери в теплообменнике/ИТП (3 м если ТО наш; 0 если ГВС готовое)
    h_apartment_c_meter_m: Optional[float] = None  # потери квартирного ВУ ХВС по принятому счётчику
    h_apartment_h_meter_m: Optional[float] = None  # потери квартирного ВУ ГВС по принятому счётчику
    hws_heater_in_scope: bool = False    # ГВС готовится в проектируемом ИТП/водонагревателе
    # Hlввод = i·Lввод·1,1: il_vvod_m — линейные i·l ввода, ×1,1 (стадия П). h_vvod_m — готовой суммой.
    il_vvod_m: Optional[float] = None       # линейные i·l ввода, м
    h_vvod_m: Optional[float] = None        # Hlввод готовой суммой (если задан — используется как есть)
    water_use_period_h: float = 24.0        # период водопотребления для подбора счётчика
    inputs_count: int = 1                   # количество вводов
    npsh_available_m: Optional[float] = None  # располагаемый кавитационный запас насоса
    # --- лимиты присоединения по ТУ (дебит), для проверки соответствия ---
    tu_limit_q_day: Optional[float] = None      # лимит суточного расхода ХВС, м³/сут
    tu_limit_q_sec: Optional[float] = None      # лимит секундного расхода ХВС, л/с
    tu_fire_outdoor_l_s: Optional[float] = None # наружное пожаротушение по ТУ, л/с


@dataclass
class PipeMaterials:
    cold_mains: str = "сталь ВГП обыкновенная по ГОСТ 3262-75"
    cold_distribution: str = "сшитый полиэтилен PE-X"
    hot_mains: str = "сталь ВГП обыкновенная по ГОСТ 3262-75"
    hot_distribution: str = "сшитый полиэтилен PE-X"
    fire_pipes: str = "сталь ВГП обыкновенная по ГОСТ 3262-75"
    # Хоз-питьевая сеть выполнена из пластиковых труб без пожарного сертификата
    # -> при наличии ВПВ магистрали/стояки пожаротушения обязаны быть раздельными
    #    из металла (СП 30.13330.2020, п. 7.1.3)
    cold_is_plastic_uncertified: bool = False


@dataclass
class FlowsData:
    q_day_tot: float = 0.0
    q_day_c: float = 0.0
    q_day_h: float = 0.0
    q_sec_tot: float = 0.0
    q_sec_c: float = 0.0
    q_sec_h: float = 0.0
    q_hr_tot: float = 0.0
    q_hr_c: float = 0.0
    q_hr_h: float = 0.0
    sewage_l_per_s: float = 0.0
    sewage_q0s_l_per_s: float = 1.6
    heat_max_kw: float = 0.0
    irrigation_m3_day: float = 0.0
    q_year_m3: float = 0.0


# ── БАЛАНС ВОДОПОТРЕБЛЕНИЯ/ВОДООТВЕДЕНИЯ (форма 2, прил. А ГОСТ Р 21.619-2023) ──

@dataclass
class ConsumerRow:
    """Строка формы 2 приложения А ГОСТ Р 21.619-2023."""
    name: str = ""
    process: str = "Хозяйственно-питьевые нужды"
    regime_h: Optional[float] = None
    quantity_display: str = ""
    norm_basis: str = "СП 30.13330.2020, таблица А.2"
    norm_m3_per_unit_day: float = 0.0
    water_quality: str = "питьевая"
    total_m3_day: float = 0.0
    source_city_m3_day: float = 0.0
    source_artesian_m3_day: float = 0.0
    source_technical_m3_day: float = 0.0
    source_reused_m3_day: float = 0.0
    losses_m3_day: float = 0.0
    sewage_domestic_m3_day: float = 0.0
    sewage_clean_m3_day: float = 0.0
    sewage_mechanical_m3_day: float = 0.0
    sewage_chemical_m3_day: float = 0.0
    storm_m3_day: float = 0.0


@dataclass
class BalanceData:
    """Баланс формы 2 для объекта непроизводственного назначения."""
    rows: list = field(default_factory=list)   # list[ConsumerRow]
    note: str = ""                              # сноска под таблицей


@dataclass
class FireSystem:
    required: bool = False
    determination_mode: str = "auto"
    normative_note: str = ""
    streams: int = 0                          # число струй
    q_per_stream: float = 0.0                 # расход струи, л/с
    q_total: float = 0.0                      # Q_пож, л/с
    pressure_mpa: Optional[float] = None      # давление у диктующего ПК
    # --- данные для выбора схемы В2 (объединённая/раздельная) ---
    pressure_at_lowest_pk_mpa: Optional[float] = None  # гидростат. давление у нижнего ПК, МПа
    has_aupt: bool = False                    # есть АУПТ (спринклер и т.п.)
    fire_duration_min: int = 60               # продолжительность пожаротушения, мин
    hose_length_m: int = 20                   # длина рукава ПК, м
    nozzle_dn: int = 50                       # Ду пожарного крана
    pk_total: int = 0                         # всего пожарных шкафов/кранов
    # Схема В1/В2 задаётся явно проектировщиком или определяется нормами.
    # auto / combined / separate / pre_meter_branch.
    network_topology: str = "auto"
    topology_basis: str = ""                 # ссылка на ТУ/СКС/задание либо принятое решение
    branch_electric_valves: bool = False      # электроприводы на отводах В2 по ТУ/СКС
    # --- результаты гидравлического расчёта В2 (из fire_hydraulics) ---
    required_head_m: Optional[float] = None   # требуемый напор на вводе В2, м
    available_head_m: Optional[float] = None  # доступный напор источника, м
    needs_pump: Optional[bool] = None         # нужна ли повысительная насосная В2
    dictating_cabinet_id: Optional[str] = None  # диктующий ПК (или диктующая пара)


# ============================================================
# СПЕЦИФИКАЦИИ ГЕОМЕТРИИ ВПВ (автопостроение layout/network)
# ============================================================
# Высокоуровневое инженерное описание: проектировщик задаёт помещения, стояки
# и магистраль в СВОИХ терминах; geometry_builder разворачивает это в
# (ctx, room) для layout и FireNetwork для гидравлики. Спеки — только данные,
# никакой расчётной логики.

@dataclass
class FireRoomSpec:
    """Помещение для расстановки ПК (разворачивается в ctx + RectangularRoom).

    space_kind: "corridor" / "room" / "hall" / "storage" (FireSpaceKind).
    placement_mode: "one_side" / "two_opposite_sides".
    """
    room_id: str
    length_m: float
    width_m: float
    height_m: float
    space_kind: str = "corridor"
    placement_mode: str = "two_opposite_sides"


@dataclass
class MainNodeSpec:
    """Узел магистрали В2 (кольца или тупиковой)."""
    node_id: str
    elevation_m: float = 0.0


@dataclass
class MainSegmentSpec:
    """Участок магистрали между узлами."""
    segment_id: str
    from_node: str
    to_node: str
    length_m: float
    A: float                      # удельное сопротивление (h = A·L_eff·Q²)
    dn: int = 100
    equiv_length_m: float = 0.0
    repair_section_id: str = ""       # секция между запорными устройствами СП 10


@dataclass
class RiserSpec:
    """Стояк В2: тупиковая ветвь от узла магистрали до ПК наверху.

    Разворачивается в участок(и) + FireCabinetNode. jet_m — высота компактной
    части струи для табл. 7.3 (обычно = нормативный Rk).
    """
    riser_id: str
    attach_node: str              # узел магистрали
    length_m: float               # длина стояка (обычно = высота подъёма)
    cabinet_elevation_m: float    # отметка ПК
    A: float = 0.011
    dn: int = 50
    equiv_length_m: float = 0.0
    cabinet_id: str = ""          # пусто → riser_id + "-PK"
    jet_m: int = 6
    repair_section_id: str = ""   # ремонтная секция кольца по СП 10


@dataclass
class FireNetworkSpec:
    """Сеть В2 целиком: магистраль (кольцевая или тупиковая — топологию граф
    покажет сам) + стояки + источник."""
    nodes: List[MainNodeSpec] = field(default_factory=list)
    segments: List[MainSegmentSpec] = field(default_factory=list)
    risers: List[RiserSpec] = field(default_factory=list)
    source_node: str = ""
    source_kind: str = "city_main"          # city_main/reservoir/pond/well
    available_head_m: Optional[float] = None
    second_source_node: str = ""            # второй ввод (MultiSource)
    second_available_head_m: Optional[float] = None
    water_level_m: Optional[float] = None
    suction_head_loss_m: float = 0.0


# ── СЧЁТЧИКИ (детальный подбор, таблица 5.1.13 ГОСТ 21.619-2023) ──

@dataclass
class MeterRow:
    """Один водомерный узел (результат checkMeter). Проверки а)/б)/в) по
    табл. 12.1 и пп. 12.x СП 30.13330.2020."""
    label: str = ""            # «Счётчик ХВС», «Счётчик на вводе (общий)» …
    dn: int = 0                # Ду, мм
    type_label: str = ""       # «крыльчатый» / «турбинный»
    s_resist: float = 0.0      # S, м/(л/с)²
    qexpl: float = 0.0         # эксплуатационный расход, м³/ч
    q_meter_min: float = 0.0   # минимальный расход счётчика, м³/ч
    qmax: float = 0.0          # максимальный расход счётчика, м³/ч
    qmin: float = 0.0          # порог чувствительности qthr, м³/ч
    # проверка а): потери при расчётном секундном расходе
    h_a: float = 0.0
    lim_a: float = 0.0         # предел (крыльч. 5 / турб. 2,5 м)
    ok_a: bool = True
    # проверка б): потери при q + Q_пож (None — пожара нет)
    h_b: Optional[float] = None
    lim_b: float = 0.0         # предел (крыльч. 10 / турб. 5 м)
    ok_b: bool = True
    need_bypass: bool = False  # требуется обводная с электрозадвижкой
    # проверка в): измерение малых расходов
    q_hr: float = 0.0          # часовой расход для сравнения
    ok_v: bool = True
    need_combo: bool = False   # рекомендован комбинированный счётчик


@dataclass
class MetersSystem:
    hws_type_meters: str = ""
    cold_meter_dn: Optional[int] = None
    hot_meter_dn: Optional[int] = None
    has_bypass: bool = False
    notes: str = ""
    # --- жилые дома ---
    has_apartment_meters: bool = False   # поквартирные счётчики
    has_askue: bool = False              # импульсный выход / АСКУЭ
    owner_groups_count: int = 1          # группы помещений разных собственников
    # --- детальный подбор (таблица 5.1.13) ---
    rows: list = field(default_factory=list)   # list[MeterRow]
    single_input_bypass_note: bool = False     # примечание про обводную при 1 вводе
    inputs_count: int = 1                      # число одинаковых вводных ВУ
    fire_flow_through_meter: bool = False      # пожарный расход проходит через ВУ В1


# ── НАСОС (детальный подбор, таблица 5.1.8 + данные графика Q-H) ──

@dataclass
class PumpCandidate:
    """Один кандидат из подбора (renderTop3). top3[0] — принятый."""
    model: str = ""
    brand: str = ""
    type_label: str = ""        # «хозяйственно-питьевой» / «пожарный»
    note: str = ""              # схема: «1 раб. + 1 рез., DN32»
    wp_q: float = 0.0           # рабочая точка Q, м³/ч
    wp_h: float = 0.0           # рабочая точка H, м
    p2_kw: float = 0.0          # потребляемая мощность в раб. точке, кВт
    motor_min_kw: float = 0.0   # мин. мощность двигателя (запас 15%), кВт
    p_max_bar: float = 0.0
    npshr: Optional[float] = None
    score: float = 0.0
    reasons: list = field(default_factory=list)  # list[str] — обоснование
    archived: bool = False        # архивная каталожная кривая, требует подтверждения
    source_url: str = ""
    source_note: str = ""


@dataclass
class PumpComplianceCheck:
    """Строка нормативной проверки пожарной насосной установки."""
    clause: str = ""
    requirement: str = ""
    decision: str = ""
    status: str = "specified"    # verified / specified / pending / fail


@dataclass
class PumpSystem:
    required: bool = False
    purpose: str = ""
    # итоговые (как было) — дублируют принятый top3[0]
    model: str = ""
    q_m3h: float = 0.0
    head_m: float = 0.0
    power_kw: float = 0.0
    count_note: str = ""
    q_design_m3h: float = 0.0                    # расчётная точка системы, Q
    h_design_m: float = 0.0                      # расчётная точка системы, H насоса
    # --- детальный подбор (таблица 5.1.8) ---
    top3: list = field(default_factory=list)    # list[PumpCandidate]
    # --- данные графика Q-H принятого насоса (для pump_chart.render_*) ---
    curve: list = field(default_factory=list)   # list[(q, h)] эффективная кривая
    h_stat: float = 0.0                          # статич. напор системы, м
    k_sys: float = 0.0                           # коэф. кривой системы
    wp_q: float = 0.0                            # рабочая точка Q, м³/ч
    wp_h: float = 0.0                            # рабочая точка H, м
    q_opt: float = 0.0                           # BEP насоса, м³/ч
    selection_note: str = ""                    # статус/границы каталожного подбора
    working_units: int = 0
    reserve_units: int = 0
    pump_head_at_design_m: Optional[float] = None
    maximum_system_pressure_bar: Optional[float] = None
    sp10_compliant: Optional[bool] = None
    sp10_checks: list = field(default_factory=list)  # list[PumpComplianceCheck]
    frequency_drive_required: bool = False
    dispatch_required: bool = False


@dataclass
class BuiltInUnit:
    """Встроенное помещение (для жилого дома со встройкой)."""
    name: str = ""               # назначение (супермаркет, аптека, офис)
    area_m2: float = 0.0         # площадь, м²
    consumer_code: str = ""      # код в CONSUMER_NORMS
    persons: int = 0             # расчётное число потребителей


@dataclass
class BuildingFlags:
    purpose: BuildingPurpose = BuildingPurpose.PUBLIC
    floors_above: int = 1
    floors_below: int = 0
    height_m: float = 0.0
    fire_height_m: Optional[float] = None
    total_area_m2: float = 0.0   # общая площадь здания, м² (для удельного расчёта труб, Метод 2)
    has_parking: bool = False
    has_built_in: bool = False
    fire_class: str = ""
    hws_type: HwsType = HwsType.CENTRAL
    seats: int = 0
    # --- жилые дома ---
    apartments: int = 0          # число квартир
    residents: int = 0           # расчётное число жителей
    zones: int = 1               # число зон водоснабжения (1 / 2)
    zone_split_note: str = ""    # описание границы зон (напр. "1 зона 1-5 эт., 2 зона 6-10 эт.")
    built_in_units: list = field(default_factory=list)  # список BuiltInUnit
    separate_k1: bool = False    # раздельные выпуски К1 жильё/встройка
    # --- число стояков по системам (для воздухоотводчиков в спецификации) ---
    risers_v1: int = 0           # стояки ХВС (В1)
    risers_t3: int = 0           # стояки ГВС подающие (Т3)
    risers_t4: int = 0           # стояки ГВС циркуляционные (Т4)
    # --- условия эксплуатации (дефолты — нормальные; негатив поднимается из ТЗ) ---
    seismicity: int = 0          # балльность; ≥7 → мероприятия по СП 30 р.15.2/22.3
    permafrost: bool = False     # вечномёрзлые грунты
    unheated_zones: bool = False # есть неотапливаемые зоны прокладки труб
    high_humidity: bool = False  # влажные помещения (усиленная защита от конденсата)
    noise_protection: bool = True  # нужна защита от шума (вибро у насоса; СП 30)
    fire_barriers: bool = True   # пересечение противопожарных преград (муфты на пластике)

    @property
    def seismic(self) -> bool:
        return (self.seismicity or 0) >= 7


# Справочник приборов от АР: имя -> (есть ХВС, есть ГВС, Ду запорного крана)
FIXTURE_CATALOG = {
    "Унитаз":                       (True,  False, 15),
    "Писсуар":                      (True,  False, 15),
    "Биде":                         (True,  True,  15),
    "Умывальник":                   (True,  True,  15),
    "Ванна":                        (True,  True,  15),
    "Душевой поддон":               (True,  True,  15),
    "Душевая кабина":               (True,  True,  15),
    "Мойка кухонная":               (True,  True,  15),
    "Раковина хозяйственная (видуар)": (True, True, 15),
    "Мойка медицинская":            (True,  True,  15),
    "Питьевой фонтанчик":           (True,  False, 15),
    "Ножная ванна":                 (True,  True,  15),
    "Душевая сетка (производств.)": (True,  True,  15),
}


@dataclass
class FixtureGroup:
    """Группа однотипных приборов из задания АР (для арматуры спецификации).
    На расход не влияет (расход считается по потребителям). has_cold/has_hot/
    valve_dn = None -> берутся из FIXTURE_CATALOG по name."""
    name: str
    count: int
    has_cold: Optional[bool] = None
    has_hot: Optional[bool] = None
    valve_dn: Optional[int] = None

    def resolved(self):
        c, h, dn = FIXTURE_CATALOG.get(self.name, (True, False, 15))
        return (
            c if self.has_cold is None else self.has_cold,
            h if self.has_hot is None else self.has_hot,
            dn if self.valve_dn is None else self.valve_dn,
        )


@dataclass
class V1SectionSpec:
    section_id: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    roughness_mm: float
    role: str = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""


@dataclass
class V1NodeSpec:
    node_id: str
    elevation_m: float
    consumer_groups: List[tuple] = field(default_factory=list)
    direct_demand_lps: float = 0.0
    h_pr_m: float = 20.0
    max_static_head_m: float = 45.0


@dataclass
class V1NetworkSectionSpec:
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
class V1InletSpec:
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
class V1NetworkSpec:
    source_node: str
    nodes: List[V1NodeSpec] = field(default_factory=list)
    sections: List[V1NetworkSectionSpec] = field(default_factory=list)
    inlets: List[V1InletSpec] = field(default_factory=list)


@dataclass
class InsulationDesign:
    """Исходные данные расчёта изоляции, перенесённого из legacy SP calculator."""
    location: str = "room_hot"
    t_room_manual: float = 5.0
    humidity: int = 60
    hvs_water_temp: float = 10.0
    gvs_water_temp: float = 60.0


@dataclass
class NormativeRequirements:
    """Нормативный профиль объекта, не подменяющий расчётное ядро."""
    sp54_applicable: bool = False
    sp118_applicable: bool = False
    sp253_applicable: bool = False
    mixed_use: bool = False
    separate_v1_v2_required: bool = False
    apartment_hose_tap_required: bool = False
    hvs_min_insulation_mm: int = 0
    gvs_min_insulation_mm: int = 0
    frequency_drive_required: bool = False
    pump_full_reserve_required: bool = False
    pump_dispatch_required: bool = False
    separate_k1_required: bool = False
    separate_owner_metering_required: bool = False
    references: List[str] = field(default_factory=list)


@dataclass
class SewageRiserSpec:
    riser_id: str = ""
    design_flow_lps: float = 0.0
    material: str = "pp"
    ventilation: str = "ventilated"
    riser_dn_mm: int = 110
    branch_dn_mm: int = 110
    branch_angle_deg: float = 87.5
    has_toilet: bool = True
    working_height_m: Optional[float] = None


@dataclass
class SewerPipeSpec:
    system: str = "K1"
    section_id: str = ""
    purpose: str = ""
    material: str = ""
    standard: str = ""
    outer_diameter_mm: float = 0.0
    wall_thickness_mm: float = 0.0
    length_m: float = 0.0
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
class SewerElementSpec:
    """Подтверждённый элемент систем К1/К2/К3 для схемы и спецификации."""
    element_id: str = ""
    system: str = "K1"
    kind: str = "other"
    name: str = ""
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
class SewageDesign:
    """К1: расчёт системы и явно подтверждённые данные стадии П."""
    risers: List[SewageRiserSpec] = field(default_factory=list)
    pipes: List[SewerPipeSpec] = field(default_factory=list)
    elements: List[SewerElementSpec] = field(default_factory=list)
    outlets_count: int = 0
    result: Optional[object] = None
    hydraulic_assessment: Optional[object] = None
    # Исходные данные и границы проектирования по ГОСТ Р 21.620-2023, 5.1.2.
    design_assignment_ref: str = ""
    survey_ref: str = ""
    service_life_years: Optional[int] = None
    overhaul_period_years: Optional[int] = None
    disposal_mode: str = "not_set"  # not_set / centralized / local / water_body
    connection_tu_org: str = ""
    connection_tu_number: str = ""
    connection_tu_date: str = ""
    discharge_standard_ref: str = ""
    water_body_characteristics_note: str = ""
    existing_network_type: str = ""
    existing_network_material: str = ""
    existing_network_standard: str = ""
    existing_network_outer_diameter_mm: Optional[float] = None
    existing_network_wall_thickness_mm: Optional[float] = None
    discharge_point_k1: str = ""
    discharge_point_k2: str = ""
    discharge_point_k3: str = ""
    k1_min_hourly_m3h: Optional[float] = None
    k3_max_hourly_m3h: Optional[float] = None
    k3_min_hourly_m3h: Optional[float] = None
    quality_indicators_note: str = ""
    laying_method: str = ""
    fire_barrier_note: str = ""
    deformation_joint_note: str = ""
    waste_handling_note: str = ""
    # Наружные сети входят в подраздел только при явном включении в границы.
    external_network_in_scope: bool = False
    external_network_design_note: str = ""
    external_scheme_source: str = ""
    site_plan_source: str = ""
    # Условно применимые требования 5.1.4.2-5.1.4.3.
    pump_required: bool = False
    pump_location: str = ""
    pump_model: str = ""
    pump_q_m3h: Optional[float] = None
    pump_head_m: Optional[float] = None
    pump_power_kw: Optional[float] = None
    pump_reserve_note: str = ""
    pump_power_category: str = ""
    pump_automation_note: str = ""
    treatment_required: bool = False
    treatment_location: str = ""
    treatment_type: str = ""
    treatment_capacity_lps: Optional[float] = None
    treatment_capacity_m3_day: Optional[float] = None
    treatment_technology: str = ""


@dataclass
class StormDesign:
    """Проектное решение и расчёт К2 на стадии П."""
    roof_type: str = "not_set"  # not_set / flat / sloped
    system_kind: str = "not_determined"
    system_note: str = ""
    city_code: str = ""
    roof_area_m2: float = 0.0
    walls_area_m2: float = 0.0
    period_years: int = 1
    roof_sections: int = 0
    funnels_count: int = 0
    sectional_residential_single_funnel: bool = False
    max_funnel_spacing_m: Optional[float] = None
    selected_funnel_capacity_lps: Optional[float] = None
    max_funnel_flow_lps: Optional[float] = None
    risers_count: int = 0
    selected_riser_dn_mm: int = 0
    max_riser_flow_lps: Optional[float] = None
    funnels_on_different_levels: bool = False
    design_m3_day: Optional[float] = None
    annual_m3: Optional[float] = None
    melt_m3h: Optional[float] = None
    melt_m3_day: Optional[float] = None
    melt_m3_year: Optional[float] = None
    treatment_volume_m3: Optional[float] = None
    storage_volume_m3: Optional[float] = None
    result: Optional[object] = None
    network_assessment: Optional[object] = None


@dataclass
class GreaseTrapDesign:
    """Проверка необходимости жироуловителей по СП 118, п. 8.7."""
    preparation_type: str = "none"
    seats: int = 0
    conditional_dishes: int = 0
    school_by_assignment: bool = False
    required: bool = False
    decision_note: str = ""


@dataclass
class Project:
    document: DocumentInfo = field(default_factory=DocumentInfo)
    building: BuildingFlags = field(default_factory=BuildingFlags)
    source: WaterSource = field(default_factory=WaterSource)
    materials: PipeMaterials = field(default_factory=PipeMaterials)
    insulation: InsulationDesign = field(default_factory=InsulationDesign)
    normative: NormativeRequirements = field(default_factory=NormativeRequirements)
    sewage: SewageDesign = field(default_factory=SewageDesign)
    storm: StormDesign = field(default_factory=StormDesign)
    grease_trap: GreaseTrapDesign = field(default_factory=GreaseTrapDesign)
    flows: FlowsData = field(default_factory=FlowsData)
    fire: FireSystem = field(default_factory=FireSystem)
    meters: MetersSystem = field(default_factory=MetersSystem)
    pumps: PumpSystem = field(default_factory=PumpSystem)
    fire_pumps: PumpSystem = field(default_factory=PumpSystem)
    balance: BalanceData = field(default_factory=BalanceData)
    fixtures: list = field(default_factory=list)  # список FixtureGroup (от АР)
    # --- спецификации геометрии ВПВ (для автопостроения layout/network) ---
    fire_rooms: List["FireRoomSpec"] = field(default_factory=list)
    consumer_groups: List[tuple] = field(default_factory=list)  # [(код, кол-во)] расходы В1
    consumer_details: list = field(default_factory=list)  # [(название части, код, количество)]
    v1_sections: List[V1SectionSpec] = field(default_factory=list)
    v1_network: Optional[V1NetworkSpec] = None
    v1_hydraulic_result: Optional[object] = None
    v1_stage_p_result: Optional[object] = None
    water_inlet_decision: Optional[object] = None
    head_paths: Optional[object] = None
    sewage_max_fixture_lps: float = 1.6  # q_0s по фактическому диктующему прибору
    storm_city: str = ""        # город для дождя (К2)
    fire_network: Optional["FireNetworkSpec"] = None
    digital_passport: Optional[DigitalPassportInfo] = None

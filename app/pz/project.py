"""
Модель данных "Проект" — всё, что нужно для генерации пояснительной записки
по разделу ИОС2 (водоснабжение) согласно ПП-87 §17.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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


@dataclass
class DocumentInfo:
    cipher: str = ""
    object_name: str = ""
    object_address: str = ""
    stage: Stage = Stage.P
    sheet_title: str = "Текстовая часть"
    organization: str = ""
    gip_name: str = ""
    developer_name: str = ""
    inspector_name: str = ""
    norm_control_name: str = ""


@dataclass
class WaterSource:
    description: str = ""
    connection_point: str = ""
    tu_number: str = ""
    tu_date: str = ""
    guaranteed_head_m: Optional[float] = None
    pressure_note: str = ""
    # --- составляющие требуемого напора Hтр по формуле (14) п.8.27 СП 30.13330.2020 ---
    # Hтр = Hgeom + ∑Hil + Hпр + ∑Hвод + Hтепл + Hlввод
    h_geom_m: Optional[float] = None    # Hgeom — геом. высота диктующего прибора над точкой подключения
    h_il_m: Optional[float] = None      # ∑Hil — потери на всех участках диктующего направления
    h_pr_m: float = 20.0                # Hпр — напор перед прибором, п.8.21 (минимум 20 м)
    h_vod_m: Optional[float] = None     # ∑Hвод — потери в узлах учёта (12.15)
    h_tepl_m: float = 0.0               # Hтепл — потери в теплообменнике/ИТП (≈3 м при централ. ГВС)
    h_vvod_m: Optional[float] = None    # Hlввод — потери на вводе/вводах
    # --- лимиты присоединения по ТУ (дебит), для проверки соответствия ---
    tu_limit_q_day: Optional[float] = None      # лимит суточного расхода ХВС, м³/сут
    tu_limit_q_sec: Optional[float] = None      # лимит секундного расхода ХВС, л/с
    tu_fire_outdoor_l_s: Optional[float] = None # наружное пожаротушение по ТУ, л/с


@dataclass
class PipeMaterials:
    cold_mains: str = "сталь по ГОСТ 3262-75"
    cold_distribution: str = "сшитый полиэтилен PE-X"
    hot_mains: str = "сталь по ГОСТ 3262-75"
    hot_distribution: str = "сшитый полиэтилен PE-X"
    fire_pipes: str = "сталь по ГОСТ 3262-75"
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
    heat_max_kw: float = 0.0
    irrigation_m3_day: float = 0.0
    q_year_m3: float = 0.0


@dataclass
class FireSystem:
    required: bool = False
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


@dataclass
class PumpSystem:
    required: bool = False
    purpose: str = ""
    model: str = ""
    q_m3h: float = 0.0
    head_m: float = 0.0
    power_kw: float = 0.0
    count_note: str = ""


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


@dataclass
class Project:
    document: DocumentInfo = field(default_factory=DocumentInfo)
    building: BuildingFlags = field(default_factory=BuildingFlags)
    source: WaterSource = field(default_factory=WaterSource)
    materials: PipeMaterials = field(default_factory=PipeMaterials)
    flows: FlowsData = field(default_factory=FlowsData)
    fire: FireSystem = field(default_factory=FireSystem)
    meters: MetersSystem = field(default_factory=MetersSystem)
    pumps: PumpSystem = field(default_factory=PumpSystem)

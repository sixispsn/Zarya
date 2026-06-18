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


# ── БАЛАНС ВОДОПОТРЕБЛЕНИЯ/ВОДООТВЕДЕНИЯ (форма 2, прил. А ГОСТ Р 21.619-2023) ──

@dataclass
class ConsumerRow:
    """Одна строка баланса. Объёмы — в м³; q_*_year = q_*_day · days_year,
    но держим явными, чтобы мост мог положить точные значения из ядра."""
    name: str = ""              # наименование потребителя
    count: float = 0.0          # расчётное число потребителей
    count_unit: str = ""        # ед. изм.: «мест», «чел.», «м²», «кг сух. белья»
    norm_display: str = ""      # норма расхода, напр. «8,1 л/место·сут»
    nd_ref: str = ""            # норм. документ: «СП 30.13330.2020, табл. А.2»
    regime_h: float = 0.0       # режим работы, ч/сут
    days_year: int = 0          # число суток работы в году
    q_cold_day: float = 0.0     # ХВС, м³/сут
    q_cold_year: float = 0.0    # ХВС, м³/год
    q_hot_day: float = 0.0      # ГВС, м³/сут
    q_hot_year: float = 0.0     # ГВС, м³/год
    q_sew_day: float = 0.0      # водоотведение, м³/сут
    q_sew_year: float = 0.0     # водоотведение, м³/год


@dataclass
class BalanceData:
    """Баланс целиком. Итоги считаются в шаблоне (sum по строкам)."""
    rows: list = field(default_factory=list)   # list[ConsumerRow]
    note: str = ""                              # сноска под таблицей


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
    # --- детальный подбор (таблица 5.1.13) ---
    rows: list = field(default_factory=list)   # list[MeterRow]
    single_input_bypass_note: bool = False     # примечание про обводную при 1 вводе


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
    npshr: float = 0.0
    score: float = 0.0
    reasons: list = field(default_factory=list)  # list[str] — обоснование


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
    # --- детальный подбор (таблица 5.1.8) ---
    top3: list = field(default_factory=list)    # list[PumpCandidate]
    # --- данные графика Q-H принятого насоса (для pump_chart.render_*) ---
    curve: list = field(default_factory=list)   # list[(q, h)] эффективная кривая
    h_stat: float = 0.0                          # статич. напор системы, м
    k_sys: float = 0.0                           # коэф. кривой системы
    wp_q: float = 0.0                            # рабочая точка Q, м³/ч
    wp_h: float = 0.0                            # рабочая точка H, м
    q_opt: float = 0.0                           # BEP насоса, м³/ч


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
    balance: BalanceData = field(default_factory=BalanceData)

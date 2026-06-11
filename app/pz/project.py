"""
Модель данных "Проект" — всё, что нужно для генерации пояснительной записки
по разделу ИОС2 (водоснабжение) согласно ПП-87 §17.

Поля сгруппированы:
  - реквизиты документа (для штампа и титула)
  - характеристики объекта (тип, этажность, флаги)
  - источники подключения (из ТУ)
  - материалы трубопроводов
  - расходы (из расчётного ядра)
  - параметры систем (ВПВ, ГВС, насосы, счётчики)

На MVP заполняется вручную. Позже часть полей будет приходить из парсера ТЗ/ТУ
и напрямую из калькулятора.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class BuildingPurpose(str, Enum):
    """Тип объекта (определяет набор шаблонов подпунктов)."""
    RESIDENTIAL = "residential"          # жилой
    PUBLIC = "public"                    # общественный непроизводственный
    INDUSTRIAL = "industrial"            # производственный


class HwsType(str, Enum):
    """Тип горячего водоснабжения."""
    CENTRAL = "central"                  # централизованное (от теплосети/ИТП)
    LOCAL = "local"                      # местное (электро/газовый нагрев)
    NONE = "none"                        # ГВС отсутствует


class Stage(str, Enum):
    """Стадия проектирования."""
    P = "П"                              # проектная документация
    R = "Р"                              # рабочая документация


@dataclass
class DocumentInfo:
    """Реквизиты документа — для штампа (основной надписи) и титула."""
    cipher: str = ""                     # шифр проекта (вводится вручную), напр. "3010-713-2025-ИОС2"
    object_name: str = ""                # наименование объекта
    object_address: str = ""             # адрес объекта
    stage: Stage = Stage.P               # стадия П / Р
    # Поля организации — пока пустые (заполнятся позже автоматически)
    organization: str = ""               # наименование проектной организации
    gip_name: str = ""                   # ФИО ГИП
    developer_name: str = ""             # ФИО разработчика
    inspector_name: str = ""             # ФИО проверившего
    norm_control_name: str = ""          # ФИО нормоконтроля
    # Нумерация листов проставляется автоматически при сборке


@dataclass
class WaterSource:
    """Источник водоснабжения (из ТУ)."""
    description: str = ""                # откуда подключение (напр. "от городской сети")
    connection_point: str = ""           # точка подключения (напр. "корпус А, подвал")
    tu_number: str = ""                  # № технических условий
    tu_date: str = ""                    # дата ТУ
    guaranteed_head_m: Optional[float] = None  # гарантированный напор, м вод. ст.
    pressure_note: str = ""              # доп. сведения о давлении


@dataclass
class PipeMaterials:
    """Материалы трубопроводов (из ТЗ/ТУ)."""
    cold_mains: str = "сталь по ГОСТ 3262-75"          # магистрали ХВС
    cold_distribution: str = "сшитый полиэтилен PE-X"  # разводка ХВС
    hot_mains: str = "сталь по ГОСТ 3262-75"           # магистрали ГВС
    hot_distribution: str = "сшитый полиэтилен PE-X"   # разводка ГВС
    fire_pipes: str = "сталь по ГОСТ 3262-75"          # противопожарный водопровод


@dataclass
class FlowsData:
    """Расходы воды — из расчётного ядра (блок водопотребления)."""
    # Суточные, м³/сут
    q_day_tot: float = 0.0
    q_day_c: float = 0.0
    q_day_h: float = 0.0
    # Секундные, л/с
    q_sec_tot: float = 0.0
    q_sec_c: float = 0.0
    q_sec_h: float = 0.0
    # Часовые, м³/ч
    q_hr_tot: float = 0.0
    q_hr_c: float = 0.0
    q_hr_h: float = 0.0
    # Стоки и тепло
    sewage_l_per_s: float = 0.0
    heat_max_kw: float = 0.0
    # Полив (если есть)
    irrigation_m3_day: float = 0.0
    # Годовой расход (для подпунктов т4/т5)
    q_year_m3: float = 0.0


@dataclass
class FireSystem:
    """Параметры внутреннего пожаротушения (ВПВ)."""
    required: bool = False               # требуется ли ВПВ
    streams: int = 0                     # число струй
    q_per_stream: float = 0.0            # расход струи, л/с
    q_total: float = 0.0                 # Q_пож, л/с
    pressure_mpa: Optional[float] = None # давление у диктующего ПК


@dataclass
class MetersSystem:
    """Узел учёта воды (счётчики)."""
    hws_type_meters: str = ""            # описание схемы учёта
    cold_meter_dn: Optional[int] = None  # калибр счётчика ХВС
    hot_meter_dn: Optional[int] = None   # калибр счётчика ГВС
    has_bypass: bool = False             # наличие обводной линии
    notes: str = ""


@dataclass
class PumpSystem:
    """Насосная установка (если требуется)."""
    required: bool = False
    purpose: str = ""                    # назначение (повышение давления / пожарная)
    model: str = ""                      # подобранная модель
    q_m3h: float = 0.0
    head_m: float = 0.0
    power_kw: float = 0.0
    count_note: str = ""                 # "1 рабочий + 1 резервный" и т.п.


@dataclass
class BuildingFlags:
    """Характеристики и флаги объекта (влияют на состав подпунктов)."""
    purpose: BuildingPurpose = BuildingPurpose.PUBLIC
    floors_above: int = 1                # этажей надземных
    floors_below: int = 0                # этажей подземных
    height_m: float = 0.0                # высота здания, м
    has_parking: bool = False            # есть подземная автостоянка
    has_built_in: bool = False           # есть встроенные помещения
    fire_class: str = ""                 # класс функц. пожарной опасности (Ф...)
    hws_type: HwsType = HwsType.CENTRAL  # тип ГВС
    seats: int = 0                       # вместимость (для зрелищных)


@dataclass
class Project:
    """
    Полная модель проекта для генерации ПЗ.
    Агрегирует все группы данных.
    """
    document: DocumentInfo = field(default_factory=DocumentInfo)
    building: BuildingFlags = field(default_factory=BuildingFlags)
    source: WaterSource = field(default_factory=WaterSource)
    materials: PipeMaterials = field(default_factory=PipeMaterials)
    flows: FlowsData = field(default_factory=FlowsData)
    fire: FireSystem = field(default_factory=FireSystem)
    meters: MetersSystem = field(default_factory=MetersSystem)
    pumps: PumpSystem = field(default_factory=PumpSystem)
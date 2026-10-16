"""Conservative document intake for the opt-in residential workspace.

No engineering formulas live here. PDF text supplies candidates, never approved
inputs. Every accepted value retains its page evidence; new conflicts reopen it.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
import math
import re
from dataclasses import asdict, dataclass

from pypdf import PdfReader

from app.calc.fire_table_7_1 import Table71Category, resolve_table_7_1
from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.calc.t3_hydraulics import T3SectionInput, calculate_t3_hydraulics
from app.data.sp30_tables import CONSUMER_NORMS
from app.data.storm_cities import STORM_CITIES
from app.data.metering_supports import CHOICES as SUPPORT_CHOICES
from app.intake.request_dto import (
    ConsumerGroupRequest,
    DocumentRequest,
    IOS2Request,
    SewerPipeRequest,
    SewerElementRequest,
    SewageRiserRequest,
    SourceDataRequest,
)
from app.intake.studio_roofs import ROOF_CHOICES, roof_rule
from app.intake.studio_section import representative_presentation
from app.intake.studio_sewer_pipes import validate_registry, editor_columns, MAX_ROWS as MAX_SEWER_ROWS
from app.intake import studio_sewer_elements
from app.intake import studio_fans
from app.intake import studio_risers
from app.intake import studio_design_basis as design_basis
from app.pz.metering_options import METERING_OPTIONS
from app.pz.wastewater_service import (
    METER_REGIMES, SUMP_ROOMS, RESERVE_LOCATIONS,
    from_studio as wastewater_service_from_studio, assess as assess_wastewater_service,
)
from app.calc.rainwater_reuse import (
    PURPOSES as RAINWATER_PURPOSES, LOCATIONS as RAINWATER_LOCATIONS,
    from_studio as rainwater_from_studio, assess as assess_rainwater, parse_profile,
)
from app.calc.rainwater_pump import SETUPS as RAIN_PUMP_SETUPS, HOSES as RAIN_HOSES, NUMBERS as RAIN_PUMP_NUMBERS
from app.calc.rainwater_treatment import SETUPS as RAIN_TREATMENT_SETUPS, SURFACES as RAIN_TREATMENT_SURFACES, NUMBERS as RAIN_TREATMENT_NUMBERS
from app.calc.rainwater_design import SECTIONS as RAIN_DESIGN_SECTIONS, WINTER as RAIN_WINTER, DISCHARGE as RAIN_DISCHARGE
from app.pz.metering_detail_data import MeteringDetailData
from app.intake.studio_metering import MINIMUM_NODES, VU_ORIENTATIONS, minimum_checks, studio_layout_choices
from app.pz.apartment_water_units import apartment_units_from_values
from app.pz.water_service_assemblies import (
    SERVICE_MODES, BALANCE_MODES, SERVICE_COUNTS, from_values as service_layout_from_values,
)
from app.intake.studio_apartment_meters import estimate_apartment_meters
from app.intake.studio_hws import from_values as hws_stage_p_from_values
from app.intake.studio_hydraulics import (
    section_requests, sections_complete, validate_sections, validate_t3_sections,
)

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_DOCUMENTS = 10
MAX_PAGES = 100
MAX_PAGE_TEXT = 100_000


class IntakeError(ValueError):
    def __init__(self, message, *, source=None):
        super().__init__(message)
        self.input_issues = getattr(source, "input_issues", [])
        self.input_message = getattr(source, "input_message", None)


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    section: str
    kind: str = "number"
    unit: str = ""
    required: bool = False  # Required for this workspace's demand calculation only.
    help: str = ""


FIELDS = (
    Field('station_room_number', 'Номер помещения насосной по АР', 'water', 'text',
          help='Для подписи схемы. Не подставляем номер подвала или ИТП автоматически.'),
    Field('station_floor_elevation_m', 'Отметка пола насосной', 'water', unit='м',
          help='Относительно 0,000 здания; не заменяет отметку ввода в расчёте напора.'),
    Field('station_suction_elevation_m', 'Отметка оси всасывающего патрубка НУ', 'water', unit='м',
          help='По размещению установки. Высота из каталога над рамой не является этой отметкой.'),
    Field("hws_stage_p_enabled", "Оценить циркуляцию для стадии П", "water", "choice",
          help="Укрупнённый тепловой баланс, без длин труб. Напор насоса и кольца не рассчитывает."),
    Field("hws_water_towel_rails", "Водяные полотенцесушители подключены к ГВС", "water", "choice",
          help="Электрические и подключённые к отоплению не подходят для этого метода."),
    Field("hws_circulation_zones", "Зон горячего водоснабжения", "water", "choice"),
    Field("hws_delta_t_c", "Допустимое охлаждение воды Δt", "water", unit="°C",
          help="До 10 °C. Для этой оценки температура возврата не ниже 60 °C; например, при подаче 65 °C допустимо не более 5 °C. Перепад выбирает проектировщик."),
    Field("hws_loss_percent", "Принятая доля теплопотерь · необязательно", "water", unit="%",
          help="Пусто — диапазон 30–40%, до 60% при двух зонах. Одно значение появляется только после вашего выбора."),
    Field("hws_hot_temp_c", "Температура горячей воды в оценке", "water", unit="°C",
          help="Пусто — 65 °C по п. 5.12 для предварительного расчёта; при наличии исходных данных измените."),
    Field("hws_cold_temp_c", "Температура холодной воды в оценке", "water", unit="°C",
          help="Пусто — 5 °C по п. 5.12 при отсутствии данных; при наличии исходных данных измените."),
    Field(
        "residents",
        "Сколько жителей в доме?",
        "object",
        "integer",
        "чел.",
        True,
        "Расчётное число жителей по заданию. Оно не выводится из количества квартир.",
    ),
    Field(
        "consumer_code",
        "Какие приборы предусмотрены в квартирах?",
        "water",
        "norm",
        "",
        True,
        "Выберите одну группу для всей жилой части. Для смешанного объекта нужна полная форма.",
    ),
    Field(
        "sewage_max_fixture_lps",
        "Расчётный сброс прибора q₀s",
        "sewer",
        "number",
        "л/с",
        False,
        "В жилом сценарии принято 1,6 л/с из рабочего legacy-калькулятора. Меняйте только при явно заданном другом расчётном приборе; это не график залпового сброса.",
    ),
    Field("floors", "Надземных этажей", "object", "integer", "эт."),
    Field("apartments", "Квартир всего", "object", "integer", "шт."),
    Field("floor_height_m", "Высота этажа (от пола до пола)", "object", unit="м",
          help="По разрезу АР. Для предварительного разреза можно явно принять типовую высоту; из пожарной высоты её не выводим."),
    Field("basement_kind", "Что под первым этажом?", "object", "choice"),
    Field("basement_floor_m", "Отметка пола подвала / техподполья", "object", unit="м",
          help="Относительно пола первого этажа 0,000. Например: −3,100. Только если подвал или техподполье есть."),
    Field("section_drainage", "Водосток на предварительной схеме", "sewer", "choice",
          help="Уточните по АР: внутренние воронки К2 или наружный водосток. Этот выбор не подтверждает проектное решение и расчёт К2."),
    Field("section_funnel_heated", "Электрообогрев кровельной воронки", "sewer", "choice",
          help="Меняет УГО на схеме. Наличие электропитания и выбор изделия подтверждаются проектом; автоматически не предполагаются."),
    Field("section_fan_mode", "Решение вытяжной части К1", "sewer", "choice",
          help="Необязательно. Без уточнения показываются самостоятельные выводы для неэксплуатируемой/скатной кровли; для эксплуатируемой — запрос решения."),
    Field("section_fan_height_m", "Высота открытого устья над кровлей", "sewer", unit="м",
          help="Пусто — на схеме нормативный минимум со знаком ≥, а не назначенная высота."),
    Field("section_fan_member_ids", "Стояки общей вытяжки К1", "sewer", "text",
          help="Марки через запятую, например К1-1, К1-2, К1-3, К1-4. Не число линий на разрезе."),
    Field("section_fan_space", "Место объединения", "sewer", "choice"),
    Field("section_fan_space_floor_m", "Пол технического пространства", "sewer", unit="м"),
    Field("section_fan_roof_level_m", "Отметка кровли", "object", unit="м",
          help="По АР, относительно пола первого этажа 0,000. Общая привязка для схем воды и канализации; не высота фанового устья."),
    Field("section_fan_collector_low_m", "Низкий конец коллектора", "sewer", unit="м"),
    Field("section_fan_collector_high_m", "Высокий конец коллектора", "sewer", unit="м"),
    Field("section_fan_source_ref", "Основание решения вентиляции · АР / ВК", "sewer", "text",
          help="Отметки относительно 0,000. Укажите лист/ревизию или явно обозначьте предварительное допущение. Длины и диаметры по этому рисунку не вычисляются."),
    Field("section_fan_working_diameter_mm", "DN одинаковых рабочих стояков К1", "sewer", "integer", "мм",
          help="Для показанной типовой группы одинакового DN. Вытяжка и коллектор принимают этот DN по существующей проверке СП 30; пропускная способность рабочих стояков проверяется отдельно."),
    Field("section_fan_opening_distance_m", "До открываемых окон / балконов", "sewer", unit="м"),
    Field("section_fan_no_openings_confirmed", "Открываемых окон / балконов рядом нет", "sewer", "choice"),
    Field("section_fan_attic_insulated", "Коллектор в холодном чердаке теплоизолирован", "sewer", "choice"),
    Field("section_fan_plastic_exposed", "Над кровлей применяется пластик", "sewer", "choice"),
    Field("section_fan_uv_protected", "Защита пластика от УФ предусмотрена", "sewer", "choice"),
    Field(
        "building_height_m",
        "Общая геометрическая высота здания",
        "object",
        "number",
        "м",
    ),
    Field(
        "fire_height_m",
        "Пожарно-техническая высота",
        "object",
        "number",
        "м",
        help="Отдельная исходная величина по АР, не равна автоматически высоте здания.",
    ),
    Field(
        "guaranteed_head_m",
        "Гарантированный напор",
        "water",
        "number",
        "м",
        help="По ТУ. Не нужен для расчёта расходов; понадобится для расчёта требуемого повышения напора.",
    ),
    Field(
        "hws_type",
        "Источник горячей воды",
        "water",
        "hws",
        help="Определяет состав расчёта водомеров и путей В1/Т3.",
    ),
    Field("inputs_count", "Количество вводов водопровода", "water", "integer", "шт."),
    Field("fire_topology", "Как связаны В1 и В2?", "water", "choice",
          help="Нужно только если ВПВ требуется. Выберите принятое решение: оно влияет на расчёт потерь и состав узла учёта. Автоматически объединять системы нельзя."),
    Field("fire_station_model", "Расчётная модель пожарной станции", "water", "fire_station",
          help="Необязательный экспертный импорт JSON: явная сеть В2, отметки, два ввода, A и местные сопротивления. Версия 2 также задаёт диафрагмы и отключения для отдельной проверки. Не планы PDF. Без модели предварительная ПЗ остаётся доступна."),
    Field(
        "fire_corridor_length_m", "Длина общего коридора", "object", unit="м",
        help="По АР. Нужна для проверки В2 по таблице 7.1 СП 10; не заменяет план помещений.",
    ),
    Field(
        "h_geom_m",
        "Геометрическая высота диктующего прибора над вводом",
        "water",
        unit="м",
        help="Перепад отметок, не общая высота здания. Не вычисляется по этажности.",
    ),
    Field(
        "pressure_loss_mode", "Потери в трубах", "water", "choice",
        help="По участкам — ЗАРЯ считает потери. Готовые суммы — только если уже есть отдельный расчёт.",
    ),
    Field("water_inlet_elevation_m", "Отметка оси ввода воды у здания", "water", unit="м",
          help="Необязательно для расчёта расходов. Для схемы — относительно пола первого этажа 0,000, например −2,100. Не отметка подключения в наружной сети и не Hгеом."),
    Field(
        "v1_sections", "Расчётный путь В1", "water", "sections",
        help="Один последовательный путь: ввод и внутренняя сеть. Длины, внутренние диаметры и шероховатость — по проекту. Не заменяет проверку всей сети и отдельной трассы Т3.",
    ),
    Field(
        "h_il_m",
        "Потери по диктующему направлению",
        "water",
        unit="м",
        help="Готовая сумма потерь внутренней сети, включая местные сопротивления. Без расчётной трассы оставьте незаданной.",
    ),
    Field(
        "h_vvod_m",
        "Потери на вводе",
        "water",
        unit="м",
        help="Готовые расчётные потери. Не заменяются условным запасом.",
    ),
    Field("t3_loss_mode", "Потери по пути к горячему прибору", "water", "choice"),
    Field("t3_sections", "Расчётный путь Т3", "water", "t3_sections",
          help="Все внутренние участки от общего ввода до горячего прибора, включая подводку к ИТП при её наличии. Общий ввод, водомеры и теплообменник повторно не включайте. Расход — по потребителям именно участка, не всего дома."),
    Field("h_il_hot_m", "Потери труб по отдельной трассе Т3", "water", unit="м",
          help="Готовая сумма линейных и местных потерь до горячего диктующего прибора, без водомеров и теплообменника. Расчёт участков В1 её не заменяет."),
    Field(
        "h_apartment_c_meter_m", "Квартирный счётчик ХВС: ручная поправка потерь", "water", unit="м",
        help="Рассчитывается автоматически. Ручное значение имеет приоритет; очистите поле, чтобы вернуться к авторасчёту.",
    ),
    Field(
        "h_apartment_h_meter_m", "Квартирный счётчик ГВС: ручная поправка потерь", "water", unit="м",
        help="Рассчитывается автоматически. Ручное значение имеет приоритет; очистите поле, чтобы вернуться к авторасчёту.",
    ),
    Field("apartment_design_residents", "Жителей в расчётной квартире", "water", "integer", "чел.",
          help="Необязательно: заменяет среднюю заселённость для предварительного расчёта квартирных водомеров."),
    Field(
        "h_pr_m",
        "Свободный напор у диктующего прибора",
        "water",
        unit="м",
        help="Принятое в рабочем ядре значение — 20 м; это одно из слагаемых требуемого напора.",
    ),
    Field(
        "hws_heater_in_scope",
        "ГВС готовится в нашем водонагревателе/ИТП?",
        "water",
        "choice",
    ),
    Field("h_tepl_m", "ИТП / водонагреватель: ручная поправка потерь", "water", unit="м",
          help="Только если ГВС готовится в проектируемом ИТП/водонагревателе. Не относится к каждой квартире автоматически."),
    Field("roof_type", "Кровля", "sewer", "choice"),
    Field("storm_city", "Город для расчёта дождя", "sewer", "choice"),
    Field("storm_selected_riser_dn_mm", "Принятый DN водосточных стояков", "sewer", "integer", "мм",
          help="Проверка существующим расчётом К2. Не диаметр горизонтальной магистрали."),
    Field("storm_funnels_count", "Всего воронок по плану кровли", "sewer", "integer", "шт.",
          help="Необязательно для принципиального разреза. Фактическое количество для спецификации, не число символов на схеме."),
    Field("storm_risers_count", "Всего стояков К2 по планам", "sewer", "integer", "шт.",
          help="Необязательно для принципиального разреза. Используется только для проверки суммарной пропускной способности."),
    Field("storm_max_riser_flow_lps", "Нагрузка наиболее нагруженного стояка К2", "sewer", unit="л/с",
          help="По водосборным площадям. Общий расход дома не делится поровну автоматически."),
    Field("storm_funnels_on_different_levels", "Воронки одного стояка на разных уровнях", "sewer", "choice"),
    Field("storm_roof_area_m2", "Водосборная площадь кровли", "sewer", unit="м²"),
    Field(
        "storm_walls_area_m2",
        "Площадь примыкающих стен",
        "sewer",
        unit="м²",
        help="Если примыкающих стен нет, укажите 0. При расчёте используется коэффициент существующего ядра.",
    ),
    Field("object_name", "Наименование объекта", "object", "text"),
    # Context only; these fields never invent a new demand/hydraulic method.
    Field("building_purpose", "Назначение здания", "object", "choice"),
    Field("building_area_m2", "Общая площадь", "object", unit="м²"),
    Field("building_volume_m3", "Строительный объём", "object", unit="м³",
          help="Сохраняется в анкете объекта; не заменяет расчётные геометрические данные."),
    Field("attic_kind", "Чердак", "object", "choice"),
    Field("foundation_kind", "Фундамент", "object", "choice",
          help="Для дальнейшей детализации вводов и выпусков. Конструктивный узел автоматически не назначается."),
    Field("geology_status", "Инженерная геология", "object", "choice"),
    Field("geology_note", "Особенности грунтов и грунтовых вод", "object", "text"),
    Field("permafrost", "Вечномерзлые грунты", "object", "choice"),
    Field("seismic_zone", "Сейсмический район", "object", "choice"),
    Field("building_operation", "Режим работы", "object", "text",
          help="Контекст объекта. Расчётная методика жилой группы этим текстом не меняется."),
    Field("technology_presence", "Есть нежилые / технологические потребители?", "object", "choice",
          help="Например, магазин, кафе, общая прачечная или бассейн. Их нельзя включать в число жителей."),
    Field("technology_note", "Какие помещения и потребители?", "object", "text"),
    Field("connection_note", "Другие условия подключения", "water", "text",
          help="Например, ограничения ТУ или сведения о точках подключения. Текст сам по себе не выполняет расчёт."),
    *(Field("vu_" + key, option.title, "water", "choice", help=option.help)
      for key, option in METERING_OPTIONS.items()),
    Field("russian_equipment_only", "Только российское оборудование", "water", "choice",
          help="Для всего проекта. Неподтверждённые изделия исключаются из подбора ВУ; остальные позиции проверяются перед выпуском. Расчёт не подгоняется под каталог."),
    Field("vu_drawing_scale", "Масштаб габаритных фрагментов ВУ", "water", "choice",
          help="Паспортные осевые размеры в масштабе. Полный монтажный размер доступен только при подтверждённых присоединениях."),
    Field("vu_orientation", "Общий ввод / по умолчанию", "water", "choice",
          help="Общее положение узлов. Ниже можно отдельно изменить ХВС и ГВС; для расчётного горячего узла формируются отдельные листы."),
    Field("vu_per_inlet", "Отдельный ВУ на каждом вводе", "water", "choice",
          help="Без галочки — один общий ВУ для вводов. С галочкой — свой узел на каждом вводе. Схему коммерческого учёта согласовать с ТУ; каждый ввод проверяется на полный расход."),
    Field("vu_cold_orientation", "Счётчик ХВС", "water", "choice",
          help="Независимая ориентация узла ХВС. Пусто — как по умолчанию. Класс и минимальный расход проверяются заново."),
    Field("vu_hot_orientation", "ГВС / перед нагревателем", "water", "choice",
          help="Независимая ориентация расчётного горячего узла. Свои листы и позиции Г. в спецификации; размеры и обвязка холодного ввода не переносятся."),
    Field("vu_filter_layout", "Фильтр основного узла", "water", "choice",
          help="VT.386 на оси: DN15–25, горизонтально или поток вверх. VT.192 на горизонтальном участке: DN15–50, с двумя угольниками VTr.090. Стыки, рабочие P/T и уплотнения проверяются отдельно; российское происхождение не подтверждено."),
    Field("vu_maintenance_layout", "Обслуживание основного ВУ", "water", "choice",
          help="Ремонтная компоновка: отсечка за обратным клапаном и два сервисных отбора. Контрольные краны для поверки сохраняются. Профиль, полости и приём воды проверяются отдельно; обвязка ГВС не копируется."),
    Field("rainwater_enabled", "Использовать дождевую воду", "water", "choice"),
    *(Field('vu_support_' + key, title, 'water', 'choice',
        help='Необязательно. Одна явно заданная постоянная точка на каждый одинаковый основной ВУ. Это предварительный состав, не подтверждение несущей способности.')
      for key, title in (('inlet','Опора трубы до ВУ'), ('outlet','Опора трубы после ВУ'),
                         ('bypass','Опора обводной до арматуры'), ('bypass_after','Опора обводной после арматуры'))),
    Field('vu_support_height_mm', 'Высота напольных стоек', 'water', unit='мм',
          help='Для ОСВУ-1: 500–800 мм. Не отметка трубы; привязку и нагрузку проверить отдельно.'),
    Field("rainwater_purpose", "Для чего", "water", "choice"),
    Field("rainwater_location", "Где разместить бак", "water", "choice"),
    Field("rainwater_demand_m3_day", "Потребность в технической воде", "water", unit="м³/сут",
          help="Не расход всего здания. Можно вместо постоянного значения задать график ниже."),
    Field("rainwater_useful_volume_m3", "Проверяемый полезный объём бака", "water", unit="м³",
          help="Если объём пока неизвестен, оставьте пустым. Автоматический подбор ёмкости не выполняется."),
    Field("rainwater_collection_area_m2", "Кровля, подключённая к баку", "water", unit="м²",
          help="Фактическая площадь сбора; приведённая площадь К2 со стенами сюда не переносится."),
    Field("rainwater_collection_factor", "Коэффициент сбора воды", "water",
          help="От 0 до 1, без нуля. Учитывает потери сбора и подготовки; требуется обоснование."),
    Field("rainwater_profile", "Суточные осадки и водоразбор", "water", "rain_profile",
          help="Каждая строка: ГГГГ-ММ-ДД; дождь в мм; потребность в м³ (необязательно). Включите сухие дни с 0 мм. Без третьего столбца используется потребность выше. Снег и снеготаяние не моделируются."),
    Field("rainwater_source", "Источник осадков и коэффициента", "water", "text"),
    Field("rainwater_technical_use", "Технический потребитель и качество воды", "water", "text"),
    Field("rainwater_treatment_setup", "Подготовка воды", "water", "choice",
          help="Первая версия: жилая терраса с твёрдым покрытием → полив декоративного озеленения. Тип кровли берётся из блока «Здание»."),
    Field("rainwater_treatment_surface", "С какой поверхности собираем дождь", "water", "choice",
          help="Без грунта, парковки, моющих растворов и бытовых стоков. Наличие террасы не подтверждает качество воды."),
    Field("rainwater_treatment_selection_flow_lps", "Расход по листу подбора очистки", "water", unit="л/с",
          help="Должен совпадать с одновременным расходом полива. При его изменении прежние потери не используются."),
    Field("rainwater_treatment_filter_loss_m", "Потери фильтра по листу подбора", "water", unit="м",
          help="Для Гейзер Джамбо 20 с PP 5–20BB, с учётом принятого загрязнения. Не повторять в потерях сети."),
    Field("rainwater_treatment_uv_loss_m", "Потери УФ по листу подбора", "water", unit="м",
          help="Для ЛЕНА DUV-1-48-N MST при этом расходе. Не повторять в потерях сети."),
    Field("rainwater_treatment_selection_source", "Лист подбора оборудования", "water", "text",
          help="Реквизиты подтверждения изготовителями расхода, потерь и условий работы обоих изделий, включая режим УФ и температуру."),
    Field("rainwater_treatment_quality_basis", "Основание по качеству воды", "water", "text",
          help="Исходное и требуемое качество, материал кровли, способ полива и пригодность выбранных изделий. Не подменяется названием города."),
    Field("rainwater_pump_setup", "Подача из бака", "water", "choice"),
    Field("rainwater_pump_flow_lps", "Одновременный расход полива", "water", unit="л/с", help="Всех одновременно работающих точек. Не вычисляется из м³/сут."),
    Field("rainwater_outlets_count", "Всего точек полива", "water", "integer"),
    Field("rainwater_hose_choice", "Шланг", "water", "choice"),
    Field("rainwater_pump_geometric_head_m", "Подъём от минимального уровня воды", "water", unit="м", help="До диктующего потребителя, а не от дна бака. Допускается отрицательная разность отметок."),
    Field("rainwater_pump_terminal_head_m", "Напор у поливочного устройства", "water", unit="м", help="По паспорту при расчётном расходе. 20 м от бытового прибора сюда автоматически не переносятся."),
    Field("rainwater_pump_network_loss_m", "Потери труб и арматуры", "water", unit="м", help="При указанном расходе, без шланга и оборудования подготовки. Готовая сумма без повторной процентной надбавки."),
    Field("rainwater_pump_treatment_loss_m", "Потери очистки и обеззараживания", "water", unit="м", help="По принятому оборудованию при расчётном расходе; учитывать загрязнение фильтра."),
    Field("rainwater_pump_loss_source", "Расчёт потерь / паспорта потребителя", "water", "text"),
    Field("rainwater_pump_pipe_inner_mm", "Внутренний диаметр магистрали", "water", unit="мм"),
    Field("rainwater_pump_pipe_length_m", "Длина напорной трубы для спецификации", "water", unit="м", help="Не определяет потери автоматически. Если трассы нет, длина остаётся неизвестной."),
    Field("rainwater_pump_min_submergence_m", "Минимальное погружение водозабора", "water", unit="м"),
    Field("rainwater_pump_max_submergence_m", "Максимальное погружение насоса", "water", unit="м"),
    Field("rainwater_pump_temperature_c", "Температура воды в баке", "water", unit="°C"),
    Field("rainwater_pump_clean_water", "Подготовленная вода соответствует паспорту насоса", "water", "choice"),
    Field("rainwater_hose_model", "Модель / паспорт шланга", "water", "text"),
    Field("rainwater_hose_length_m", "Длина одного шланга", "water", unit="м"),
    Field("rainwater_hose_inner_mm", "Внутренний диаметр шланга", "water", unit="мм"),
    Field("rainwater_hose_pn_bar", "Рабочее давление шланга", "water", unit="бар", help="Не давление разрыва. Проверяется также при закрытом выходе насоса."),
    Field("rainwater_hose_loss_m", "Потери в диктующем шланге", "water", unit="м", help="При расходе этой ветви. Длины параллельных шлангов не складываются для напора."),
    Field("rainwater_hose_sets", "Комплектов шланга", "water", "integer"),
)
FIELDS += tuple(Field("rainwater_" + key, title, "water", "design_note", help=note)
                for key, (title, note) in RAIN_DESIGN_SECTIONS.items()) + (
    Field("rainwater_design_storage_days", "Предельный срок хранения по решению", "water", unit="сут",
          help="Для полива — не более 3–7 суток; срок обосновывается, слив при застое задаётся в решении по баку."),
    Field("rainwater_design_annual_saving_m3", "Годовая экономия по отдельному расчёту", "water", unit="м³/год",
          help="Не переносите результат нескольких суток. Не вычитается автоматически из В1."),
    Field("rainwater_design_winter", "Зимний режим", "water", "choice"),
    Field("rainwater_design_discharge", "Приёмник слива и перелива", "water", "choice"),
)
FIELDS += tuple(Field(f"section_{system}_{key}", f"{system.upper().replace('K', 'К')} · {title}",
                       "sewer", kind, unit, help=note)
    for system in ("k1", "k2") for key, title, kind, unit, note in (
        ("dn_mm", "DN характерной магистрали", "integer", "мм",
         "Номинальный диаметр по проектному решению. Один DN для всей показанной магистрали, включая выпуск. Это не наружный диаметр и не гидравлический подбор."),
        ("slope", "Уклон магистрали", "number", "м/м",
         "По расчёту / проектному решению, например 0,02. Не в процентах. Размеры рисунка не используются для расчёта."),
        ("outlet_invert_m", "Отметка лотка выпуска", "number", "м",
         "В месте пересечения наружной стены, относительно 0,000 первого этажа. Не отметка крышки колодца и не глубина промерзания."),
        ("start_invert_m", "Лоток в начале показанной магистрали", "number", "м",
         "Относительно 0,000 первого этажа, у первого показанного стояка. Отметку не определяем по длине линии на схеме. Основание укажите ниже."),
        ("discharge_point", "Куда направлен выпуск", "text", "",
         "Обозначение приёмника по ТУ / НВК, например КК-1. К1 и К2 не объединяем."),
        ("source_ref", "Основание решения", "text", "",
         "Документ, лист и редакция либо явно обозначенное предварительное решение проектировщика. Не является автоматическим подтверждением расчёта."),
    ))
FIELDS += tuple(field for node, label in MINIMUM_NODES.items() for field in (
    Field(f"meter_min_{node}_m3h", f"{label} · минимальный часовой расход", "water", unit="м³/ч",
          help="Не средний и не максимальный расход. Только обоснованный минимум по расчёту или графику водопотребления; при отсутствии оставьте пустым."),
    Field(f"meter_min_{node}_source", f"{label} · основание минимума", "water", "text",
          help="Расчёт / график, лист и редакция. Паспортный Qmin ЗАРЯ берёт из каталога отдельно. Проверка относится к этому узлу, не ко всем водомерам."),
))
FIELDS += (
    Field("sewage_risers", "Расчётные стояки К1", "sewer", "sewage_risers",
          help="Явные исходные каждого стояка из реестра труб. Расход здания не подставляется. Размеры расчётной таблицы не копируются из номинального DN вытяжки: у пластиковых труб табличный размер может быть наружным. Внутренние диаметры задаются отдельно. Режим и наличие унитаза — явный выбор. Отсутствие обязательных данных не заменяется числами; необязательные оставьте пустыми."),
    Field("wastewater_fan_ventilation", "Фановые окончания реальных стояков К1", "sewer", "fan_evidence",
          help="Явные данные по каждому окончанию и привязка к ID стояков реального реестра труб. Пусто — неизвестно, не подтверждение. Данные условного разреза не переносятся. Режимы реальных стояков проверяются отдельно; отсутствие их ввода не заменяется выбранным типом окончания. Общие вытяжки и клапаны не означают готовность штатной графики."),
    Field("sewer_elements", "Элементы реальной сети К1/К2", "sewer", "sewer_elements",
          help="Только явные элементы проекта, без автоматического назначения приборов и фасонных частей. Количество, этаж и доступность задаются явно. Нет / не подтверждена доступность не означает успешной проверки обслуживания. Ссылки проверяются по двум реестрам; фановые окончания этим реестром не подтверждаются."),
    Field("sewer_pipes", "Реальные участки К1/К2", "sewer", "sewer_pipes",
          help="Только явные данные проекта. Это реестр труб, не полный состав сети: элементы, связи и фановые окончания требуют отдельного ввода. Условный разрез не служит источником длин или диаметров. Пустой реестр не добавляет труб."),
    Field("risers_v1", "Стояков ХВС (В1) всего", "water", "integer", "шт.",
          help="По принятой схеме здания. Не число стояков на условном разрезе. Если неизвестно, оставьте пустым."),
    Field("risers_t3", "Подающих стояков ГВС (Т3) всего", "water", "integer", "шт.",
          help="Не число квартир. Не определяет расход каждой ветви и не заменяет расчёт сети."),
    Field("risers_t4", "Циркуляционных стояков (Т4) всего", "water", "integer", "шт.",
          help="Может отличаться от Т3. Для количества арматуры, не для назначения DN, Kv и настроек."),
    Field("v1_sectional_valves_count", "Дополнительных секционных кранов В1", "water", "integer", "шт.",
          help="На основной магистрали выбранного DN, по принятой компоновке. Не включайте краны стояков, ВУ, квартир и насосов, учтённые отдельно. Пусто — неизвестно; 0 — дополнительных нет. Для расчёта расходов не требуется."),
    Field("v1_sectional_valves_basis", "Основание количества секционных кранов", "water", "text",
          help="Какие участки отключаются, схема / лист и редакция. До заполнения основания количество в спецификации остаётся открытым; расчёт доступен."),
    Field("apartment_units_mode", "Количество квартирных узлов", "water", "choice",
          help="Для типового жилья с центральным ГВС. Считаем кран, фильтр, счётчик и обратный клапан по составу узла, не по числу квартир на рисунке. DN и модели — по отдельному подбору."),
    Field("apartment_units_cold_count", "Квартирных узлов ХВС всего", "water", "integer", "шт.",
          help="Число вводов ХВС во все квартиры здания. При нескольких вводах в квартиру учитывайте каждый. Пусто — неизвестно."),
    Field("apartment_units_hot_count", "Квартирных узлов ГВС всего", "water", "integer", "шт.",
          help="Число вводов ГВС во все квартиры здания, не на один этаж. Пусто — неизвестно."),
)
FIELDS += (
    Field("water_service_mode", "Воздушные и спускные узлы", "water", "choice",
          help="Для спецификации, не для запуска расчёта. Верхний узел: воздухосборник, кран, автоматический воздухоотводчик; нижний: спускной кран. Только точки стояков, без повторного учёта ВУ и насосов. Воздушные узлы вне квартир; СП 30, п. 11.17."),
    *(Field("water_service_" + key,
            {"v1": "В1", "t3": "Т3", "t4": "Т4"}[key[:2]] +
            (" · верхних воздушных узлов" if key.endswith("upper") else " · нижних спускных узлов"),
            "water", "integer", "шт.", help="По принятой компоновке всего здания, не рисунку. Пусто — неизвестно. Ноль не подтверждает соблюдение требований обслуживания.")
      for key in SERVICE_COUNTS),
    Field("hws_balance_mode", "Где расположены балансировочные клапаны", "water", "choice",
          help="Выберите принятую схему циркуляции по СП 30, пп. 10.6–10.7. Это основание количества, не расчёт DN, Kv и настроек. Необязательно для расчёта расходов и просмотра схемы."),
    Field("hws_balance_count", "Точек балансировки ветвей / колец", "water", "integer", "шт.",
          help="Фактическое число подключений по выбранной схеме всего здания. Не вычисляется из этажности или числа квартир. Для полотенцесушителей — только их возвратные ветви; сборные возвраты ниже."),
    Field("hws_balance_collector_count", "Точек балансировки сборных возвратов", "water", "integer", "шт.",
          help="Отдельные подключения сборных возвратов полотенцесушителей к стоякам Т4; не входят в количество клапанов их ветвей (СП 30, п. 10.7)."),
)
FIELDS += tuple(Field("section_k1_"+key, title, "sewer", kind, unit, help=note)
    for key, title, kind, unit, note in (
        ("flow_basis", "Нагрузка конечного участка К1", "choice", "",
         "Весь расход здания допустим только для участка после сбора всех бытовых стоков. На предыдущие ветви он не переносится."),
        ("design_flow_lps", "Собственный расход участка К1", "number", "л/с",
         "Не нужен при выборе всего расхода здания. Нельзя делить расход дома на число нарисованных стояков."),
        ("flow_source", "Основание ручного расхода К1", "text", "", "Расчёт горизонтального участка по п. 5.7, не расход стояка. Документ / лист / методика."),
        ("q_hour_max_m3h", "Максимальный часовой расход участка", "number", "м³/ч", "Для отдельного участка. Для конечного участка всего здания вычисляется по текущим потребителям, не Qсут/24."),
        ("fixtures_count", "Подключённые приборы N", "integer", "шт.", "Число приборов расчётного участка, не жителей и не условных значков на схеме."),
        ("receiving_length_m", "Длина L для коэффициента Ks", "number", "м", "Таблица 5.1: от последнего стояка до ближайшего следующего присоединения, а при его отсутствии — до ближайшего колодца. Не вся длина магистрали."),
        ("fixture_max_lps", "q0s расчётного участка", "number", "л/с", "Таблица А.1. Для всего здания берётся из текущих исходных; для отдельного участка задаётся явно."),
        ("outer_diameter_mm", "Наружный диаметр выбранной трубы К1", "number", "мм", "По сортаменту конкретной трубы; DN не заменяет наружный диаметр."),
        ("wall_thickness_mm", "Толщина стенки трубы К1", "number", "мм", "Внутренний диаметр вычисляется из наружного диаметра и стенки."),
        ("material", "Материал трубы К1", "choice", "", "Для существующей проверки режима самотечного участка."),
        ("manning_n", "Коэффициент шероховатости n", "number", "", "Только по выбранной методике/источнику. Скрытого значения по материалу нет."),
        ("roughness_source", "Источник коэффициента n", "text", "", "Документ и значение либо явно обозначенное учебное допущение."),
    ))
FIELDS += (
    Field("section_zero_absolute_m", "Абсолютная отметка ±0,000", "object", unit="м",
          help="По АР / геодезии. Абсолютный лоток выпуска = эта отметка + относительный лоток. Не высота с интернет-карты."),
    Field("section_zero_source_ref", "Основание привязки нуля", "object", "text",
          help="Документ, лист и редакция. Для учебного примера явно напишите, что это допущение. Без основания абсолютные отметки не печатаются."),
    Field("project_assignment_ref", "Задание на проектирование · ссылка на раздел", "object", "text",
          help="Шифр/раздел проекта с заданием, дата и ревизия. Один ввод для ИОС2 и ИОС3."),
    Field("project_survey_ref", "Инженерные изыскания · ссылка на раздел", "object", "text",
          help="Шифр отчёта или раздела с изысканиями, дата и ревизия. Название загруженного файла само по себе не подтверждает эти сведения."),
    Field("project_service_life_years", "Расчётный срок службы здания", "object", "integer", "лет",
          help="По заданию/проекту. Типовое число автоматически не принимается."),
    Field("project_overhaul_period_years", "Период до капитального ремонта", "object", "integer", "лет"),
    Field("water_source_description", "Источник водоснабжения", "water", "text",
          help="Описание существующей сети по ТУ. Не наименование организации, выдавшей ТУ."),
    Field("water_connection_point", "Точка подключения по ТУ", "water", "text",
          help="Обозначение точки, к которой относится введённый гарантированный напор. Не место водомерного узла."),
    Field("water_tu_org", "Кто выдал ТУ на водоснабжение", "water", "text"),
    Field("water_tu_number", "Номер ТУ на водоснабжение", "water", "text"),
    Field("water_tu_date", "Дата ТУ на водоснабжение", "water", "text", help="ДД.ММ.ГГГГ. Копия ТУ прикладывается к проекту отдельно."),
    Field("wastewater_disposal_mode", "Куда отводятся стоки", "sewer", "choice",
          help="Выбор по проектным решениям; не объединяет К1 и К2 и не назначает точки выпусков."),
    Field("wastewater_tu_org", "Кто выдал ТУ на водоотведение", "sewer", "text"),
    Field("wastewater_tu_number", "Номер ТУ на водоотведение", "sewer", "text"),
    Field("wastewater_tu_date", "Дата ТУ на водоотведение", "sewer", "text", help="ДД.ММ.ГГГГ. Не копируется из ТУ на водоснабжение."),
)
FIELDS += (
    Field("sewer_service_k1_metering_enabled", "Узел учёта К1", "sewer", "choice",
          help="Необязательно. Задаёт требование учёта; прибор и деталировка выбираются отдельно по документации изготовителя."),
    Field("sewer_service_k1_metering_location", "Место узла учёта К1", "sewer", "text",
          help="Помещение или участок выпуска по проекту."),
    Field("sewer_service_k1_metering_regime", "Режим участка К1", "sewer", "choice"),
    Field("sewer_service_k1_metering_basis", "Основание учёта К1", "sewer", "text",
          help="Например, пункт ТУ или задания на проектирование."),
    Field("sewer_service_sump_enabled", "Приямок для утечек и обслуживания", "sewer", "choice",
          help="Без грунтового дренажа, фекальных стоков и пожаротушения. Пока настройки и требования, без расчёта объёма и подбора насоса."),
    Field("sewer_service_sump_room", "Назначение помещения с приямком", "sewer", "choice",
          help="Определяет требование к резервному насосу по п. 20.14 СП 30 с изменением № 4."),
    Field("sewer_service_sump_location", "Место приямка", "sewer", "text",
          help="Номер помещения и привязка по АР. Одно заданное место, не все приямки здания."),
    Field("sewer_service_sump_reserve_location", "Где резервный насос", "sewer", "choice",
          help="Хранение на складе допускается для техподполья и эксплуатируемого подвала, не для насосной или ВУ."),
    Field("sewer_service_sump_discharge_note", "Условия отвода воды из приямка", "sewer", "text",
          help="Приёмная сеть, точка и основание подключения. Автоматически к К1 или К2 не присоединяем."),
    Field("sewer_service_sump_basis", "Основание решения по приямку", "sewer", "text",
          help="Задание или согласованное решение проектировщика."),
)
FIELD_MAP = {field.key: field for field in FIELDS}
HANDOFF_FIELDS = (
    "floors",
    "building_height_m",
    "fire_height_m",
    "hws_type",
    "apartments",
)
RESIDENTIAL_NORMS = {
    key: norm for key, norm in CONSUMER_NORMS.items() if key.startswith("residential_")
}
HWS_OPTIONS = {
    "central": "Централизованное ГВС",
    "local": "Местные водонагреватели",
    "none": "Без ГВС",
}
OPTIONS = {
    **{'vu_support_' + key: SUPPORT_CHOICES
       for key in ('inlet', 'outlet', 'bypass', 'bypass_after')},
    "sewer_service_k1_metering_enabled": {"yes": "Да", "no": "Нет"},
    "sewer_service_sump_enabled": {"yes": "Да", "no": "Нет"},
    "sewer_service_k1_metering_regime": METER_REGIMES,
    "sewer_service_sump_room": SUMP_ROOMS,
    "sewer_service_sump_reserve_location": RESERVE_LOCATIONS,
    "water_service_mode": SERVICE_MODES,
    "hws_balance_mode": BALANCE_MODES,
    "apartment_units_mode": {"unspecified": "Пока не задано",
        "one_per_apartment": "По одному узлу ХВС и ГВС на квартиру",
        "explicit_counts": "Своё количество узлов"},
    "hws_stage_p_enabled": {"no": "Не выполнять", "yes": "Выполнить укрупнённую оценку"},
    "hws_water_towel_rails": {"yes": "Да", "no": "Нет"},
    "hws_circulation_zones": {"1": "Одна", "2": "Две"},
    "wastewater_disposal_mode": {"not_set":"Пока не определено", "centralized":"Централизованная сеть",
        "local":"Локальные очистные сооружения", "water_body":"Водный объект · отдельное обоснование"},
    "fire_topology": {"separate": "Раздельные В1 и В2", "combined": "Объединённая В1 + В2",
                      "pre_meter_branch": "Отвод В2 до узла учёта В1"},
    "section_k1_flow_basis": {"manual":"Готовый расход горизонтального участка", "whole_building":"По часовому расходу здания · конечный участок", "section_hourly":"По часовому расходу отдельного участка"},
    "section_k1_material": {"pp":"Полипропилен", "pvc":"ПВХ", "pe":"Полиэтилен", "cast_iron":"Чугун", "steel":"Сталь"},
    "rainwater_design_winter": RAIN_WINTER,
    "rainwater_design_discharge": RAIN_DISCHARGE,
    "rainwater_enabled": {"no": "Нет", "yes": "Да"},
    "rainwater_purpose": RAINWATER_PURPOSES,
    "rainwater_location": RAINWATER_LOCATIONS,
    "rainwater_pump_setup": RAIN_PUMP_SETUPS,
    "rainwater_hose_choice": RAIN_HOSES,
    "rainwater_pump_clean_water": {"yes": "Да", "no": "Нет"},
    "rainwater_treatment_setup": RAIN_TREATMENT_SETUPS,
    "rainwater_treatment_surface": RAIN_TREATMENT_SURFACES,
    **{"vu_" + key: option.choices for key, option in METERING_OPTIONS.items()},
    "russian_equipment_only": {"no": "Нет", "yes": "Да"},
    "vu_drawing_scale": {"5": "1:5", "10": "1:10", "20": "1:20", "25": "1:25", "50": "1:50"},
    "vu_orientation": VU_ORIENTATIONS,
    "vu_per_inlet": {"no": "Общий ВУ", "yes": "На каждом вводе"},
    "vu_cold_orientation": VU_ORIENTATIONS,
    "vu_hot_orientation": VU_ORIENTATIONS,
    "vu_filter_layout": {"inline": "На оси узла", "valtec_vt386": "На оси · универсальный VT.386 (DN15–25)", "valtec_vt192_vtr090": "Горизонтальный · VT.192 + 2 отвода"},
    "vu_maintenance_layout": {"existing": "Существующая компоновка", "serviceable": "Сервисные отборы и выходная отсечка"},
    "building_purpose": {"residential": "Многоквартирный жилой дом", "individual": "Индивидуальный жилой дом", "mixed": "Жилой дом со встроенными помещениями"},
    "attic_kind": {"none": "Без чердака", "cold": "Холодный чердак", "warm": "Тёплый чердак", "technical": "Технический этаж"},
    "foundation_kind": {"slab": "Плитный", "strip": "Ленточный", "piles": "Свайный", "other": "Другой / комбинированный"},
    "geology_status": {"available": "Отчёт есть", "pending": "Изыскания в работе", "unknown": "Пока нет данных"},
    **{key: {"no": "Нет", "yes": "Да", "unknown": "Нужно уточнить"}
       for key in ("permafrost", "seismic_zone", "technology_presence")},
    "basement_kind": {"none": "Без подвала", "basement": "Подвал", "subfloor": "Техподполье"},
    "section_drainage": {"internal": "Внутренний · воронки К2", "external": "Наружный водосток"},
    "section_funnel_heated": {"yes":"Да", "no":"Нет", "unknown":"Не определён"},
    "section_fan_mode": {"auto":"По типу кровли", "individual":"Самостоятельные выводы", "common":"Общая вытяжка", "unresolved":"Решение ещё не принято"},
    "section_fan_space": {"cold_attic":"Холодный чердак", "warm_attic":"Тёплый чердак", "technical_storey":"Технический этаж"},
    **{f"section_fan_{key}": {"yes":"Да", "no":"Нет", "unknown":"Не подтверждено"}
       for key in ("no_openings_confirmed", "attic_insulated", "plastic_exposed", "uv_protected")},
    "storm_funnels_on_different_levels": {"no":"Нет, на одном уровне", "yes":"Да, на разных уровнях"},
    "t3_loss_mode": {"sections": "Рассчитать по участкам", "ready": "Ввести готовую сумму"},
    "pressure_loss_mode": {
        "sections": "Рассчитать по участкам",
        "ready": "Ввести готовые суммы",
    },
    "hws_type": HWS_OPTIONS,
    "consumer_code": {key: norm.label for key, norm in RESIDENTIAL_NORMS.items()},
    "hws_heater_in_scope": {"yes": "Да", "no": "Нет, готовая горячая вода"},
    "roof_type": {
        **ROOF_CHOICES,
        "flat": "Плоская — уточните эксплуатацию",
        "sloped": "Скатная — форма не уточнена",
    },
    "storm_city": {key: city.name for key, city in STORM_CITIES.items()},
}
# Reuse accepted defaults, never introduce a second engineering policy here.
DEFAULTS = {
    "vu_per_inlet": "no",
    "t3_loss_mode": "sections",
    "pressure_loss_mode": "sections",
    "sewage_max_fixture_lps": IOS2Request.__dataclass_fields__[
        "sewage_max_fixture_lps"
    ].default,
    "h_pr_m": SourceDataRequest.__dataclass_fields__["h_pr_m"].default,
    "inputs_count": SourceDataRequest.__dataclass_fields__["inputs_count"].default,
}
# UI suggestions explicitly requested for the residential quick start. These are
# NOT calculation defaults: only a visible form submission adopts them. Existing
# answers and document candidates always take precedence.
QUICK_START_PRESETS = {
    "building_purpose": "residential",  # Existing residential scope, explicitly adopted in step 1.
    "consumer_code": "residential_full_bath",
    "hws_type": "central",
    "roof_type": "flat_non_accessible",
}
DEMAND_FIELDS = ("residents", "consumer_code", "sewage_max_fixture_lps")
HEAD_FIELDS = (
    "guaranteed_head_m",
    "h_geom_m",
    "h_il_m",
    "h_vvod_m",
    "h_apartment_c_meter_m",
)
STORM_FIELDS = ("roof_type", "storm_city", "storm_roof_area_m2", "storm_walls_area_m2")

# Only explicitly labelled scalars. No heights inferred from floors or head,
# no residents inferred from apartments, no inference from plan geometry.
_NUM = r"(?P<value>\d+(?:[.,]\d+)?)(?!\d|[.,]\d)"
_JOIN = r"\s*(?::|=|составляет)?\s*"
_METRES = r"\s*м(?:\b|(?=\s|[.;,]|$))(?![²³23]|\s*/|\s*Па)"
PATTERNS = {
    "project_service_life_years": re.compile(r"расч[её]тный\s+срок\s+службы\s+здания" + _JOIN + _NUM + r"\s*(?:лет|год(?:а)?)\b", re.I),
    "project_overhaul_period_years": re.compile(r"период\s+(?:эксплуатации\s+здания\s+)?до\s+(?:проведения\s+)?капитального\s+ремонта" + _JOIN + _NUM + r"\s*(?:лет|год(?:а)?)\b", re.I),
    # Only an explicitly stated building total. Do not count plan symbols or
    # treat a local catchment/floor count as the quantity for the whole roof.
    "storm_funnels_count": re.compile(
        r"общее\s+(?:количество|число)\s+(?:водосточных|кровельных)\s+воронок"
        r"(?:\s+[КK]2)?" + _JOIN + _NUM + r"\s*шт\b\.?", re.I),
    "building_area_m2": re.compile(r"общая\s+площадь\s+здания" + _JOIN + _NUM + r"\s*м[²2]", re.I),
    "building_volume_m3": re.compile(r"строительный\s+объ[её]м(?:\s+здания)?" + _JOIN + _NUM + r"\s*м[³3]", re.I),
    "floor_height_m": re.compile(r"высота\s+(?:типового\s+)?этажа(?:\s*\(от\s+пола\s+до\s+пола\))?" + _JOIN + _NUM + _METRES, re.I),
    "basement_floor_m": re.compile(r"отметка\s+пола\s+(?:подвала|техподполья)" + _JOIN + r"(?P<value>[-−]\d+(?:[.,]\d+)?)(?!\d|[.,]\d)" + _METRES, re.I),
    "residents": re.compile(
        r"(?:расч[её]тное\s+число|число|количество|численность)\s+жителей"
        + _JOIN
        + _NUM
        + r"(?!\s*[-–—+/])",
        re.I,
    ),
    "floors": re.compile(
        r"(?:количество\s+надземных\s+этажей|этажность)"
        + _JOIN
        + _NUM
        + r"(?!\s*[-–—+/])",
        re.I,
    ),
    "apartments": re.compile(
        r"(?:количество|число)\s+квартир" + _JOIN + _NUM + r"(?!\s*[-–—+/])", re.I
    ),
    "building_height_m": re.compile(
        r"(?:общая\s+(?:геометрическая\s+)?высота\s+здания)" + _JOIN + _NUM + _METRES,
        re.I,
    ),
    "fire_height_m": re.compile(
        r"пожарно[\s-]+техническая\s+высота" + _JOIN + _NUM + _METRES, re.I
    ),
    "fire_corridor_length_m": re.compile(
        r"длина\s+общего\s+коридора" + _JOIN + _NUM + _METRES, re.I
    ),
    "guaranteed_head_m": re.compile(
        r"гарантированный\s+напор(?:\s+воды)?" + _JOIN + _NUM + _METRES, re.I
    ),
    "sewage_max_fixture_lps": re.compile(
        r"(?:максимальный\s+сброс\s+(?:одного\s+)?прибора|q[₀0][sс])"
        + _JOIN
        + _NUM
        + r"\s*л\s*/\s*с\b",
        re.I,
    ),
}


for _system in ("k1", "k2"):
    _mark = r"[КK]" + _system[-1]
    PATTERNS[f"section_{_system}_dn_mm"] = re.compile(
        r"DN\s+магистрали\s+" + _mark + _JOIN + _NUM + r"\s*мм\b", re.I)
    PATTERNS[f"section_{_system}_slope"] = re.compile(
        r"уклон\s+магистрали\s+" + _mark + _JOIN + _NUM + r"\s*м\s*/\s*м\b", re.I)
    PATTERNS[f"section_{_system}_outlet_invert_m"] = re.compile(
        r"отметка\s+лотка\s+выпуска\s+" + _mark + _JOIN +
        r"(?P<value>[+−-]?\d+(?:[.,]\d+)?)(?!\d|[.,]\d)" + _METRES, re.I)


def validate_value(key: str, value):
    field = FIELD_MAP.get(key)
    if field is None:
        raise IntakeError("Неизвестное поле.")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if key in design_basis.DATES:
        try:
            return design_basis.document_date(value)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    if field.kind == "rain_profile":
        try:
            parse_profile(value)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
        return value.strip()
    if field.kind == "fire_station":
        from app.intake.studio_fire_station import parse_model
        try:
            return parse_model(value).model
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    if field.kind == "t3_sections":
        try:
            return validate_t3_sections(value)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    if field.kind == "sewer_pipes":
        try:
            return validate_registry(value)
        except ValueError as exc:
            raise IntakeError(str(exc), source=exc) from exc
    if field.kind == "sewage_risers":
        try:
            return studio_risers.validate_value(value)
        except ValueError as exc:
            raise IntakeError(str(exc), source=exc) from exc
    if field.kind == "fan_evidence":
        try:
            return studio_fans.validate_value(value)
        except (ValueError, TypeError) as exc:
            raise IntakeError(str(exc), source=exc) from exc
    if field.kind == "sewer_elements":
        try:
            return studio_sewer_elements.validate_registry(value)
        except ValueError as exc:
            raise IntakeError(str(exc), source=exc) from exc
    if field.kind == "sections":
        try:
            return validate_sections(value)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    if field.kind == "design_note":
        if not isinstance(value, str) or len(value.strip()) > 1200:
            raise IntakeError("Проектное решение: текст до 1200 символов, включая реквизиты документа и ревизию.")
        return value.strip()
    if field.kind == "text":
        if not isinstance(value, str) or len(value.strip()) > 200:
            raise IntakeError(
                "Текст должен быть строкой не длиннее 200 символов."
            )
        if key == 'station_room_number' and len(value.strip()) > 40:
            raise IntakeError('Номер помещения: не более 40 символов.')
        if key == "section_fan_member_ids":
            from app.intake.studio_section import section_fan
            try:
                section_fan({key:value.strip()})
            except ValueError as exc:
                raise IntakeError(str(exc)) from exc
        return value.strip()
    if field.kind in {"norm", "hws", "choice"}:
        options = OPTIONS[key]
        if not isinstance(value, str) or value not in options:
            raise IntakeError("Выберите значение из предложенного списка.")
        return value
    text = str(value).strip().replace(",", ".").replace("−", "-")
    if isinstance(value, bool) or not re.fullmatch(
        r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)", text
    ):
        raise IntakeError("Укажите число; десятичная запятая допускается.")
    number = float(text)
    if key in {"hws_hot_temp_c", "hws_cold_temp_c", "hws_delta_t_c", "hws_loss_percent"}:
        limits = {"hws_hot_temp_c": (60, 75), "hws_cold_temp_c": (0, 75),
                  "hws_delta_t_c": (0, 10), "hws_loss_percent": (30, 60)}
        lo, hi = limits[key]
        if not math.isfinite(number) or not lo <= number <= hi or (key == "hws_delta_t_c" and number == 0):
            raise IntakeError(f"Недопустимое значение: {lo}…{hi}; Δt должен быть положительным.")
        return number
    if key == "section_zero_absolute_m":
        from app.pz.wastewater_presentation import RepresentativeSectionInput
        try:
            RepresentativeSectionInput(zero_absolute_m=number)
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
        return number
    if key in design_basis.YEARS:
        if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= 1000:
            raise IntakeError("Укажите целое число лет от 1 до 1000; это ограничение ввода, не нормативный срок.")
        return int(number)
    if key.startswith("section_fan_"):
        from app.pz.section_fan import SectionFanInput
        if key == "section_fan_working_diameter_mm" and number.is_integer():
            number = int(number)
        try:
            SectionFanInput(**{key.removeprefix("section_fan_"):number})
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
        return number
    if key.startswith(("section_k1_", "section_k2_")):
        from app.pz.wastewater_presentation import SectionMainInput
        name = key.split("_", 2)[2]
        if name in {"dn_mm", "fixtures_count"} and number.is_integer():
            number = int(number)
        try:
            SectionMainInput(**{name: number})
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
        return number
    rain_key = key.removeprefix("rainwater_")
    if key.startswith("rainwater_") and rain_key in RAIN_TREATMENT_NUMBERS:
        if not math.isfinite(number) or number < 0 or (number == 0 and not RAIN_TREATMENT_NUMBERS[rain_key]) or number > 1e6:
            raise IntakeError("Подготовка воды: требуется допустимое неотрицательное число; расход должен быть положительным.")
        return number
    if key.startswith("rainwater_") and rain_key in RAIN_PUMP_NUMBERS:
        zero, signed = RAIN_PUMP_NUMBERS[rain_key]
        if not math.isfinite(number) or abs(number) > 1e6 or (not signed and (number < 0 or (number == 0 and not zero))):
            raise IntakeError("Некорректное значение параметра насоса/шланга.")
        if field.kind == "integer":
            if not number.is_integer() or number > 1000:
                raise IntakeError("Укажите целое количество от 1 до 1000.")
            return int(number)
        return number
    if key == "rainwater_collection_factor" and number > 1:
        raise IntakeError("Коэффициент сбора должен быть не больше 1.")
    if key in {"water_inlet_elevation_m", "station_floor_elevation_m", "station_suction_elevation_m"}:
        if not math.isfinite(number) or abs(number) > 1000:
            raise IntakeError("Укажите конечную относительную отметку в пределах ±1000 м.")
        return number
    if key == "basement_floor_m":
        if not math.isfinite(number) or number >= 0:
            raise IntakeError("Отметка подвала должна быть ниже пола первого этажа 0,000, например −3,100.")
        return number
    minimum_zero = (key.startswith("meter_min_") and key.endswith("_m3h")) or key in {
        "v1_sectional_valves_count",
        *("water_service_" + key for key in SERVICE_COUNTS),
        "hws_balance_count", "hws_balance_collector_count",
        "apartment_units_cold_count", "apartment_units_hot_count",
        "rainwater_design_annual_saving_m3",
        "fire_corridor_length_m",
        "guaranteed_head_m",
        "fire_height_m",
        "h_geom_m",
        "h_il_m",
        "h_il_hot_m",
        "h_vvod_m",
        "h_apartment_c_meter_m",
        "h_apartment_h_meter_m",
        "h_tepl_m",
        "storm_walls_area_m2",
    }
    if not math.isfinite(number) or number < 0 or (number == 0 and not minimum_zero):
        raise IntakeError(
            "Укажите неотрицательное число."
            if minimum_zero
            else "Укажите число больше нуля."
        )
    if field.kind == "integer":
        if not number.is_integer() or number > 1_000_000:
            raise IntakeError("Укажите целое положительное число, не более 1 000 000.")
        return int(number)
    return number


def extract_candidates(text: str, document_id: str, page: int) -> list[dict]:
    text = text.replace("\xa0", " ")
    candidates = []
    for key, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            # A range, tolerance, or comparison is not a scalar project input.
            tail = text[match.end() : match.end() + 20]
            if re.match(r"\s*(?:[-–—±+/]|до\b)", tail):
                continue
            if FIELD_MAP[key].kind == "integer" and re.match(r"(?:\s+\d|\s*%)", tail):
                continue
            try:
                value = validate_value(key, match.group("value"))
            except IntakeError:
                continue
            candidates.append(
                {
                    "field": key,
                    "value": value,
                    "document_id": document_id,
                    "page": page,
                    "quote": match.group(0).strip()[:220],
                }
            )
    return candidates


def read_document(content: bytes, name: str) -> dict:
    if not name.lower().endswith(".pdf") or not content.startswith(b"%PDF-"):
        raise IntakeError("Принимаются только PDF-документы.")
    if len(content) > MAX_FILE_BYTES:
        raise IntakeError("Один PDF должен быть не больше 10 МБ.")
    document_id = hashlib.sha256(content).hexdigest()[:24]
    # User supplied paths are never used for storage.
    name = name.replace("\\", "/").rsplit("/", 1)[-1][:180]
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise IntakeError("PDF защищён паролем. Загрузите доступную копию.")
        if not 0 < len(reader.pages) <= MAX_PAGES:
            raise IntakeError("Поддерживаются PDF от 1 до 100 страниц.")
        candidates, readable, failed = [], 0, 0
        truncated = False
        for page_number, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ""
                truncated = truncated or len(text) > MAX_PAGE_TEXT
                text = text[:MAX_PAGE_TEXT]
            except Exception:
                text = ""
                failed += 1
            if text.strip():
                readable += 1
                candidates.extend(extract_candidates(text, document_id, page_number))
                if len(candidates) > 250:
                    raise IntakeError(
                        "Слишком много исходных значений в PDF. Загрузите только нужные страницы ТЗ/ТУ."
                    )
        return {
            "id": document_id,
            "name": name,
            "bytes": len(content),
            "pages": len(reader.pages),
            "text_pages": readable,
            "status": "scan"
            if readable == 0
            else "partial"
            if readable < len(reader.pages) or failed or truncated
            else "text",
            "candidates": candidates,
        }
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError(
            "Не удалось прочитать PDF. Проверьте файл и повторите загрузку."
        ) from exc


def candidates_for(draft: dict, key: str) -> list[dict]:
    return [
        item
        for doc in draft["documents"]
        for item in doc["candidates"]
        if item["field"] == key
    ]


def candidate_hash(candidates: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(candidates, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def field_state(draft: dict, field: Field) -> dict:
    candidates = candidates_for(draft, field.key)
    answer = draft["answers"].get(field.key)
    if answer is None and not candidates and field.key in {"h_apartment_c_meter_m", "h_apartment_h_meter_m"}:
        estimate = apartment_meter_estimate(draft)
        row = (estimate or {}).get("rows", {}).get(field.key)
        if row:
            return {**asdict(field), "status": "default", "value": row["loss_m"],
                    "previous_value": None, "candidates": [],
                    "source": {"kind": "apartment_estimate", "evidence": [],
                               "note": estimate["basis"], **row}}
    if (answer is None and not candidates and field.key in DEFAULTS
            and not (draft.get("study") and field.key == "vu_per_inlet")):
        default = DEFAULTS[field.key]
        if field.key == "vu_per_inlet" and draft.get("metering_default") == "per_inlet":
            default = "yes"
        # Preserve pre-existing drafts; never silently reinterpret ready totals.
        if field.key == "pressure_loss_mode" and any(
            key in draft["answers"] for key in ("h_il_m", "h_vvod_m")
        ):
            default = "ready"
        if field.key == "t3_loss_mode":
            answers = draft["answers"]
            old_ready = any(k in answers for k in ("h_il_m", "h_vvod_m")) and answers.get("pressure_loss_mode", {}).get("value") != "sections"
            if "h_il_hot_m" in answers or old_ready:
                default = "ready"
        return {
            **asdict(field),
            "status": "default",
            "value": default,
            "previous_value": None,
            "source": {"kind": "core_default", "evidence": []},
            "candidates": [],
        }
    unique = {row["value"] for row in candidates}
    confirmed = answer is not None and (
        all(value == answer["value"] for value in unique)
        or answer["candidates_hash"] == candidate_hash(candidates)
    )
    status = (
        "confirmed"
        if confirmed
        else "conflict"
        if len(unique) > 1 or (answer and candidates)
        else "review"
        if candidates
        else "missing"
    )
    return {
        **asdict(field),
        "status": status,
        "value": answer["value"] if confirmed else None,
        "previous_value": answer["value"] if answer else None,
        "source": answer.get("source") if confirmed else None,
        "candidates": candidates,
    }


def accepted_values(draft: dict) -> dict:
    return {
        field.key: item["value"]
        for field in FIELDS
        if (item := field_state(draft, field))["status"] in {"confirmed", "default"}
    }


def apartment_meter_estimate(draft: dict) -> dict | None:
    values = {}
    for key in ("residents", "apartments", "consumer_code", "hws_type", "apartment_design_residents"):
        row = field_state(draft, FIELD_MAP[key])
        if row["status"] in {"confirmed", "default"}:
            values[key] = row["value"]
    try:
        return estimate_apartment_meters(values)
    except ValueError:
        # Unsupported demands must not break saving a draft or turn into zeros.
        return None


def apartment_meter_basis(draft: dict) -> str:
    uses_estimate = any(
        (field_state(draft, FIELD_MAP[key])["source"] or {}).get("kind") == "apartment_estimate"
        for key in ("h_apartment_c_meter_m", "h_apartment_h_meter_m")
    )
    return (apartment_meter_estimate(draft) or {}).get("basis", "") if uses_estimate else ""


def active_apartment_estimate(draft: dict, fields: list[dict]) -> dict | None:
    """Expose only applied automatic rows, never replace explicit/manual evidence."""
    active = {row["key"] for row in fields
              if (row["source"] or {}).get("kind") == "apartment_estimate"}
    if not active:
        return None
    estimate = apartment_meter_estimate(draft)
    return {**estimate, "rows": {key: row for key, row in estimate["rows"].items() if key in active}}


def answer_field(draft: dict, key: str, raw, *, _defer_registry=False) -> None:
    if draft.get('study', {}).get('kind') == 'samara':
        raise IntakeError('Самарский контрольный пример имеет фиксированные проверенные исходные. Для другого объекта вернитесь к своему проекту.')
    if draft.get("study"):
        from app.intake.studio_study import EDITABLE
        if key not in EDITABLE:
            raise IntakeError("В учебной компоновке меняются жители, город, площадь и вид кровли. Для других исходных вернитесь к проекту.")
    value = validate_value(key, raw)
    if key in {"sewer_pipes", "sewer_elements", "wastewater_fan_ventilation", "sewage_risers"} and not _defer_registry:
        proposed = {**accepted_values(draft), key: value}
        try:
            studio_sewer_elements.validate_network(proposed)
            studio_fans.validate_links(proposed)
            studio_risers.validate_links(proposed)
        except ValueError as exc:
            raise IntakeError(str(exc), source=exc) from exc
    if key == 'vu_per_inlet' and value == 'no' and field_state(draft, FIELD_MAP[key])['value'] != 'no':
        draft['common_vu_topology'] = 'gost_g1'
    if key in {f"section_{system}_{end}_invert_m" for system in ("k1", "k2") for end in ("start", "outlet")}:
        # Reject a counter-slope BEFORE persisting either end of the declared
        # gravity main. This does not introduce the separate hydraulic study.
        from app.pz.wastewater_presentation import SectionMainInput
        prefix = key.rsplit("_", 3)[0]  # section_k1 / section_k2
        proposed = accepted_values(draft)
        proposed[key] = value
        try:
            SectionMainInput(start_invert_m=proposed.get(prefix+"_start_invert_m"),
                             outlet_invert_m=proposed.get(prefix+"_outlet_invert_m"))
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    if key.startswith(("section_k1_", "section_k2_")):
        # Validate dependent geometry BEFORE saving; a bad wall thickness must
        # not leave an unopenable draft or consume a successful revision.
        from app.intake.studio_section import section_main
        proposed = accepted_values(draft)
        if value is None:
            proposed.pop(key, None)
        else:
            proposed[key] = value
        try:
            section_main(proposed, key.split("_")[1])
        except ValueError as exc:
            raise IntakeError(str(exc)) from exc
    if key in QUICK_START_PRESETS:
        excluded = set(draft.get("preset_exclusions", []))
        if value is None:
            excluded.add(key)
        else:
            excluded.discard(key)
        draft["preset_exclusions"] = sorted(excluded)
    if value is None:
        draft["answers"].pop(key, None)
    else:
        candidates = candidates_for(draft, key)
        evidence = [row for row in candidates if row["value"] == value]
        draft["answers"][key] = {
            "value": value,
            "candidates_hash": candidate_hash(candidates),
            "source": {
                "kind": "document_confirmed" if evidence else "user",
                "evidence": evidence,
            },
        }
    if key in DEMAND_FIELDS:
        draft["calculation"] = None
    draft["project_calculation"] = None
    draft["package"] = None
    draft["preview"] = None


def answer_visible_form(draft: dict, answers: dict, preset_keys: list[str]) -> None:
    """Adopt the displayed form atomically; never silently populate core inputs."""
    original = draft
    draft = deepcopy(draft)
    if len(answers) > len(FIELDS) or len(preset_keys) != len(set(preset_keys)):
        raise IntakeError("Некорректный набор исходных данных.")
    for key in preset_keys:
        if key not in QUICK_START_PRESETS or key not in answers:
            raise IntakeError("Неизвестный типовой вариант.")
        row = field_state(draft, FIELD_MAP[key])
        if (
            row["status"] != "missing"
            or answers[key] != QUICK_START_PRESETS[key]
            or key in draft.get("preset_exclusions", [])
        ):
            raise IntakeError("Типовой вариант не может заменить данные проекта или PDF.")
    for key, value in answers.items():
        try:
            answer_field(draft, key, value, _defer_registry=True)
        except IntakeError as exc:
            label = FIELD_MAP[key].label if key in FIELD_MAP else key
            raise IntakeError(f"{label}: {exc}", source=exc) from exc
        if key in preset_keys:
            draft["answers"][key]["source"]["kind"] = "residential_preset"
    if {"sewer_pipes", "sewer_elements", "wastewater_fan_ventilation", "sewage_risers"} & answers.keys():
        try:
            studio_sewer_elements.validate_network(accepted_values(draft))
            studio_fans.validate_links(accepted_values(draft))
            studio_risers.validate_links(accepted_values(draft))
        except ValueError as exc:
            raise IntakeError(str(exc), source=exc) from exc
    original.clear()
    original.update(draft)


def calculate_draft(draft: dict) -> dict:
    values = accepted_values(draft)
    missing = [key for key in DEMAND_FIELDS if key not in values]
    if missing:
        raise IntakeError(
            "Подтвердите исходные данные: "
            + ", ".join(FIELD_MAP[key].label for key in missing)
        )
    # Call the existing, legacy-parity-tested core without changing defaults or formulas.
    result = calculate_water_demand(
        [ConsumerGroup(values["consumer_code"], values["residents"])],
        apply_k06=False,
        sewage_max_fixture_lps=values["sewage_max_fixture_lps"],
    )
    return asdict(result)


def fire_missing(draft: dict) -> list[str]:
    """Ask only when the canonical residential resolver needs this input."""
    values = accepted_values(draft)
    if not {"floors", "fire_height_m"}.issubset(values):
        return []
    if "fire_corridor_length_m" in values:
        return []
    result = resolve_table_7_1(
        Table71Category.RESIDENTIAL_F13,
        floors=values["floors"], height_m=values["fire_height_m"],
    )
    return ["fire_corridor_length_m"] if result.manual_review else []


def handoff_missing(draft: dict) -> list[str]:
    values = accepted_values(draft)
    pending = [key for key in HANDOFF_FIELDS if key not in values]
    pending.extend(fire_missing(draft))
    pending.extend(fire_topology_missing(draft))
    # Do not silently leave an imported TU value behind at the bridge to Wizard.
    # An unconfirmed roof quantity is different: keep it unknown in the spec
    # and visible for review, but never block a representative preview on it.
    pending.extend(
        field.key
        for field in FIELDS
        if field.key not in values
        and field.key not in pending
        and field.key != "storm_funnels_count"
        and candidates_for(draft, field.key)
    )
    return pending


def fire_topology_missing(draft: dict) -> list[str]:
    """A hydraulic network type is a decision, not the old auto/combined default."""
    values = accepted_values(draft)
    if "fire_topology" in values or not {"floors", "fire_height_m"}.issubset(values):
        return []
    result = resolve_table_7_1(
        Table71Category.RESIDENTIAL_F13, floors=values["floors"],
        height_m=values["fire_height_m"], corridor_length_m=values.get("fire_corridor_length_m"),
    )
    # Resolve the corridor question first; never infer a solution from a manual verdict.
    return ["fire_topology"] if result.vpv_required and not result.manual_review else []


def context_issues(draft: dict) -> list[str]:
    """Prevent new context fields being silently discarded by the residential bridge."""
    values = accepted_values(draft)
    issues = []
    if values.get("building_purpose", "residential") != "residential" or values.get("technology_presence") == "yes":
        issues.append("Анкета содержит другой тип жилья или нежилых потребителей. Сейчас рассчитана только выбранная жилая группа; полный комплект требует отдельной настройки состава потребителей.")
    if values.get("permafrost") == "yes" or values.get("seismic_zone") == "yes":
        issues.append("Указаны особые условия строительства. Их решения ещё не подключены к генератору; комплект нельзя выдавать как учитывающий эти условия.")
    return issues


def rainwater_input(draft: dict):
    """Only the dedicated review endpoint may write a Studio approval record."""
    data = rainwater_from_studio(accepted_values(draft))
    saved = draft.get("rainwater_review") or {}
    if saved.get("record"):
        data.design_review = dict(saved["record"])
        if saved.get("source") != rainwater_review_source(draft):
            data.design_review["fingerprint"] = "stale"
    return data


def rainwater_review_source(draft: dict):
    return candidate_hash({"answers": draft["answers"], "documents": draft["documents"]})


def build_handoff_request(draft: dict) -> IOS2Request:
    values = accepted_values(draft)
    if issues := context_issues(draft):
        raise IntakeError(" ".join(issues))
    demand = calculate_draft(draft)  # No unreviewed/conflicting demand inputs.
    missing = handoff_missing(draft)
    if missing:
        raise IntakeError(
            "Для расчёта проекта подтвердите: "
            + ", ".join(FIELD_MAP[key].label for key in missing)
        )
    by_sections = values.get("pressure_loss_mode") == "sections"
    hot_sections = values.get("t3_loss_mode") == "sections" and values["hws_type"] != "none"
    rows = values.get("v1_sections", [])
    auto_inlet_ready = (
        not any(row["flow_lps"] is None for row in rows)
        or values["hws_type"] in {"none", "local"}
        or "hws_heater_in_scope" in values
    )
    station_model = values.get("fire_station_model")
    cabinet = station_model["cabinet"] if station_model else None
    from app.schemas.pump_suction import persisted_suction
    return IOS2Request(
        suction_check=persisted_suction(draft),
        apartment_water_units=apartment_units_from_values(values),
        hws_stage_p=hws_stage_p_from_values(values),
        **design_basis.request_fields(values),
        fire_station_model=station_model,
        **({"cabinet_dn": cabinet["dn"], "nozzle_mm": cabinet["nozzle_mm"],
            "hose_length_m": cabinet["hose_length_m"], "compact_jet_m": cabinet["compact_jet_m"]}
           if cabinet else {}),
        rainwater_reuse=rainwater_input(draft),
        wastewater_service=wastewater_service_from_studio(values),
        metering_detail=studio_layout_choices(MeteringDetailData(
            russian_equipment_only=values.get("russian_equipment_only") == "yes",
            mounting={"enabled": True, "scale": int(values.get("vu_drawing_scale", "5"))},
            inlet_elevation_m=values.get("water_inlet_elevation_m"),
            enhancements={
            key: values["vu_" + key] for key in METERING_OPTIONS if "vu_" + key in values
        }), values, common_topology=draft.get("common_vu_topology", "merge_before")),
        document=DocumentRequest("", values.get("object_name", ""), ""),
        building_type="residential",
        total_area_m2=values.get("building_area_m2", 0),
        floors=values.get("floors", 0),
        building_height_m=values.get("building_height_m", 0),
        residents=values["residents"],
        apartments=values.get("apartments", 0),
        risers_v1=values.get("risers_v1", 0),
        risers_t3=values.get("risers_t3", 0) if values["hws_type"] == "central" else 0,
        risers_t4=values.get("risers_t4", 0) if values["hws_type"] == "central" else 0,
        v1_sectional_valves_count=values.get("v1_sectional_valves_count"),
        v1_sectional_valves_basis=values.get("v1_sectional_valves_basis", ""),
        water_service_layout=service_layout_from_values(values),
        floor_elevations_m={
            **({floor: (floor - 1) * values["floor_height_m"]
                for floor in range(1, values["floors"] + 1)}
               if "floor_height_m" in values else {1: 0.0}),
            **({-1: values["basement_floor_m"]}
               if values.get("basement_kind") in {"basement", "subfloor"}
               and "basement_floor_m" in values else {}),
        },
        hws_type=values["hws_type"],
        fire_mode="auto",
        fire_category="residential_f13",
        fire_topology=values.get("fire_topology", "auto"),
        fire_topology_basis=("Схема связи В1/В2 выбрана проектировщиком в Studio."
                             if "fire_topology" in values else ""),
        fire_height_m=values.get("fire_height_m"),
        fire_corridor_length_m=values.get("fire_corridor_length_m"),
        source_data=SourceDataRequest(
            **design_basis.source_fields(values),
            basis=("Условия подключения, введённые в Studio: " + values["connection_note"]
                   if values.get("connection_note") else ""),
            apartment_meter_basis=apartment_meter_basis(draft),
            meter_minimum_checks=minimum_checks(values),
            **{
                key: values[key]
                for key in (
                    "station_room_number",
                    "station_floor_elevation_m",
                    "station_suction_elevation_m",
                    "guaranteed_head_m",
                    "inputs_count",
                    "h_geom_m",
                    "h_il_m",
                    "h_il_hot_m",
                    "h_vvod_m",
                    "h_apartment_c_meter_m",
                    "h_apartment_h_meter_m",
                    "h_pr_m",
                    "h_tepl_m",
                )
                if key in values and not (by_sections and key in {"h_il_m", "h_vvod_m"})
                and not (hot_sections and key == "h_il_hot_m")
            },
            hws_heater_in_scope=values.get("hws_heater_in_scope") == "yes",
            internal_losses_scope="cold_only" if by_sections or hot_sections or "h_il_hot_m" in values or "t3_loss_mode" in draft["answers"] else "shared",
        ),
        t3_sections=[T3SectionInput(**row) for row in values.get("t3_sections", [])] if hot_sections else [],
        v1_sections=section_requests(
            rows, demand, heater_in_scope=values.get("hws_heater_in_scope") == "yes",
            hws_type=values["hws_type"],
        ) if by_sections and sections_complete(rows) and auto_inlet_ready else [],
        consumers=[
            ConsumerGroupRequest(
                values["consumer_code"], values["residents"], "Жилая часть"
            )
        ],
        sewage_max_fixture_lps=values["sewage_max_fixture_lps"],
        roof_type=roof_rule(values.get("roof_type"))["rain_type"],
        wastewater_presentation=representative_presentation(values),
        sewer_pipes=[SewerPipeRequest(**row) for row in values.get("sewer_pipes", [])],
        sewer_elements=[SewerElementRequest(**row) for row in values.get("sewer_elements", [])],
        sewage_risers=[SewageRiserRequest(**row) for row in values.get("sewage_risers", [])],
        wastewater_fan_ventilation=studio_fans.from_values(values),
        wastewater_roof_kind=roof_rule(values.get("roof_type"))["fan_kind"],
        floors_below=1 if values.get("basement_kind") in {"basement", "subfloor"} else 0,
        wastewater_basement_floor_elevation_m=(values.get("basement_floor_m")
            if values.get("basement_kind") in {"basement", "subfloor"} else None),
        wastewater_floor_height_m=values.get("floor_height_m"),
        wastewater_roof_relative_elevation_m=values.get("section_fan_roof_level_m"),
        storm_city=values.get("storm_city", ""),
        storm_roof_area_m2=values.get("storm_roof_area_m2", 0),
        storm_walls_area_m2=values.get("storm_walls_area_m2", 0),
        storm_funnels_count=values.get("storm_funnels_count", 0),
        storm_selected_riser_dn_mm=values.get("storm_selected_riser_dn_mm", 0),
        storm_risers_count=values.get("storm_risers_count", 0),
        storm_max_riser_flow_lps=values.get("storm_max_riser_flow_lps"),
        storm_funnels_on_different_levels=values.get("storm_funnels_on_different_levels") == "yes",
    )


def head_missing(draft: dict) -> list[str]:
    values = accepted_values(draft)
    keys = HEAD_FIELDS
    route_missing = False
    if values.get("pressure_loss_mode") == "sections":
        keys = tuple(key for key in keys if key not in {"h_il_m", "h_vvod_m"})
        route_missing = not sections_complete(values.get("v1_sections"))
    if values.get("hws_type") != "none":
        if values.get("t3_loss_mode") == "sections":
            rows = values.get("t3_sections", [])
            if not rows or calculate_t3_hydraulics([T3SectionInput(**r) for r in rows]).missing:
                # Include the editor even if a partial route has been saved.
                keys += ("t3_sections",)
                values = {k: v for k, v in values.items() if k != "t3_sections"}
        elif values.get("pressure_loss_mode") == "sections" or "h_il_hot_m" in values or "t3_loss_mode" in draft["answers"]:
            keys += ("h_il_hot_m",)
        keys += ("h_apartment_h_meter_m", "hws_heater_in_scope")
        if values.get("hws_heater_in_scope") == "yes":
            keys += ("h_tepl_m",)
            if not values.get("h_tepl_m"):
                # The core cannot confirm an in-scope heater with zero loss.
                # Keep the reason visible even when the user previously entered 0.
                values = {k: v for k, v in values.items() if k != "h_tepl_m"}
    return [key for key in keys if key not in values] + (["v1_sections"] if route_missing else [])


def next_steps(draft: dict) -> list[dict]:
    """Small, contextual input groups. Order is UX, never a calculation rule."""
    if not draft.get("calculation"):
        return []
    values = accepted_values(draft)
    groups = []

    def add(key, title, description, fields):
        pending = [name for name in fields if name not in values]
        if pending:
            groups.append(dict(id=key, title=title, description=description, fields=pending))

    review = [
        field.key for field in FIELDS
        if field_state(draft, field)["status"] in {"review", "conflict"}
    ]
    if review:
        add("sources", "Проверим данные из документов",
            "Показаны цитаты-источники. При расхождении выберите верное значение.", review[:3])
    add("building", "Параметры здания",
        "Нужны для расчёта проекта и проверки необходимости пожарного водопровода.",
        HANDOFF_FIELDS)
    add("fire", "Уточнение для проверки В2",
        "Уточните длину общего коридора по АР и принятое решение В1/В2. Расходы воды уже рассчитаны.",
        fire_missing(draft) + fire_topology_missing(draft))
    from app.intake.studio_section import section_readiness
    add("section", "Соберём разрез дома",
        "Стояки и выпуски ЗАРЯ нарисует сама. Нужны только параметры этажа, подвала и водостока.",
        section_readiness(values)["missing"])
    missing_head = head_missing(draft)
    add("supply", "Напор: ввод и диктующий прибор",
        "Возьмите напор из ТУ и перепад отметок до диктующего прибора. По этажности их не угадываем.",
        [key for key in ("guaranteed_head_m", "h_geom_m", "hws_heater_in_scope") if key in missing_head])
    # Stage P intake is not a mandatory section-by-section hydraulic editor.
    # The route and ready totals remain available in manual settings. Missing
    # losses still prevent a confirmed head/pump, never the other calculations.
    add("storm", "Дождевые воды",
        "Укажите город и водосборную площадь. Если примыкающих стен нет, их площадь — 0.",
        STORM_FIELDS)
    return groups


def public_draft(draft: dict) -> dict:
    from app.intake.studio_study import public_study
    from app.data.metering_extras import catalogue_option_details
    fields = [field_state(draft, field) for field in FIELDS]
    required = [
        row
        for row in fields
        if row["key"] in DEMAND_FIELDS and row["status"] not in {"confirmed", "default"}
    ]
    return {
        "revision": draft["revision"],
        "sewer_pipe_editor": {"columns": editor_columns(), "max_rows": MAX_SEWER_ROWS},
        "sewer_element_editor": {"columns": studio_sewer_elements.editor_columns(), "max_rows": studio_sewer_elements.MAX_ROWS},
        "fan_editor": {"columns": studio_fans.editor_columns(), "max_rows": studio_fans.MAX_ROWS},
        "riser_editor": {"columns": studio_risers.editor_columns(), "max_rows": studio_risers.MAX_ROWS},
        "study": public_study(draft),
        "roof_rules": {key: roof_rule(key) for key in (*ROOF_CHOICES, "flat", "sloped")},
        "roof_ventilation": roof_rule(accepted_values(draft).get("roof_type")),
        "quick_start_presets": {
            key: value for key, value in QUICK_START_PRESETS.items()
            if key not in draft.get("preset_exclusions", [])
        },
        "fields": fields,
        "design_basis": design_basis.assess(accepted_values(draft)),
        "metering_catalogue": catalogue_option_details(),
        "wastewater_service": assess_wastewater_service(wastewater_service_from_studio(accepted_values(draft))),
        "rainwater_reuse": assess_rainwater(rainwater_input(draft),
            building_kind=accepted_values(draft).get("building_purpose", "residential"),
            roof_kind=accepted_values(draft).get("roof_type")),
        "apartment_meters": active_apartment_estimate(draft, fields),
        "documents": [
            {key: value for key, value in doc.items() if key != "candidates"}
            for doc in draft["documents"]
        ],
        "can_calculate": not required,
        "next_question": required[0]["key"] if required else None,
        "handoff_missing": handoff_missing(draft),
        "calculation": draft.get("calculation"),
        "project_calculation": draft.get("project_calculation"),
        "package": draft.get("package"),
        "preview": draft.get("preview"),
        "next_steps": [] if draft.get("study") else next_steps(draft),
        "options": {
            key: [{"value": value, "label": label} for value, label in choices.items()
                  if key != "roof_type" or value in ROOF_CHOICES]
            for key, choices in OPTIONS.items()
        },
        "head_missing": head_missing(draft),
        "storm_missing": [
            key for key in STORM_FIELDS if key not in accepted_values(draft)
        ],
        "norms": [
            {"value": key, "label": norm.label, "daily_litres": norm.qu_tot}
            for key, norm in RESIDENTIAL_NORMS.items()
        ],
        "hws_options": [
            {"value": key, "label": label} for key, label in HWS_OPTIONS.items()
        ],
    }

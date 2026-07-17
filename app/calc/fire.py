"""
Расчёт расхода на внутреннее пожаротушение (ВПВ) по СП 10.13130.2020.

Числовая таблица 7.3 перенесена 1-в-1 из legacy/sp30_calculator.html. Область
применения и нормативные минимумы проверяются по СП 10.13130.2020: legacy
использует 2,6 л/с как удобную базу выбранного ПК, тогда как таблицы 7.1/7.2
задают минимум 2,5 л/с, а фактический расход определяется таблицей 7.3.

Логика:
  1. По типу здания и его параметрам определяем число струй n и базовый расход q
     (таблица 7.1 для жилых/общественных, 7.2 для производственных)
  2. Из таблицы 7.3 берём расход диктующего ПК (q_dikt) по выбранному оборудованию
  3. Q_пож = n × q_dikt

Если для здания ВПВ не требуется — возвращаем None (required=False).
"""
from dataclasses import dataclass
from typing import Literal, Optional

from app.calc.fire_table_7_1 import (
    Table71Category,
    resolve_table_7_1,
    resolve_table_7_2,
)
from app.data.fire_tables import get_nozzle_data


# Типы зданий (соответствуют HTML)
BuildingType = Literal[
    "f13",          # Ф1.3 многоквартирные жилые
    "f12_hotel",    # Ф1.2 гостиницы
    "f12_hostel",   # Ф1.2 общежития коридорного типа
    "f11",          # Ф1.1 больницы, дома престарелых, интернаты
    "f21_theater",  # Ф2.1 театры, кинотеатры, концертные залы, клубы, цирки
    "f21_lib",      # Ф2.1 библиотеки, архивы, спортивные сооружения
    "f22",          # Ф2.2 музеи, выставки / Ф3.1 магазины
    "f_office",     # Ф1.2/Ф3.4/Ф3.6/Ф4.2/Ф4.3 офисы и пр.
    "f5",           # Ф5.1/Ф5.2 производственные и складские
]


@dataclass
class FireInput:
    """Входные данные расчёта ВПВ."""
    building_type: BuildingType
    floors: int = 1                     # этажность
    height_m: Optional[float] = None     # высота здания; определяющая по сноске **
    # Доп. параметры (нужны для отдельных типов)
    corridor_length_m: Optional[float] = None  # длина коридора (для Ф1.3)
    seats: Optional[int] = None               # вместимость зала (для Ф2.1 театры)
    area_m2: Optional[float] = None            # общая площадь (для Ф2.1 библ.)
    # Параметры производственных зданий (Ф5)
    fire_degree: str = "I_II"           # степень огнестойкости: I_II / III / IV / V
    category: str = "V"                 # категория: AB / V / GD
    construction_class: str = "C0"      # класс конструктивной опасности: C0 / C1 / C2 / C3
    volume_thousand_m3: float = 5.0     # объём здания, тыс. м³
    # Параметры пожарного крана (для таблицы 7.3)
    dn: int = 50                        # диаметр клапана: 50 / 65
    nozzle_mm: int = 13                 # диаметр ствола: 13 / 16 / 19
    hose_m: int = 20                    # длина рукава: 10 / 15 / 20
    jet_m: int = 12                     # высота струи: 6...20


@dataclass
class FireResult:
    """Результат расчёта ВПВ."""
    required: bool                          # требуется ли ВПВ
    streams: int = 0                        # число струй n
    q_per_stream: float = 0.0               # расход диктующего ПК, л/с
    q_total: float = 0.0                    # Q_пож = n × q, л/с
    pressure_mpa: Optional[float] = None    # давление у клапана, МПа
    table_used: str = ""                    # "7.1" или "7.2"
    nozzle_found: bool = True               # найдена ли комбинация в табл. 7.3
    pressure_control_required: bool = False # диафрагма/регулятор по п. 7.5
    message: str = ""                       # пояснение


def _get_t71(
    building_type: str,
    floors: int,
    corridor_length: Optional[float],
    seats: Optional[int],
    area: Optional[float],
    height_m: Optional[float] = None,
) -> Optional[tuple[int, float]]:
    """
    Таблица 7.1 — жилые и общественные здания.
    Возвращает (число_струй, базовый_расход) или None если ВПВ не требуется.
    """
    categories = {
        "f13": Table71Category.RESIDENTIAL_F13,
        "f_office": Table71Category.OFFICE_PUBLIC,
        "f12_hotel": Table71Category.OFFICE_PUBLIC,
        "f12_hostel": Table71Category.DORMITORY_F12,
        "f11": Table71Category.HOSPITAL_F11,
        "f21_theater": Table71Category.THEATRE_F21,
        "f21_lib": Table71Category.LIBRARY_SPORT,
        "f22": Table71Category.MUSEUM_TRADE,
    }
    category = categories.get(building_type)
    if category is None:
        return None
    result = resolve_table_7_1(
        category,
        floors=floors,
        height_m=height_m,
        corridor_length_m=corridor_length,
        hall_seats=seats,
        total_area_m2=area,
    )
    if result.manual_review:
        raise ValueError("Требуется ручная проверка по СП 10: " + "; ".join(result.notes))
    if not result.vpv_required:
        return None
    return result.jets, result.q_per_jet_lps


def _get_t72(
    fire_degree: str,
    category: str,
    construction_class: str,
    volume_thousand_m3: float,
    height_m: Optional[float] = None,
) -> Optional[tuple[int, float]]:
    """
    Таблица 7.2 — производственные и складские здания.
    Возвращает (число_струй, базовый_расход) или None.
    """
    if height_m is None:
        raise ValueError(
            "Для производственного/складского здания задайте высоту: "
            "таблица 7.2 СП 10 применима только до 50 м включительно"
        )
    if height_m > 50.0:
        if volume_thousand_m3 > 150.0:
            return 4, 5.0  # п. 7.13 СП 10
        raise ValueError(
            "Производственное здание выше 50 м при объёме не более 150 тыс. м³ "
            "находится вне таблицы 7.2 и условия п. 7.13 СП 10"
        )
    if fire_degree == "I_II" and category == "GD":
        return None  # правило canonical legacy для отсутствующей строки таблицы
    degree = "I" if fire_degree == "I_II" else fire_degree
    hazard = {"AB": "А", "V": "В", "GD": "Г"}[category]
    structural = construction_class.replace("C", "С")
    result = resolve_table_7_2(
        degree, hazard, structural, volume_thousand_m3,
    )
    if result.manual_review:
        raise ValueError("Требуется ручная проверка по СП 10: " + "; ".join(result.notes))
    if not result.vpv_required:
        return None
    return result.jets, result.q_per_jet_lps


def calculate_fire(data: FireInput) -> FireResult:
    """
    Главная функция расчёта ВПВ.

    Returns:
        FireResult. Если ВПВ не требуется — required=False.
    """
    # Определяем число струй и базовый расход
    if data.building_type == "f5":
        res = _get_t72(
            data.fire_degree, data.category,
            data.construction_class, data.volume_thousand_m3, data.height_m,
        )
        table_used = (
            "п. 7.13" if (data.height_m or 0) > 50 and data.volume_thousand_m3 > 150
            else "7.2"
        )
    else:
        res = _get_t71(
            data.building_type, data.floors,
            data.corridor_length_m, data.seats, data.area_m2, data.height_m,
        )
        table_used = "7.1"

    if res is None:
        return FireResult(
            required=False,
            table_used=table_used,
            message="Внутренний противопожарный водопровод не требуется "
                    "(по таблице {} СП 10.13130.2020)".format(table_used),
        )

    n_streams, q_base = res

    if data.height_m is None:
        raise ValueError(
            "Для проверки высоты компактной части струи по п. 7.15 СП 10 "
            "задайте высоту здания"
        )
    if data.height_m > 50.0:
        minimum_jet_m = 8 if data.building_type == "f13" else 16
    else:
        minimum_jet_m = 6
    if data.jet_m < minimum_jet_m:
        raise ValueError(
            f"Высота компактной части струи {data.jet_m} м меньше минимума "
            f"{minimum_jet_m} м по п. 7.15 СП 10"
        )

    # Данные диктующего ПК из таблицы 7.3
    nozzle = get_nozzle_data(data.dn, data.nozzle_mm, data.hose_m, data.jet_m)

    if nozzle is None:
        # Комбинация не найдена — используем базовый расход из 7.1/7.2
        return FireResult(
            required=True,
            streams=n_streams,
            q_per_stream=q_base,
            q_total=round(n_streams * q_base, 2),
            pressure_mpa=None,
            table_used=table_used,
            nozzle_found=False,
            message="Комбинация оборудования не найдена в таблице 7.3 — "
                    "использован базовый расход из таблицы {}".format(table_used),
        )

    # Расход диктующего ПК и итог
    q_dikt = nozzle.q
    if q_dikt < q_base:
        raise ValueError(
            f"Выбранный ПК даёт {q_dikt:g} л/с, что меньше нормативного минимума "
            f"{q_base:g} л/с по {table_used} СП 10; выберите другое оборудование"
        )
    q_total = n_streams * q_dikt
    pressure_control_required = nozzle.p > 0.45
    pressure_note = (
        "; давление у ПК более 0,45 МПа — требуется диафрагма или регулятор "
        "давления по п. 7.5 СП 10"
        if pressure_control_required else ""
    )

    return FireResult(
        required=True,
        streams=n_streams,
        q_per_stream=q_dikt,
        q_total=round(q_total, 2),
        pressure_mpa=nozzle.p,
        table_used=table_used,
        nozzle_found=True,
        pressure_control_required=pressure_control_required,
        message="ВПВ: {} струи × {} л/с = {} л/с{}".format(
            n_streams, q_dikt, round(q_total, 2), pressure_note,
        ),
    )

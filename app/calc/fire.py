"""
Расчёт расхода на внутреннее пожаротушение (ВПВ) по СП 10.13130.2020.

Алгоритм 1-в-1 из legacy/sp30_calculator.html (функции getFireT71, getFireT72, calcFire).

Логика:
  1. По типу здания и его параметрам определяем число струй n и базовый расход q
     (таблица 7.1 для жилых/общественных, 7.2 для производственных)
  2. Из таблицы 7.3 берём расход диктующего ПК (q_dikt) по выбранному оборудованию
  3. Q_пож = n × q_dikt

Если для здания ВПВ не требуется — возвращаем None (required=False).
"""
from dataclasses import dataclass
from typing import Literal, Optional

from app.data.fire_tables import FireNozzleData, get_nozzle_data


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
    # Доп. параметры (нужны для отдельных типов)
    corridor_length_m: float = 0.0      # длина коридора (для Ф1.3)
    seats: int = 0                      # вместимость зала (для Ф2.1 театры)
    area_m2: float = 0.0                # общая площадь (для Ф2.1 библ. / Ф2.2)
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
    message: str = ""                       # пояснение


def _get_t71(
    building_type: str,
    floors: int,
    corridor_length: float,
    seats: int,
    area: float,
) -> Optional[tuple[int, float]]:
    """
    Таблица 7.1 — жилые и общественные здания.
    Возвращает (число_струй, базовый_расход) или None если ВПВ не требуется.
    """
    if building_type == "f13":
        # Многоквартирные жилые Ф1.3
        if floors < 12:
            return None  # ВПВ не требуется
        if floors <= 16:
            return (2, 2.6) if corridor_length > 10 else (1, 2.6)
        return (2, 2.6)  # 17-25 и выше

    if building_type == "f_office":
        if floors < 6:
            return None
        if floors <= 10:
            return (1, 2.6)
        return (2, 2.6)

    if building_type == "f12_hotel":
        if floors < 6:
            return None
        if floors <= 10:
            return (1, 2.6)
        return (2, 2.6)

    if building_type == "f12_hostel":
        if floors <= 10:
            return (1, 2.6)
        return (2, 2.6)

    if building_type == "f11":
        # Больницы, дома престарелых — независимо от объёма
        if floors <= 3:
            return (1, 2.6)
        return (2, 2.6)

    if building_type == "f21_theater":
        if seats <= 300:
            return (1, 2.6)
        return (2, 2.6)

    if building_type == "f21_lib":
        if area <= 2500:
            return (1, 2.6)
        return (2, 2.6)

    if building_type == "f22":
        if floors <= 3:
            return (1, 2.6)
        return (2, 2.6)

    return None


def _get_t72(
    fire_degree: str,
    category: str,
    construction_class: str,
    volume_thousand_m3: float,
) -> Optional[tuple[int, float]]:
    """
    Таблица 7.2 — производственные и складские здания.
    Возвращает (число_струй, базовый_расход) или None.
    """
    big = volume_thousand_m3 > 150

    if fire_degree == "I_II":
        if category in ("AB", "V"):
            if construction_class in ("C0", "C1"):
                return (3, 2.6) if big else (2, 2.6)
        if category == "GD":
            return None

    if fire_degree == "III":
        if category in ("AB", "V"):
            if construction_class == "C0":
                return (3, 2.6) if big else (2, 2.6)
        if category == "GD":
            if construction_class in ("C0", "C1"):
                return (2, 2.6) if big else None

    if fire_degree == "IV":
        if category == "AB" and construction_class == "C0":
            return (3, 2.6) if big else (2, 2.6)
        if category == "V":
            if construction_class in ("C0", "C1"):
                return (2, 5.0) if big else (2, 2.6)
            if construction_class in ("C2", "C3"):
                return (4, 2.6) if big else (3, 2.6)
        if category == "GD":
            return (2, 2.6) if big else None

    if fire_degree == "V":
        if category == "V":
            return (2, 5.0) if big else (2, 2.6)
        if category == "GD":
            return (2, 2.6) if big else (1, 2.6)

    return None


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
            data.construction_class, data.volume_thousand_m3,
        )
        table_used = "7.2"
    else:
        res = _get_t71(
            data.building_type, data.floors,
            data.corridor_length_m, data.seats, data.area_m2,
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
    q_total = n_streams * q_dikt

    return FireResult(
        required=True,
        streams=n_streams,
        q_per_stream=q_dikt,
        q_total=round(q_total, 2),
        pressure_mpa=nozzle.p,
        table_used=table_used,
        nozzle_found=True,
        message="ВПВ: {} струи × {} л/с = {} л/с".format(
            n_streams, q_dikt, round(q_total, 2)
        ),
    )
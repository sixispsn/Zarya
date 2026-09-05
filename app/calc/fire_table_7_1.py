# -*- coding: utf-8 -*-
"""Таблицы 7.1 и 7.2 СП 10.13130.2020 с Изменением № 1.

Модуль определяет нормативный минимум одновременно действующих ПК-с и расход
диктующего ПК-с. Числовая таблица 7.3 и гидравлика находятся в других слоях.

Ключевое правило сноски ``**`` таблицы 7.1: диапазон применяется при любом из
событий (этажность ИЛИ пожарно-техническая высота) либо при их совокупности.
Если два заданных показателя попали в разные диапазоны, принимается более
требовательный результат. Ни высота, ни этажность не имеют скрытого приоритета.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Table71Category(str, Enum):
    """Шесть строк таблицы 7.1 в редакции Изменения № 1.

    Старые строковые значения сохранены как стабильные значения DTO/API. Имена
    ``THEATRE_F21``/``LIBRARY_SPORT``/``MUSEUM_TRADE`` оставлены алиасами для
    обратной совместимости сохранённых проектов.
    """

    RESIDENTIAL_F13 = "residential_f13"
    OFFICE_PUBLIC = "office_public"
    HOSPITAL_F11 = "hospital_f11"
    SPORTS_LIBRARY_LAB = "library_sport"
    LIBRARY_SPORT = "library_sport"
    F21_AUDITORIUM = "theatre_f21"
    THEATRE_F21 = "theatre_f21"
    TRADE_PUBLIC_MULTI = "museum_trade"
    MUSEUM_TRADE = "museum_trade"
    # Ф1.2 теперь относится к строке 2. Значение оставлено для старых файлов.
    DORMITORY_F12 = "dormitory_f12"


@dataclass
class Table71Result:
    vpv_required: bool
    jets: int
    q_per_jet_lps: float
    manual_review: bool = False
    notes: List[str] = field(default_factory=list)


def _not_required(note: str) -> Table71Result:
    return Table71Result(False, 0, 0.0, notes=[note])


def _manual(note: str, jets_conservative: int = 2) -> Table71Result:
    return Table71Result(
        True, jets_conservative, 2.5, manual_review=True, notes=[note]
    )


def _jets(n: int, note: str, q: float = 2.5) -> Table71Result:
    return Table71Result(True, n, q, notes=[note])


def _positive(value: Optional[float | int]) -> bool:
    return value is not None and value > 0


def _event_band(
    *,
    floors: Optional[int],
    height_m: Optional[float],
    floor_low: int,
    height_low: float,
    floor_high: int,
    height_high: float,
) -> Optional[int]:
    """Вернуть 0/1 по событию этажности ИЛИ высоты; 1 имеет приоритет."""
    if not _positive(floors) and not _positive(height_m):
        return None
    if (floors or 0) >= floor_high or (height_m or 0) > height_high:
        return 1
    if (floors or 0) >= floor_low or (height_m or 0) >= height_low:
        return 0
    return None


def resolve_table_7_1(
    category: Table71Category,
    *,
    floors: Optional[int] = None,
    height_m: Optional[float] = None,
    corridor_length_m: Optional[float] = None,
    hall_seats: Optional[int] = None,
    total_area_m2: Optional[float] = None,
) -> Table71Result:
    """Разрешить строку таблицы 7.1 в редакции Изменения № 1.

    Категория должна уже учитывать исключения пп. 1.4 и 1.5 (например, ДОО без
    спальных корпусов сюда не передаётся). Неизвестные обязательные исходные
    данные не заменяются значением по умолчанию.
    """
    c = Table71Category(category)

    # Строка 1: Ф1.3.
    if c == Table71Category.RESIDENTIAL_F13:
        band = _event_band(
            floors=floors,
            height_m=height_m,
            floor_low=12,
            height_low=30.0,
            floor_high=17,
            height_high=50.0,
        )
        if band is None:
            if not _positive(floors) and not _positive(height_m):
                return _manual("табл. 7.1 стр. 1: не заданы этажность и высота")
            return _not_required(
                "табл. 7.1 стр. 1: менее 12 этажей и ниже 30 м — "
                "ВПВ по таблице не требуется"
            )
        if band == 1:
            return _jets(
                2,
                "табл. 7.1 стр. 1: более 16 этажей или выше 50 м — 2 ПК-с",
            )
        if corridor_length_m is None:
            return _manual(
                "табл. 7.1 стр. 1: 12–16 этажей или 30–50 м, но общая "
                "длина коридора не задана — требуется уточнение; временно 2 ПК-с"
            )
        if corridor_length_m > 10.0:
            return _jets(
                2,
                "табл. 7.1 стр. 1: 12–16 этажей или 30–50 м, "
                "коридор более 10 м — 2 ПК-с",
            )
        return _jets(
            1,
            "табл. 7.1 стр. 1: 12–16 этажей или 30–50 м, "
            "коридор до 10 м включительно — 1 ПК-с",
        )

    # Строка 2: Ф1.2, Ф3.4–Ф3.6, Ф4.2, Ф4.3.
    if c in (Table71Category.OFFICE_PUBLIC, Table71Category.DORMITORY_F12):
        band = _event_band(
            floors=floors,
            height_m=height_m,
            floor_low=6,
            height_low=18.0,
            floor_high=11,
            height_high=30.0,
        )
        if band is None:
            if not _positive(floors) and not _positive(height_m):
                return _manual("табл. 7.1 стр. 2: не заданы этажность и высота")
            return _not_required(
                "табл. 7.1 стр. 2: менее 6 этажей и ниже 18 м — "
                "ВПВ по таблице не требуется"
            )
        return _jets(
            1 if band == 0 else 2,
            "табл. 7.1 стр. 2: "
            + (
                "6–10 этажей или 18–30 м — 1 ПК-с"
                if band == 0
                else "более 10 этажей или выше 30 м — 2 ПК-с"
            ),
        )

    # Строка 3: Ф1.1, кроме ДОО без спальных корпусов.
    if c == Table71Category.HOSPITAL_F11:
        if not _positive(floors) and not _positive(height_m):
            return _manual("табл. 7.1 стр. 3: не заданы этажность и высота")
        high = (floors or 0) > 3 or (height_m or 0) > 8.0
        return _jets(
            2 if high else 1,
            "табл. 7.1 стр. 3: Ф1.1 "
            + (
                "более 3 этажей или выше 8 м — 2 ПК-с"
                if high
                else "до 3 этажей или до 8 м включительно — 1 ПК-с"
            ),
        )

    # Строка 4: спорт; библиотеки с местами; лаборатории/мастерские Ф5.1;
    # книжные склады и архивы Ф5.2 — по площади.
    if c == Table71Category.SPORTS_LIBRARY_LAB:
        if total_area_m2 is None or total_area_m2 <= 0:
            return _manual("табл. 7.1 стр. 4: площадь расчётной части не задана")
        return _jets(
            1 if total_area_m2 <= 2500.0 else 2,
            "табл. 7.1 стр. 4: площадь "
            + (
                "до 2,5 тыс. м² включительно — 1 ПК-с"
                if total_area_m2 <= 2500.0
                else "более 2,5 тыс. м² — 2 ПК-с"
            ),
        )

    # Строка 5: Ф2.1, кроме объектов строки 4 — по числу мест.
    if c == Table71Category.F21_AUDITORIUM:
        if hall_seats is None or hall_seats <= 0:
            return _manual("табл. 7.1 стр. 5: вместимость зала не задана")
        return _jets(
            2 if hall_seats <= 300 else 4,
            "табл. 7.1 стр. 5: "
            + (
                "до 300 мест включительно — 2 ПК-с"
                if hall_seats <= 300
                else "более 300 мест — 4 ПК-с"
            ),
        )

    # Строка 6: Ф2.2, Ф3.1–Ф3.3 и многофункциональные здания — по площади.
    if c == Table71Category.TRADE_PUBLIC_MULTI:
        if total_area_m2 is None or total_area_m2 <= 0:
            return _manual("табл. 7.1 стр. 6: площадь расчётной части не задана")
        if total_area_m2 < 1000.0:
            return _not_required(
                "табл. 7.1 стр. 6 и п. 1.4: площадь менее 1 тыс. м² — "
                "ВПВ по таблице не требуется"
            )
        return _jets(
            1 if total_area_m2 <= 5000.0 else 2,
            "табл. 7.1 стр. 6: площадь "
            + (
                "от 1 до 5 тыс. м² включительно — 1 ПК-с"
                if total_area_m2 <= 5000.0
                else "более 5 тыс. м² — 2 ПК-с"
            ),
        )

    raise ValueError(f"неизвестная категория табл. 7.1: {category}")


# Таблица 7.2. Ключ: степень, категории, допустимые классы. ``None`` = «-».
_T72 = (
    ("I-II", frozenset("АБВ"), frozenset(("С0", "С1")), (2, 2.5), (3, 2.5)),
    ("III", frozenset("АБВ"), frozenset(("С0", "С1")), (2, 2.5), (3, 2.5)),
    ("III", frozenset("ГД"), frozenset(("С0", "С1")), None, (2, 2.5)),
    ("IV", frozenset("АБ"), frozenset(("С0",)), (2, 2.5), (3, 2.5)),
    ("IV", frozenset(("В",)), frozenset(("С0", "С1")), (2, 2.5), (2, 5.0)),
    ("IV", frozenset(("В",)), frozenset(("С2", "С3")), (3, 2.5), (4, 2.5)),
    ("IV", frozenset("ГД"), frozenset(("С0", "С1", "С2", "С3")), None, (2, 2.5)),
    ("V", frozenset(("В",)), None, (2, 2.5), (2, 5.0)),
)


def resolve_table_7_2(
    fire_resistance_degree: str,
    hazard_category: str,
    structural_class: str,
    volume_thousand_m3: float,
) -> Table71Result:
    """Разрешить таблицу 7.2 для здания высотой не более 50 м."""
    if volume_thousand_m3 <= 0:
        return _manual("табл. 7.2: объём здания должен быть больше нуля")
    if volume_thousand_m3 < 0.5:
        return _not_required(
            "табл. 7.2 и п. 1.4: объём менее 0,5 тыс. м³ — ВПВ не требуется"
        )

    deg = fire_resistance_degree.upper().replace("І", "I")
    deg_key = "I-II" if deg in ("I", "II") else deg
    cat = hazard_category.upper().replace(" ", "")
    cls = structural_class.upper().replace("C", "С").replace(" ", "")

    if len(cat) != 1:
        return _manual(
            "табл. 7.2: задайте одну категорию помещения А, Б, В, Г или Д"
        )
    if cat in "ГД" and deg_key in ("I-II", "V"):
        return _not_required(
            f"п. 1.4: степень {deg}, категория {cat} — ВПВ не требуется"
        )

    for degree, categories, classes, low, high in _T72:
        if degree != deg_key or cat not in categories:
            continue
        if classes is not None and cls not in classes:
            continue
        cell = low if volume_thousand_m3 <= 150.0 else high
        if cell is None:
            return _not_required(
                f"табл. 7.2: {deg}/{cat}/{cls or 'класс не нормируется'}, "
                f"объём {volume_thousand_m3:g} тыс. м³ — ВПВ не требуется («-»)"
            )
        n, q = cell
        return Table71Result(
            True,
            n,
            q,
            notes=[
                f"табл. 7.2: {deg}/{cat}/{cls or 'класс не нормируется'}, "
                f"объём {volume_thousand_m3:g} тыс. м³ → {n}×{q:g} л/с"
            ],
        )

    return _manual(
        f"табл. 7.2: сочетание {deg}/{cat}/{cls or 'класс не задан'} "
        "не найдено — требуется проверить исходные данные"
    )

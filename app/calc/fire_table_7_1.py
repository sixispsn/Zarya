# -*- coding: utf-8 -*-
"""
app/calc/fire_table_7_1.py — таблицы 7.1 и 7.2 СП 10.13130.2020: число ПК-с,
одновременно используемых при тушении, и минимальный расход диктующего ПК-с.

Перенос буквы нормы, не памяти. Ключевые правила текста:
  • сноска <**>: значение принимается при любом из событий (этажность ИЛИ высота)
    или их совокупности, при этом ОПРЕДЕЛЯЮЩИМ является ВЫСОТА здания;
  • строка 1: порог «общая ДЛИНА коридора до/свыше 10 м» (длина, не ширина!);
  • ниже нижней границы строки ВПВ по данной таблице не требуется (jets=0);
  • выше верхней границы — вне таблицы (СТУ/особые случаи) → manual_review;
  • табл. 7.2 (производственные/складские): «-» означает, что ВПВ не требуется.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class Table71Category(str, Enum):
    """Строки табл. 7.1 (категория объекта)."""
    RESIDENTIAL_F13 = "residential_f13"      # 1. многокв. жилые Ф1.3 (+Ф1.2 кварт. типа)
    OFFICE_PUBLIC = "office_public"          # 2. адм-бытовые/общественные/офисы Ф4.3, Ф3.4/3.5/3.6, Ф4.2, гостиницы Ф1.2
    HOSPITAL_F11 = "hospital_f11"            # 3. дома престарелых/больницы/интернаты Ф1.1
    THEATRE_F21 = "theatre_f21"              # 4. театры/кино/клубы/цирки Ф2.1 (по местам)
    LIBRARY_SPORT = "library_sport"          # 5. библиотеки/архивы/спорт Ф2.1,Ф3.6,Ф5.1/5.2 (по площади)
    MUSEUM_TRADE = "museum_trade"            # 6. музеи/выставки/танцзалы Ф2.2, торговля Ф3.1
    DORMITORY_F12 = "dormitory_f12"          # 7. общежития коридорного типа Ф1.2


@dataclass
class Table71Result:
    """Результат резолва по табл. 7.1/7.2."""
    vpv_required: bool                 # требуется ли ВПВ по таблице
    jets: int                          # число расчётных ПК-с (0 если не требуется)
    q_per_jet_lps: float               # мин. расход диктующего ПК-с, л/с
    manual_review: bool = False        # вне таблицы / не хватает данных
    notes: List[str] = field(default_factory=list)


def _not_required(note: str) -> Table71Result:
    return Table71Result(False, 0, 0.0, notes=[note])


def _manual(note: str, jets_conservative: int = 2) -> Table71Result:
    return Table71Result(True, jets_conservative, 2.5, manual_review=True, notes=[note])


def _jets(n: int, note: str, q: float = 2.5) -> Table71Result:
    return Table71Result(True, n, q, notes=[note])


def _band_by_height_or_floors(
    height_m: Optional[float], floors: Optional[int],
    height_bands: List[Tuple[float, float]],
    floor_bands: List[Tuple[int, int]],
) -> Optional[int]:
    """Индекс диапазона по сноске <**>: определяющим является ВЫСОТА.
    Если высота задана (>0) — классифицируем по ней; иначе по этажности.
    None — вне всех диапазонов (ниже нижней или выше верхней границы решает вызывающий)."""
    if height_m is not None and height_m > 0:
        for i, (lo, hi) in enumerate(height_bands):
            if lo < height_m <= hi:
                return i
        return None
    if floors is not None and floors > 0:
        for i, (lo, hi) in enumerate(floor_bands):
            if lo <= floors <= hi:
                return i
        return None
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
    """Число расчётных ПК-с и расход по табл. 7.1 (жилые/общественные/адм-бытовые).

    Строго по строкам таблицы; чего не хватает (коридор/места/площадь) —
    manual_review с консервативным значением, не молчаливый дефолт.
    """
    c = category

    # ── строка 1: жилые Ф1.3 ──
    if c == Table71Category.RESIDENTIAL_F13:
        band = _band_by_height_or_floors(height_m, floors,
                                         [(30.0, 50.0), (50.0, 75.0)],
                                         [(12, 16), (17, 25)])
        if band is None:
            hf = height_m if (height_m or 0) > 0 else floors
            if hf is not None and ((height_m or 0) > 75.0 or (floors or 0) > 25):
                return _manual("жилое выше 75 м / 25 эт. — вне табл. 7.1 (СТУ)")
            return _not_required("жилое ниже 12 эт. / 30 м — ВПВ по табл. 7.1 не требуется")
        if band == 1:
            return _jets(2, "табл. 7.1 стр. 1: жилое свыше 16 до 25 эт. (50–75 м) — "
                            "2 ПК независимо от длины коридора")
        # band 0: 12–16 эт. (30–50 м) — решает ДЛИНА коридора
        if corridor_length_m is None:
            return _manual("табл. 7.1 стр. 1: 12–16 эт., но общая длина коридора не "
                           "задана — принято консервативно 2 ПК, уточните")
        if corridor_length_m > 10.0:
            return _jets(2, "табл. 7.1 стр. 1: 12–16 эт., коридор свыше 10 м — 2 ПК")
        return _jets(1, "табл. 7.1 стр. 1: 12–16 эт., коридор до 10 м включ. — 1 ПК")

    # ── строка 2: адм-бытовые/общественные/офисы/гостиницы/поликлиники/ФОК/вузы ──
    if c == Table71Category.OFFICE_PUBLIC:
        band = _band_by_height_or_floors(height_m, floors,
                                         [(18.0, 30.0), (30.0, 50.0)],
                                         [(6, 10), (11, 16)])
        if band is None:
            if (height_m or 0) > 50.0 or (floors or 0) > 16:
                return _manual("общественное выше 50 м / 16 эт. — вне табл. 7.1")
            return _not_required("общественное ниже 6 эт. / 18 м — ВПВ по табл. 7.1 "
                                 "не требуется")
        return _jets(1 if band == 0 else 2,
                     f"табл. 7.1 стр. 2: {'6–10 эт. (18–30 м) — 1 ПК' if band == 0 else 'свыше 10 до 16 эт. (30–50 м) — 2 ПК'}")

    # ── строка 3: больницы/интернаты Ф1.1 (независимо от объёма) ──
    if c == Table71Category.HOSPITAL_F11:
        band = _band_by_height_or_floors(height_m, floors,
                                         [(0.0, 8.0), (8.0, 1e9)],
                                         [(1, 3), (4, 10**6)])
        if band is None:
            return _manual("Ф1.1: не заданы ни этажность, ни высота")
        return _jets(1 if band == 0 else 2,
                     f"табл. 7.1 стр. 3: Ф1.1 {'до 3 эт. (до 8 м) — 1 ПК' if band == 0 else 'свыше 3 эт. (свыше 8 м) — 2 ПК'}")

    # ── строка 4: театры/кино/клубы/цирки Ф2.1 — по местам ──
    if c == Table71Category.THEATRE_F21:
        if hall_seats is None:
            return _manual("табл. 7.1 стр. 4: вместимость зала не задана")
        if hall_seats <= 300:
            return _jets(1, "табл. 7.1 стр. 4: зал до 300 мест включ. — 1 ПК")
        return _jets(2, "табл. 7.1 стр. 4: зал более 300 мест — 2 ПК")

    # ── строка 5: библиотеки/архивы/спорт — по площади (высотой до 50 м) ──
    if c == Table71Category.LIBRARY_SPORT:
        if (height_m or 0) > 50.0:
            return _manual("табл. 7.1 стр. 5: высота более 50 м — вне строки")
        if total_area_m2 is None:
            return _manual("табл. 7.1 стр. 5: общая площадь не задана")
        if total_area_m2 <= 2500.0:
            return _jets(1, "табл. 7.1 стр. 5: площадь до 2,5 тыс. м² включ. — 1 ПК")
        return _jets(2, "табл. 7.1 стр. 5: площадь свыше 2,5 тыс. м² — 2 ПК")

    # ── строка 6: музеи/выставки/танцзалы Ф2.2, торговля Ф3.1 ──
    if c == Table71Category.MUSEUM_TRADE:
        band = _band_by_height_or_floors(height_m, floors,
                                         [(0.0, 8.0), (8.0, 28.0)],
                                         [(1, 3), (4, 10**6)])
        if band is None:
            if (height_m or 0) > 28.0:
                return _manual("табл. 7.1 стр. 6: высота более 28 м — вне строки")
            return _manual("стр. 6: не заданы ни этажность, ни высота")
        return _jets(1 if band == 0 else 2,
                     f"табл. 7.1 стр. 6: {'до 3 эт. (до 8 м) — 1 ПК' if band == 0 else 'более 3 эт. (до 28 м) — 2 ПК'}")

    # ── строка 7: общежития коридорного типа Ф1.2 ──
    if c == Table71Category.DORMITORY_F12:
        band = _band_by_height_or_floors(height_m, floors,
                                         [(0.0, 28.0), (28.0, 1e9)],
                                         [(1, 10), (11, 16)])
        if band is None:
            if (floors or 0) > 16:
                return _manual("стр. 7: общежитие выше 16 эт. — вне строки")
            return _manual("стр. 7: не заданы ни этажность, ни высота")
        return _jets(1 if band == 0 else 2,
                     f"табл. 7.1 стр. 7: {'до 10 эт. (до 28 м) — 1 ПК' if band == 0 else 'свыше 10 до 16 эт. (свыше 28 м) — 2 ПК'}")

    raise ValueError(f"неизвестная категория табл. 7.1: {category}")


# ============================================================
# ТАБЛ. 7.2 — производственные и складские здания
# ============================================================
# Ключ: (степень огнестойкости, категория по ПО, класс конструктивной ПО).
# Значение: (jets×q при объёме 0,5–150 тыс. м³, jets×q свыше 150). None = «-».

_T72 = {
    ("I-II", "АБВ", "С0С1"): ((2, 2.5), (3, 2.5)),
    ("III",  "АБВ", "С0"):   ((2, 2.5), (3, 2.5)),
    ("III",  "ГД",  "С0С1"): (None,     (2, 2.5)),
    ("IV",   "АБ",  "С0"):   ((2, 2.5), (3, 2.5)),
    ("IV",   "В",   "С0С1"): ((2, 2.5), (2, 5.0)),
    ("IV",   "В",   "С2С3"): ((3, 2.5), (4, 2.5)),
    ("IV",   "ГД",  "С0С1С2С3"): (None, (2, 2.5)),
    ("V",    "В",   "НЕНОРМ"):   ((2, 2.5), (2, 5.0)),
    ("V",    "ГД",  "НЕНОРМ"):   ((1, 2.5), (2, 2.5)),
}


def resolve_table_7_2(
    fire_resistance_degree: str,     # "I", "II", "III", "IV", "V"
    hazard_category: str,            # "А","Б","В","Г","Д"
    structural_class: str,           # "С0","С1","С2","С3" или "" (не норм.)
    volume_thousand_m3: float,
) -> Table71Result:
    """Число ПК-с и расход для производственных/складских (табл. 7.2).
    «-» в таблице = ВПВ не требуется. Здания выше 50 м — вне таблицы (manual)."""
    deg = fire_resistance_degree.upper().replace("І", "I")
    deg_key = "I-II" if deg in ("I", "II") else deg
    cat = hazard_category.upper()
    cls = structural_class.upper().replace(" ", "")

    for (d, cats, classes), (low, high) in _T72.items():
        if d != deg_key or cat not in cats:
            continue
        if classes != "НЕНОРМ" and cls and cls not in classes:
            continue
        cell = low if volume_thousand_m3 <= 150.0 else high
        if cell is None:
            return _not_required(f"табл. 7.2: {deg}/{cat}/{cls or 'не норм.'} при объёме "
                                 f"{volume_thousand_m3:g} тыс. м³ — ВПВ не требуется («-»)")
        n, q = cell
        return Table71Result(True, n, q, notes=[
            f"табл. 7.2: {deg}/{cat}/{cls or 'не норм.'}, объём {volume_thousand_m3:g} "
            f"тыс. м³ → {n}×{q:g} л/с"])
    return _manual(f"табл. 7.2: сочетание {deg}/{cat}/{cls} не найдено — проверьте вход")

# -*- coding: utf-8 -*-
"""Тесты app/calc/fire_table_7_1.py + интеграция в fire_normative."""
import pytest

from app.calc.fire_table_7_1 import (
    Table71Category as C, resolve_table_7_1, resolve_table_7_2,
)


# ── строка 1: жилые Ф1.3 ─────────────────────────────────────────────────────

def test_residential_short_corridor_1pk():
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=14, corridor_length_m=8.0)
    assert (r.vpv_required, r.jets, r.q_per_jet_lps) == (True, 1, 2.5)


def test_residential_long_corridor_2pk():
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=14, corridor_length_m=25.0)
    assert r.jets == 2


def test_residential_high_2pk_regardless_corridor():
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=20)
    assert r.jets == 2 and not r.manual_review


def test_residential_below_threshold_not_required():
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=9)
    assert r.vpv_required is False and r.jets == 0


def test_residential_exactly_30m_is_inclusive():
    r = resolve_table_7_1(
        C.RESIDENTIAL_F13, floors=8, height_m=30.0, corridor_length_m=8.0)
    assert r.vpv_required is True and r.jets == 1


def test_residential_eight_floors_below_30m_not_required():
    r = resolve_table_7_1(
        C.RESIDENTIAL_F13, floors=8, height_m=29.9, corridor_length_m=42.0)
    assert r.vpv_required is False and r.jets == 0


def test_residential_above_75m_manual():
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=30)
    assert r.manual_review is True


def test_residential_no_corridor_conservative_manual():
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=14)   # коридор не задан
    assert r.manual_review is True and r.jets == 2   # консервативно


def test_footnote_height_is_determining():
    # 14 эт. (диапазон 1), но h=55 м (диапазон 2) → определяет ВЫСОТА → 2 ПК
    r = resolve_table_7_1(C.RESIDENTIAL_F13, floors=14, height_m=55.0,
                          corridor_length_m=8.0)
    assert r.jets == 2 and "свыше 50 до 75" in r.notes[0]


# ── строка 2: общественные/офисы ─────────────────────────────────────────────

def test_office_6_10_floors_1pk():
    assert resolve_table_7_1(C.OFFICE_PUBLIC, floors=8).jets == 1


def test_office_11_16_floors_2pk():
    assert resolve_table_7_1(C.OFFICE_PUBLIC, height_m=40.0).jets == 2


def test_office_low_not_required():
    assert resolve_table_7_1(C.OFFICE_PUBLIC, floors=4).vpv_required is False


# ── строки 3–7 ───────────────────────────────────────────────────────────────

def test_hospital_bands():
    assert resolve_table_7_1(C.HOSPITAL_F11, floors=2).jets == 1
    assert resolve_table_7_1(C.HOSPITAL_F11, height_m=12.0).jets == 2


def test_theatre_by_seats():
    assert resolve_table_7_1(C.THEATRE_F21, hall_seats=300).jets == 1
    assert resolve_table_7_1(C.THEATRE_F21, hall_seats=301).jets == 2


def test_theatre_no_seats_manual():
    assert resolve_table_7_1(C.THEATRE_F21).manual_review is True


def test_library_by_area():
    assert resolve_table_7_1(C.LIBRARY_SPORT, total_area_m2=2500).jets == 1
    assert resolve_table_7_1(C.LIBRARY_SPORT, total_area_m2=2501).jets == 2


def test_museum_trade_bands():
    assert resolve_table_7_1(C.MUSEUM_TRADE, floors=3).jets == 1
    assert resolve_table_7_1(C.MUSEUM_TRADE, floors=5, height_m=20.0).jets == 2


def test_dormitory_bands():
    assert resolve_table_7_1(C.DORMITORY_F12, floors=10).jets == 1
    assert resolve_table_7_1(C.DORMITORY_F12, floors=12, height_m=34.0).jets == 2


# ── табл. 7.2: производственные/складские ────────────────────────────────────

def test_t72_basic():
    r = resolve_table_7_2("II", "В", "С0", 80)
    assert (r.jets, r.q_per_jet_lps) == (2, 2.5)


def test_t72_large_volume_3pk():
    assert resolve_table_7_2("II", "В", "С0", 200).jets == 3


def test_t72_dash_not_required():
    r = resolve_table_7_2("III", "Д", "С1", 50)
    assert r.vpv_required is False


def test_t72_four_pk():
    assert resolve_table_7_2("IV", "В", "С3", 200).jets == 4


def test_t72_v_degree():
    assert resolve_table_7_2("V", "Г", "", 100).jets == 1


def test_t72_unknown_combo_manual():
    assert resolve_table_7_2("I", "Д", "С0", 50).manual_review is True


# ── интеграция в fire_normative ──────────────────────────────────────────────

def _ctx(**kw):
    from app.calc.fire_normative import (
        FireNormativeContext, FireBuildingKind, FireSpaceKind)
    base = dict(building_kind=FireBuildingKind.RESIDENTIAL,
                space_kind=FireSpaceKind.CORRIDOR,
                room_height_m=3.0, room_width_m=2.0, building_height_m=45.0)
    base.update(kw)
    return FireNormativeContext(**base)


def test_normative_uses_table71():
    from app.calc.fire_normative import resolve_fire_normative
    r = resolve_fire_normative(_ctx(table71_category=C.RESIDENTIAL_F13,
                                    floors_above=14, corridor_length_m=25.0))
    assert r.jet_multiplicity.required_jets == 2
    # п. 6.2.2 сработал по ДЛИНЕ коридора (25 > 10)
    assert r.jet_multiplicity.require_different_risers is True


def test_normative_corridor_length_priority_over_width():
    from app.calc.fire_normative import resolve_fire_normative
    # ширина 12 (>10), но ДЛИНА 8 (≤10): по длине один стояк допустим
    r = resolve_fire_normative(_ctx(table71_category=C.RESIDENTIAL_F13,
                                    floors_above=20, room_width_m=12.0,
                                    corridor_length_m=8.0))
    assert r.jet_multiplicity.require_different_risers is False


def test_normative_fallback_width_flagged():
    from app.calc.fire_normative import resolve_fire_normative
    # длина не задана → fallback на ширину, но с пометкой ВНИМАНИЕ
    r = resolve_fire_normative(_ctx(required_jets_override=2, room_width_m=12.0))
    assert r.jet_multiplicity.require_different_risers is True
    assert any("ВНИМАНИЕ" in n for n in r.jet_multiplicity.notes)


def test_normative_override_beats_table():
    from app.calc.fire_normative import resolve_fire_normative
    r = resolve_fire_normative(_ctx(required_jets_override=1,
                                    table71_category=C.RESIDENTIAL_F13,
                                    floors_above=20))
    assert r.jet_multiplicity.required_jets == 1   # override приоритетен


def test_normative_not_required_raises():
    from app.calc.fire_normative import resolve_fire_normative
    with pytest.raises(ValueError, match="не требуется"):
        resolve_fire_normative(_ctx(table71_category=C.RESIDENTIAL_F13,
                                    floors_above=9, building_height_m=27.0,
                                    corridor_length_m=25.0))

"""Тесты препроцессора общепита (прим.5 табл. А.2)."""
import pytest
from app.pz.catering import dishes_from_seats, CateringDataNeeded


def test_cafe_basic():
    r = dishes_from_seats(50, "cafe", work_hours=12)
    assert r.dishes_per_hour == 220        # 2.2*50*2
    assert r.dishes_per_day == 1188        # 220*12*0.45


def test_restaurant():
    r = dishes_from_seats(80, "restaurant", work_hours=14)
    assert r.dishes_per_hour == 264        # 2.2*80*1.5
    assert r.dishes_per_day == 2033        # 264*14*0.55


def test_no_seats_raises():
    with pytest.raises(CateringDataNeeded):
        dishes_from_seats(0, "cafe", work_hours=12)


def test_no_hours_raises():
    with pytest.raises(CateringDataNeeded):
        dishes_from_seats(50, "cafe", work_hours=None)


def test_unknown_type():
    with pytest.raises(ValueError):
        dishes_from_seats(50, "bistro", work_hours=12)

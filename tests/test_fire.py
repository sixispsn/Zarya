"""
Тесты расчёта ВПВ.

Эталонные значения по таблицам 7.1, 7.2, 7.3 СП 10.13130.2020.
"""
import pytest

from app.calc.fire import FireInput, calculate_fire
from app.data.fire_tables import get_nozzle_data


# ============================================================
# Таблица 7.3 — данные диктующего ПК
# ============================================================

class TestNozzleTable:
    def test_dn50_standard(self):
        """DN50, ствол 13, рукав 20, струя 12 → q=2.6, p=0.210."""
        d = get_nozzle_data(50, 13, 20, 12)
        assert d is not None
        assert d.q == 2.6
        assert d.p == 0.210

    def test_dn65_big_nozzle(self):
        """DN65, ствол 19, рукав 20, струя 20 → q=7.5."""
        d = get_nozzle_data(65, 19, 20, 20)
        assert d is not None
        assert d.q == 7.5

    def test_missing_combination(self):
        """Несуществующая комбинация → None."""
        d = get_nozzle_data(50, 13, 10, 20)  # для DN50/13 нет струи 20
        assert d is None


# ============================================================
# Жилые дома Ф1.3 (таблица 7.1)
# ============================================================

class TestResidentialF13:
    def test_below_12_floors_not_required(self):
        """Менее 12 этажей — ВПВ не требуется."""
        r = calculate_fire(FireInput(building_type="f13", floors=9))
        assert r.required is False

    def test_12_floors_short_corridor_one_stream(self):
        """12-16 этажей, короткий коридор (≤10м) → 1 струя."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.required is True
        assert r.streams == 1
        # q_dikt = 2.6, Q = 1 × 2.6 = 2.6
        assert r.q_total == 2.6

    def test_12_floors_long_corridor_two_streams(self):
        """12-16 этажей, длинный коридор (>10м) → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, corridor_length_m=15,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 2
        assert r.q_total == 5.2  # 2 × 2.6

    def test_high_rise_two_streams(self):
        """Свыше 16 этажей → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=22, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 2


# ============================================================
# Офисы / общественные Ф_office (таблица 7.1)
# ============================================================

class TestOffice:
    def test_below_6_not_required(self):
        r = calculate_fire(FireInput(building_type="f_office", floors=5))
        assert r.required is False

    def test_6_to_10_one_stream(self):
        r = calculate_fire(FireInput(
            building_type="f_office", floors=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 1

    def test_above_10_two_streams(self):
        r = calculate_fire(FireInput(
            building_type="f_office", floors=15,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 2


# ============================================================
# Театры Ф2.1
# ============================================================

class TestTheater:
    def test_small_one_stream(self):
        """≤300 мест → 1 струя."""
        r = calculate_fire(FireInput(
            building_type="f21_theater", seats=200,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 1

    def test_large_two_streams(self):
        """>300 мест → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f21_theater", seats=500,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 2


# ============================================================
# Производственные Ф5 (таблица 7.2)
# ============================================================

class TestProduction:
    def test_i_ii_category_v_small(self):
        """I-II степень, категория В, класс С0, малый объём → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f5",
            fire_degree="I_II", category="V", construction_class="C0",
            volume_thousand_m3=50,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.required is True
        assert r.streams == 2
        assert r.table_used == "7.2"

    def test_i_ii_category_v_big(self):
        """I-II, В, С0, большой объём (>150) → 3 струи."""
        r = calculate_fire(FireInput(
            building_type="f5",
            fire_degree="I_II", category="V", construction_class="C0",
            volume_thousand_m3=200,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 3

    def test_category_gd_not_required(self):
        """I-II, категория Г/Д → ВПВ не требуется."""
        r = calculate_fire(FireInput(
            building_type="f5",
            fire_degree="I_II", category="GD", construction_class="C0",
            volume_thousand_m3=50,
        ))
        assert r.required is False


# ============================================================
# Давление и оборудование
# ============================================================

class TestPressure:
    def test_pressure_returned(self):
        """Давление у клапана возвращается из таблицы 7.3."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.pressure_mpa == 0.210

    def test_big_nozzle_higher_flow(self):
        """Больший ствол (19мм) даёт больший расход."""
        r = calculate_fire(FireInput(
            building_type="f_office", floors=15,
            dn=65, nozzle_mm=19, hose_m=20, jet_m=16,
        ))
        # DN65/19/20/16 → q=6.3, streams=2 → Q=12.6
        assert r.q_per_stream == 6.3
        assert r.q_total == 12.6
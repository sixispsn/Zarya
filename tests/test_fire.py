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

    def test_dn65_d13_twenty_metre_jet(self):
        """Строка 20 м табл. 7.3 для DN65/13 не должна теряться при переносе."""
        for hose, pressure in ((10, 0.464), (15, 0.467), (20, 0.470)):
            row = get_nozzle_data(65, 13, hose, 20)
            assert row is not None
            assert (row.q, row.p) == pytest.approx((4.0, pressure))

    def test_missing_combination(self):
        """Несуществующая комбинация → None."""
        d = get_nozzle_data(50, 13, 10, 20)  # для DN50/13 нет струи 20
        assert d is None


# ============================================================
# Жилые дома Ф1.3 (таблица 7.1)
# ============================================================

class TestResidentialF13:
    def test_eight_floors_below_30m_not_required(self):
        """8 этажей и hпт < 30 м — ВПВ по строке 1 табл. 7.1 не требуется."""
        r = calculate_fire(FireInput(building_type="f13", floors=8, height_m=24))
        assert r.required is False
        assert "ниже 12 эт. и ниже 30 м" in r.message

    def test_eight_floors_at_48m_explains_height_trigger(self):
        r = calculate_fire(FireInput(
            building_type="f13", floors=8, height_m=48,
            corridor_length_m=42, dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.required is True
        assert "hпт=48 м" in r.message
        assert "коридор свыше 10 м" in r.message

    def test_below_12_floors_not_required(self):
        """Менее 12 этажей — ВПВ не требуется."""
        r = calculate_fire(FireInput(building_type="f13", floors=9, height_m=27))
        assert r.required is False

    def test_12_floors_short_corridor_one_stream(self):
        """12-16 этажей, короткий коридор (≤10м) → 1 струя."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, height_m=42, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.required is True
        assert r.streams == 1
        # q_dikt = 2.6, Q = 1 × 2.6 = 2.6
        assert r.q_total == 2.6

    def test_12_floors_long_corridor_two_streams(self):
        """12-16 этажей, длинный коридор (>10м) → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, height_m=42, corridor_length_m=15,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 2
        assert r.q_total == 5.2  # 2 × 2.6

    def test_high_rise_two_streams(self):
        """Свыше 16 этажей → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=22, height_m=66, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 2


# ============================================================
# Офисы / общественные Ф_office (таблица 7.1)
# ============================================================

class TestOffice:
    def test_below_6_not_required(self):
        r = calculate_fire(FireInput(building_type="f_office", floors=5, height_m=15))
        assert r.required is False

    def test_6_to_10_one_stream(self):
        r = calculate_fire(FireInput(
            building_type="f_office", floors=8, height_m=24,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 1

    def test_above_10_two_streams(self):
        r = calculate_fire(FireInput(
            building_type="f_office", floors=15, height_m=45,
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
            building_type="f21_theater", seats=200, height_m=20,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 1

    def test_large_two_streams(self):
        """>300 мест → 2 струи."""
        r = calculate_fire(FireInput(
            building_type="f21_theater", seats=500, height_m=20,
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
            volume_thousand_m3=50, height_m=30,
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
            volume_thousand_m3=200, height_m=30,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.streams == 3

    def test_category_gd_not_required(self):
        """I-II, категория Г/Д → ВПВ не требуется."""
        r = calculate_fire(FireInput(
            building_type="f5",
            fire_degree="I_II", category="GD", construction_class="C0",
            volume_thousand_m3=50, height_m=30,
        ))
        assert r.required is False

    def test_production_height_is_required_for_table_7_2(self):
        with pytest.raises(ValueError, match="задайте высоту"):
            calculate_fire(FireInput(building_type="f5"))

    def test_high_production_uses_p_7_13(self):
        r = calculate_fire(FireInput(
            building_type="f5", fire_degree="I_II", category="V",
            construction_class="C0", height_m=55, volume_thousand_m3=151,
            dn=65, nozzle_mm=19, hose_m=20, jet_m=20,
        ))
        assert (r.streams, r.q_per_stream, r.q_total) == (4, 7.5, 30.0)
        assert r.table_used == "п. 7.13"

    def test_invalid_nozzle_falls_back_to_normative_minimum_not_legacy_26(self):
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, height_m=42, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=10, jet_m=6,
        ))
        assert r.nozzle_found is False
        assert (r.q_per_stream, r.q_total, r.pressure_mpa) == (2.5, 2.5, None)


# ============================================================
# Давление и оборудование
# ============================================================

class TestPressure:
    def test_pressure_returned(self):
        """Давление у клапана возвращается из таблицы 7.3."""
        r = calculate_fire(FireInput(
            building_type="f13", floors=14, height_m=42, corridor_length_m=8,
            dn=50, nozzle_mm=13, hose_m=20, jet_m=12,
        ))
        assert r.pressure_mpa == 0.210

    def test_big_nozzle_higher_flow(self):
        """Больший ствол (19мм) даёт больший расход."""
        r = calculate_fire(FireInput(
            building_type="f_office", floors=15, height_m=45,
            dn=65, nozzle_mm=19, hose_m=20, jet_m=16,
        ))
        # DN65/19/20/16 → q=6.3, streams=2 → Q=12.6
        assert r.q_per_stream == 6.3
        assert r.q_total == 12.6

    def test_compact_jet_minimum_is_checked_by_building_height(self):
        with pytest.raises(ValueError, match="меньше минимума 8 м"):
            calculate_fire(FireInput(
                building_type="f13", floors=20, height_m=60,
                dn=65, nozzle_mm=16, hose_m=20, jet_m=6,
            ))

    def test_pressure_over_045_requires_control_device(self):
        r = calculate_fire(FireInput(
            building_type="f13", floors=20, height_m=60,
            dn=65, nozzle_mm=13, hose_m=20, jet_m=20,
        ))
        assert r.pressure_mpa == 0.470
        assert r.pressure_control_required is True
        assert "п. 7.5" in r.message

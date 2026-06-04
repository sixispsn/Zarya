"""
Тесты подбора счётчиков воды.

Эталонные числа: пересчитаны вручную по формулам HTML.
"""
import pytest

from app.calc.water_meters import MeterInput, calculate_meters
from app.data.water_meters import get_meter_by_d, pick_meter


# ============================================================
# Тесты подбора типоразмера
# ============================================================

class TestPickMeter:
    """Подбор счётчика по среднему часовому расходу."""

    def test_small_load_picks_d15(self):
        """q_sr < 1.2 → счётчик d=15 (q_expl=1.2)."""
        m = pick_meter(1.0)
        assert m.d_mm == 15

    def test_d15_full_load(self):
        """q_sr = 1.2 → ещё d=15."""
        m = pick_meter(1.2)
        assert m.d_mm == 15

    def test_d20(self):
        """q_sr = 1.5 → d=20."""
        m = pick_meter(1.5)
        assert m.d_mm == 20

    def test_d40(self):
        """q_sr = 5 → d=40."""
        m = pick_meter(5)
        assert m.d_mm == 40

    def test_d50(self):
        """q_sr = 10 → d=50."""
        m = pick_meter(10)
        assert m.d_mm == 50

    def test_max(self):
        """Очень большой расход → самый большой счётчик."""
        m = pick_meter(10000)
        assert m.d_mm == 250


# ============================================================
# Golden test: офис 480 работающих, централизованное ГВС
# ============================================================

class TestGoldenOffice480Central:
    """
    Офис 480 чел, централизованное ГВС, без пожара.
    Расходы (из блока водопотребления):
      q_sec_c=0.933, q_sec_h=0.774, q_sec_tot=1.499
      q_day_c=3.6,   q_day_h=2.16,  q_day_tot=5.76
      q_hr_c=1.941,  q_hr_h=1.547
    Период T=24ч.
    """

    @pytest.fixture
    def result(self):
        return calculate_meters(MeterInput(
            hws_type="central",
            period_hours=24.0,
            q_fire_l_per_s=0.0,
            q_sec_tot=1.499, q_sec_c=0.933, q_sec_h=0.774,
            q_day_tot=5.76, q_day_c=3.6, q_day_h=2.16,
            q_hr_c=1.941, q_hr_h=1.547,
        ))

    def test_two_meters(self, result):
        """Должно быть ровно 2 счётчика."""
        assert len(result.meters) == 2

    def test_cold_meter_d15(self, result):
        """ХВС: q_sr_c = 3.6/24 = 0.15 → d=15 (q_expl=1.2)."""
        # Проверка а): h = 14.5 × 0.933² = 12.625 м > 5 м → fail
        # Автоповышение: d=20, S=5.18, h = 5.18 × 0.933² = 4.510 м ≤ 5 → ok
        cold = result.meters[0]
        assert cold.meter.d_mm == 20
        assert cold.pass_normal is True

    def test_hot_meter(self, result):
        """ГВС: q_sr_h = 2.16/24 = 0.09 → d=15."""
        # h = 14.5 × 0.774² = 8.687 > 5 → fail, повышение до d=20
        # h = 5.18 × 0.774² = 3.103 ≤ 5 ✓
        hot = result.meters[1]
        assert hot.meter.d_mm == 20
        assert hot.pass_normal is True

    def test_no_fire_check(self, result):
        """Без пожара — проверки (б) нет."""
        cold = result.meters[0]
        assert cold.has_fire_check is False
        assert cold.pass_fire is None
        assert cold.h_fire is None


# ============================================================
# Golden test: офис 480, с пожарным расходом
# ============================================================

class TestGoldenOffice480WithFire:
    """С пожарным расходом 5 л/с — проверка (б) должна сработать."""

    @pytest.fixture
    def result(self):
        return calculate_meters(MeterInput(
            hws_type="central",
            period_hours=24.0,
            q_fire_l_per_s=5.0,
            q_sec_tot=1.499, q_sec_c=0.933, q_sec_h=0.774,
            q_day_tot=5.76, q_day_c=3.6, q_day_h=2.16,
            q_hr_c=1.941, q_hr_h=1.547,
        ))

    def test_cold_fire_check_applied(self, result):
        """Проверка (б) применяется только к ХВС."""
        cold = result.meters[0]
        assert cold.has_fire_check is True
        assert cold.pass_fire is not None
        # ХВС d=20 (после автоповышения), S=5.18
        # h_fire = 5.18 × (0.933 + 5)² = 5.18 × 35.21 = 182.4 — слишком много
        # 182.4 > 10 → fail → need_bypass=True
        assert cold.need_bypass is True

    def test_hot_no_fire_check(self, result):
        """ГВС не проверяется по пожару."""
        hot = result.meters[1]
        assert hot.has_fire_check is False
        assert hot.need_bypass is False


# ============================================================
# Тесты local ГВС (3 счётчика)
# ============================================================

class TestLocalHws:
    """Местный нагрев — должно быть 3 счётчика."""

    def test_three_meters(self):
        result = calculate_meters(MeterInput(
            hws_type="local",
            period_hours=24.0,
            q_sec_tot=1.499, q_sec_c=0.933, q_sec_h=0.774,
            q_day_tot=5.76, q_day_c=3.6, q_day_h=2.16,
            q_hr_c=1.941, q_hr_h=1.547,
        ))
        assert len(result.meters) == 3
        assert "вводе" in result.meters[0].label.lower() or "общий" in result.meters[0].label.lower()


# ============================================================
# Тесты примечаний
# ============================================================

class TestNotes:
    def test_one_input_warning(self):
        """При 1 вводе и не индивидуальном доме — примечание про обводную."""
        result = calculate_meters(MeterInput(
            hws_type="central",
            inputs_count=1,
            is_individual_house=False,
            q_sec_c=0.5, q_day_c=1.0, q_hr_c=0.5,
            q_sec_h=0.3, q_day_h=0.5, q_hr_h=0.3,
        ))
        assert any("обводная" in n.lower() for n in result.notes)

    def test_individual_no_warning(self):
        """Для индивидуального дома — нет такого примечания."""
        result = calculate_meters(MeterInput(
            hws_type="central",
            inputs_count=1,
            is_individual_house=True,
            q_sec_c=0.5, q_day_c=1.0, q_hr_c=0.5,
            q_sec_h=0.3, q_day_h=0.5, q_hr_h=0.3,
        ))
        assert not any("обводная" in n.lower() for n in result.notes)


# ============================================================
# Валидация
# ============================================================

class TestValidation:
    def test_zero_period_raises(self):
        with pytest.raises(ValueError, match="Период"):
            calculate_meters(MeterInput(period_hours=0, q_sec_c=1, q_day_c=1, q_hr_c=1))

    def test_all_zero_raises(self):
        with pytest.raises(ValueError, match="нечего считать"):
            calculate_meters(MeterInput(period_hours=24))


# ============================================================
# Проверка автоповышения (а) при больших расходах
# ============================================================

class TestAutoUpgrade:
    def test_upgrades_to_larger(self):
        """При q_sec=2 л/с (слишком много для d=15) — должен автоповыситься."""
        result = calculate_meters(MeterInput(
            hws_type="central",
            period_hours=24,
            q_sec_c=2.0, q_day_c=10.0, q_hr_c=1.0,
            q_sec_h=0.5, q_day_h=2.0, q_hr_h=0.3,
        ))
        cold = result.meters[0]
        # h_15 = 14.5 × 4 = 58 → fail
        # h_20 = 5.18 × 4 = 20.72 → fail
        # h_25 = 2.64 × 4 = 10.56 → fail
        # h_32 = 1.3 × 4 = 5.2 → fail (5 limit)
        # h_40 = 0.5 × 4 = 2 → ok
        assert cold.meter.d_mm == 40
        assert cold.pass_normal is True
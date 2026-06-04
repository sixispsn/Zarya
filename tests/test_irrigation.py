"""
Тесты для расчёта полива.

Эталон взят из legacy/sp30_calculator.html.
"""
import pytest

from app.calc.irrigation import IrrigationInput, calculate_irrigation


# ============================================================
# Golden tests: эталонные расчёты по формулам HTML
# ============================================================

class TestGoldenSingleType:
    """Расчёт по одному типу полива."""

    def test_grass_only(self):
        """Только травяной покров 1000 м² × 3 л/м² = 3.0 м³/сут."""
        result = calculate_irrigation(IrrigationInput(grass_m2=1000))
        assert result.summer_m3_per_day == 3.0
        assert result.winter_m3_per_season == 0.0
        assert len(result.items) == 1
        assert result.items[0].name == "Травяной покров"
        assert result.items[0].value_m3 == 3.0

    def test_football_only(self):
        """Только футбольное поле 7000 м² × 0.5 = 3.5 м³/сут."""
        result = calculate_irrigation(IrrigationInput(football_m2=7000))
        assert result.summer_m3_per_day == 3.5

    def test_sport_only(self):
        """Только спорт. сооружения 500 м² × 1.5 = 0.75 м³/сут."""
        result = calculate_irrigation(IrrigationInput(sport_m2=500))
        assert result.summer_m3_per_day == 0.75

    def test_paving_default(self):
        """Покрытия 2000 м² × 0.5 (по умолчанию) = 1.0 м³/сут."""
        result = calculate_irrigation(IrrigationInput(paving_m2=2000))
        assert result.summer_m3_per_day == 1.0

    def test_paving_low_norm(self):
        """Покрытия 2000 м² × 0.4 = 0.8 м³/сут."""
        result = calculate_irrigation(IrrigationInput(paving_m2=2000, paving_norm="0.4"))
        assert result.summer_m3_per_day == 0.8

    def test_lawn_loam_default(self):
        """Газоны 1500 м² × 4 (суглинок, по умолчанию) = 6.0 м³/сут."""
        result = calculate_irrigation(IrrigationInput(lawn_m2=1500))
        assert result.summer_m3_per_day == 6.0

    def test_lawn_sand(self):
        """Газоны 1500 м² × 6 (песок) = 9.0 м³/сут."""
        result = calculate_irrigation(IrrigationInput(lawn_m2=1500, lawn_soil="sand"))
        assert result.summer_m3_per_day == 9.0

    def test_lawn_clay(self):
        """Газоны 1500 м² × 3 (глина) = 4.5 м³/сут."""
        result = calculate_irrigation(IrrigationInput(lawn_m2=1500, lawn_soil="clay"))
        assert result.summer_m3_per_day == 4.5

    def test_rink_only(self):
        """Каток 800 м² × 0.5 = 0.4 м³ (разово, зимний)."""
        result = calculate_irrigation(IrrigationInput(rink_m2=800))
        assert result.summer_m3_per_day == 0.0
        assert result.winter_m3_per_season == 0.4


class TestGoldenCombined:
    """Расчёты с несколькими видами полива."""

    def test_combined_basic(self):
        """
        Комбинированный полив:
          grass 1000 × 3   = 3000 л
          football 7000 × 0.5 = 3500 л
          sport 500 × 1.5  = 750 л
          paving 2000 × 0.5 = 1000 л
          lawn 1500 × 4 (loam) = 6000 л
          rink 800 × 0.5    = 400 л (зима)
        Лето: 3000 + 3500 + 750 + 1000 + 6000 = 14250 л = 14.25 м³/сут
        Зима: 0.4 м³
        """
        result = calculate_irrigation(IrrigationInput(
            grass_m2=1000,
            football_m2=7000,
            sport_m2=500,
            paving_m2=2000,
            lawn_m2=1500,
            rink_m2=800,
        ))
        assert result.summer_m3_per_day == 14.25
        assert result.winter_m3_per_season == 0.4
        assert len(result.items) == 6


class TestIrrigationTimes:
    """Тесты числа поливок в сутки."""

    def test_two_times(self):
        """grass 1000 м² × 3 × 2 поливки = 6.0 м³/сут."""
        result = calculate_irrigation(IrrigationInput(grass_m2=1000, irrigation_times=2))
        assert result.summer_m3_per_day == 6.0
        assert result.irrigation_times == 2

    def test_three_times(self):
        """grass 1000 м² × 3 × 3 = 9.0 м³/сут."""
        result = calculate_irrigation(IrrigationInput(grass_m2=1000, irrigation_times=3))
        assert result.summer_m3_per_day == 9.0

    def test_rink_not_multiplied(self):
        """Каток не умножается на irrigation_times."""
        result = calculate_irrigation(IrrigationInput(
            grass_m2=1000,
            rink_m2=800,
            irrigation_times=3,
        ))
        # Лето: 1000 × 3 × 3 = 9.0
        # Зима: 800 × 0.5 = 0.4 (без умножения)
        assert result.summer_m3_per_day == 9.0
        assert result.winter_m3_per_season == 0.4


class TestEmpty:
    """Пустой расчёт - все нули."""

    def test_all_zero(self):
        result = calculate_irrigation(IrrigationInput())
        assert result.summer_m3_per_day == 0.0
        assert result.winter_m3_per_season == 0.0
        assert len(result.items) == 0


class TestValidation:
    """Валидация входных данных."""

    def test_invalid_paving_norm(self):
        with pytest.raises(ValueError, match="норма покрытия"):
            calculate_irrigation(IrrigationInput(paving_m2=100, paving_norm="0.7"))

    def test_invalid_lawn_soil(self):
        with pytest.raises(ValueError, match="тип грунта"):
            calculate_irrigation(IrrigationInput(lawn_m2=100, lawn_soil="rock"))

    def test_invalid_irrigation_times_low(self):
        with pytest.raises(ValueError, match="1-3"):
            calculate_irrigation(IrrigationInput(grass_m2=100, irrigation_times=0))

    def test_invalid_irrigation_times_high(self):
        with pytest.raises(ValueError, match="1-3"):
            calculate_irrigation(IrrigationInput(grass_m2=100, irrigation_times=4))
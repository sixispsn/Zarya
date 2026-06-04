"""
Тесты для расчёта водостоков кровли.

Эталонные числа: пересчитаны вручную по формулам из legacy HTML.
"""
import math

import pytest

from app.calc.storm import StormInput, calculate_storm


# ============================================================
# Golden tests
# ============================================================

class TestGoldenMoscow:
    """Эталон: Москва (q20=80, n=0.71), кровля 1000 м²."""

    def test_basic(self):
        result = calculate_storm(StormInput(
            city_code="moscow",
            roof_area_m2=1000,
        ))
        assert result.f_calculated_m2 == 1000.0
        assert result.q20_base == 80
        assert result.gamma == 1.0
        assert result.q20_adjusted == 80.0
        assert result.n == 0.71
        # q5 = 4^0.71 × 80
        expected_q5 = round(math.pow(4, 0.71) * 80, 2)
        assert result.q5 == expected_q5
        # Q = 1000 × q5 / 10000
        expected_Q = round(1000 * expected_q5 / 10000, 3)
        assert result.q_total_l_per_s == expected_Q

    def test_with_walls(self):
        """Со стенами: F = 1000 + 0.3×500 = 1150."""
        result = calculate_storm(StormInput(
            city_code="moscow",
            roof_area_m2=1000,
            walls_area_m2=500,
        ))
        assert result.f_calculated_m2 == 1150.0
        # Расход прямо пропорционален F
        expected_q5 = round(math.pow(4, 0.71) * 80, 2)
        expected_Q = round(1150 * expected_q5 / 10000, 3)
        assert result.q_total_l_per_s == expected_Q


class TestGoldenSochi:
    """Эталон: Сочи (q20=110, n=0.62), сложный случай."""

    def test_p2_with_walls(self):
        """Кровля 500, стены 200, период P=2."""
        result = calculate_storm(StormInput(
            city_code="sochi",
            roof_area_m2=500,
            walls_area_m2=200,
            period_years=2,
        ))
        assert result.f_calculated_m2 == 560.0
        assert result.gamma == 1.20
        assert result.q20_adjusted == 132.0  # 110 × 1.20
        expected_q5 = round(math.pow(4, 0.62) * 132, 2)
        assert result.q5 == expected_q5
        expected_Q = round(560 * expected_q5 / 10000, 3)
        assert result.q_total_l_per_s == expected_Q


class TestPeriods:
    """Проверка коэффициентов γ для разных периодов."""

    def test_period_1(self):
        result = calculate_storm(StormInput(city_code="moscow", roof_area_m2=100, period_years=1))
        assert result.gamma == 1.00

    def test_period_2(self):
        result = calculate_storm(StormInput(city_code="moscow", roof_area_m2=100, period_years=2))
        assert result.gamma == 1.20

    def test_period_3(self):
        result = calculate_storm(StormInput(city_code="moscow", roof_area_m2=100, period_years=3))
        assert result.gamma == 1.38

    def test_period_5(self):
        result = calculate_storm(StormInput(city_code="moscow", roof_area_m2=100, period_years=5))
        assert result.gamma == 1.59

    def test_period_10(self):
        result = calculate_storm(StormInput(city_code="moscow", roof_area_m2=100, period_years=10))
        assert result.gamma == 1.87


class TestCities:
    """Проверка что параметры разных городов корректные."""

    def test_yakutsk_lowest_q20(self):
        """Якутск имеет наименьший q20 (30)."""
        result = calculate_storm(StormInput(city_code="yakutsk", roof_area_m2=1000))
        assert result.q20_base == 30
        assert result.n == 0.60

    def test_sochi_highest_q20(self):
        """Сочи имеет наибольший q20 (110)."""
        result = calculate_storm(StormInput(city_code="sochi", roof_area_m2=1000))
        assert result.q20_base == 110
        assert result.n == 0.62

    def test_petropavlovsk_lowest_n(self):
        """Петропавловск-Камчатский имеет наименьший n (0.36)."""
        result = calculate_storm(StormInput(city_code="petropavlovsk", roof_area_m2=1000))
        assert result.n == 0.36


class TestValidation:
    """Валидация входных данных."""

    def test_unknown_city(self):
        with pytest.raises(ValueError, match="Неизвестный код города"):
            calculate_storm(StormInput(city_code="atlantis", roof_area_m2=100))

    def test_zero_roof(self):
        with pytest.raises(ValueError, match="кровли должна быть больше 0"):
            calculate_storm(StormInput(city_code="moscow", roof_area_m2=0))

    def test_negative_roof(self):
        with pytest.raises(ValueError, match="кровли должна быть больше 0"):
            calculate_storm(StormInput(city_code="moscow", roof_area_m2=-100))

    def test_negative_walls(self):
        with pytest.raises(ValueError, match="Площадь стен"):
            calculate_storm(StormInput(city_code="moscow", roof_area_m2=100, walls_area_m2=-10))


class TestProportionality:
    """Проверка пропорциональности — должна линейно зависеть от F."""

    def test_double_roof_doubles_q(self):
        """Удвоение площади кровли удваивает расход."""
        r1 = calculate_storm(StormInput(city_code="moscow", roof_area_m2=500))
        r2 = calculate_storm(StormInput(city_code="moscow", roof_area_m2=1000))
        assert abs(r2.q_total_l_per_s - 2 * r1.q_total_l_per_s) < 0.01
"""
Тесты для расчёта водопотребления.

Эталонные числа взяты из legacy/sp30_calculator.html — режим расчёта 1-в-1.
"""
import pytest

from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.data.sp30_tables import get_alpha


# ============================================================
# Тесты таблицы Б.2 (коэффициенты α)
# ============================================================

class TestAlphaTable:
    """Проверка функции получения α из таблицы Б.2."""

    def test_alpha_at_exact_point(self):
        """α при точном попадании в табличное значение."""
        assert get_alpha(0.015) == 0.200
        assert get_alpha(1.000) == 0.969
        assert get_alpha(10.0) == 4.126

    def test_alpha_below_minimum(self):
        """NP ниже минимума - возвращается 0.200."""
        assert get_alpha(0.001) == 0.200
        assert get_alpha(0.0) == 0.200
        assert get_alpha(-1.0) == 0.200

    def test_alpha_above_maximum(self):
        """NP выше максимума - аппроксимация формулой."""
        # NP=100: α = 1.72 × 100^0.49 - 0.5 ≈ 1.72 × 9.55 - 0.5 ≈ 15.92
        result = get_alpha(100.0)
        assert 15.0 < result < 17.0

    def test_alpha_interpolation(self):
        """Линейная интерполяция между точками."""
        # При NP=3.8095 (между 3.8→2.138 и 3.9→2.174)
        # α = 2.138 + 0.095 × (2.174-2.138) = 2.138 + 0.00342 = 2.141
        result = get_alpha(3.8095)
        assert abs(result - 2.141) < 0.001


# ============================================================
# Golden tests: сверка с эталонным расчётом из HTML
# ============================================================

class TestGoldenOffice480:
    """
    Эталон: Административные здания (office), 480 работающих.
    Из legacy/sp30_calculator.html: ожидаемые результаты в каждом поле.
    """

    @pytest.fixture
    def result(self):
        groups = [ConsumerGroup(code="office", count=480)]
        return calculate_water_demand(groups)

    def test_total_q_sec(self, result):
        """q_sec_tot = 1.499 л/с."""
        assert result.total.q_sec == 1.499

    def test_total_q_hr(self, result):
        """q_hr_tot = 3.182 м³/ч (округлено до 3 знаков)."""
        # В HTML: 3.1816 → round до 3 знаков = 3.182
        assert result.total.q_hr == 3.182

    def test_total_q_day(self, result):
        """q_day_tot = 5.760 м³/сут."""
        assert result.total.q_day == 5.760

    def test_total_alpha(self, result):
        """α для общего потока ≈ 2.141."""
        assert result.total.alpha == 2.141

    def test_total_np(self, result):
        """∑NP для общего потока ≈ 3.8095."""
        assert result.total.np_sec == 3.8095

    def test_cold_q_sec(self, result):
        """q_sec_c = 0.933 л/с."""
        assert result.cold.q_sec == 0.933

    def test_cold_q_hr(self, result):
        """q_hr_c = 1.941 м³/ч."""
        # В HTML: 1.9407 → 1.941
        assert result.cold.q_hr == 1.941

    def test_cold_q_day(self, result):
        """q_day_c = 3.600 м³/сут."""
        assert result.cold.q_day == 3.600

    def test_hot_q_sec(self, result):
        """q_sec_h = 0.774 л/с."""
        assert result.hot.q_sec == 0.774

    def test_hot_q_hr(self, result):
        """q_hr_h = 1.547 м³/ч."""
        # В HTML: 1.5474 → 1.547
        assert result.hot.q_hr == 1.547

    def test_hot_q_day(self, result):
        """q_day_h = 2.160 м³/сут."""
        assert result.hot.q_day == 2.160

    def test_sewage(self, result):
        """q_sewage = 1.499 + 1.6 = 3.099 л/с."""
        assert result.sewage_flow == 3.099

    def test_heat_max(self, result):
        """Q_max = 1.16 × 1.5474 × 60 ≈ 107.7 кВт."""
        assert result.heat_max_kw == 107.7

    def test_heat_avg(self, result):
        """Q_avg = 1.16 × 2.160/24 × 60 ≈ 6.3 кВт."""
        assert result.heat_avg_kw == 6.3


# ============================================================
# Базовые тесты
# ============================================================

class TestErrors:
    def test_empty_groups_raises(self):
        with pytest.raises(ValueError, match="пуст"):
            calculate_water_demand([])

    def test_unknown_code_raises(self):
        groups = [ConsumerGroup(code="unknown_type", count=100)]
        with pytest.raises(ValueError, match="Неизвестный код"):
            calculate_water_demand(groups)


class TestK06:
    """Тесты коэффициента 0.6 (примечание 7 СП 30)."""

    def test_apply_k06_reduces_count(self):
        """k06 уменьшает количество потребителей в 0.6 раза."""
        groups = [ConsumerGroup(code="office", count=480)]
        with_k = calculate_water_demand(groups, apply_k06=True)
        # 480 × 0.6 = 288 → расход должен быть меньше
        without_k = calculate_water_demand(groups, apply_k06=False)
        assert with_k.total.q_day < without_k.total.q_day


class TestNoHotWater:
    """Тесты для потребителей без горячей воды."""

    def test_no_bath_has_zero_hot(self):
        """Жилые дома без ванн — горячей воды нет."""
        groups = [ConsumerGroup(code="residential_no_bath", count=100)]
        result = calculate_water_demand(groups)
        assert result.hot.q_sec == 0.0
        assert result.hot.q_hr == 0.0
        assert result.hot.q_day == 0.0


class TestMixedGroups:
    """Тесты для смешанных групп."""

    def test_office_plus_residential(self):
        """Смесь офиса и жилья считается корректно."""
        groups = [
            ConsumerGroup(code="office", count=100),
            ConsumerGroup(code="residential_central_hw", count=200),
        ]
        result = calculate_water_demand(groups)
        # Должно работать, результаты положительные
        assert result.total.q_sec > 0
        assert result.total.q_day > 0
        # Суточный = арифметическая сумма
        # Офис: 12 × 100 / 1000 = 1.2 м³
        # Жильё центр. ГВС: 130 × 200 / 1000 = 26.0 м³
        # Итого: 27.2 м³
        assert abs(result.total.q_day - 27.2) < 0.01
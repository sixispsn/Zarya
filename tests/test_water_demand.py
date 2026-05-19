"""
Тесты для расчёта водопотребления.
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
        assert get_alpha(0.1) == 0.249
        assert get_alpha(1.0) == 0.691
        assert get_alpha(10.0) == 3.820

    def test_alpha_below_minimum(self):
        """NP ниже минимума - возвращается минимальная α."""
        assert get_alpha(0.001) == 0.200
        assert get_alpha(0.0) == 0.200

    def test_alpha_above_maximum(self):
        """NP выше максимума - возвращается максимальная α."""
        assert get_alpha(100.0) == 3.820
        assert get_alpha(1000.0) == 3.820

    def test_alpha_interpolation(self):
        """Линейная интерполяция между точками."""
        # Между NP=0.1 (α=0.249) и NP=0.15 (α=0.279)
        # При NP=0.125: α = 0.249 + (0.279 - 0.249) × (0.125 - 0.1) / 0.05 = 0.264
        result = get_alpha(0.125)
        assert abs(result - 0.264) < 0.001


# ============================================================
# Тесты расчёта водопотребления
# ============================================================

class TestWaterDemand:
    """Проверка расчёта водопотребления для разных сценариев."""

    def test_simple_residential(self):
        """Базовый расчёт: 480 жителей в жилом доме с централизованным ГВС."""
        groups = [ConsumerGroup(code="residential_with_bath_centralized_hw", count=480)]
        result = calculate_water_demand(groups)

        # Базовые проверки - результаты должны быть положительными
        assert result.total.q_sec > 0
        assert result.cold.q_sec > 0
        assert result.hot.q_sec > 0

        # Суточные расходы по нормам: 300 л × 480 = 144000 л = 144 м³
        assert result.total.q_day == 144.0
        # Холодная: 180 л × 480 = 86.4 м³
        assert result.cold.q_day == 86.4
        # Горячая: 120 л × 480 = 57.6 м³
        assert result.hot.q_day == 57.6

    def test_empty_groups_raises(self):
        """Пустой список групп - ошибка."""
        with pytest.raises(ValueError, match="пуст"):
            calculate_water_demand([])

    def test_unknown_code_raises(self):
        """Неизвестный код потребителя - ошибка."""
        groups = [ConsumerGroup(code="unknown_type", count=100)]
        with pytest.raises(ValueError, match="Неизвестный код"):
            calculate_water_demand(groups)

    def test_local_hw_has_zero_hot(self):
        """Местное ГВС - горячая вода = 0 (вся идёт как холодная)."""
        groups = [ConsumerGroup(code="residential_with_bath_local_hw", count=100)]
        result = calculate_water_demand(groups)
        assert result.hot.q_sec == 0.0
        assert result.hot.q_day == 0.0
        # Но общий и холодный должны быть равны
        assert result.total.q_sec == result.cold.q_sec
        assert result.total.q_day == result.cold.q_day

    def test_apply_k06_reduces_all_flows(self):
        """Коэффициент 0.6 уменьшает все расходы."""
        groups = [ConsumerGroup(code="office", count=200)]
        without_k = calculate_water_demand(groups, apply_k06=False)
        with_k = calculate_water_demand(groups, apply_k06=True)

        assert with_k.total.q_sec == round(without_k.total.q_sec * 0.6, 3)
        assert with_k.cold.q_day == round(without_k.cold.q_day * 0.6, 3)

    def test_sewage_flow_low_consumption(self):
        """Стоки при низком расходе = q_total (без +1.6)."""
        groups = [ConsumerGroup(code="office", count=50)]
        result = calculate_water_demand(groups)
        # При малом расходе q_sec < 8, стоки = q_total
        assert result.total.q_sec < 8.0
        assert result.sewage_flow == result.total.q_sec

    def test_heat_calculations(self):
        """Тепловые потоки рассчитаны и положительны для ГВС."""
        groups = [ConsumerGroup(code="residential_with_bath_centralized_hw", count=480)]
        result = calculate_water_demand(groups)
        assert result.heat_max_kw > 0
        assert result.heat_avg_kw > 0
        # Максимальный должен быть больше или равен среднему
        assert result.heat_max_kw >= result.heat_avg_kw

    def test_mixed_groups(self):
        """Смешанная группа: жилой дом + офис."""
        groups = [
            ConsumerGroup(code="residential_with_bath_centralized_hw", count=300),
            ConsumerGroup(code="office", count=50),
        ]
        result = calculate_water_demand(groups)
        # Должно работать без ошибок
        assert result.total.q_day > 0
        # Суточный = сумма по группам
        # Жилые: 300×480/1000 = но нет, 300 л × 300 = 90 м³
        # Офис: 16 × 50 = 800 л = 0.8 м³
        # Итого: 90.8 м³
        assert abs(result.total.q_day - 90.8) < 0.01
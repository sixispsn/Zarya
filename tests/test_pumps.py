"""
Тесты подбора насосов.

Эталон: формулы из legacy/sp30_calculator.html.
"""
import pytest

from app.calc.pumps import PumpInput, calculate_pump


class TestHead:
    """Расчёт требуемого напора."""

    def test_head_manual(self):
        """H_geom вручную: Hp = 25 + 5 + 20 - 20 = 30."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=25, h_losses=5, h_pr=20, h_gar=20,
        ))
        assert r.h_geom == 25.0
        assert r.h_required == 30.0

    def test_head_auto_floors(self):
        """H_geom авто: (9-1)*3 + 1 = 25."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            floors=9, floor_height=3.0,
            h_losses=5, h_pr=20, h_gar=20,
        ))
        assert r.h_geom == 25.0
        assert r.h_required == 30.0

    def test_head_never_negative(self):
        """Если гарантированный напор большой - Hp не уходит в минус."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=5, h_losses=2, h_pr=10, h_gar=100,
        ))
        assert r.h_required == 0.0


class TestSelection:
    """Подбор насосов."""

    def test_boost_returns_candidates(self):
        """Для повысительного - есть кандидаты из базы Grundfos."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=25, h_losses=5, h_pr=20, h_gar=20,
        ))
        assert len(r.candidates) > 0
        assert len(r.candidates) <= 3

    def test_candidates_sorted_by_score(self):
        """Кандидаты отсортированы по убыванию score."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=25, h_gar=20,
        ))
        scores = [c.score for c in r.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_fire_pump(self):
        """Пожарный тип - подбирается Hydro MX."""
        r = calculate_pump(PumpInput(
            q_design_m3h=12, pump_type="fire",
            h_geom_manual=60, h_losses=5, h_pr=20, h_gar=20,
        ))
        assert len(r.candidates) >= 1
        assert r.candidates[0].pump.type == "fire"

    def test_curve_returned(self):
        """Для построения графика возвращается кривая насоса."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost", h_geom_manual=25, h_gar=20))
        assert len(r.candidates[0].eff_curve) > 0


class TestModes:
    """Режимы параллельный/последовательный."""

    def test_parallel_mode(self):
        r = calculate_pump(PumpInput(
            q_design_m3h=10, pump_type="boost", mode="2p",
            h_geom_manual=25, h_gar=20,
        ))
        assert r.h_required >= 0

    def test_series_mode(self):
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost", mode="2s",
            h_geom_manual=50, h_gar=20,
        ))
        assert r.h_required >= 0


class TestValidation:
    def test_zero_flow_raises(self):
        with pytest.raises(ValueError, match="расход"):
            calculate_pump(PumpInput(q_design_m3h=0, pump_type="boost"))

    def test_missing_guaranteed_head_raises(self):
        with pytest.raises(ValueError, match="Hгар"):
            calculate_pump(PumpInput(
                q_design_m3h=5, pump_type="boost", h_geom_manual=25))

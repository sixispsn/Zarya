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

    def test_system_curve_is_exact_legacy_formula(self):
        """legacy: Hстат=Hгар; k=(Hp-Hстат)/Q² при Hp>Hстат."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=25, h_losses=5, h_pr=20, h_gar=20,
        ))
        assert r.h_required == 30.0
        assert r.h_stat == 20.0
        assert r.k_sys == 0.4

    def test_system_curve_legacy_fallback_k(self):
        """legacy: если Hp не больше Hстат, используется k=0,1."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=5, h_losses=2, h_pr=10, h_gar=20,
        ))
        assert r.h_required == 0.0
        assert r.h_stat == 20.0
        assert r.k_sys == 0.1


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

    @pytest.mark.parametrize("mode,q_design,h_geom,h_losses,h_gar,expected", [
        ("1", 5.0, 25.0, 5.0, 20.0,
         [("CR 10-4", 5.94, 34.1, 160), ("CR 5-8", 5.99, 34.1, 110)]),
        ("2p", 10.0, 25.0, 5.0, 20.0,
         [("CR 10-4", 11.88, 34.1, 160), ("CR 5-8", 11.97, 34.1, 110)]),
        ("2s", 5.0, 50.0, 5.0, 20.0,
         [("CR 10-4", 5.88, 68.3, 145), ("CR 5-8", 5.95, 69.0, 95)]),
    ])
    def test_candidates_match_legacy_golden_working_points(
            self, mode, q_design, h_geom, h_losses, h_gar, expected):
        """Golden получен выполнением JS-функций legacy без DOM-обвязки."""
        result = calculate_pump(PumpInput(
            q_design_m3h=q_design, pump_type="boost", mode=mode,
            h_geom_manual=h_geom, h_losses=h_losses,
            h_pr=20, h_gar=h_gar, npsh_a=8,
        ))
        actual = [(x.pump.model, x.working_point.q, x.working_point.h, x.score)
                  for x in result.candidates]
        assert actual == expected


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

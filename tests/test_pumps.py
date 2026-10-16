"""
Тесты подбора насосов.

Каталог/скоринг legacy; разложение кривой исправлено по согласованию L02.
"""
import pytest
import math

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

    def test_system_curve_uses_head_balance_l02(self):
        """L02: H0=25+20−20; k=5/5², а не прежние 20 и 0.4."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=25, h_losses=5, h_pr=20, h_gar=20,
        ))
        assert r.h_required == 30.0
        assert r.h_stat == 25.0
        assert r.k_sys == 0.2

    def test_sufficient_source_head_has_no_fallback_or_pump(self):
        """L02: signed H0=-5; потери 2 м; насос не нужен."""
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost",
            h_geom_manual=5, h_losses=2, h_pr=10, h_gar=20,
        ))
        assert r.h_required == 0.0
        assert r.h_stat == -5.0
        assert r.k_sys == 0.08
        assert not r.required and not r.candidates


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
            h_geom_manual=25, h_losses=5, h_gar=20,
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
            q_design_m3h=5, pump_type="boost", h_geom_manual=25, h_losses=5, h_gar=20))
        assert len(r.candidates[0].eff_curve) > 0

    def test_current_catalog_covers_project_working_point(self):
        """Расширение каталога перекрывает точку В1 14,46 м³/ч / 54,0 м."""
        r = calculate_pump(PumpInput(
            q_design_m3h=14.4612,
            pump_type="boost",
            h_geom_manual=46.0,
            h_losses=8.007,
            h_pr=20.0,
            h_gar=20.0,
            npsh_a=8.0,
            include_current_catalog=True,
        ))
        assert r.candidates
        accepted = r.candidates[0]
        assert accepted.pump.model == "Helix FIRST V 1606-5/16/E/S/400-50"
        # Independent quadratic: catalog segment H=99.7-2.5Q, system H=46+kQ².
        k = 8.007 / 14.4612**2
        q = (-2.5 + math.sqrt(2.5**2 + 4*k*53.7)) / (2*k)
        assert accepted.working_point.q == pytest.approx(q, abs=1e-8)
        assert accepted.working_point.h == pytest.approx(99.7-2.5*q, abs=1e-8)
        assert accepted.pump.source_url.startswith("https://wilo.com/")

    @pytest.mark.parametrize("mode,q_design,h_geom,h_losses,h_gar,expected", [
        ("1", 5.0, 25.0, 5.0, 20.0,
         [("CR 10-4", 6.361998256, 33.095004361, 150), ("CR 5-8", 6.109609582, 32.465465849, 100)]),
        ("2p", 10.0, 25.0, 5.0, 20.0,
         [("CR 10-4", 12.723996511, 33.095004361, 150), ("CR 5-8", 12.219219164, 32.465465849, 100)]),
        ("2s", 5.0, 50.0, 5.0, 20.0,
         [("CR 10-4", 7.406029237, 60.969853813, 100), ("CR 5-8", 6.354436675, 58.075773092, 100)]),
    ])
    def test_candidates_match_l04_golden_working_points(
            self, mode, q_design, h_geom, h_losses, h_gar, expected):
        """L04 algebraic JS oracle; scoring rules unchanged, their inputs corrected."""
        result = calculate_pump(PumpInput(
            q_design_m3h=q_design, pump_type="boost", mode=mode,
            h_geom_manual=h_geom, h_losses=h_losses,
            h_pr=20, h_gar=h_gar, npsh_a=8,
        ))
        actual = [(x.pump.model, x.working_point.q, x.working_point.h, x.score)
                  for x in result.candidates]
        assert len(actual) == len(expected)
        for (model, q, h, score), (wm, wq, wh, ws) in zip(actual, expected, strict=True):
            assert (model, score) == (wm, ws)
            assert q == pytest.approx(wq, abs=1e-8)
            assert h == pytest.approx(wh, abs=1e-8)


class TestModes:
    """Режимы параллельный/последовательный."""

    def test_parallel_mode(self):
        r = calculate_pump(PumpInput(
            q_design_m3h=10, pump_type="boost", mode="2p",
            h_geom_manual=25, h_losses=5, h_gar=20,
        ))
        assert r.h_required >= 0

    def test_series_mode(self):
        r = calculate_pump(PumpInput(
            q_design_m3h=5, pump_type="boost", mode="2s",
            h_geom_manual=50, h_losses=5, h_gar=20,
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

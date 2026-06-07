"""
Тесты расчёта тепловой изоляции.

Эталон: формулы из legacy/sp30_calculator.html (calcGvs, calcHvs).
"""
import math

import pytest

from app.calc.insulation import (
    InsulationParams,
    PipeGvs,
    PipeHvs,
    calc_gvs_pipe,
    calc_hvs_pipe,
    calculate_insulation,
)


class TestGvs:
    """ГВС — защита от теплопотерь."""

    def test_dn25_60_room20(self):
        """DN25, t=60°С, помещение 20°С — толщина > 0, кратна 10."""
        r = calc_gvs_pipe(PipeGvs(dn=25, t_water=60), t_room=20)
        assert r.delta >= 10
        assert r.delta % 10 == 0
        assert r.ql == 10.0  # сверено: qL DN25@60 = 10.0
        assert r.d_mm == 33.7  # наружный диаметр DN25

    def test_higher_temp_more_insulation(self):
        """Чем горячее вода, тем толще изоляция."""
        cold = calc_gvs_pipe(PipeGvs(dn=25, t_water=50), t_room=20)
        hot = calc_gvs_pipe(PipeGvs(dn=25, t_water=70), t_room=20)
        assert hot.delta_calc > cold.delta_calc

    def test_parking_colder_more_insulation(self):
        """В паркинге (5°С) изоляция толще чем в тёплом (20°С)."""
        warm = calc_gvs_pipe(PipeGvs(dn=25, t_water=60), t_room=20)
        cold = calc_gvs_pipe(PipeGvs(dn=25, t_water=60), t_room=5)
        assert cold.delta_calc > warm.delta_calc

    def test_min_10mm(self):
        """Минимальная толщина 10 мм."""
        r = calc_gvs_pipe(PipeGvs(dn=15, t_water=55), t_room=20)
        assert r.delta >= 10


class TestHvs:
    """ХВС — защита от конденсата."""

    def test_no_insulation_when_warm_pipe(self):
        """Если t_трубы ≥ t_крит — изоляция не нужна."""
        # помещение 20°С, влажность 60% → Δt=8.4 → t_крит=11.6
        # труба 15°С > 11.6 → не нужна
        r = calc_hvs_pipe(PipeHvs(dn=25, t_water=15), t_room=20, humidity=60)
        assert r.need_insulation is False
        assert r.t_surf == 11.6

    def test_insulation_needed_cold_pipe(self):
        """Холодная труба ниже t_крит — изоляция нужна."""
        # труба 5°С < 11.6 → нужна
        r = calc_hvs_pipe(PipeHvs(dn=25, t_water=5), t_room=20, humidity=60)
        assert r.need_insulation is True
        assert r.delta is not None
        assert r.delta >= 10

    def test_high_humidity_needs_insulation(self):
        """При высокой влажности t_крит выше → чаще нужна изоляция."""
        # 90% влажности, помещение 20°С → Δt=1.8 → t_крит=18.2
        # труба 15°С < 18.2 → нужна
        r = calc_hvs_pipe(PipeHvs(dn=25, t_water=15), t_room=20, humidity=90)
        assert r.need_insulation is True


class TestFull:
    """Полный расчёт."""

    def test_combined(self):
        result = calculate_insulation(
            InsulationParams(location="room_hot", humidity=60),
            gvs_pipes=[PipeGvs(dn=25, t_water=60, label="Стояк ГВС")],
            hvs_pipes=[PipeHvs(dn=25, t_water=5, label="Стояк ХВС")],
        )
        assert result.t_room == 20.0
        assert result.is_parking is False
        assert len(result.gvs) == 1
        assert len(result.hvs) == 1

    def test_parking_location(self):
        result = calculate_insulation(
            InsulationParams(location="parking"),
            gvs_pipes=[PipeGvs(dn=25, t_water=60)],
            hvs_pipes=[],
        )
        assert result.t_room == 5.0
        assert result.is_parking is True

    def test_invalid_humidity(self):
        with pytest.raises(ValueError, match="Влажность"):
            calculate_insulation(
                InsulationParams(humidity=55),
                gvs_pipes=[],
                hvs_pipes=[],
            )


class TestEmpty:
    def test_no_pipes(self):
        result = calculate_insulation(
            InsulationParams(),
            gvs_pipes=[],
            hvs_pipes=[],
        )
        assert len(result.gvs) == 0
        assert len(result.hvs) == 0
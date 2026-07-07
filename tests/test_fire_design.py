# -*- coding: utf-8 -*-
"""Тесты app/calc/fire_design.py — сквозная сшивка слоёв 1-2-3."""
import pytest

from app.calc.fire_design import design_fire_cabinets_from_context, FireDesignResult
from app.calc.fire_normative import (
    FireNormativeContext, FireBuildingKind, FireSpaceKind,
)
from app.calc.fire_layout import RectangularRoom
from app.calc.fire_models import PlacementMode


def _ctx(**kw):
    base = dict(building_kind=FireBuildingKind.PUBLIC, space_kind=FireSpaceKind.CORRIDOR,
                room_height_m=3.3, room_width_m=12.0, building_height_m=40.0,
                placement_mode=PlacementMode.TWO_OPPOSITE_SIDES, required_jets_override=2)
    base.update(kw)
    return FireNormativeContext(**base)


def test_end_to_end_corridor_over_10m():
    ctx = _ctx()
    room = RectangularRoom("c1", 48.0, 12.0, 3.3)
    res = design_fire_cabinets_from_context(ctx, room)
    assert isinstance(res, FireDesignResult)
    # Rk из п.7.15 (общественное ≤50 → 6), кратность и стояки из п.6.2.2
    assert res.resolved_normative.jet_params.compact_jet_radius_m == 6.0
    assert res.resolved_normative.cabinet_normative.required_jets == 2
    assert res.resolved_normative.cabinet_normative.require_different_risers is True
    assert res.pk_total > 0
    assert res.coverage_ok


def test_normative_flows_into_layout_without_manual_jet():
    # ключевое: JetParams/normative не передаются руками — берутся из ctx
    ctx = _ctx(building_kind=FireBuildingKind.RESIDENTIAL, building_height_m=60.0,
               space_kind=FireSpaceKind.CORRIDOR, room_width_m=8.0)
    room = RectangularRoom("c2", 30.0, 8.0, 3.0)
    res = design_fire_cabinets_from_context(ctx, room)
    # жилое >50 → Rk=8; коридор ≤10 → один стояк допустим
    assert res.resolved_normative.jet_params.compact_jet_radius_m == 8.0
    assert res.resolved_normative.cabinet_normative.require_different_risers is False


def test_manual_review_propagates():
    # склад, 2 струи, не-коридор → нормативный слой ставит manual_review.
    # высота 6 м, чтобы Rk=6 добивал до верха (H-1.35=4.65 < 6).
    ctx = _ctx(building_kind=FireBuildingKind.WAREHOUSE, space_kind=FireSpaceKind.STORAGE,
               room_height_m=6.0, room_width_m=10.0, building_height_m=24.0,
               placement_mode=PlacementMode.TWO_OPPOSITE_SIDES, required_jets_override=2)
    room = RectangularRoom("s1", 40.0, 10.0, 6.0)
    res = design_fire_cabinets_from_context(ctx, room)
    assert res.manual_review_required is True
    assert any("ручная проверка" in n.lower() for n in res.notes)


def test_unreachable_geometry_returns_diagnostic():
    # высокий склад + Rk=6 (warehouse ≤50м) → струя не добивает до верха.
    # оркестратор не падает, а возвращает диагностируемый результат.
    ctx = _ctx(building_kind=FireBuildingKind.WAREHOUSE, space_kind=FireSpaceKind.STORAGE,
               room_height_m=8.0, room_width_m=20.0, building_height_m=24.0,
               required_jets_override=2)
    room = RectangularRoom("s2", 40.0, 20.0, 8.0)
    res = design_fire_cabinets_from_context(ctx, room)
    assert res.layout is None
    assert res.coverage_ok is False
    assert any("невозможна" in n.lower() for n in res.notes)


def test_one_jet_single_side():
    ctx = _ctx(space_kind=FireSpaceKind.ROOM, room_width_m=8.0,
               placement_mode=PlacementMode.ONE_SIDE, required_jets_override=1)
    room = RectangularRoom("r1", 24.0, 8.0, 4.0)
    res = design_fire_cabinets_from_context(ctx, room)
    assert res.resolved_normative.cabinet_normative.required_jets == 1
    assert res.coverage_ok


def test_notes_aggregate_normative_and_layout():
    res = design_fire_cabinets_from_context(_ctx(), RectangularRoom("c", 48.0, 12.0, 3.3))
    # в notes есть и нормативные пометки (п.7.15/6.2.2), и layout (шаг L)
    joined = " ".join(res.notes)
    assert "7.15" in joined or "Rk" in joined
    assert "L=" in joined or "SP rectangular" in joined

# -*- coding: utf-8 -*-
"""Тесты app/calc/placement_rules.py — контракт движка, прямоугольный адаптер,
прореживание по L, заглушка PlanAware."""
import pytest

from app.calc.placement_rules import (
    CandidatePosition, PlacementRuleEngine, RectangularWallPlacementEngine,
    PlanAwarePlacementEngine, select_cabinets_from_candidates,
)
from app.calc.fire_models import PlacementMode
from app.calc.fire_layout import RectangularRoom


def test_engine_satisfies_protocol():
    eng = RectangularWallPlacementEngine()
    assert isinstance(eng, PlacementRuleEngine)


def test_one_side_generates_single_row():
    room = RectangularRoom("r", 24.0, 12.0, 6.0)
    eng = RectangularWallPlacementEngine(candidate_step_m=2.0, edge_offset_m=1.0)
    cands = eng.generate_candidates(room, PlacementMode.ONE_SIDE)
    assert all(c.wall_side == "left" and c.y_m == 0.0 for c in cands)


def test_two_sides_generates_both_rows():
    room = RectangularRoom("r", 24.0, 12.0, 6.0)
    eng = RectangularWallPlacementEngine(candidate_step_m=2.0, edge_offset_m=1.0)
    cands = eng.generate_candidates(room, PlacementMode.TWO_OPPOSITE_SIDES)
    left = [c for c in cands if c.wall_side == "left"]
    right = [c for c in cands if c.wall_side == "right"]
    assert len(left) == len(right) and len(right) > 0
    assert all(c.y_m == room.width_m for c in right)


def test_edge_offset_respected():
    room = RectangularRoom("r", 24.0, 12.0, 6.0)
    eng = RectangularWallPlacementEngine(candidate_step_m=2.0, edge_offset_m=1.5)
    cands = eng.generate_candidates(room, PlacementMode.ONE_SIDE)
    xs = [c.x_m for c in cands]
    assert min(xs) >= 1.5 - 1e-9
    assert max(xs) <= 24.0 - 1.5 + 1e-9


def test_select_respects_spacing_and_keeps_end():
    room = RectangularRoom("r", 36.0, 12.0, 6.0)
    eng = RectangularWallPlacementEngine(candidate_step_m=1.0, edge_offset_m=1.0)
    cands = eng.generate_candidates(room, PlacementMode.ONE_SIDE)
    sel = select_cabinets_from_candidates(cands, spacing_L_m=12.0, side="left")
    xs = [c.x_m for c in sel]
    # шаг между выбранными не меньше L (кроме финального «дотягивания» до торца)
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    assert all(g >= 12.0 - 1e-9 for g in gaps[:-1])
    # последний кандидат ряда сохранён (торец покрыт)
    assert xs[-1] == pytest.approx(max(c.x_m for c in cands if c.wall_side == "left"))


def test_plan_aware_not_implemented():
    room = RectangularRoom("r", 24.0, 12.0, 6.0)
    with pytest.raises(NotImplementedError):
        PlanAwarePlacementEngine().generate_candidates(room, PlacementMode.ONE_SIDE)


def test_candidate_reason_default_wall():
    c = CandidatePosition(1.0, 0.0, "left")
    assert c.reason == "wall"

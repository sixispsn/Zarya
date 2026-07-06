# -*- coding: utf-8 -*-
"""Тесты app/calc/fire_layout.py — по списку спринта:
compute_spacing_L (обе схемы), ошибка Rk<=H-1.35, coverage True/False,
require_different_risers, edge_offset, автовыбор симметрия/шахматка."""
import math
import pytest

from app.calc.fire_layout import (
    PlacementMode, SidePattern, JetParams, FireCabinetNormative, RectangularRoom,
    compute_plan_reach, compute_spacing_L, generate_positions_along_length,
    layout_rectangular_room, assign_risers, check_required_jet_coverage,
    design_fire_cabinets_for_room,
)


# ── формула шага L: ONE_SIDE ────────────────────────────────────────────────

def test_spacing_one_side_matches_formula():
    jet = JetParams(hose_length_m=20.0, compact_jet_radius_m=12.0)
    H, B = 6.0, 12.0
    L = compute_spacing_L(H, B, jet, PlacementMode.ONE_SIDE)
    # ручной пересчёт по формуле (1): reach=√(12²-(6-1.35)²)+(20-2); L=√(reach²-B²)
    vert = H - 1.35
    reach = math.sqrt(12.0**2 - vert**2) + 18.0
    expected = math.sqrt(reach**2 - B**2)
    assert L == pytest.approx(expected, rel=1e-9)


# ── формула шага L: TWO_OPPOSITE_SIDES (cross = B/2) ─────────────────────────

def test_spacing_two_sides_uses_half_width():
    jet = JetParams(hose_length_m=20.0, compact_jet_radius_m=14.0)
    H, B = 8.0, 18.0
    L1 = compute_spacing_L(H, B, jet, PlacementMode.ONE_SIDE)
    L2 = compute_spacing_L(H, B, jet, PlacementMode.TWO_OPPOSITE_SIDES)
    # при двух сторонах поперечное плечо меньше (B/2) → шаг больше
    assert L2 > L1
    vert = H - 1.35
    reach = math.sqrt(14.0**2 - vert**2) + 18.0
    assert L2 == pytest.approx(math.sqrt(reach**2 - (B / 2)**2), rel=1e-9)


# ── ошибка, если Rk <= H - 1.35 (струя не достаёт до верха) ──────────────────

def test_error_when_jet_cannot_reach_top():
    jet = JetParams(hose_length_m=20.0, compact_jet_radius_m=4.0)  # Rk=4
    H = 6.0  # H-1.35 = 4.65 > Rk
    with pytest.raises(ValueError, match="reach the upper point"):
        compute_plan_reach(H, jet)


# ── помещение, где coverage = True при 1 струе ──────────────────────────────

def test_coverage_true_one_jet():
    room = RectangularRoom("r", 24.0, 12.0, 6.0)
    jet = JetParams(20.0, 12.0)
    norm = FireCabinetNormative(1, False, PlacementMode.ONE_SIDE)
    s = design_fire_cabinets_for_room(room, jet, norm, control_step_m=1.0)
    assert s.coverage_result.ok
    assert s.coverage_result.min_multiplicity >= 1


# ── помещение, где coverage = False при 2 струях ────────────────────────────

def test_coverage_false_two_jets_when_geometry_insufficient():
    # длинный зал + короткий рукав/малый Rk → reach мал, торцы берёт лишь 1 ПК
    room = RectangularRoom("r", 50.0, 8.0, 5.0)
    jet = JetParams(hose_length_m=10.0, compact_jet_radius_m=6.0)  # reach ≈ √(36-13.3)+8 ≈ 12.8
    norm = FireCabinetNormative(2, False, PlacementMode.ONE_SIDE)
    s = design_fire_cabinets_for_room(room, jet, norm, control_step_m=2.0)
    # шаг L мал → ПК много, но точки у торцов достаёт только один ближайший ПК
    assert not s.coverage_result.ok
    assert s.coverage_result.min_multiplicity < 2


# ── require_different_risers=True: две стороны дают два стояка ───────────────

def test_require_different_risers_two_sides():
    room = RectangularRoom("r", 30.0, 16.0, 7.0)
    jet = JetParams(20.0, 14.0)
    norm = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    s = design_fire_cabinets_for_room(room, jet, norm, control_step_m=1.0)
    left = {p.riser_id for p in s.placement_result.placements if p.wall_side == "left"}
    right = {p.riser_id for p in s.placement_result.placements if p.wall_side == "right"}
    assert left == {"R1"} and right == {"R2"}
    # покрытие двумя разными стояками должно быть обеспечено
    assert s.coverage_result.ok
    assert not s.coverage_result.riser_violations


# ── edge_offset: ПК не в самом углу (x >= offset) ───────────────────────────

def test_edge_offset_keeps_cabinets_off_corners():
    xs = generate_positions_along_length(24.0, max_spacing_m=26.0, edge_offset_m=1.0)
    assert min(xs) >= 1.0 - 1e-9
    assert max(xs) <= 24.0 - 1.0 + 1e-9


def test_edge_offset_zero_reaches_ends():
    xs = generate_positions_along_length(24.0, max_spacing_m=26.0, edge_offset_m=0.0)
    assert min(xs) == pytest.approx(0.0)
    assert max(xs) == pytest.approx(24.0)


# ── автовыбор симметрия/шахматка не хуже симметрии ──────────────────────────

def test_auto_pattern_no_worse_than_symmetric():
    room = RectangularRoom("r", 40.0, 18.0, 8.0)
    jet = JetParams(20.0, 14.0)
    norm = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    auto = design_fire_cabinets_for_room(room, jet, norm, auto_pattern=True)
    sym = layout_rectangular_room(room, jet, norm, pattern=SidePattern.SYMMETRIC)
    assign_risers(sym.placements, norm)
    sym_cov = check_required_jet_coverage(room, sym.placements, jet, norm)
    # автовыбор: непокрытых не больше, чем у чистой симметрии
    assert len(auto.coverage_result.insufficient_points) <= len(sym_cov.insufficient_points)


# ── валидации входа ─────────────────────────────────────────────────────────

def test_validate_rejects_bad_room():
    with pytest.raises(ValueError):
        layout_rectangular_room(RectangularRoom("r", -1, 10, 6),
                                JetParams(20, 12),
                                FireCabinetNormative(1, False, PlacementMode.ONE_SIDE))


def test_validate_rejects_three_jets():
    from app.calc.fire_layout import validate_normative
    with pytest.raises(ValueError):
        validate_normative(FireCabinetNormative(3, False, PlacementMode.ONE_SIDE))

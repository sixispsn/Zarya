# -*- coding: utf-8 -*-
"""Тесты app/calc/ring_hydraulics.py — увязка одного кольца методом Хантера-Кросса."""
import pytest

from app.calc.fire_hydraulics import PipeSegment
from app.calc.ring_hydraulics import (
    SingleLoopProblem, RingSolveResult, build_loop_problem, solve_single_loop,
)


def _ring_segments(A1=0.002, A2=0.002):
    """Кольцо R0-R1-R2-R3; A1 — плечо R0→R1→R2, A2 — плечо R2→R3→R0."""
    return [
        PipeSegment("L01", "R0", "R1", length_m=20, A=A1, equiv_length_m=2),
        PipeSegment("L12", "R1", "R2", length_m=25, A=A1, equiv_length_m=2),
        PipeSegment("L23", "R2", "R3", length_m=20, A=A2, equiv_length_m=2),
        PipeSegment("L30", "R3", "R0", length_m=25, A=A2, equiv_length_m=2),
    ]


def _solve(demands=None, **kw):
    problem = build_loop_problem(
        "R0", ["R0", "R1", "R2", "R3"], _ring_segments(**kw),
        demands or {"R1": 2.5, "R2": 2.6})
    return solve_single_loop(problem), problem


# ── сходимость и невязка ─────────────────────────────────────────────────────

def test_converges():
    res, _ = _solve()
    assert res.converged
    assert res.final_residual_m < 1e-4


def test_loop_head_residual_is_zero():
    # ключевой инвариант Кросса: Σh по замкнутому контуру = 0
    res, _ = _solve()
    total = sum(s.head_loss_m for s in res.segments)
    assert abs(total) < 1e-9


# ── узловые балансы ──────────────────────────────────────────────────────────

def test_node_balance_r1():
    res, _ = _solve()
    q = {s.segment_id: s.flow_lps for s in res.segments}
    # приход по L01 − уход по L12 = отбор R1
    assert q["L01"] - q["L12"] == pytest.approx(2.5, abs=1e-6)


def test_node_balance_r2():
    res, _ = _solve()
    q = {s.segment_id: s.flow_lps for s in res.segments}
    # приход по L12 + приход против обхода (−L23) = отбор R2
    assert q["L12"] - q["L23"] == pytest.approx(2.6, abs=1e-6)


def test_source_supplies_total_demand():
    res, _ = _solve()
    q = {s.segment_id: s.flow_lps for s in res.segments}
    # из источника уходит |Q_L01| + |Q_L30| = суммарный отбор
    assert abs(q["L01"]) + abs(q["L30"]) == pytest.approx(5.1, abs=1e-6)


# ── физика распределения ─────────────────────────────────────────────────────

def test_asymmetric_ring_prefers_low_resistance():
    # плечо с меньшим сопротивлением несёт больше расхода
    res, _ = _solve(demands={"R2": 5.0}, A1=0.001, A2=0.005)
    q = {s.segment_id: s.abs_flow_lps for s in res.segments}
    assert q["L01"] > q["L23"]   # лёгкое плечо > тяжёлого


def test_symmetric_ring_splits_evenly():
    # симметричное кольцо с отбором в противоположном узле → плечи поровну
    segs = _ring_segments()
    # выравниваю длины для полной симметрии
    for s in segs:
        s.length_m = 20.0
    problem = build_loop_problem("R0", ["R0", "R1", "R2", "R3"], segs, {"R2": 5.0})
    res = solve_single_loop(problem)
    q = {s.segment_id: s.abs_flow_lps for s in res.segments}
    assert q["L01"] == pytest.approx(q["L30"], rel=1e-3)   # 2.5 / 2.5


# ── смещение напора по узлам ─────────────────────────────────────────────────

def test_node_head_offsets():
    res, _ = _solve()
    off = res.node_head_offset_m
    assert off["R0"] == 0.0                 # источник — ноль
    assert all(v >= 0 for v in off.values())  # потери неотрицательны
    assert set(off) == {"R0", "R1", "R2", "R3"}


# ── валидация ────────────────────────────────────────────────────────────────

def test_invalid_source_not_on_loop():
    problem = SingleLoopProblem("XX", ["R0", "R1", "R2", "R3"],
                                _ring_segments(), {"R1": 2.5})
    res = solve_single_loop(problem)
    assert res.converged is False
    assert any("не на кольце" in w for w in res.warnings)


def test_invalid_zero_demand():
    problem = build_loop_problem("R0", ["R0", "R1", "R2", "R3"],
                                 _ring_segments(), {})
    res = solve_single_loop(problem)
    assert res.converged is False
    assert any("отбор" in w for w in res.warnings)


def test_invalid_segment_order():
    segs = _ring_segments()
    segs[1], segs[2] = segs[2], segs[1]   # ломаю порядок обхода
    problem = SingleLoopProblem("R0", ["R0", "R1", "R2", "R3"], segs, {"R1": 2.5})
    res = solve_single_loop(problem)
    assert res.converged is False


def test_too_few_nodes():
    segs = _ring_segments()[:2]
    problem = SingleLoopProblem("R0", ["R0", "R1"], segs, {"R1": 2.5})
    res = solve_single_loop(problem)
    assert res.converged is False


# ============================================================
# ШАГ 3: ПОЛНЫЙ ПУТЬ ДО ПК ЧЕРЕЗ КОЛЬЦО
# ============================================================

from app.calc.ring_hydraulics import (
    BranchToPK, PKRequiredHead, required_head_via_ring, dictating_pk_via_ring,
)


def _ring_with_risers():
    segs = _ring_segments()
    problem = build_loop_problem("R0", ["R0", "R1", "R2", "R3"], segs,
                                 {"R1": 2.6, "R2": 2.6})
    ring = solve_single_loop(problem)
    riser_A = BranchToPK(
        attach_node="R1",
        segments=[PipeSegment("rA", "R1", "a", length_m=27.5, A=0.011, equiv_length_m=4)],
        flow_lps=2.6, cabinet_id="PK-A", cabinet_head_m=10.19,
        cabinet_elevation_m=27.5, source_elevation_m=0.0)
    riser_B = BranchToPK(
        attach_node="R2",
        segments=[PipeSegment("rB", "R2", "b", length_m=27.5, A=0.011, equiv_length_m=4)],
        flow_lps=2.6, cabinet_id="PK-B", cabinet_head_m=10.19,
        cabinet_elevation_m=27.5, source_elevation_m=0.0)
    return ring, [riser_A, riser_B]


def test_required_head_decomposition_via_ring():
    ring, branches = _ring_with_risers()
    h = required_head_via_ring(ring, branches[0])
    # H_треб = H_ПК + Δz + h_кольца + h_ветви
    assert h.required_head_at_source_m == pytest.approx(
        h.cabinet_head_m + h.geodesic_lift_m + h.ring_loss_m + h.branch_loss_m)


def test_branch_loss_formula():
    ring, branches = _ring_with_risers()
    h = required_head_via_ring(ring, branches[0])
    # потери стояка = A·L_eff·Q² = 0.011·31.5·2.6²
    assert h.branch_loss_m == pytest.approx(0.011 * 31.5 * 2.6 ** 2, rel=1e-9)


def test_dictating_is_max():
    ring, branches = _ring_with_risers()
    dic, heads = dictating_pk_via_ring(ring, branches)
    assert dic.required_head_at_source_m == max(h.required_head_at_source_m for h in heads)


def test_ring_cheaper_than_tree():
    # кольцо экономит напор против дерева: расход делится по плечам,
    # потери подводящей части меньше, чем при одной магистрали с Q_сумм
    ring, branches = _ring_with_risers()
    dic, _ = dictating_pk_via_ring(ring, branches)
    # потери кольца до узла < потерь эквивалентной магистрали с полным расходом
    # (магистраль L=45м А=0.002 с Q=5.2: h = 0.002·49·5.2² ≈ 2.65 м; кольцо даёт <1 м)
    assert dic.ring_loss_m < 1.0


def test_unknown_attach_node_raises():
    ring, branches = _ring_with_risers()
    bad = BranchToPK(attach_node="NOPE", segments=[], flow_lps=2.6,
                     cabinet_id="X", cabinet_head_m=10.0, cabinet_elevation_m=20.0)
    with pytest.raises(ValueError, match="не найден"):
        required_head_via_ring(ring, bad)


def test_empty_branches():
    ring, _ = _ring_with_risers()
    dic, heads = dictating_pk_via_ring(ring, [])
    assert dic is None and heads == []

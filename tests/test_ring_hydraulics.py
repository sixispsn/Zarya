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


# ============================================================
# АВАРИЙНЫЕ РЕЖИМЫ: живучесть при отказе участка кольца
# ============================================================

from app.calc.ring_hydraulics import analyze_ring_resilience


def _resilience_net(available=70.0):
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode,
        HydraulicSource, SourceKind)
    return FireNetwork(
        nodes={"К1": HydraulicNode("К1", 0.0), "К2": HydraulicNode("К2", 0.0),
               "К3": HydraulicNode("К3", 0.0), "К4": HydraulicNode("К4", 0.0),
               "t1": HydraulicNode("t1", 45.6), "t2": HydraulicNode("t2", 45.6),
               "t3": HydraulicNode("t3", 45.6), "t4": HydraulicNode("t4", 45.6)},
        segments=[
            PipeSegment("М1-2", "К1", "К2", length_m=36, A=0.0023, equiv_length_m=6, diameter_mm=100),
            PipeSegment("М2-3", "К2", "К3", length_m=15, A=0.0023, equiv_length_m=4, diameter_mm=100),
            PipeSegment("М3-4", "К3", "К4", length_m=36, A=0.0023, equiv_length_m=6, diameter_mm=100),
            PipeSegment("М4-1", "К4", "К1", length_m=15, A=0.0023, equiv_length_m=4, diameter_mm=100),
            PipeSegment("с1", "К1", "t1", length_m=46.5, A=0.011, equiv_length_m=6, diameter_mm=65),
            PipeSegment("с2", "К2", "t2", length_m=46.5, A=0.011, equiv_length_m=6, diameter_mm=65),
            PipeSegment("с3", "К3", "t3", length_m=46.5, A=0.011, equiv_length_m=6, diameter_mm=65),
            PipeSegment("с4", "К4", "t4", length_m=46.5, A=0.011, equiv_length_m=6, diameter_mm=65)],
        cabinets=[FireCabinetNode("ПК-1", "t1", riser_id="R1"),
                  FireCabinetNode("ПК-2", "t2", riser_id="R2"),
                  FireCabinetNode("ПК-3", "t3", riser_id="R3"),
                  FireCabinetNode("ПК-4", "t4", riser_id="R4")],
        source=HydraulicSource("К1", kind=SourceKind.CITY_MAIN,
                               available_head_m=available))


def test_resilience_covers_every_loop_segment():
    rep = analyze_ring_resilience(_resilience_net(), 2)
    assert rep is not None
    assert {c.failed_segment_id for c in rep.cases} == {"М1-2", "М2-3", "М3-4", "М4-1"}
    assert rep.all_cases_solved


def test_failure_is_worse_than_normal():
    # любой отказ участка кольца ухудшает (или не улучшает) напор
    rep = analyze_ring_resilience(_resilience_net(), 2)
    for c in rep.cases:
        assert c.head_penalty_m >= -1e-6


def test_worst_case_is_max():
    rep = analyze_ring_resilience(_resilience_net(), 2)
    worst = max(c.required_head_at_source_m for c in rep.cases)
    assert rep.worst_case.required_head_at_source_m == pytest.approx(worst)


def test_survives_with_strong_source():
    rep = analyze_ring_resilience(_resilience_net(available=70.0), 2)
    assert rep.survives_worst_case is True


def test_weak_source_flagged():
    # 61 м: штатный режим (60.5) держит, худшую аварию (64+) — нет
    rep = analyze_ring_resilience(_resilience_net(available=61.0), 2)
    assert rep.worst_case.available_head_ok is False
    # но насос закрывает → формально выживает с насосом
    assert rep.worst_case.needs_pump is True


def test_non_ring_returns_none():
    from app.calc.fire_hydraulics import (
        FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource)
    tree = FireNetwork(
        nodes={"a": HydraulicNode("a", 0.0), "b": HydraulicNode("b", 10.0)},
        segments=[PipeSegment("s", "a", "b", length_m=10, A=0.01)],
        cabinets=[FireCabinetNode("ПК", "b")],
        source=HydraulicSource("a"))
    assert analyze_ring_resilience(tree, 1) is None


def test_render_text_readable():
    txt = analyze_ring_resilience(_resilience_net(), 2).render_text()
    assert "ЖИВУЧЕСТИ" in txt
    assert "Худший отказ" in txt
    assert "сохраняет работоспособность" in txt


# ============================================================
# ДВА ВВОДА (MultiSource): двухконтурный Кросс
# ============================================================

from app.calc.ring_hydraulics import (
    TwoSourceLoopProblem, solve_two_source_loop,
    solve_two_source_loop_with_check_valves,
)


def _two_src(h1=50.0, h2=50.0, demands=None):
    segs = [PipeSegment("L01", "R0", "R1", length_m=20, A=0.002, equiv_length_m=2),
            PipeSegment("L12", "R1", "R2", length_m=20, A=0.002, equiv_length_m=2),
            PipeSegment("L23", "R2", "R3", length_m=20, A=0.002, equiv_length_m=2),
            PipeSegment("L30", "R3", "R0", length_m=20, A=0.002, equiv_length_m=2)]
    return TwoSourceLoopProblem(
        source1_node="R0", source1_head_m=h1,
        source2_node="R2", source2_head_m=h2,
        loop_nodes=["R0", "R1", "R2", "R3"], loop_segments=segs,
        node_demands=demands or {"R1": 2.6, "R3": 2.6})


def test_two_source_symmetric_splits_evenly():
    r = solve_two_source_loop(_two_src(50.0, 50.0))
    assert r.converged
    assert r.supply1_lps == pytest.approx(2.6, abs=1e-3)
    assert r.supply2_lps == pytest.approx(2.6, abs=1e-3)


def test_two_source_supply_balance():
    # сумма подач = суммарный отбор (закон сохранения)
    for h2 in (50.0, 48.0, 45.0):
        r = solve_two_source_loop(_two_src(50.0, h2))
        assert r.supply1_lps + r.supply2_lps == pytest.approx(5.2, abs=1e-6)


def test_two_source_boundary_heads_consistent():
    # ключ метода: напор из обхода в узле ввода 2 = его граничный напор
    r = solve_two_source_loop(_two_src(55.0, 48.0))
    assert r.converged
    assert r.node_head_m["R2"] == pytest.approx(48.0, abs=1e-3)
    assert r.node_head_m["R0"] == pytest.approx(55.0)


def test_two_source_stronger_supplies_more():
    r = solve_two_source_loop(_two_src(51.0, 49.0))
    assert r.supply1_lps > r.supply2_lps


def test_two_source_reverse_flagged():
    # сильный перекос → слабый ввод принимает воду → warning
    r = solve_two_source_loop(_two_src(60.0, 40.0))
    assert r.supply2_lps < 0
    assert any("отрицательна" in w for w in r.warnings)


def test_check_valves_close_weak_source():
    r = solve_two_source_loop_with_check_valves(_two_src(60.0, 40.0))
    assert r.converged
    assert r.supply2_lps == 0.0
    assert r.supply1_lps == pytest.approx(5.2)
    assert any("клапан" in w for w in r.warnings)


def test_check_valves_keep_both_when_balanced():
    r = solve_two_source_loop_with_check_valves(_two_src(50.0, 50.0))
    assert r.supply1_lps > 0 and r.supply2_lps > 0
    assert not any("клапан" in w for w in r.warnings)


def test_two_source_invalid_same_node():
    p = _two_src()
    p.source2_node = "R0"
    r = solve_two_source_loop(p)
    assert r.converged is False
    assert any("разных узлах" in w for w in r.warnings)


def test_two_source_loop_residual_zero():
    # инвариант Кросса держится и в двухвводном: Σh по кольцу ≈ 0
    r = solve_two_source_loop(_two_src(53.0, 49.0))
    total = sum(s.head_loss_m for s in r.segments)
    assert abs(total) < 1e-3

"""External inlet topology: unchanged h=A·L_eff·Q², no relocation of Hgar."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.calc.fire_hydraulics import (
    FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource,
    solve_fire_hydraulics_scenario,
)
from app.calc.ring_hydraulics import (
    decompose_ring_network, solve_ring_scenario, solve_two_source_scenario,
    analyze_ring_resilience,
)


def network(*, h1=65.0, h2=65.0, inlet2_length=20.0):
    nodes = {f"R{i}": HydraulicNode(f"R{i}", -.5) for i in range(4)}
    nodes.update({"S1": HydraulicNode("S1", -2), "S2": HydraulicNode("S2", -2),
                  "P1": HydraulicNode("P1", 45), "P2": HydraulicNode("P2", 45)})
    segments = [PipeSegment(f"L{i}", f"R{i}", f"R{(i+1)%4}", 20, .002,
                            diameter_mm=100, repair_section_id=f"SEC{i}") for i in range(4)]
    segments += [PipeSegment("I1", "S1", "R0", 20, .002, equiv_length_m=2, diameter_mm=100),
                 PipeSegment("I2", "S2", "R2", inlet2_length, .002, equiv_length_m=2, diameter_mm=100),
                 PipeSegment("B1", "R1", "P1", 45.5, .01, diameter_mm=65),
                 PipeSegment("B2", "R3", "P2", 45.5, .01, diameter_mm=65)]
    cabs = [FireCabinetNode("PK1", "P1", riser_id="ST1", repair_section_id="SEC1"),
            FireCabinetNode("PK2", "P2", riser_id="ST2", repair_section_id="SEC3")]
    return FireNetwork(nodes, segments, cabs, HydraulicSource("S1", available_head_m=h1),
                       second_source=HydraulicSource("S2", available_head_m=h2))


def solve(net):
    return solve_two_source_scenario(net, net.cabinets, {"PK1":2.6, "PK2":2.6},
                                     {"PK1":10, "PK2":10})


def test_symmetric_two_feeds_have_analytical_flow_and_head():
    net = network()
    before = deepcopy(net)
    out = solve(net)
    assert out.solve.converged
    assert out.supply1_lps == pytest.approx(2.6, abs=1e-4)
    assert out.supply2_lps == pytest.approx(2.6, abs=1e-4)
    # External pressure + external elevation - inlet - half ring - branch - z_PK.
    expected = 65 - 2 - .002*22*2.6**2 - .002*20*1.3**2 - .01*45.5*2.6**2 - 45
    assert all(c.actual_head_at_pk_m == pytest.approx(expected, abs=1e-4) for c in out.per_pk)
    sections = {s.segment_id:s for s in out.sections}
    assert len(sections) == len(net.segments)
    assert sections["I1"].head_loss_m == pytest.approx(.002*22*2.6**2, abs=1e-4)
    assert net == before  # source heads and pipe inputs are not rewritten


def test_single_feed_includes_full_flow_loss_and_external_geodesy_once():
    net = network()
    net.second_source = None
    out = solve_ring_scenario(net, net.cabinets, {"PK1":2.6,"PK2":2.6}, {"PK1":10,"PK2":10})
    expected_inlet = .002*22*5.2**2
    assert out.ring_result.converged
    assert all(p.inlet_loss_m == pytest.approx(expected_inlet) for p in out.per_pk)
    assert all(p.geodesic_lift_m == 47 for p in out.per_pk)
    for p in out.per_pk:
        assert p.required_head_at_source_m == pytest.approx(
            p.cabinet_head_m + 47 + expected_inlet + p.ring_loss_m + p.branch_loss_m)
    sections = {s.segment_id:s for s in out.sections}
    assert sections["I1"].flow_lps == 5.2
    assert "I2" not in sections


def test_asymmetric_inlets_redistribute_flow_and_match_both_boundaries():
    net = network(inlet2_length=80)
    out = solve(net)
    assert out.solve.converged
    assert out.supply1_lps > out.supply2_lps > 0
    assert out.supply1_lps + out.supply2_lps == pytest.approx(5.2)
    assert out.solve.node_head_m["R0"] == pytest.approx(63-.002*22*out.supply1_lps**2, abs=1e-4)
    assert out.solve.node_head_m["R2"] == pytest.approx(63-.002*82*out.supply2_lps**2, abs=1e-4)


def test_boundary_is_piezometric_not_pressure_only():
    reference = solve(network())
    net = network(h2=60)
    net.nodes["S2"].elevation_m = 3  # same total head 63, pressure differs by 5
    out = solve(net)
    assert out.supply1_lps == pytest.approx(reference.supply1_lps)
    assert out.supply2_lps == pytest.approx(reference.supply2_lps)
    assert [p.actual_head_at_pk_m for p in out.per_pk] == pytest.approx(
        [p.actual_head_at_pk_m for p in reference.per_pk])


@pytest.mark.parametrize("strong", [1,2])
def test_check_valve_fallback_charges_only_strong_inlet_at_full_flow(strong):
    net = network(h1=80 if strong == 1 else 30, h2=80 if strong == 2 else 30)
    out = solve(net)
    assert out.solve.converged
    assert getattr(out, f"supply{strong}_lps") == pytest.approx(5.2)
    weak = 3-strong
    assert getattr(out, f"supply{weak}_lps") == 0
    sections = {s.segment_id:s for s in out.sections}
    assert sections[f"I{strong}"].head_loss_m == pytest.approx(.002*22*5.2**2)
    assert sections[f"I{weak}"].head_loss_m == 0
    assert out.solve.node_head_m["R0" if strong == 1 else "R2"] == pytest.approx(78-.002*22*5.2**2)


def test_multi_segment_feeder_is_exact_series_resistance():
    net = network()
    base = solve(net)
    net.nodes["MID"] = HydraulicNode("MID", -1)
    net.segments = [s for s in net.segments if s.segment_id != "I1"] + [
        PipeSegment("I1a", "S1", "MID", 8, .002, diameter_mm=100),
        PipeSegment("I1b", "MID", "R0", 12, .002, equiv_length_m=2, diameter_mm=100)]
    out = solve(net)
    assert out.solve.converged
    assert out.supply1_lps == pytest.approx(base.supply1_lps, abs=1e-4)
    assert [p.actual_head_at_pk_m for p in out.per_pk] == pytest.approx(
        [p.actual_head_at_pk_m for p in base.per_pk], abs=1e-4)


def test_segment_direction_and_input_order_do_not_change_physical_answer():
    net = network(inlet2_length=80)
    reference = solve(net)
    net.segments.reverse()
    for segment in net.segments:
        segment.from_node, segment.to_node = segment.to_node, segment.from_node
    out = solve(net)
    assert out.solve.converged
    assert out.supply1_lps == pytest.approx(reference.supply1_lps, abs=1e-4)
    assert out.supply2_lps == pytest.approx(reference.supply2_lps, abs=1e-4)
    assert out.solve.node_head_m == pytest.approx(reference.solve.node_head_m, abs=1e-4)


def test_both_source_failures_recompute_full_flow_without_relocating_available_head():
    net = network()
    report = analyze_ring_resilience(net, 2)
    assert report.all_cases_solved
    assert not report.normative_warnings
    assert len(report.source_failure_cases) == 2
    for case in report.source_failure_cases:
        remaining = net.source if case.source_used_id == "S1" else net.second_source
        direct = solve_fire_hydraulics_scenario(replace(net, source=remaining, second_source=None), 2)
        assert case.solved and case.available_head_m == 65
        assert case.required_head_at_source_m == pytest.approx(direct.required_head_at_source_m)
        inlet = next(s for s in direct.dictating_scenario.sections if s.segment_id == ("I1" if case.source_used_id == "S1" else "I2"))
        assert inlet.flow_lps == pytest.approx(direct.dictating_scenario.total_flow_lps)
        assert case.required_head_at_source_m > report.normal_required_head_m


@pytest.mark.parametrize("fault", ["missing_head", "offtake", "same_attachment", "negative_resistance", "nan_head"])
def test_unsupported_two_source_inputs_never_fall_back_to_primary_only(fault):
    net = network()
    if fault == "missing_head":
        net.second_source.available_head_m = None
    elif fault == "nan_head":
        net.second_source.available_head_m = float("nan")
    elif fault == "offtake":
        net.nodes["EXTRA"] = HydraulicNode("EXTRA", -2)
        net.segments.append(PipeSegment("EXTRA", "S2", "EXTRA", 2, .002))
    elif fault == "same_attachment":
        next(s for s in net.segments if s.segment_id == "I2").to_node = "R0"
    else:
        next(s for s in net.segments if s.segment_id == "I2").A = -.1
    result = solve_fire_hydraulics_scenario(net, 2)
    assert result.dictating_scenario is None
    assert result.pump_duty is None
    assert any("двухвводный кольцевой сценарий не рассчитан" in w for w in result.warnings)

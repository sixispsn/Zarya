# -*- coding: utf-8 -*-
"""Тесты app/calc/fire_hydraulics.py — проверка пяти инженерных решений:
A·L_eff·Q², L_eff=L+L_eq, явный граф, диктующий по max H_source, напор из табл.7.3."""
import pytest

from app.calc.fire_hydraulics import (
    HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource, FireNetwork,
    SpecificResistanceBackend, DarcyWeisbachBackend, solve_fire_hydraulics,
    MPA_TO_M,
)
from app.data.fire_tables import get_nozzle_data


def _simple_net(available=None, elev=27.5):
    return FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0),
               "n1": HydraulicNode("n1", 0.0),
               "n2": HydraulicNode("n2", elev)},
        segments=[
            PipeSegment("mag", "src", "n1", length_m=30.0, A=0.00246, equiv_length_m=8.0),
            PipeSegment("riser", "n1", "n2", length_m=27.5, A=0.0110, equiv_length_m=4.0),
        ],
        cabinets=[FireCabinetNode("PK-1", "n2", dn=50, nozzle_mm=16, hose_m=20, jet_m=6)],
        source=HydraulicSource("src", available_head_m=available),
    )


# ── решение 1: h = A·L_eff·Q² ────────────────────────────────────────────────

def test_specific_resistance_formula():
    seg = PipeSegment("s", "a", "b", length_m=30.0, A=0.002, equiv_length_m=8.0)
    b = SpecificResistanceBackend()
    # h = A·(L+Leq)·Q² = 0.002·38·2.6²
    assert b.segment_loss(seg, 2.6) == pytest.approx(0.002 * 38.0 * 2.6**2)


# ── решение 2: L_eff = L + L_eq ──────────────────────────────────────────────

def test_effective_length_includes_equiv():
    seg = PipeSegment("s", "a", "b", length_m=30.0, A=0.002, equiv_length_m=8.0)
    assert seg.effective_length_m == 38.0


def test_equiv_length_affects_loss():
    b = SpecificResistanceBackend()
    s_no = PipeSegment("s", "a", "b", length_m=30.0, A=0.002, equiv_length_m=0.0)
    s_eq = PipeSegment("s", "a", "b", length_m=30.0, A=0.002, equiv_length_m=8.0)
    assert b.segment_loss(s_eq, 2.6) > b.segment_loss(s_no, 2.6)


# ── решение 4: H_source,req = H_ПК + Δz + Σh ─────────────────────────────────

def test_required_head_decomposition():
    r = solve_fire_hydraulics(_simple_net(available=40.0))
    c = r.per_cabinet[0]
    assert c.required_head_at_source_m == pytest.approx(
        c.required_head_at_cabinet_m + c.geodesic_lift_m + c.path_head_loss_m)


def test_geodesic_lift_from_source():
    r = solve_fire_hydraulics(_simple_net(elev=27.5))
    assert r.per_cabinet[0].geodesic_lift_m == pytest.approx(27.5)


# ── решение 5: H_ПК из табл. 7.3, не формула ─────────────────────────────────

def test_cabinet_head_from_table_7_3():
    r = solve_fire_hydraulics(_simple_net())
    # DN50/16мм/20м/6м → p=0.100 МПа из табл.7.3
    data = get_nozzle_data(50, 16, 20, 6)
    assert data.p == 0.100
    assert r.per_cabinet[0].required_head_at_cabinet_m == pytest.approx(0.100 * MPA_TO_M)
    assert r.per_cabinet[0].flow_lps == data.q


def test_missing_table_entry_warns_not_invents():
    net = _simple_net()
    net.cabinets[0].jet_m = 99  # нет такой строки в табл.7.3
    r = solve_fire_hydraulics(net)
    # напор не выдуман — H_ПК=0 и предупреждение
    assert r.per_cabinet[0].required_head_at_cabinet_m == 0.0
    assert any("табл. 7.3" in w for w in r.warnings)


# ── вердикт о насосе ─────────────────────────────────────────────────────────

def test_needs_pump_when_head_insufficient():
    r = solve_fire_hydraulics(_simple_net(available=40.0))
    assert r.needs_pump is True
    assert r.available_head_ok is False


def test_no_pump_when_head_sufficient():
    r = solve_fire_hydraulics(_simple_net(available=100.0))
    assert r.needs_pump is False
    assert r.available_head_ok is True


def test_unknown_source_head_gives_none_verdict():
    r = solve_fire_hydraulics(_simple_net(available=None))
    assert r.available_head_ok is None
    assert r.needs_pump is None
    assert r.required_head_at_source_m > 0  # требуемый всё равно считается


# ── диктующий ПК = максимум требуемого напора ───────────────────────────────

def test_dictating_is_max_required_head():
    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0),
               "low": HydraulicNode("low", 3.0),
               "high": HydraulicNode("high", 27.0)},
        segments=[
            PipeSegment("s_low", "src", "low", length_m=10.0, A=0.003),
            PipeSegment("s_high", "src", "high", length_m=30.0, A=0.003),
        ],
        cabinets=[
            FireCabinetNode("PK-low", "low", dn=50, nozzle_mm=16, hose_m=20, jet_m=6),
            FireCabinetNode("PK-high", "high", dn=50, nozzle_mm=16, hose_m=20, jet_m=6),
        ],
        source=HydraulicSource("src", available_head_m=50.0),
    )
    r = solve_fire_hydraulics(net)
    # верхний ПК — больше геодезия и длиннее путь → он диктующий
    assert r.dictating_cabinet_id == "PK-high"


# ── решение 3: граф явный, нет пути → предупреждение ─────────────────────────

def test_disconnected_cabinet_warns():
    net = _simple_net()
    net.cabinets.append(FireCabinetNode("PK-orphan", "n2", dn=50, nozzle_mm=16, hose_m=20, jet_m=6))
    net.nodes["island"] = HydraulicNode("island", 5.0)
    net.cabinets.append(FireCabinetNode("PK-island", "island", dn=50, nozzle_mm=16, hose_m=20, jet_m=6))
    r = solve_fire_hydraulics(net)
    assert any("нет пути" in w for w in r.warnings)


# ── второй backend — заглушка ────────────────────────────────────────────────

def test_darcy_backend_not_implemented():
    seg = PipeSegment("s", "a", "b", length_m=10.0, A=0.0)
    with pytest.raises(NotImplementedError):
        DarcyWeisbachBackend().segment_loss(seg, 2.6)

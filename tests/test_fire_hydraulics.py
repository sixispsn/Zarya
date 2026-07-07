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


# ============================================================
# СЦЕНАРИЙ СОВМЕСТНОЙ РАБОТЫ ПК (вариант 2)
# ============================================================

from app.calc.fire_hydraulics import solve_fire_hydraulics_scenario


def _forked_net(available=45.0):
    """Общая магистраль → развилка на два стояка, по ПК на каждом."""
    return FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5)},
        segments=[
            PipeSegment("mag", "src", "fork", length_m=30.0, A=0.00246, equiv_length_m=8.0),
            PipeSegment("riserA", "fork", "a", length_m=27.5, A=0.0110, equiv_length_m=4.0),
            PipeSegment("riserB", "fork", "b", length_m=27.5, A=0.0110, equiv_length_m=4.0),
        ],
        cabinets=[FireCabinetNode("PK-A", "a", dn=50, nozzle_mm=16, hose_m=20, jet_m=6),
                  FireCabinetNode("PK-B", "b", dn=50, nozzle_mm=16, hose_m=20, jet_m=6)],
        source=HydraulicSource("src", available_head_m=available),
    )


def test_scenario_aggregates_flow_on_shared_segment():
    # шаг 3: через общую магистраль идёт суммарный расход двух ПК
    r = solve_fire_hydraulics_scenario(_forked_net(), required_jets=2)
    s = r.dictating_scenario
    assert s.segment_flows["mag"] == pytest.approx(2 * 2.6)   # оба ПК
    assert s.segment_flows["riserA"] == pytest.approx(2.6)     # личный стояк
    assert s.segment_flows["riserB"] == pytest.approx(2.6)


def test_scenario_two_jets_needs_more_head_than_one():
    # потери на общем участке ∝ Q² → совместный сценарий требует больше напора
    r1 = solve_fire_hydraulics_scenario(_forked_net(), required_jets=1)
    r2 = solve_fire_hydraulics_scenario(_forked_net(), required_jets=2)
    assert r2.required_head_at_source_m > r1.required_head_at_source_m


def test_scenario_loss_uses_aggregated_flow():
    # потери магистрали в сценарии из 2 ПК считаются по 5.2, не по 2.6
    r = solve_fire_hydraulics_scenario(_forked_net(), required_jets=2)
    mag_row = next(row for row in r.dictating_scenario.cabinets[0].path
                   if row.segment_id == "mag")
    assert mag_row.flow_lps == pytest.approx(5.2)
    # h = A·Leff·Q² = 0.00246·38·5.2²
    assert mag_row.head_loss_m == pytest.approx(0.00246 * 38.0 * 5.2**2)


def test_scenario_required_head_is_max_over_cabinets():
    # шаг 5: требуемый напор сценария = max по активным ПК
    r = solve_fire_hydraulics_scenario(_forked_net(), required_jets=2)
    s = r.dictating_scenario
    assert r.required_head_at_source_m == pytest.approx(
        max(c.required_head_at_source_m for c in s.cabinets))


def test_scenario_picks_worst_pair():
    # три ПК на разной высоте; худшая пара — с наибольшим суммарным требованием
    net = _forked_net()
    net.nodes["c"] = HydraulicNode("c", 40.0)  # выше всех
    net.segments.append(PipeSegment("riserC", "fork", "c", length_m=40.0, A=0.0110, equiv_length_m=4.0))
    net.cabinets.append(FireCabinetNode("PK-C", "c", dn=50, nozzle_mm=16, hose_m=20, jet_m=6))
    r = solve_fire_hydraulics_scenario(net, required_jets=2)
    # диктующая пара должна включать самый высокий ПК-C
    assert "PK-C" in r.dictating_scenario.active_cabinet_ids


def test_scenario_one_jet_equals_single_cabinet():
    # required_jets=1 → один активный ПК, совпадает с одиночным расчётом
    r_scen = solve_fire_hydraulics_scenario(_forked_net(), required_jets=1)
    assert len(r_scen.dictating_scenario.active_cabinet_ids) == 1


def test_scenario_total_flow():
    r = solve_fire_hydraulics_scenario(_forked_net(), required_jets=2)
    assert r.dictating_scenario.total_flow_lps == pytest.approx(5.2)


def test_scenario_fewer_candidates_than_jets_warns():
    net = _forked_net()
    net.cabinets = [net.cabinets[0]]  # только один ПК
    r = solve_fire_hydraulics_scenario(net, required_jets=2)
    assert any("меньше required_jets" in w for w in r.warnings)


# ============================================================
# ФИЛЬТР ДОПУСТИМОСТИ СЦЕНАРИЯ (вариант 2: п. 6.2.2 разные стояки)
# ============================================================

def _net_with_risers():
    """4 ПК: A(R1), B(R2), C1(R3), C2(R3) — C1 и C2 на одном стояке."""
    return FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5),
               "c1": HydraulicNode("c1", 24.0), "c2": HydraulicNode("c2", 27.5)},
        segments=[
            PipeSegment("mag", "src", "fork", length_m=30, A=0.00246, equiv_length_m=8),
            PipeSegment("rA", "fork", "a", length_m=27.5, A=0.011, equiv_length_m=4),
            PipeSegment("rB", "fork", "b", length_m=27.5, A=0.011, equiv_length_m=4),
            PipeSegment("rC", "fork", "c1", length_m=24, A=0.011, equiv_length_m=4),
            PipeSegment("rC2", "c1", "c2", length_m=3.5, A=0.011, equiv_length_m=1),
        ],
        cabinets=[
            FireCabinetNode("PK-A", "a", riser_id="R1"),
            FireCabinetNode("PK-B", "b", riser_id="R2"),
            FireCabinetNode("PK-C1", "c1", riser_id="R3"),
            FireCabinetNode("PK-C2", "c2", riser_id="R3"),
        ],
        source=HydraulicSource("src", available_head_m=45.0),
    )


def test_cabinet_has_riser_id():
    cab = FireCabinetNode("PK", "n", riser_id="R1")
    assert cab.riser_id == "R1"


def test_riser_id_defaults_none():
    assert FireCabinetNode("PK", "n").riser_id is None


def test_filter_excludes_same_riser_pair():
    from app.calc.fire_design import build_scenario_filter
    from app.calc.fire_models import FireCabinetNormative, PlacementMode
    norm = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    filt = build_scenario_filter(norm)
    net = _net_with_risers()
    r = solve_fire_hydraulics_scenario(net, 2, scenario_filter=filt)
    # диктующая пара НЕ может быть C1+C2 (один стояк R3)
    ids = set(r.dictating_scenario.active_cabinet_ids)
    assert ids != {"PK-C1", "PK-C2"}


def test_filter_none_allows_same_riser():
    # без фильтра худшая пара может быть с одного стояка
    net = _net_with_risers()
    r = solve_fire_hydraulics_scenario(net, 2)  # фильтра нет
    assert r.evaluated_scenarios == 6  # C(4,2) = 6, ничего не отсеяно


def test_filter_strict_rejects_missing_riser():
    from app.calc.fire_design import build_scenario_filter
    from app.calc.fire_models import FireCabinetNormative, PlacementMode
    norm = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    filt = build_scenario_filter(norm)
    # два ПК, один без riser_id → пара недопустима (строгий режим)
    assert filt((FireCabinetNode("X", "a", riser_id="R1"),
                 FireCabinetNode("Y", "b", riser_id=None))) is False


def test_filter_all_same_riser_returns_warning():
    from app.calc.fire_design import build_scenario_filter
    from app.calc.fire_models import FireCabinetNormative, PlacementMode
    norm = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    filt = build_scenario_filter(norm)
    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "a": HydraulicNode("a", 20.0),
               "b": HydraulicNode("b", 20.0)},
        segments=[PipeSegment("s1", "src", "a", length_m=20, A=0.01),
                  PipeSegment("s2", "src", "b", length_m=20, A=0.01)],
        cabinets=[FireCabinetNode("X", "a", riser_id="R1"),
                  FireCabinetNode("Y", "b", riser_id="R1")],  # оба R1
        source=HydraulicSource("src", available_head_m=50.0),
    )
    r = solve_fire_hydraulics_scenario(net, 2, scenario_filter=filt)
    assert r.dictating_scenario is None
    assert any("отсея" in w for w in r.warnings)


def test_filter_single_cabinet_always_allowed():
    from app.calc.fire_design import build_scenario_filter
    from app.calc.fire_models import FireCabinetNormative, PlacementMode
    norm = FireCabinetNormative(2, True, PlacementMode.TWO_OPPOSITE_SIDES)
    filt = build_scenario_filter(norm)
    assert filt((FireCabinetNode("X", "a", riser_id=None),)) is True  # 1 ПК → ок


def test_filter_off_when_not_required():
    from app.calc.fire_design import build_scenario_filter
    from app.calc.fire_models import FireCabinetNormative, PlacementMode
    norm = FireCabinetNormative(2, False, PlacementMode.ONE_SIDE)  # разные стояки НЕ требуются
    filt = build_scenario_filter(norm)
    # даже одинаковые стояки допустимы
    assert filt((FireCabinetNode("X", "a", riser_id="R1"),
                 FireCabinetNode("Y", "b", riser_id="R1"))) is True


# ============================================================
# РАБОЧАЯ ТОЧКА НАСОСА / ТИПЫ ИСТОЧНИКА (Hydraulic Engine v2.1)
# ============================================================

from app.calc.fire_hydraulics import SourceKind, PumpDutyPoint


def _net_src(source):
    return FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "n1": HydraulicNode("n1", 0.0),
               "n2": HydraulicNode("n2", 27.5)},
        segments=[PipeSegment("mag", "src", "n1", length_m=30, A=0.00246, equiv_length_m=8),
                  PipeSegment("riser", "n1", "n2", length_m=27.5, A=0.011, equiv_length_m=4)],
        cabinets=[FireCabinetNode("PK-1", "n2", riser_id="R1")],
        source=source,
    )


def test_city_sufficient_head_no_pump():
    r = solve_fire_hydraulics_scenario(
        _net_src(HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=45.0)), 1)
    assert r.needs_pump is False
    assert r.pump_duty is None


def test_city_insufficient_pump_covers_deficit():
    r = solve_fire_hydraulics_scenario(
        _net_src(HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=30.0)), 1)
    assert r.needs_pump is True
    # насос добирает недостачу: H_треб − H_город
    assert r.pump_duty.required_head_m == pytest.approx(r.required_head_at_source_m - 30.0)
    assert r.pump_duty.flow_lps == pytest.approx(2.6)
    assert r.pump_duty.source_kind == SourceKind.CITY_MAIN


def test_city_unknown_head_treated_as_zero():
    r = solve_fire_hydraulics_scenario(
        _net_src(HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=None)), 1)
    assert r.needs_pump is True
    # насос на весь требуемый напор
    assert r.pump_duty.required_head_m == pytest.approx(r.required_head_at_source_m)
    assert any("неизвестен" in w for w in r.warnings)


def test_reservoir_pump_includes_suction():
    # уровень воды -3 м (ниже оси насоса) + потери всаса 2 м
    src = HydraulicSource("src", kind=SourceKind.RESERVOIR,
                          water_level_m=-3.0, suction_head_loss_m=2.0)
    r = solve_fire_hydraulics_scenario(_net_src(src), 1)
    assert r.needs_pump is True
    # H_насоса = H_треб + подъём всаса(3) + потери всаса(2)
    assert r.pump_duty.required_head_m == pytest.approx(r.required_head_at_source_m + 3.0 + 2.0)
    assert r.pump_duty.suction_lift_m == pytest.approx(3.0)
    assert r.pump_duty.source_kind == SourceKind.RESERVOIR


def test_reservoir_always_needs_pump():
    # даже без подъёма и потерь — у резервуара напора нет, насос обязателен
    src = HydraulicSource("src", kind=SourceKind.RESERVOIR, water_level_m=0.0)
    r = solve_fire_hydraulics_scenario(_net_src(src), 1)
    assert r.needs_pump is True
    assert r.pump_duty.required_head_m == pytest.approx(r.required_head_at_source_m)


def test_pond_source_kind():
    src = HydraulicSource("src", kind=SourceKind.POND, water_level_m=-1.0, suction_head_loss_m=1.5)
    r = solve_fire_hydraulics_scenario(_net_src(src), 1)
    assert r.pump_duty.source_kind == SourceKind.POND
    assert r.needs_pump is True


def test_pump_flow_equals_scenario_flow():
    # рабочая точка Q = суммарный расход диктующего сценария
    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5)},
        segments=[PipeSegment("mag", "src", "fork", length_m=30, A=0.00246, equiv_length_m=8),
                  PipeSegment("rA", "fork", "a", length_m=27.5, A=0.011, equiv_length_m=4),
                  PipeSegment("rB", "fork", "b", length_m=27.5, A=0.011, equiv_length_m=4)],
        cabinets=[FireCabinetNode("PK-A", "a", riser_id="R1"),
                  FireCabinetNode("PK-B", "b", riser_id="R2")],
        source=HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=20.0),
    )
    r = solve_fire_hydraulics_scenario(net, 2)
    assert r.pump_duty.flow_lps == pytest.approx(5.2)  # 2 струи по 2.6


def test_source_defaults_city_main():
    # обратная совместимость: старый источник без kind → CITY_MAIN
    src = HydraulicSource("src", available_head_m=40.0)
    assert src.kind == SourceKind.CITY_MAIN

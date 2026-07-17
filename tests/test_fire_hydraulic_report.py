# -*- coding: utf-8 -*-
"""Тесты app/calc/fire_hydraulic_report.py — отчёт-сборщик из результатов."""
import pytest

from app.calc.fire_hydraulics import (
    FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource,
    SourceKind, NetworkMode, solve_fire_hydraulics_scenario,
)
from app.calc.diameter_audit import audit_sections, AuditVerdict
from app.calc.fire_hydraulic_report import (
    build_hydraulic_report, FireHydraulicReport,
)


def _net(available=30.0):
    return FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5)},
        segments=[
            PipeSegment("mag", "src", "fork", length_m=30, A=0.00246, equiv_length_m=8, diameter_mm=65),
            PipeSegment("rA", "fork", "a", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50),
            PipeSegment("rB", "fork", "b", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50)],
        cabinets=[FireCabinetNode("PK-A", "a", riser_id="R1"),
                  FireCabinetNode("PK-B", "b", riser_id="R2")],
        source=HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=available))


def _report(available=30.0):
    r = solve_fire_hydraulics_scenario(_net(available), 2, mode=NetworkMode.PURE_FIRE)
    audit = audit_sections(r.dictating_scenario.sections, NetworkMode.PURE_FIRE,
                           dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    return build_hydraulic_report(r, audit)


# ── сборка ───────────────────────────────────────────────────────────────────

def test_report_builds():
    rep = _report()
    assert isinstance(rep, FireHydraulicReport)
    assert rep.header.n_simultaneous == 2
    assert rep.header.total_flow_lps == pytest.approx(5.2)


def test_report_none_when_no_scenario():
    # кольцо → нет диктующего сценария → отчёт None
    ring = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "a": HydraulicNode("a", 10),
               "b": HydraulicNode("b", 10)},
        segments=[PipeSegment("s1", "src", "a", length_m=10, A=0.01),
                  PipeSegment("s2", "a", "b", length_m=10, A=0.01),
                  PipeSegment("s3", "b", "src", length_m=10, A=0.01)],
        cabinets=[FireCabinetNode("PK", "a")],
        source=HydraulicSource("src"))
    r = solve_fire_hydraulics_scenario(ring, 1)
    assert build_hydraulic_report(r) is None


# ── блок 1: шапка ────────────────────────────────────────────────────────────

def test_header_pump_needed():
    rep = _report(available=30.0)   # 30 < 42.6 → насос
    assert rep.header.needs_pump is True
    assert rep.header.pump_duty is not None
    assert rep.header.pump_duty.flow_lps == pytest.approx(5.2)


def test_header_no_pump():
    rep = _report(available=100.0)  # хватает
    assert rep.header.needs_pump is False


# ── блок 2: таблица участков ─────────────────────────────────────────────────

def test_segments_table_has_all():
    rep = _report()
    assert len(rep.segments) == 3
    mag = next(s for s in rep.segments if s.segment_id == "mag")
    assert mag.is_shared is True
    assert mag.flow_lps == pytest.approx(5.2)
    assert mag.inner_diameter_mm == 68.0


# ── блок 3: вердикты по диаметрам ────────────────────────────────────────────

def test_diameter_verdicts_from_audit():
    rep = _report()
    for s in rep.segments:
        assert s.verdict in (AuditVerdict.OK, AuditVerdict.OVERSIZED_TARGET,
                             AuditVerdict.NORMATIVE_FAIL)
        assert s.recommended_dn is not None


# ── блок 4: диктующий путь ───────────────────────────────────────────────────

def test_dictating_path_present():
    rep = _report()
    assert len(rep.dictating_paths) == 1   # один диктующий
    p = rep.dictating_paths[0]
    assert "mag" in p.segments             # путь идёт через магистраль
    assert p.max_loss_segment is not None
    assert p.total_loss_m > 0


# ── блок 5: текст ────────────────────────────────────────────────────────────

def test_render_text_contains_all_blocks():
    txt = _report().render_text()
    assert "РАСЧЁТ ВНУТРЕННЕГО ПРОТИВОПОЖАРНОГО ВОДОПРОВОДА" in txt
    assert "ТАБЛИЦА УЧАСТКОВ" in txt
    assert "ВЕРДИКТ ПО ДИАМЕТРАМ" in txt
    assert "ДИКТУЮЩИЙ ПУТЬ" in txt
    assert "ЗАКЛЮЧЕНИЕ" in txt


def test_conclusion_mentions_pump():
    txt = _report(available=30.0).render_text()
    assert "насосная установка" in txt
    assert "42.6" in txt or "42,6" in txt


def test_conclusion_never_uses_ring_failure_as_pump_duty():
    txt = _report(available=30.0).render_text()
    assert "рабочую точку принять по аварийному режиму" not in txt


def test_conclusion_no_pump_variant():
    txt = _report(available=100.0).render_text()
    assert "не требуется" in txt


# ── DTO не считает, а собирает ───────────────────────────────────────────────

def test_report_does_not_recompute():
    # значения в отчёте берутся из scenario_result, не пересчитываются
    r = solve_fire_hydraulics_scenario(_net(30.0), 2, mode=NetworkMode.PURE_FIRE)
    rep = build_hydraulic_report(r)
    assert rep.header.required_head_at_source_m == r.required_head_at_source_m
    assert rep.header.total_flow_lps == r.dictating_scenario.total_flow_lps

"""Тесты реестра правил соответствия СП 30."""
from app.pz.project import (
    BuildingFlags, BuildingPurpose, FireSystem, FlowsData, HwsType,
    PipeMaterials, Project, PumpSystem, WaterSource,
)
from app.pz.compliance import run_compliance, Verdict


def _resid(**kw):
    b = dict(purpose=BuildingPurpose.RESIDENTIAL, height_m=33.0, zones=2,
             hws_type=HwsType.CENTRAL)
    b.update(kw)
    return Project(building=BuildingFlags(**b),
                   fire=FireSystem(required=True, streams=1, pressure_at_lowest_pk_mpa=0.40),
                   flows=FlowsData(q_hr_h=1.65, q_sec_tot=2.22),
                   pumps=PumpSystem(required=True))


def _verdict(project, clause):
    return {r.clause: r for r in run_compliance(project).results}[clause].verdict


def test_7_10_low_pressure_ok():
    assert _verdict(_resid(), "7.10") == Verdict.COMPLIANT


def test_26_4_high_rise_needs_zoning():
    p = _resid(height_m=60.0, zones=1)
    assert _verdict(p, "26.4") == Verdict.VIOLATION


def test_26_4_low_rise_ok():
    assert _verdict(_resid(height_m=33.0, zones=2), "26.4") == Verdict.COMPLIANT


def test_13_10_zoning_manual():
    assert _verdict(_resid(zones=2), "13.10") == Verdict.MANUAL


def test_13_10_single_zone_na():
    assert _verdict(_resid(zones=1), "13.10") == Verdict.NOT_APPLICABLE


def test_5_12_no_hws_na():
    p = _resid(hws_type=HwsType.NONE)
    assert _verdict(p, "5.12") == Verdict.NOT_APPLICABLE


def test_8_13_residential_manual():
    assert _verdict(_resid(), "8.13") == Verdict.MANUAL


def test_7_7_with_seats_needs_two_streams():
    p = _resid(seats=300)
    # 1 струя при массовом пребывании -> нарушение
    assert _verdict(p, "7.7") == Verdict.VIOLATION


# --- расширенный реестр по водопроводу ---
def test_8_21_below_min_violation():
    p = _resid()
    p.source = WaterSource(h_pr_m=5.0)
    assert _verdict(p, "8.21") == Verdict.VIOLATION


def test_8_21_at_min_ok():
    p = _resid()
    p.source = WaterSource(h_pr_m=20.0)
    assert _verdict(p, "8.21") == Verdict.COMPLIANT


def test_12_11_no_bypass_na():
    p = _resid()
    p.meters.has_bypass = False
    assert _verdict(p, "12.11") == Verdict.NOT_APPLICABLE


def test_12_11_with_bypass_manual():
    p = _resid()
    p.meters.has_bypass = True
    assert _verdict(p, "12.11") == Verdict.MANUAL


def test_11_3_polymer_manual():
    p = _resid()
    p.materials = PipeMaterials(cold_distribution="сшитый полиэтилен PE-Xa")
    assert _verdict(p, "11.3") == Verdict.MANUAL


def test_registry_size():
    # реестр по водопроводу — 14 правил
    assert len(run_compliance(_resid()).results) == 14

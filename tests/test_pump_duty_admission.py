"""L03: deficient catalog curves never become acceptable merely by ranking/name."""
import math

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pumps import router
from app.calc.pumps import PumpInput, calculate_pump, check_pump_duty
from app.data.pumps import PumpCurvePoint as Point, list_pumps
from app.pz.commission import build_commission_report
from app.pz.flows_bridge import pump_from_calc
from app.pz.project import Project, PumpSystem, WaterSource, HwsType
from app.pz.pump_bridge import project_booster_flow_m3h
from app.quality_gates import build_release_quality_report


def test_original_l03_candidate_is_rejected_before_ranking(monkeypatch):
    pump = next(p for p in list_pumps("boost") if p.model == "CR 10-4")
    monkeypatch.setattr("app.calc.pumps.list_pumps", lambda *a, **kw: [pump])
    # Hzero=40 is not enough evidence: H(10)=22 < requested 26.
    result = calculate_pump(PumpInput(
        q_design_m3h=10, h_geom_manual=6, h_losses=5, h_gar=5,
    ))
    assert result.required and not result.candidates
    assert any("нет подтверждённого" in note for note in result.notes)
    ps = pump_from_calc(result)
    assert ps.required and not ps.model and not ps.top3
    assert ps.q_design_m3h == 10 and ps.h_design_m == 26


def test_current_catalog_l03_candidate_with_21_5_m_is_rejected(monkeypatch):
    pump = next(p for p in list_pumps("boost", include_current=True)
                if p.model == "PBS CDM15-2")
    check = check_pump_duty(pump.curve, 16, 25)
    assert not check.ok and check.head_at_design == 21.5
    monkeypatch.setattr("app.calc.pumps.list_pumps", lambda *a, **kw: [pump])
    result = calculate_pump(PumpInput(q_design_m3h=16, h_geom_manual=5,
                                    h_losses=5, h_gar=5))
    assert not result.candidates


@pytest.mark.parametrize("required,expected", [(20, True), (19.9999, True), (20.0001, False)])
def test_full_duty_is_checked_without_engineering_percentage_allowance(required, expected):
    check = check_pump_duty([Point(0, 30), Point(20, 10)], 10, required)
    assert check.ok is expected and check.head_at_design == 20


@pytest.mark.parametrize("curve,q,h", [
    ([], 5, 10), ([Point(0, 30)], 5, 10),
    ([Point(0, 30), Point(0, 20)], 5, 10),
    ([Point(10, 30), Point(20, 20)], 5, 10),
    ([Point(0, 30), Point(10, 20)], 15, 10),
    ([Point(0, 30), Point(10, math.nan)], 5, 10),
    ([Point(0, 30), Point(10, 20)], math.inf, 10),
    ([Point(0, 30), Point(10, 20)], 5, math.nan),
    ([Point(0, 30), Point(10, 20)], 0, 10),
])
def test_missing_invalid_or_outside_curve_never_passes(curve, q, h):
    assert not check_pump_duty(curve, q, h).ok


def test_l04_endpoint_is_now_explicitly_approved():
    from app.calc.pumps import interpolate_pump_head
    curve = [Point(0, 30), Point(10, 20)]
    assert interpolate_pump_head(curve, 10) == 20
    check = check_pump_duty(curve, 10, 15)
    assert check.ok and check.head_at_design == 20


@pytest.mark.parametrize("mode", ["1", "2p", "2s"])
@pytest.mark.parametrize("q", [1, 5, 10, 16, 25, 40])
@pytest.mark.parametrize("h", [10, 25, 55, 100])
def test_every_returned_candidate_covers_duty_independently(mode, q, h):
    result = calculate_pump(PumpInput(
        q_design_m3h=q, h_geom_manual=h, h_losses=5, h_pr=0, h_gar=5,
        mode=mode, include_current_catalog=True,
    ))
    for candidate in result.candidates:
        points = candidate.eff_curve
        assert points[0].q <= q <= points[-1].q
        a, b = next((a, b) for a, b in zip(points, points[1:]) if a.q <= q <= b.q)
        independent = a.h + (b.h-a.h)*(q-a.q)/(b.q-a.q)
        assert independent >= h - 1e-9
        assert candidate.head_at_design == pytest.approx(independent)


def _project():
    p = Project()
    p.source = WaterSource(h_geom_m=6, h_pr_m=20, h_il_m=5, h_vod_m=0,
                           h_vvod_m=0, h_tepl_m=0, guaranteed_head_m=5)
    p.flows.q_sec_c = 10/3.6
    p.flows.q_sec_tot = 16/3.6
    p.pumps = PumpSystem(required=True, model="Stored pump", q_design_m3h=10,
                         h_design_m=26, curve=[(0, 40), (20, 30)])
    return p


def _gate(p):
    report = build_commission_report(p)
    check = next(c for c in report.checks if c.code == "CALC-04")
    quality = build_release_quality_report(None, commission=report)
    return check, quality


def test_release_rechecks_curve_not_just_model_name_or_stored_head():
    p = _project()
    p.pumps.curve = [(0, 40), (10, 22), (11, 16)]
    p.pumps.pump_head_at_design_m = 999  # untrusted cached verdict
    check, quality = _gate(p)
    assert check.blocking and check.status == "fail"
    assert "22.000" in check.result
    assert any(f.code == "CALC-04" for f in quality.blocking_findings)
    assert not quality.can_release


@pytest.mark.parametrize("change", ["no_curve", "no_duty", "null_duty", "more_flow", "more_head", "unknown_head"])
def test_incomplete_or_stale_selection_blocks_release(change):
    p = _project()
    if change == "no_curve":
        p.pumps.curve = []
    elif change == "no_duty":
        p.pumps.q_design_m3h = 0
    elif change == "null_duty":
        p.pumps.q_design_m3h = None
    elif change == "more_flow":
        p.flows.q_sec_c = 20/3.6
    elif change == "more_head":
        p.source.h_il_m = 10
    else:
        p.source.guaranteed_head_m = None
    check, quality = _gate(p)
    assert check.blocking and check.status in {"missing", "fail"}
    assert not quality.can_release


def test_valid_duty_and_no_pump_needed_are_distinct():
    p = _project()
    check, _ = _gate(p)
    assert check.status == "verified" and not check.blocking
    assert "только обеспечение" in check.result
    p.source.guaranteed_head_m = 100
    check, _ = _gate(p)
    assert check.status == "not_applicable" and not check.blocking


@pytest.mark.parametrize("hws,heater,expected", [
    (HwsType.CENTRAL, False, 10), (HwsType.NONE, False, 10),
    (HwsType.LOCAL, False, 16), (HwsType.CENTRAL, True, 16),
])
def test_release_and_selection_use_same_current_flow(hws, heater, expected):
    p = _project()
    p.building.hws_type = hws
    p.source.hws_heater_in_scope = heater
    assert project_booster_flow_m3h(p) == expected


def test_api_contains_no_deficient_candidate_and_preserves_design_head():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        r = client.post("/pumps/calculate", json=dict(
            q_design_m3h=16, h_geom_manual=5, h_losses=5, h_gar=5))
    assert r.status_code == 200
    data = r.json()
    assert data["h_required"] == 25
    assert all(c["head_at_design"] >= 25 for c in data["candidates"])
    assert "PBS CDM15-2" not in [c["pump"]["model"] for c in data["candidates"]]

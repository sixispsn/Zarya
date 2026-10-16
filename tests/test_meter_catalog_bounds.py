"""L05: no max-DN fallback; accepted boundaries, API, saved projects and output."""
from dataclasses import asdict
import math
from pathlib import Path
import runpy

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.water_meters import router
from app.calc.water_meters import MeterInput, MeterSelectionUnavailable, calculate_meters
from app.data.water_meters import WATER_METERS, pick_meter
from app.pz.flows_bridge import meters_from_calc
from app.pz.generator import generate_v1_calculation_html
from app.pz.meter_validation import check_meter_average
from app.pz.project import Project, PumpSystem, WaterSource
from app.pz.commission import build_commission_report


def data(**updates):
    values = dict(q_sec_c=120, q_day_c=9600, q_hr_c=432,
                  q_sec_h=.1, q_day_h=1, q_hr_h=.36,
                  minimum_flow_checks={"cold":dict(dn_mm=250, q_min_hourly_m3h=20,
                      q_min_passport_m3h=15, passport_reference="Synthetic test evidence",
                      flow_reference="Synthetic test minimum")})
    values.update(updates)
    return MeterInput(**values)


@pytest.mark.parametrize("meter", WATER_METERS)
def test_each_catalog_boundary_is_inclusive_and_next_is_not_reused(meter):
    assert pick_meter(meter.q_expl) == meter
    assert pick_meter(math.nextafter(meter.q_expl, 0)) == meter
    next_meter = pick_meter(math.nextafter(meter.q_expl, math.inf))
    assert next_meter is None or next_meter.d_mm > meter.d_mm


@pytest.mark.parametrize("bad", [-1, math.nan, math.inf, -math.inf])
def test_invalid_average_cannot_choose_a_meter(bad):
    with pytest.raises(ValueError):
        pick_meter(bad)


@pytest.mark.parametrize("kind,field", [("central", "q_day_c"), ("central", "q_day_h"),
                                        ("local", "q_day_tot"), ("local", "q_day_c"), ("local", "q_day_h")])
def test_every_meter_branch_rejects_catalog_exhaustion(kind, field):
    values = dict(hws_type=kind, q_day_c=24, q_day_h=24, q_day_tot=24)
    values[field] = 9600
    with pytest.raises(MeterSelectionUnavailable, match="Qсред=400.*Qэкспл=380"):
        calculate_meters(data(**values))


def test_low_loss_and_confirmed_minimum_do_not_override_excess_average():
    maximum = WATER_METERS[-1]
    assert maximum.s * 120**2 == pytest.approx(.2592)
    with pytest.raises(MeterSelectionUnavailable, match="нет подходящего"):
        calculate_meters(data())
    limit = calculate_meters(data(q_day_c=380*24)).meters[0]
    assert limit.meter.d_mm == 250 and limit.pass_normal and limit.pass_sensitivity
    assert limit.pass_average and limit.q_average_m3h == 380


@pytest.mark.parametrize("period", [1, 8, 12, 24])
def test_correct_period_not_peak_or_daily_alone_drives_selection(period):
    limit = calculate_meters(data(period_hours=period, q_day_c=380*period)).meters[0]
    assert limit.q_average_m3h == 380
    with pytest.raises(MeterSelectionUnavailable):
        calculate_meters(data(period_hours=period, q_day_c=380.01*period))


def test_api_returns_clear_unavailable_not_selected_dn250():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        failed = client.post("/meters/calculate", json=asdict(data()))
        assert failed.status_code == 400
        assert "Qсред=400" in failed.json()["detail"]
        assert "Qэкспл=380" in failed.json()["detail"]
        assert "meters" not in failed.json()
        boundary = client.post("/meters/calculate", json=asdict(data(q_day_c=9120)))
        assert boundary.status_code == 200
        row = boundary.json()["meters"][0]
        assert row["meter"]["d_mm"] == 250 and row["pass_average"]
        assert row["q_average_m3h"] == 380


def saved_project():
    project = Project()
    project.source = WaterSource(h_geom_m=10, h_il_m=2, h_vvod_m=1, h_vod_m=.259,
                                 h_tepl_m=0, guaranteed_head_m=5)
    project.flows.q_day_c = 9600
    project.flows.q_day_h = 1
    project.flows.q_day_tot = 9601
    project.flows.q_sec_c = 120
    project.flows.q_sec_tot = 120.1
    project.flows.q_sec_h = .1
    project.meters = meters_from_calc(calculate_meters(data(q_day_c=9120)))
    return project


def test_saved_flags_and_forged_capacity_cannot_bypass_current_average_check():
    project = saved_project()
    row = project.meters.rows[0]
    row.ok_average = True
    row.qexpl = 10000
    ok, note = check_meter_average(row, project.flows, project.source)
    assert ok is False and "400" in note and "380" in note
    gate = next(c for c in build_commission_report(project).checks if c.code == "CALC-03")
    assert gate.status == "fail" and gate.blocking and "400" in gate.result
    html = generate_v1_calculation_html(project)
    assert "не подходит по Qсред" in html and "Qсред=400" in html
    project.source.water_use_period_h = 12
    assert "Qсред=800" in check_meter_average(row, project.flows, project.source)[1]


def test_pipeline_removes_old_meter_pump_and_losses_on_failed_recalculation(tmp_path, monkeypatch):
    from app.pz.ios2_orchestrator import design_ios2
    project = saved_project()
    project.consumer_groups = [("residential_full_bath", 20)]
    project.pumps = PumpSystem(model="Old pump", required=True, wp_q=10, wp_h=50)
    # Explicit flow fixture isolates L05 from other demand-table limits.
    monkeypatch.setattr("app.pz.demand_bridge.compute_flows", lambda *a, **kw: project.flows)
    bundle = design_ios2(project, output_dir=str(tmp_path), render_documents=False)
    p = bundle.project
    assert not p.meters.rows and p.meters.cold_meter_dn is None and p.meters.hot_meter_dn is None
    assert "Qсред=400" in p.meters.selection_error
    assert p.source.h_vod_m is None and p.head_paths is None
    assert not p.pumps.model and not p.pumps.top3
    checks = {c.code:c for c in bundle.commission_report.checks}
    assert checks["CALC-02"].blocking and checks["CALC-03"].blocking and checks["CALC-04"].blocking
    html = generate_v1_calculation_html(p)
    assert "Подбор водомерных узлов не выполнен" in html
    assert "Qсред=400" in html and "Old pump" not in html


def test_studio_ui_cannot_turn_old_or_failed_meter_green():
    js = Path("app/web/static/studio.js").read_text()
    assert "!p.meter_error" in js and "row.ok_average === true" in js
    assert "p.meter_error ? escape(p.meter_error)" in js


def test_original_archive_still_demonstrates_bug_while_l05_overlay_rejects():
    reference = runpy.run_path("tests/test_legacy_meters_execution.py")["legacy_reference"]
    cases = [asdict(data())]
    raw = reference(cases, approved_dn65_correction=True)
    assert raw["cases"][0]["meters"][0]["dn"] == 250
    patched = reference(cases, approved_dn65_correction=True, approved_l05_correction=True)
    assert patched["cases"][0] == dict(unavailable=True, meters=[])
    assert raw["source_sha256"] == patched["source_sha256"]

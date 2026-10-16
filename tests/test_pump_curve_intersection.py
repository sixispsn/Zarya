"""L04: analytical controls, no fake nearest points, shared graph/core and JS oracle."""
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess

import pytest

from app.calc.pump_curve import find_intersections, interpolate_head
from app.calc.pumps import PumpInput, calculate_pump, calculate_pump_at_duty, _find_working_point
from app.data.pumps import PumpCurvePoint, list_pumps
from app.pz.pump_chart import find_working_point, interp_h


@pytest.mark.parametrize("q,expected", [(2, 30), (6, 25), (10, 20), (0, None),
                                      (10.000001, None), (math.nan, None)])
def test_published_range_is_closed_not_extrapolated(q, expected):
    curve = [(2, 30), (10, 20)]
    assert interpolate_head(curve, q) == expected
    assert interp_h(curve, q) == expected


@pytest.mark.parametrize("curve,base,k,expected", [
    ([(0, 10), (10, 0)], 2, .1, (-1 + math.sqrt(4.2)) / .2),
    ([(0, 30), (10, 20)], 10, .1, 10),  # last published point
    ([(2, 8), (6, 4)], 4, 1, 2),        # first published point, no zero-Q data
    ([(0, 10), (10, 0)], 5, 0, 5),      # zero losses, no arbitrary k fallback
    ([(0, 2), (10, 2)], -2, .04, 10),   # signed H0 and clamp
    ([(0, 0), (4, 8)], 1, 1, 1),        # tangency with no change of sign
    ([(0, 10), (5, 5), (10, 0)], 0, .2, 5),  # shared vertex: one root, not two
    ([(0, 1), (4, 0)], -2, .1, 4),      # intersection at inactive system branch
])
def test_intersections_against_independent_analytical_values(curve, base, k, expected):
    result = find_intersections(curve, base, k)
    assert result.status == "unique"
    wp = result.working_point
    assert wp.q == pytest.approx(expected, abs=1e-8)
    assert abs(wp.h - wp.h_sys) <= 1.1e-9
    assert find_working_point(curve, base, k, steps=1) == (wp.q, wp.h)
    assert _find_working_point([PumpCurvePoint(*p) for p in curve], base, k) == wp


@pytest.mark.parametrize("curve,base,k", [
    ([(0, 10), (10, 5)], 20, .1),    # system always above catalog
    ([(0, 40), (10, 30)], 5, .01),   # catalog always above system
    ([(5, 30), (10, 20)], 0, 2),     # root below first published Q
    ([(0, 20), (10, 10)], 0, .001),  # root beyond last published Q
])
def test_no_intersection_is_not_a_nearest_point(curve, base, k):
    result = find_intersections(curve, base, k)
    assert result.status == "none" and not result.points
    assert find_working_point(curve, base, k) is None


@pytest.mark.parametrize("curve,base,k", [
    ([(0, 0), (4, 8)], .75, 1),  # two roots within ONE segment
    ([(0, 5), (10, 5)], 5, 0),  # infinitely many roots
    ([(0, 0), (4, 0)], -2, .1), # coincidence on zero-pressure clamp
    ([(0, 0), (2, 10), (4, 0)], 5, 0),
])
def test_multiple_or_coincident_roots_are_explicitly_ambiguous(curve, base, k):
    result = find_intersections(curve, base, k)
    assert result.status == "ambiguous" and result.working_point is None
    assert find_working_point(curve, base, k) is None


@pytest.mark.parametrize("curve,base,k", [
    ([], 0, 1), ([(0, 1)], 0, 1), ([(0, 2), (0, 1)], 0, 1),
    ([(0, 2), (1, -1)], 0, 1), ([(0, 2), (1, math.nan)], 0, 1),
    ([(0, 2), (1, 1)], math.inf, 1), ([(0, 2), (1, 1)], 0, -1),
])
def test_invalid_inputs_cannot_produce_working_points(curve, base, k):
    assert find_intersections(curve, base, k).status == "invalid"


def test_duty_sufficient_pump_without_intersection_is_not_presented_as_selected(monkeypatch):
    from dataclasses import replace
    pump = replace(list_pumps("boost")[0], curve=(PumpCurvePoint(0, 40), PumpCurvePoint(10, 30)))
    monkeypatch.setattr("app.calc.pumps.list_pumps", lambda *a, **kw: [pump])
    data = PumpInput(q_design_m3h=5, h_geom_manual=5, h_losses=.25, h_pr=0, h_gar=0)
    result = calculate_pump(data)
    assert result.required and not result.candidates
    assert any("Пересечения нет" in note for note in result.notes)
    assert any("Расчётная пара обеспечивается" in note for note in result.notes)
    # Duty-only is distinct: known Q/H is NOT enough to invent a system curve.
    duty = calculate_pump_at_duty(data, required_head_m=5.25)
    assert duty.candidates and duty.curve_kind == "duty_only"
    assert duty.h_stat is None and duty.k_sys is None


@pytest.mark.parametrize("mode", ["1", "2p", "2s"])
@pytest.mark.parametrize("q,h,loss,gar", [(1, 10, 1, 0), (5, 25, 5, 20),
                                        (10, 6, 5, 5), (20, 50, 8, 25)])
def test_all_selected_points_actually_lie_on_both_curves_without_rounding(mode, q, h, loss, gar):
    result = calculate_pump(PumpInput(q_design_m3h=q, h_geom_manual=h, h_losses=loss,
                                    h_gar=gar, mode=mode, include_current_catalog=True))
    for candidate in result.candidates:
        wp = candidate.working_point
        catalog = interpolate_head([(p.q, p.h) for p in candidate.eff_curve], wp.q)
        assert wp.h == pytest.approx(catalog, abs=1e-9)
        assert wp.h == pytest.approx(max(0, result.h_stat + result.k_sys * wp.q**2), abs=1.1e-9)
        assert wp.h_sys == pytest.approx(wp.h, abs=1.1e-9)


def test_independent_algebraic_js_oracle_for_catalog_and_nonmonotonic_probes():
    rng = random.Random(104)
    probes = []
    for pump in list_pumps(include_current=True):
        for base, k in [(0, 0), (15, .2), (-10, .08), (1000, 1)]:
            probes.append(dict(curve=[dict(q=p.q, h=p.h) for p in pump.curve], hstat=base, k=k))
    for _ in range(120):
        probes.append(dict(curve=[dict(q=i*3, h=rng.uniform(0, 80)) for i in range(5)],
                           hstat=rng.uniform(-10, 40), k=rng.uniform(.001, 2)))
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    assert node, "Node is required for the independent L04 oracle"
    oracle = json.loads(subprocess.run(
        [node, str(Path(__file__).resolve().parents[1] / "scripts/legacy_pumps_reference.mjs")],
        input=json.dumps(dict(cases=[], probes=probes, approved_l02_correction=True,
                              approved_l03_correction=True, approved_l04_correction=True)),
        text=True, capture_output=True, check=True,
    ).stdout)
    for probe, expected in zip(probes, oracle["probes"], strict=True):
        result = find_intersections([(p["q"], p["h"]) for p in probe["curve"]],
                                    probe["hstat"], probe["k"])
        if expected is None:
            assert result.working_point is None, probe
        else:
            assert result.status == "unique", probe
            assert result.working_point.q == pytest.approx(expected["q"], abs=1e-7)
            assert result.working_point.h == pytest.approx(expected["h"], abs=1e-7)


def test_exact_last_catalog_point_is_admitted_through_api(monkeypatch):
    from dataclasses import replace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.pumps import router
    pump = replace(list_pumps("boost")[0], curve=(PumpCurvePoint(0, 30), PumpCurvePoint(10, 20)))
    monkeypatch.setattr("app.calc.pumps.list_pumps", lambda *a, **kw: [pump])
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/pumps/calculate", json=dict(q_design_m3h=10, h_geom_manual=10,
                                                            h_losses=10, h_pr=0, h_gar=0))
    assert response.status_code == 200
    point = response.json()["candidates"][0]["working_point"]
    assert point == dict(q=10, h=20, h_sys=20)


@pytest.mark.parametrize("change", ["rounded", "no_intersection", "ambiguous", "stale_system", "missing"])
def test_saved_false_intersection_blocks_release_and_loses_green_marker(change):
    from app.pz.flows_bridge import pump_from_calc
    from app.pz.generator import _pump_chart_for, generate_pump_selection_html
    from app.pz.project import Project, WaterSource
    from app.pz.pump_validation import check_project_booster, check_saved_pump_intersection
    from app.pz.rules import calc_required_head
    p = Project()
    p.source = WaterSource(h_geom_m=25, h_pr_m=20, h_il_m=3, h_vod_m=1,
                           h_vvod_m=1, h_tepl_m=0, guaranteed_head_m=20)
    p.flows.q_sec_c = 5/3.6
    p.flows.q_sec_tot = 5/3.6
    p.pumps = pump_from_calc(calculate_pump(PumpInput(
        q_design_m3h=5, h_geom_manual=25, h_losses=5, h_gar=20)))
    head = calc_required_head(p.source)
    assert check_saved_pump_intersection(p.pumps)[0]
    assert check_project_booster(p, head)[0] == "verified"
    assert 'data-role="working-point"' in _pump_chart_for(p.pumps)
    if change == "rounded":
        p.pumps.wp_q = round(p.pumps.wp_q, 2)
        p.pumps.wp_h = round(p.pumps.wp_h, 1)
    elif change == "no_intersection":
        p.pumps.curve = [(0, 100), (11, 90)]
    elif change == "ambiguous":
        p.pumps.curve = [(0, 40), (2, 20), (5, 40), (11, 40)]
    elif change == "stale_system":
        p.pumps.h_stat += .5
    else:
        p.pumps.wp_q = 0
    assert not check_saved_pump_intersection(p.pumps)[0]
    assert check_project_booster(p, head)[0] == "fail"
    assert 'data-role="working-point"' not in _pump_chart_for(p.pumps)
    html = generate_pump_selection_html(p)
    assert "требуется пересчёт" in html
    assert "Пересечение не подтверждено; маркер рабочей точки не показан" in html

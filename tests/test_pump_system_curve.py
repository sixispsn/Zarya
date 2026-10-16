"""Approved L02: same head balance in calculation, selection, API and PDF chart."""
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from xml.etree import ElementTree as ET

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pumps import router
from app.calc.pump_system_curve import PumpSystemCurve, required_boost_head
from app.calc.pumps import PumpInput, calculate_pump
from app.pz.flows_bridge import pump_from_calc
from app.pz.generator import _pump_chart_for, generate_pump_selection_html
from app.pz.project import Project, PumpSystem, WaterSource
from app.pz.pump_bridge import compute_pump, compute_pump_from_head
from app.pz.rules import calc_required_head

ROOT = Path(__file__).resolve().parents[1]
BASE = PumpInput(q_design_m3h=5, h_geom_manual=25, h_losses=5, h_pr=20, h_gar=40)


@pytest.mark.parametrize("q", [.1, 5, 14.4612, 50, 5000])
@pytest.mark.parametrize("loss", [0, .00001, 5, 8.007, 50])
@pytest.mark.parametrize("available", [0, 20, 40, 47, 50, 100])
def test_curve_passes_through_design_head_for_all_source_regimes(q, loss, available):
    curve = PumpSystemCurve(q, 25, loss, 20, available)
    assert curve.h_base == 45 - available
    assert curve.h_required == pytest.approx(max(0, 45 + loss - available), abs=1e-12)
    assert curve.head_at(q) == pytest.approx(curve.h_required, abs=1e-12)
    assert curve.head_at(0) <= curve.head_at(q / 2) <= curve.head_at(q)
    assert curve.head_at(2 * q) == pytest.approx(max(0, 45 - available + 4 * loss))


def test_audit_case_and_serialized_curve_have_the_same_ten_meters():
    result = calculate_pump(BASE)
    assert (result.h_required, result.h_stat, result.k_sys) == (10, 5, .2)
    assert required_boost_head(result.h_stat, result.k_sys, result.q_design) == 10
    model = pump_from_calc(result)
    assert model.curve_kind == "quadratic_estimate"
    assert required_boost_head(model.h_stat, model.k_sys, model.q_design_m3h) == model.h_design_m


def test_small_coefficient_is_not_rounded_to_zero_before_plotting():
    result = calculate_pump(replace(BASE, q_design_m3h=1000, h_losses=3.4567))
    model = pump_from_calc(result)
    assert result.k_sys == pytest.approx(.0000034567)
    assert required_boost_head(model.h_stat, model.k_sys, 1000) == pytest.approx(8.4567)


@pytest.mark.parametrize("available", [50, 51, 100])
def test_no_pump_when_source_covers_design_demand(available):
    result = calculate_pump(replace(BASE, h_gar=available))
    assert result.h_required == 0
    assert not result.required and not result.candidates
    assert not pump_from_calc(result).required
    ps, h = compute_pump(q_design_m3h=5, floors=9, h_losses_m=5, h_gar_m=available)
    assert not ps.required and h == 0


def test_negative_intercept_is_not_clamped_before_adding_losses():
    result = calculate_pump(replace(BASE, h_gar=47))
    assert result.h_stat == -2
    assert result.h_required == 3
    assert required_boost_head(result.h_stat, result.k_sys, 0) == 0


@pytest.mark.parametrize("field,value", [
    ("h_losses", None), ("h_losses", -1), ("h_losses", math.inf),
    ("h_geom_manual", math.nan), ("h_gar", None), ("h_gar", math.nan),
    ("h_pr", -1), ("q_design_m3h", 0), ("q_design_m3h", math.nan),
])
def test_incomplete_and_invalid_input_is_not_replaced_by_defaults(field, value):
    with pytest.raises(ValueError):
        calculate_pump(replace(BASE, **{field: value}))


def test_missing_geometry_is_not_nine_floors_by_default():
    with pytest.raises(ValueError, match="Hgeom"):
        calculate_pump(replace(BASE, h_geom_manual=None))


def test_pz_bridge_uses_real_head_components_and_does_not_add_losses_twice():
    head = calc_required_head(WaterSource(
        h_geom_m=25, h_pr_m=20, h_il_m=3, h_vod_m=1, h_vvod_m=1,
        h_tepl_m=0, guaranteed_head_m=40,
    ))
    ps = compute_pump_from_head(q_design_m3h=5, head=head)
    assert ps.h_design_m == head.h_pump_m == 10
    assert (ps.h_stat, ps.k_sys) == (5, .2)


def test_live_api_contract_requires_losses_and_preserves_curve_precision():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        payload = dict(q_design_m3h=14.4612, h_geom_manual=25, h_losses=8.007, h_gar=40)
        response = client.post("/pumps/calculate", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["q_design"] == payload["q_design_m3h"]
        assert required_boost_head(data["h_stat"], data["k_sys"], data["q_design"]) == pytest.approx(data["h_required"])
        assert data["notes"] and data["curve_kind"] == "quadratic_estimate"
        del payload["h_losses"]
        missing = client.post("/pumps/calculate", json=payload)
        assert missing.status_code == 400 and "Потери" in missing.json()["detail"]


def test_svg_and_pdf_text_distinguish_curve_estimate_and_required_point():
    ps = pump_from_calc(calculate_pump(BASE))
    svg = _pump_chart_for(ps)
    root = ET.fromstring(svg)
    assert len(root.findall(".//*[@data-role='system-curve']")) == 1
    assert len(root.findall(".//*[@data-role='design-point']")) == 1
    assert "nan" not in svg.lower() and "inf" not in svg.lower()
    # With negative intercept, no point may be drawn below the Q-axis (y=275).
    ps.h_stat = -2
    points = ET.fromstring(_pump_chart_for(ps)).find(".//*[@data-role='system-curve']").get("points")
    assert all(float(p.split(",")[1]) <= 275 for p in points.split())
    ps = pump_from_calc(calculate_pump(BASE))
    project = Project()
    project.source = WaterSource(h_geom_m=25, h_il_m=3, h_vod_m=1,
                                 h_vvod_m=1, h_tepl_m=0, guaranteed_head_m=40)
    project.pumps = ps
    html = generate_pump_selection_html(project)
    assert "Оценочная кривая" in html and "опубликованном диапазоне" in html
    assert "требует завершения аудита L04" not in html
    old = PumpSystem(required=True, curve=ps.curve, h_stat=40, k_sys=.1)
    assert "system-curve" not in _pump_chart_for(old)


def _legacy(cases, correction):
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        pytest.fail("Node required for legacy comparison")
    return json.loads(subprocess.run(
        [node, str(ROOT / "scripts/legacy_pumps_reference.mjs")],
        input=json.dumps({"cases": cases, "approved_l02_correction": correction,
                         "approved_l03_correction": correction,
                         "approved_l04_correction": correction}),
        text=True, capture_output=True, check=True,
    ).stdout)


def test_archive_preserved_and_only_approved_curve_overlay_changes_selection():
    audit = dict(q=5, geom=25, loss=5, gar=40)
    raw = _legacy([audit], False)
    assert raw["source_sha256"] == "ace54b14e2f30fadaec768ec06aa5a326553709b9a869263208ef8ee58df3788"
    assert raw["cases"][0]["hstat"] == 40
    assert raw["cases"][0]["k"] == .1
    deficient = dict(q=10, geom=6, loss=5, gar=5)
    assert _legacy([deficient], False)["cases"][0]["candidates"][0]["model"] == "CR 10-4"
    assert not _legacy([deficient], True)["cases"][0]["candidates"]
    cases = [dict(q=q, geom=g, loss=loss, gar=a, mode=m)
             for m in ("1", "2p", "2s")
             for q, g, loss, a in [(5,25,5,20),(5,25,5,40),(10,50,8,20),(5,25,5,47)]]
    corrected = _legacy(cases, True)
    for data, expected in zip(cases, corrected["cases"], strict=True):
        result = calculate_pump(PumpInput(
            q_design_m3h=data["q"], h_geom_manual=data["geom"], h_losses=data["loss"],
            h_gar=data["gar"], npsh_a=8, mode=data["mode"],
        ))
        assert len(result.candidates) == len(expected["candidates"])
        for actual, wanted in zip(result.candidates, expected["candidates"], strict=True):
            assert actual.pump.model == wanted["model"]
            assert actual.score == wanted["score"]
            assert actual.working_point.q == pytest.approx(wanted["wp"]["q"], abs=1e-8)
            assert actual.working_point.h == pytest.approx(wanted["wp"]["h"], abs=1e-8)

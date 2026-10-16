"""L07: no booster head in T4; SP30(16) is an explicitly separate extension."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pumps import router
from app.calc.hws_circulation import CirculationHeatLoss, calculate_circulation_demand
from app.calc.pumps import PumpInput, calculate_pump
from tests.legacy_history import pre_l08_builder_source

ROOT = Path(__file__).resolve().parents[1]
PUMP = PumpInput(q_design_m3h=1.8, pump_type="circ", circulation_head_m=5,
                 circulation_basis="ТЕСТ: тепловой расчёт и потери кольца с оборудованием")
LOSSES = (
    CirculationHeatLoss("supply", "T3", 1200, "ТЕСТ: расчёт Т3"),
    CirculationHeatLoss("return", "T4", 800, "ТЕСТ: расчёт Т4"),
    CirculationHeatLoss("equipment", "equipment", 100, "ТЕСТ: расчёт оборудования"),
)


def thermal(parts=LOSSES, **kwargs):
    inputs = dict(delta_t_c=5, temperature_basis="ТЕСТ: обеспечение 60 °C у потребителей",
                  heat_losses_complete=True)
    inputs.update(kwargs)
    return calculate_circulation_demand(parts, **inputs)


def test_circulation_is_independent_of_booster_fields_and_has_no_fake_intersection():
    reference = calculate_pump(PUMP)
    # Before L07, these inputs yielded 0 and 41 m instead of the same ring head.
    for height in (4, 46, 100):
        for gar in (0, 30, 100):
            actual = calculate_pump(replace(PUMP, h_geom_manual=height, h_gar=gar,
                                            h_pr=20, h_losses=5, floors=40))
            assert asdict(actual) == asdict(reference)
    assert reference.h_required == 5
    assert reference.required
    assert reference.curve_kind == "duty_only"
    assert (reference.h_geom, reference.h_stat, reference.k_sys) == (None, None, None)
    assert reference.candidates[0].head_at_design == pytest.approx(8.06)
    assert reference.candidates[0].npsh_ok is None
    assert "13.12" in " ".join(reference.notes)
    assert "питьевой горячей воды" in " ".join(reference.notes)


@pytest.mark.parametrize("field,value", [
    ("circulation_head_m", None), ("circulation_head_m", 0), ("circulation_head_m", -1),
    ("circulation_head_m", math.nan), ("circulation_head_m", math.inf),
    ("circulation_basis", ""), ("circulation_basis", "   "),
    ("q_design_m3h", 0), ("q_design_m3h", math.inf),
    ("npsh_a", math.nan), ("npsh_a", -1),
    ("mode", "unknown"),
])
def test_missing_circulation_data_is_not_replaced_by_draw_off_or_defaults(field, value):
    with pytest.raises(ValueError):
        calculate_pump(replace(PUMP, h_losses=5, h_geom_manual=46, h_gar=30,
                               **{field: value}))


def test_missing_old_circ_inputs_are_rejected_not_reinterpreted():
    with pytest.raises(ValueError, match="Т4"):
        calculate_pump(PumpInput(q_design_m3h=1.8, pump_type="circ", h_losses=5,
                                h_geom_manual=46, h_gar=30))


def test_heat_balance_units_and_no_rounding():
    result = thermal()
    assert result.status == "preliminary"
    assert result.heat_loss_kw == 2.1
    assert result.flow_lps == pytest.approx(.1)
    assert result.flow_m3h == pytest.approx(.36)
    assert not result.missing
    unrounded = thermal(delta_t_c=7.123)
    assert unrounded.flow_m3h == 2.1 / (4.2 * 7.123) * 3.6
    assert "(16)" in result.method


@pytest.mark.parametrize("system", ("T3", "T4", "equipment"))
def test_no_implicit_zero_for_a_missing_system(system):
    result = thermal([p for p in LOSSES if p.system != system])
    assert result.status == "needs_data"
    assert result.flow_lps is None and result.flow_m3h is None
    assert any(system in msg for msg in result.missing)


def test_all_required_thermal_evidence_and_completeness():
    for change in (dict(delta_t_c=None), dict(temperature_basis=""), dict(heat_losses_complete=False)):
        assert thermal(**change).status == "needs_data"
    for i in range(len(LOSSES)):
        for change in (dict(heat_loss_w=None), dict(basis=" ")):
            parts = list(LOSSES)
            parts[i] = replace(parts[i], **change)
            assert thermal(parts).flow_lps is None


@pytest.mark.parametrize("dt", [0, -1, 10.001, math.inf, math.nan])
def test_sp30_delta_t_limits(dt):
    with pytest.raises(ValueError):
        thermal(delta_t_c=dt)


def test_ten_degrees_is_allowed_but_not_assumed():
    assert thermal(delta_t_c=10).flow_lps == pytest.approx(.05)
    assert thermal(delta_t_c=None).flow_lps is None


def test_shared_sections_not_counted_twice_and_unknown_material_not_assumed():
    with pytest.raises(ValueError, match="дважды"):
        thermal([*LOSSES, LOSSES[0]])
    with pytest.raises(ValueError):
        thermal([replace(LOSSES[0], system="unknown"), *LOSSES[1:]])
    with pytest.raises(ValueError):
        thermal([replace(LOSSES[0], element_id="  "), *LOSSES[1:]])


@pytest.mark.parametrize("loss", [-1, math.inf, math.nan])
def test_thermal_losses_must_be_finite_nonnegative(loss):
    with pytest.raises(ValueError):
        thermal([replace(p, heat_loss_w=loss) for p in LOSSES])


def test_zero_requires_explicit_basis_and_does_not_auto_select_a_pump():
    parts = [replace(p, heat_loss_w=0) for p in LOSSES]
    result = thermal(parts)
    assert result.flow_lps == 0 and result.status == "preliminary"
    with pytest.raises(ValueError):
        calculate_pump(replace(PUMP, q_design_m3h=result.flow_m3h))
    with pytest.raises(ValueError):
        thermal([replace(p, heat_loss_w=1e308) for p in LOSSES])


def test_booster_still_requires_its_own_data():
    with pytest.raises(ValueError, match="Hгар"):
        calculate_pump(replace(PUMP, pump_type="boost"))
    data = PumpInput(q_design_m3h=5, h_geom_manual=25, h_gar=40, h_losses=5)
    assert asdict(calculate_pump(data)) == asdict(calculate_pump(
        replace(data, circulation_head_m=1, circulation_basis="irrelevant")))


def test_actual_working_legacy_matches_circulation_catalog_admission_and_scores():
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    assert node, "Node is required for parity"
    cases = [dict(q=q, head=h, basis="TEST", mode=mode, npsh=npsh)
             for mode in ("1", "2p", "2s") for q in (.1, 1.8, 3.5, 6, 6.001, 12, 12.001)
             for h in (3, 5, 8.5, 17, 20) for npsh in (None, 1, 8)]
    run = subprocess.run([node, str(ROOT / "scripts/legacy_circulation_reference.mjs")],
                         input=json.dumps(dict(cases=cases)), capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    for c, raw in zip(cases, json.loads(run.stdout), strict=True):
        result = calculate_pump(replace(PUMP, q_design_m3h=c["q"], circulation_head_m=c["head"],
                                        circulation_basis=c["basis"], mode=c["mode"], npsh_a=c["npsh"]))
        assert raw["h_required"] == result.h_required
        assert raw["curve_kind"] == result.curve_kind
        assert raw["k_sys"] is None
        assert [x["model"] for x in raw["candidates"]] == [x.pump.model for x in result.candidates]
        for a, b in zip(raw["candidates"], result.candidates, strict=True):
            assert a["head"] == pytest.approx(b.head_at_design, abs=1e-12)
            assert a["score"] == b.score
            assert a["npsh_ok"] is b.npsh_ok


def test_l07_preserves_previous_working_legacy_algorithms_verbatim():
    # Reconstruct the verified pre-L07 working copy in memory, never the archive.
    # This is a compatibility check, not a numerical oracle for circulation.
    from scripts.rebuild_working_legacy import build
    path = ROOT / "scripts/rebuild_working_legacy.py"
    # L08 is separately approved/tested. Reconstruct the actual L07 builder
    # before isolating L07, so this historical proof keeps its fixed hash.
    source = pre_l08_builder_source()
    l07_ns = {"__file__": str(path), "__name__": "compatibility_check"}
    exec(compile(source, str(path), "exec"), l07_ns)
    l07_html = l07_ns["build"]()
    start = source.index("    # L07: separate blank inputs")
    end = source.index("    # Historical JS-only crash", start)
    previous_builder = (source[:start] + source[end:]).replace(
        "<b>Рабочий legacy · 06.10.2026</b> — исправлены L01–L05, L07 (чистая циркуляция), DN65 и проверка минимума водомера.",
        "<b>Рабочий legacy · 21.09.2026</b> — исправлены L01–L05, DN65 и проверка минимума водомера.")
    ns = {"__file__": str(path), "__name__": "compatibility_check"}
    exec(compile(previous_builder, str(path), "exec"), ns)
    previous = ns["build"]()
    assert sha256(previous.encode()).hexdigest() == "00a14a5b5ec9a195894db4da92e2439b6453f4e71e34e89a48c5b622e68068e4"
    old = re.findall(r"<script[^>]*>(.*?)</script>", previous, flags=re.S)
    new = re.findall(r"<script[^>]*>(.*?)</script>", l07_html, flags=re.S)
    current = re.findall(r"<script[^>]*>(.*?)</script>", build(), flags=re.S)
    assert len(current) == 7
    assert all(a == b for a, b in zip(new, current, strict=True) if 'const PUMP_CURVES = [' not in a)
    assert len(old) == len(new) == 7
    changed = [i for i, (a, b) in enumerate(zip(old, new, strict=True)) if a != b]
    assert len(changed) == 1
    a, b = old[changed[0]], new[changed[0]]
    assert "const PUMP_CURVES = [" in a
    start = b.index("// L07: чистая циркуляция")
    end = b.index("  const required = [", start)
    assert b[:start] + "function calcPumpHead() {\n" + b[end:] == a


def test_api_circulation_does_not_require_hgar_and_thermal_endpoint_is_explicit():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/pumps/calculate", json=dict(q_design_m3h=1.8, pump_type="circ",
        circulation_head_m=5, circulation_basis="TEST"))
    assert response.status_code == 200, response.text
    assert response.json()["h_required"] == 5
    assert response.json()["h_stat"] is None
    assert client.post("/pumps/calculate", json=dict(q_design_m3h=1.8, pump_type="circ",
        h_gar=30, h_geom_manual=46, h_losses=5)).status_code == 400
    assert client.post("/pumps/calculate", json=dict(q_design_m3h=1.8)).status_code == 400
    response = client.post("/pumps/circulation-demand", json={})
    assert response.status_code == 200 and response.json()["status"] == "needs_data"
    request = dict(components=[asdict(p) for p in LOSSES], delta_t_c=5,
                   temperature_basis="TEST", heat_losses_complete=True)
    response = client.post("/pumps/circulation-demand", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["flow_m3h"] == pytest.approx(.36)
    assert client.post("/pumps/circulation-demand", json={**request, "delta_t_c": 11}).status_code == 400
    assert client.post("/pumps/circulation-demand", json={**request, "pipe_material": "guess"}).status_code == 422

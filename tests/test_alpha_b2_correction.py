"""L01: official B.2 golden, boundary regressions and explicit JS overlay parity."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.water_demand import router
from app.calc.water_demand import ConsumerGroup, _calc_block, calculate_water_demand
from app.data.sp30_tables import ALPHA_TABLE, CONSUMER_NORMS, get_alpha

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/sp30_b2_official.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())
POINTS = [(float(x), float(y)) for x, y, _ in FIXTURE["rows"]]


def test_reviewed_fixture_fingerprint_and_extent():
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == (
        "8a02e2e3eaa936e0b402e67599905ab2d42b61266ef999c0f7bc9b4c3915c483"
    )
    assert len(POINTS) == 581
    assert POINTS[0] == (0.015, 0.202)
    assert POINTS[-1] == (2000, 426.8)
    assert {page for _, _, page in FIXTURE["rows"]} == set(range(112, 119))
    assert ALPHA_TABLE == POINTS


@pytest.mark.parametrize("np_value,alpha", POINTS)
def test_every_published_cell(np_value, alpha):
    assert get_alpha(np_value) == alpha


@pytest.mark.parametrize("left,right", zip(POINTS, POINTS[1:]))
def test_interpolation_and_monotonicity_in_every_interval(left, right):
    x0, a0 = left
    x1, a1 = right
    assert x1 > x0 and a1 > a0
    middle = (x0 + x1) / 2
    assert get_alpha(middle) == pytest.approx((a0 + a1) / 2, abs=1e-12)
    assert a0 <= get_alpha(math.nextafter(x0, x1)) <= get_alpha(middle)
    assert get_alpha(middle) <= get_alpha(math.nextafter(x1, x0)) <= a1


def test_former_boundary_has_no_drop():
    assert get_alpha(62.999) == pytest.approx(17.38976)
    assert get_alpha(63) == 17.39
    assert get_alpha(63.001) == pytest.approx(17.39023)
    assert get_alpha(70) == 19.02


def test_lower_boundary_is_not_confused_with_less_than_row():
    assert get_alpha(math.nextafter(0.015, 0)) == 0.200
    assert get_alpha(0.015) == 0.202


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 2001, math.nextafter(2000, math.inf)])
def test_never_approximate_invalid_or_unsupported_np(value):
    with pytest.raises(ValueError):
        get_alpha(value)


@pytest.mark.parametrize("count,hourly,second", [
    (500, 10.075, 4.025), (1629, 26.081, 9.340), (1630, 26.094, 9.344),
    (5865, 81.437, 26.083), (5866, 81.450, 26.087),
])
def test_corrected_residential_goldens(count, hourly, second):
    result = calculate_water_demand([ConsumerGroup("residential_full_bath", count)])
    assert result.total.q_hr == hourly
    assert result.total.q_sec == second
    assert result.total.q_day == round(count * 0.18, 3)


def test_api_reports_table_limit_instead_of_a_fabricated_result():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/water-demand/calculate", json={
            "groups": [{"code": "residential_full_bath", "count": 100000}],
        })
    assert response.status_code == 400
    assert "предел таблицы Б.2" in response.json()["detail"]


def _reference(cases, *, correction, points=()):
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        pytest.fail("Node is required for demand parity; set NODE_BINARY")
    result = subprocess.run(
        [node, str(ROOT / "scripts/legacy_demand_reference.mjs")],
        input=json.dumps({
            "cases": cases, "points": list(points), "approved_l01_correction": correction,
        }), text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def test_original_html_remains_the_historical_oracle():
    raw = _reference([], correction=False, points=[63, 70])
    assert raw["approved_l01_correction"] is False
    assert raw["source_sha256"] == (
        "ace54b14e2f30fadaec768ec06aa5a326553709b9a869263208ef8ee58df3788"
    )
    assert raw["alpha"] == pytest.approx([12.598009953977556, 13.291975802])
    corrected = _reference([], correction=True, points=[63, 70, 2000])
    assert corrected["approved_l01_correction"] is True
    assert corrected["alpha"] == [17.39, 19.02, 426.8]


def test_calcblock_formulas_match_js_with_only_the_approved_b2_overlay():
    cases = []
    for norm in CONSUMER_NORMS.values():
        for count in (1, 20, 100, 480, 500, 1629, 1630, 5865, 5866):
            groups = [ConsumerGroup(norm.code, count)]
            try:
                calculate_water_demand(groups)
            except ValueError as exc:
                assert "предел таблицы Б.2" in str(exc)
                continue
            cases.append(groups)
    cases.append([ConsumerGroup("residential_full_bath", 1630), ConsumerGroup("office", 480)])
    reference = _reference([
        [{"label": CONSUMER_NORMS[g.code].label, "count": g.count} for g in groups]
        for groups in cases
    ], correction=True)
    assert len(cases) >= 200
    for groups, expected in zip(cases, reference["cases"], strict=True):
        norms = [CONSUMER_NORMS[g.code] for g in groups]
        for kind, qhr, q0, q0hr in [
            ("total", lambda n: n.q_hr_tot, lambda n: n.q0_tot, lambda n: n.q0hr_tot),
            ("cold", lambda n: n.q_hr_tot - n.q_hr_h, lambda n: n.q0_c, lambda n: n.q0hr_c),
            ("hot", lambda n: n.q_hr_h, lambda n: n.q0_h, lambda n: n.q0hr_h),
        ]:
            actual = _calc_block(groups, norms, qhr, q0, q0hr)
            assert actual[:2] == pytest.approx(
                (expected[kind]["q_sec"], expected[kind]["q_hr"]), rel=1e-12, abs=1e-12
            ), (groups, kind)

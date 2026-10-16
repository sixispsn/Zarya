"""Approved L08 + separate CNP method; not hydraulic confirmation of Samara."""
from dataclasses import asdict, replace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pumps import router
from app.calc.pump_suction import NpshaInput, calculate_npsha
from app.calc.pumps import PumpInput, calculate_pump
from scripts.rebuild_working_legacy import WORKING
from tests.test_working_legacy import execute


def example(**updates):
    # Independent arithmetic fixture, not values assigned to any project.
    return replace(NpshaInput(
        pressure_kind="absolute", pressure_bar=1, source_elevation_m=0,
        pump_elevation_m=2, suction_losses_m=1, vapor_head_m=.2,
        temperature_c=20, max_flow_m3h=12,
        basis="Контрольная арифметика; Hv условно задан явно, не таблица температуры",
        npshr_m=2, npshr_basis="Контрольное значение при Qmax=12",
    ), **updates)


def test_independent_golden_balance_and_manufacturer_rearrangement():
    data = example()
    result = calculate_npsha(data)
    assert result.available_m == pytest.approx(7)
    assert result.required_m == 2.5
    assert result.margin_m == pytest.approx(4.5)
    assert result.check_ok is True
    # Manufacturer's Hmax = Pb*10.2 - NPSHr - Hf - Hv - Hs.
    max_lift = 10.2 - 2 - 1 - .2 - .5
    assert result.margin_m == pytest.approx(max_lift - 2)


def test_gauge_and_absolute_pressure_equivalent_no_double_atmosphere():
    gauge = calculate_npsha(example(pressure_kind="gauge", pressure_bar=0,
                                   atmospheric_pressure_bar=1))
    assert gauge == calculate_npsha(example())
    assert calculate_npsha(example(pressure_kind="gauge", pressure_bar=-.1,
                                  atmospheric_pressure_bar=1)).available_m == pytest.approx(5.98)
    with pytest.raises(ValueError, match="повторно"):
        calculate_npsha(example(atmospheric_pressure_bar=1))


@pytest.mark.parametrize("name", ["pressure_kind", "pressure_bar", "source_elevation_m",
    "pump_elevation_m", "suction_losses_m", "vapor_head_m", "temperature_c", "max_flow_m3h"])
def test_each_missing_input_blocks_balance_no_zero_or_eight_default(name):
    result = calculate_npsha(example(**{name: None}))
    assert result.status == "needs_data" and name in result.missing
    assert result.available_m is None and result.check_ok is None


def test_missing_atmosphere_and_bases_are_not_guessed():
    result = calculate_npsha(example(pressure_kind="gauge", basis=" "))
    assert result.missing == ["atmospheric_pressure_bar", "basis"]
    for change in ({"npshr_m": None}, {"npshr_basis": ""}):
        result = calculate_npsha(example(**change))
        assert result.status == "available_only"
        assert result.available_m == pytest.approx(7)
        assert result.check_ok is None and result.required_m is None


def test_zero_values_signed_elevations_and_negative_balance_are_preserved():
    result = calculate_npsha(example(source_elevation_m=-3, pump_elevation_m=-3,
                                     suction_losses_m=0, vapor_head_m=0, npshr_m=0))
    assert result.available_m == 10.2
    for lift in (10.2, 11.2):
        result = calculate_npsha(example(pump_elevation_m=lift, suction_losses_m=0, vapor_head_m=0))
        assert result.available_m == pytest.approx(10.2-lift)
        assert result.status == "insufficient_margin" and result.check_ok is False


def test_full_precision_equality_boundary_and_monotonicity():
    base = example(pump_elevation_m=0, suction_losses_m=0, vapor_head_m=0, npshr_m=9.7)
    assert calculate_npsha(base).check_ok is True  # 10.2 == 9.7+0.5
    assert calculate_npsha(replace(base, suction_losses_m=1e-10)).check_ok is False
    # Same printed 3-digit NPSHa, different check: no pre-rounded comparisons.
    for key in ("suction_losses_m", "vapor_head_m", "pump_elevation_m"):
        assert calculate_npsha(replace(base, **{key: 1})).available_m == pytest.approx(9.2)
    assert calculate_npsha(replace(base, source_elevation_m=1)).available_m == pytest.approx(11.2)


@pytest.mark.parametrize("change", [
    {"pressure_kind":"unknown"}, {"pressure_bar":0}, {"pressure_bar":-1},
    {"pressure_kind":"gauge", "pressure_bar":-1, "atmospheric_pressure_bar":1},
    {"suction_losses_m":-1}, {"vapor_head_m":-1}, {"max_flow_m3h":0},
    {"npshr_m":-1}, {"safety_margin_m":.49}, {"safety_margin_m":None},
    {"pressure_bar":float('inf')}, {"suction_losses_m":float('nan')},
    {"pump_elevation_m":True}, {"pressure_bar":1e308},
    {"npshr_m":1e308, "safety_margin_m":1e308},
])
def test_invalid_explicit_data_not_replaced(change):
    with pytest.raises(ValueError):
        calculate_npsha(example(**change))


def test_cnp_method_python_working_html_parity_without_overlay():
    cases = [example(), example(pressure_kind="gauge", pressure_bar=2, atmospheric_pressure_bar=1),
             example(pump_elevation_m=-3), example(suction_losses_m=0),
             example(pump_elevation_m=50), example(npshr_m=None),
             example(npshr_basis=""), example(basis=""),
             example(pressure_kind="gauge"), NpshaInput()]
    for key in ("pressure_kind", "pressure_bar", "source_elevation_m", "pump_elevation_m",
                "suction_losses_m", "vapor_head_m", "max_flow_m3h", "temperature_c"):
        cases.append(example(**{key:None}))
    raw = execute('legacy_pumps_reference.mjs', npsha=[asdict(c) for c in cases])
    for data, expected in zip(cases, raw['npsha'], strict=True):
        actual = asdict(calculate_npsha(data))
        for key, value in expected.items():
            if isinstance(value, (float,int)) and not isinstance(value, bool):
                assert actual[key] == pytest.approx(value, abs=1e-12)
            else:
                assert actual[key] == value


def test_cnp_js_rejects_invalid_data_like_python():
    cases = [example(pressure_bar=0), example(atmospheric_pressure_bar=1),
             example(suction_losses_m=-1), example(max_flow_m3h=0),
             example(safety_margin_m=.1), example(pressure_kind="wrong")]
    raw = execute('legacy_pumps_reference.mjs', npsha=[asdict(c) for c in cases])
    assert all('error' in row for row in raw['npsha'])


@pytest.mark.parametrize('mode', ['1', '2p', '2s'])
@pytest.mark.parametrize('npsh', [None, 0, .1, 2, 4, 8])
def test_l08_pump_selector_parity_unknown_zero_and_known(npsh, mode):
    data = dict(geom=25, loss=5, gar=20, q=5, mode=mode, npsh_a=npsh)
    raw = execute('legacy_pumps_reference.mjs', cases=[data])['cases'][0]
    result = calculate_pump(PumpInput(q_design_m3h=5, h_geom_manual=25, h_losses=5,
                                      h_gar=20, npsh_a=npsh, mode=mode))
    assert result.candidates
    assert [r.pump.model for r in result.candidates] == [r['model'] for r in raw['candidates']]
    for actual, expected in zip(result.candidates, raw['candidates'], strict=True):
        assert actual.score == expected['score']
        assert actual.npsh_ok is expected['npsh_ok']
        assert asdict(actual.working_point) == pytest.approx(expected['wp'], abs=1e-8)
        if npsh is None:
            assert actual.npsh_ok is None
            assert any('не задан' in reason for reason in expected['reasons'])
            assert not any('кавитации нет' in reason for reason in expected['reasons'])
        if npsh == 0:
            assert actual.npsh_ok is False


def test_l08_success_then_delete_or_invalidate_clears_state():
    base = dict(geom=25, loss=5, gar=20, q=5)
    cases = [{**base, 'npsh_a':value} for value in (8, None, -1, 'bad', 'Infinity', 0)]
    raw = execute('legacy_pumps_reference.mjs', cases=cases, capture_ui=True)['cases']
    assert raw[0]['candidates'][0]['npsh_ok'] is True
    assert raw[1]['candidates'][0]['npsh_ok'] is None
    for row in raw[2:5]:
        assert row['candidates'] == [] and row['wp'] is None
        assert row['ui']['formula'] == ''
        assert row['ui']['result'] == 'Ошибка исходных данных'
    assert raw[5]['candidates'][0]['npsh_ok'] is False
    html = WORKING.read_text()
    assert 'id="npsh_a" value=""' in html
    assert "getElementById('npsh_a').value || 8" not in html
    assert 'Отдельный расчёт NPSHa · CNP' in html


def test_api_is_reproducible_and_does_not_accept_guaranteed_head_alias():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post('/pumps/npsha', json=asdict(example()))
    assert response.status_code == 200
    assert response.json()['available_m'] == pytest.approx(7)
    assert response.json()['inputs'] == asdict(example())
    missing = client.post('/pumps/npsha', json={}).json()
    assert missing['status'] == 'needs_data' and missing['available_m'] is None
    assert client.post('/pumps/npsha', json={'h_gar':30}).status_code == 422
    assert client.post('/pumps/npsha', json=asdict(example(pressure_bar=0))).status_code == 400
    assert client.post('/pumps/npsha', json=asdict(example(safety_margin_m=.1))).status_code == 422


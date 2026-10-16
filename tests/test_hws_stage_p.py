"""Stage P is a separate, reproducible estimate, not final loop hydraulics."""
from dataclasses import asdict, replace
from decimal import Decimal as D
from hashlib import sha256
import math
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pumps import router
from app.calc.hws_stage_p import HwsStagePInput, calculate_stage_p_circulation as calc
from app.intake.project_builder import build_project
from app.intake.studio_intake import build_handoff_request
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.hws_stage_p import stage_p_circulation
from app.pz.generator import generate_pz_html
from app.pz.ios2_orchestrator import design_ios2
from app.pz.compliance import _check_5_12, Verdict
from tests import test_studio as studio_tests
from tests.legacy_history import build_pre_l08_legacy

INPUT = HwsStagePInput(enabled=True, apartment_building=True,
                      water_towel_rails=True, zones=1, delta_t_c=5)
client = studio_tests.client


def test_formula_independent_golden_units_and_no_selected_default():
    r = calc(INPUT, 1)
    base = D('1.16') * D(1) * D(60)
    lo = base * D('.30') / (D('4.2') * D(5))
    hi = base * D('.40') / (D('4.2') * D(5))
    assert r.status == 'preliminary'
    assert r.base_heat_kw == pytest.approx(float(base))
    assert r.heat_loss_range_kw == pytest.approx((20.88, 27.84))
    assert r.flow_range_lps == pytest.approx((float(lo), float(hi)))
    assert r.flow_range_m3h == pytest.approx((float(lo * D('3.6')), float(hi * D('3.6'))))
    assert r.selected_flow_lps is None and r.selected_heat_loss_kw is None


@pytest.mark.parametrize('zones,percent', [(1,30), (1,35), (1,40), (2,30), (2,50), (2,60)])
def test_explicit_coefficient_and_temperature_use_current_data(zones, percent):
    inp = replace(INPUT, zones=zones, loss_percent=percent, hot_temp_c=70, cold_temp_c=10, delta_t_c=7)
    r = calc(inp, 1.23456789)
    heat = 1.16 * 1.23456789 * 60 * percent / 100
    assert r.selected_heat_loss_kw == heat
    assert r.selected_flow_lps == heat / (4.2 * 7)
    assert r.selected_flow_m3h == r.selected_flow_lps * 3.6
    assert r.percent_range == (30, 60 if zones == 2 else 40)


@pytest.mark.parametrize('key,value', [
    ('enabled','yes'), ('water_towel_rails','yes'), ('apartment_building',1),
    ('zones',True), ('zones',1.5), ('zones',0), ('hot_temp_c',math.nan),
    ('cold_temp_c',math.inf), ('cold_temp_c',True), ('delta_t_c',math.inf),
    ('loss_percent',math.nan), ('loss_percent',29.9), ('loss_percent',40.1),
    ('delta_t_c',0), ('delta_t_c',-1), ('delta_t_c',10.1), ('delta_t_c',6),
    ('hot_temp_c',59), ('hot_temp_c',76), ('cold_temp_c',65),
])
def test_invalid_data_not_clamped_or_replaced(key,value):
    with pytest.raises(ValueError):
        calc(replace(INPUT, **{key:value}), 1)


@pytest.mark.parametrize('key', ['apartment_building','water_towel_rails','zones','delta_t_c'])
def test_unknown_inputs_are_not_inferred(key):
    r = calc(replace(INPUT, **{key:None}), 1)
    assert r.status == 'needs_data' and r.missing and r.flow_range_lps is None


@pytest.mark.parametrize('data,context', [
    (replace(INPUT,apartment_building=False),{}),
    (replace(INPUT,water_towel_rails=False),{}),
    (replace(INPUT,zones=3),{}),
    (INPUT,{'purpose':'public'}), (INPUT,{'purpose':'industrial'}),
    (INPUT,{'hws_type':'local'}), (INPUT,{'hws_type':'none'}), (INPUT,{'stage':'Р'}),
])
def test_applicability_is_not_a_general_percent_for_all_buildings(data,context):
    r = calc(data, 1, **context)
    assert r.status == 'not_applicable' and r.flow_range_lps is None


@pytest.mark.parametrize('q', [0,-1,True,math.inf,math.nan,1e308])
def test_invalid_hourly_flow(q):
    with pytest.raises(ValueError):
        calc(INPUT,q)


def test_missing_disabled_and_no_hydraulic_outputs():
    assert calc(INPUT,None).status == 'needs_data'
    assert calc(HwsStagePInput(),None).status == 'not_requested'
    r = asdict(calc(INPUT,1))
    assert not {'head_m','kv','diameter','pump','branches'} & r.keys()


def test_api_boundary_and_unsupported_data():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        req = dict(asdict(INPUT),hot_hour_m3h=1)
        response = c.post('/pumps/circulation-stage-p',json=req)
        assert response.status_code == 200
        assert response.json()['flow_range_lps'] == pytest.approx(calc(INPUT,1).flow_range_lps)
        assert c.post('/pumps/circulation-stage-p',json={**req,'delta_t_c':10}).status_code == 400
        assert c.post('/pumps/circulation-stage-p',json={**req,'cold_temp_c':True}).status_code == 422
        assert c.post('/pumps/circulation-stage-p',json={**req,'water_towel_rails':'yes'}).status_code == 422
        assert c.post('/pumps/circulation-stage-p',json={**req,'stage':'Р'}).json()['status'] == 'not_applicable'


def prepare(client):
    state = studio_tests.residential_project(client)
    before = client.post('/studio/api/calculate',json={'revision':state['revision']}).json()
    state = before
    for key,value in dict(building_purpose='residential',hws_stage_p_enabled='yes',
                          hws_water_towel_rails='yes',hws_circulation_zones='1',hws_delta_t_c=5).items():
        state = studio_tests.answer(client,state,key,value)
    result = client.post('/studio/api/calculate',json={'revision':state['revision']})
    assert result.status_code == 200, result.text
    return before,result.json()


def test_studio_runs_without_plans_preserves_demand_and_invalidates_previous_result(client):
    before,state = prepare(client)
    assert state['calculation'] == before['calculation']
    p = state['project_calculation']
    r = p['hws_circulation']
    assert r['status'] == 'preliminary'
    assert r['hot_hour_m3h'] == p['flows']['q_hr_h']
    assert r['selected_flow_lps'] is None
    # Nothing is injected into hydraulic paths or pumps by this estimate.
    for key in ('head','hot_hydraulics','pumps'):
        assert p[key] == before['project_calculation'][key]
    state = studio_tests.answer(client,state,'hws_loss_percent',35)
    assert state.get('project_calculation') is None
    state = client.post('/studio/api/calculate',json={'revision':state['revision']}).json()
    assert state['project_calculation']['hws_circulation']['selected_flow_lps'] is not None
    state = studio_tests.answer(client,state,'hws_water_towel_rails','no')
    state = client.post('/studio/api/calculate',json={'revision':state['revision']}).json()
    assert state['project_calculation']['hws_circulation']['status'] == 'not_applicable'
    assert state['project_calculation']['hws_circulation']['selected_flow_lps'] is None


def test_yaml_builder_pz_and_current_recalculation(client,tmp_path):
    _, state = prepare(client)
    # Stored draft, not public serialisation, is the input to the adapter.
    from app.intake.studio_store import StudioStore
    store = StudioStore(tmp_path/'studio')
    draft = store.load(state['project_id'])
    request = build_handoff_request(draft)
    yaml = dump_request(request)
    restored = load_request(yaml)
    assert restored.hws_stage_p == request.hws_stage_p
    bundle = design_ios2(build_project(restored),output_dir=str(tmp_path/'bundle'),render_documents=False)
    p = bundle.project
    html = generate_pz_html(p)
    assert 'data-hws-circulation="stage-p"' in html
    assert 'одно значение не выбрано' in html
    assert 'гидравлический расчёт циркуляционных колец' in html
    before = stage_p_circulation(p)
    p.flows.q_hr_h *= 2
    assert stage_p_circulation(p).flow_range_lps[0] == before.flow_range_lps[0]*2
    assert _check_5_12(p)[0] == Verdict.MANUAL
    p.hws_stage_p = replace(p.hws_stage_p,water_towel_rails=False)
    assert 'data-hws-circulation="stage-p"' not in generate_pz_html(p)
    p.hws_stage_p = replace(INPUT,zones=2)
    assert p.building.zones == 1  # Two HWS zones do not imply two cold-water zones.
    assert stage_p_circulation(p).percent_range == (30,60)
    from app.pz.hws_presentation import hws_principle
    from app.pz.hws_building_drafting import can_draw_hws_section
    assert hws_principle(p).zones_unresolved
    assert not can_draw_hws_section(p)  # Never draw two unbound zones as one loop.
    with pytest.raises(YamlFormatError):
        load_request(yaml.replace('water_towel_rails: true','water_towel_rails: "yes"'))


def test_studio_two_hws_zones_do_not_change_cold_water(client,tmp_path):
    before,state = prepare(client)
    state = studio_tests.answer(client,state,'hws_circulation_zones','2')
    state = client.post('/studio/api/calculate',json={'revision':state['revision']}).json()
    p = state['project_calculation']
    assert p['hws_circulation']['percent_range'] == [30,60]
    for key in ('head','hot_hydraulics','pumps'):
        assert p[key] == before['project_calculation'][key]
    from app.intake.studio_store import StudioStore
    draft = StudioStore(tmp_path/'studio').load(state['project_id'])
    request = build_handoff_request(draft)
    assert request.zones == 1 and request.hws_stage_p.zones == 2


def test_legacy_unchanged_by_new_extension():
    root = Path(__file__).resolve().parents[1]
    assert sha256((root/'legacy/archive/sp30_calculator.pre-2026-09-21.html').read_bytes()).hexdigest() == 'ace54b14e2f30fadaec768ec06aa5a326553709b9a869263208ef8ee58df3788'
    # Stage-P was added after L07, before the separately approved L08. Keep
    # its historical hash rather than replacing it with today's working hash.
    assert sha256(build_pre_l08_legacy().encode('utf-8')).hexdigest() == 'b48c0ec54673bf4bb02bdcff0538ecfcc9040f1b8e934a68b452094724b55ac1'


def test_current_legacy_is_reproducible_and_preserves_nonpump_blocks():
    from scripts.rebuild_working_legacy import WORKING, build

    current = WORKING.read_text(encoding='utf-8')
    assert current == build()
    old_blocks = re.findall(r'<script[^>]*>(.*?)</script>', build_pre_l08_legacy(), flags=re.S)
    current_blocks = re.findall(r'<script[^>]*>(.*?)</script>', current, flags=re.S)
    assert len(old_blocks) == len(current_blocks) == 7
    changed = [i for i, (old, new) in enumerate(zip(old_blocks, current_blocks, strict=True))
               if old != new]
    assert len(changed) == 1
    assert 'const PUMP_CURVES = [' in old_blocks[changed[0]]
    # L08 behavior (blank/zero/invalid/known NPSHa and stale result clearing)
    # is checked independently against the actual HTML in test_pump_suction.

"""Optional rainwater pump/assembly extension; no changes to legacy demand."""
from dataclasses import asdict, replace
from copy import deepcopy

import pytest

from app.calc.rainwater_reuse import assess, from_dict, RainwaterReuseInput
from app.calc.rainwater_pump import assess_pump
from app.data.rainwater_pumps import CATALOG
from app.calc.pump_curve import interpolate_head
from app.intake.studio_intake import validate_value, IntakeError
from app.intake.yaml_io import load_request, dump_request
from app.intake.request_dto import IOS2Request, DocumentRequest
from app.pz.rainwater_reuse import specification_rows, assembly_rows, pump_chart_svg
from app.pz.generator import generate_rainwater_reuse_html
from scripts.preview_rainwater_reuse import example_project
from tests import test_studio as studio

client = studio.client


def example():
    return example_project().rainwater_reuse


def test_duty_and_catalog_do_not_create_fictitious_operating_intersection():
    r = assess_pump(example())
    assert r['status'] == 'preliminary'
    assert r['duty']['q_m3h'] == pytest.approx(1.44)
    assert r['duty']['h_m'] == 30
    p = r['selected']
    assert p['id'] == 'vodomet-55-50-a'
    assert p['nominal_head_m'] == pytest.approx(38.14)
    assert p['lower_head_m'] == pytest.approx(32.419)
    assert p['pressure_check_bar'] == pytest.approx(5.83495675)
    assert 'working_point' not in r
    assert 'не фактическая рабочая точка' in pump_chart_svg(example_project())


def test_larger_pump_or_no_match_not_reduced_requirement():
    d = replace(example(), pump_terminal_head_m=35)
    assert assess_pump(d)['selected']['id'] == 'vodomet-55-75-a'
    r = assess_pump(replace(d, pump_terminal_head_m=100))
    assert r['status'] == 'no_match' and r['selected'] is None
    assert r['duty']['h_m'] == 110


def test_hose_pressure_dry_run_and_temperature_can_reject_good_qh():
    r = assess_pump(replace(example(), hose_pn_bar=3))
    assert r['status'] == 'no_match'
    assert all(any('давление шланга' in x for x in c['reasons']) for c in r['candidates'])
    for patch in ({'pump_clean_water':'no'}, {'pump_min_submergence_m':.1},
                  {'pump_max_submergence_m':31}, {'pump_temperature_c':36},
                  {'pump_pipe_inner_mm':20}, {'pump_min_submergence_m':3}):
        r = assess_pump(replace(example(), **patch))
        assert r['status'] == 'invalid' and r['selected'] is None


@pytest.mark.parametrize('key', ['pump_flow_lps','pump_geometric_head_m','pump_terminal_head_m',
    'pump_network_loss_m','pump_treatment_loss_m','hose_loss_m','hose_pn_bar'])
def test_missing_is_not_zero_and_never_keeps_old_selection(key):
    r = assess_pump(replace(example(), **{key:None}))
    assert r['status'] == 'needs_data' and r['duty'] is None and r['selected'] is None


def test_without_hose_ignores_old_hose_inputs_and_no_required_pump():
    d = replace(example(), hose_choice='none', hose_loss_m=100, hose_pn_bar=1)
    assert assess_pump(d)['duty']['h_m'] == 27
    assert assess_pump(d)['selected']
    d = replace(d, pump_geometric_head_m=-30)
    assert assess_pump(d)['status'] == 'not_required'
    assert assess_pump(d)['selected'] is None
    assert assess(replace(example(),enabled=False))['pump']['status'] == 'not_configured'


def test_graph_range_and_min_cooling_flow_never_extrapolated():
    for p in CATALOG:
        assert interpolate_head(p['curve'], .18) == p['curve'][0][1]
        assert interpolate_head(p['curve'], 3) == p['curve'][-1][1]
        assert interpolate_head(p['curve'], 3.01) is None
    for q in (.049, .84):
        assert assess_pump(replace(example(),pump_flow_lps=q))['status'] == 'no_match'


def test_no_repurpose_toilet_network_or_sum_parallel_hose_losses():
    assert assess_pump(replace(example(),purpose='toilets'))['status'] == 'invalid'
    p = example_project()
    assert assess_pump(p.rainwater_reuse)['duty']['hose_m'] == 3
    rows = assembly_rows(p)
    assert next(r for r in rows if r.name == 'Поливочный шланг').qty == 2
    assert next(r for r in rows if r.name.startswith('Тройник')).qty == 2  # 1 comb + 1 drain
    assert next(r for r in rows if r.name.startswith('Присоединители')).qty == 4
    assert not any(r.name.startswith('Обратный клапан') for r in rows)
    assert not any(r.name.startswith('Поплав') for r in rows)
    assert all(r.qty is None or r.unit=='м' or r.qty==int(r.qty) for r in rows)
    full = specification_rows(p)
    assert sum('Погружной насос' in r.name for r in full) == 1
    p.rainwater_reuse.hose_pn_bar=1
    rows=assembly_rows(p)
    assert next(r for r in rows if r.name=='Поливочный шланг').qty is None
    assert next(r for r in rows if r.name.startswith('Погружной')).qty is None


@pytest.mark.parametrize('key,value', [('hose_sets',1.5),('outlets_count',False),
    ('hose_loss_m',float('nan')),('pump_geometric_head_m',float('inf')),
    ('hose_pn_bar',-1),('pump_setup','surface'),('pump_clean_water','maybe'),
    ('pump_setup',[]),('hose_choice',{})])
def test_strict_input(key,value):
    with pytest.raises(ValueError):
        from_dict({key:value})


def test_unmeasured_pressure_pipe_remains_in_spec_and_shallow_valve_warning():
    p = example_project()
    p.rainwater_reuse.pump_pipe_length_m = None
    row = next(r for r in assembly_rows(p) if r.name.startswith('Напорная труба'))
    assert row.qty is None and row.unit == 'м'
    assert any('1–7 м' in note for note in assess_pump(p.rainwater_reuse)['pending'])


def test_studio_signed_and_zero_losses_and_roundtrip():
    assert validate_value('rainwater_pump_geometric_head_m','−3,5') == -3.5
    assert validate_value('rainwater_hose_loss_m',0) == 0
    with pytest.raises(IntakeError):
        validate_value('rainwater_hose_sets','1.5')
    req = IOS2Request(DocumentRequest('','',''),'residential',2,6.6, fire_height_m=4.8,rainwater_reuse=example())
    assert load_request(dump_request(req)).rainwater_reuse == req.rainwater_reuse
    p=example_project(); before=deepcopy(asdict(p))
    html=generate_rainwater_reuse_html(p)
    assert 'Обвязка, арматура и шланг' in html and 'ВОДОМЕТ 55/50 А' in html
    assert asdict(p)==before


def test_studio_flow_unchanged_and_reselection_on_hose_change(client):
    state=studio.residential_project(client)
    original=client.post('/studio/api/calculate',json={'revision':state['revision']}).json()
    answers={'rainwater_'+k:v for k,v in asdict(example()).items() if k not in {'enabled','design_review'}}
    answers['rainwater_enabled']='yes'
    resp=client.post('/studio/api/calculate',json={'revision':original['revision'],'answers':answers})
    assert resp.status_code==200,resp.text
    s=resp.json()
    assert s['rainwater_reuse']['pump']['selected']['id']=='vodomet-55-50-a'
    assert s['calculation']==original['calculation']
    assert s['project_calculation']['flows']==original['project_calculation']['flows']
    s=studio.answer(client,s,'rainwater_hose_pn_bar',3)
    assert s['rainwater_reuse']['pump']['selected'] is None
    assert s['rainwater_reuse']['pump']['status']=='no_match'

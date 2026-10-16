from copy import deepcopy
from dataclasses import asdict

import pytest

from tests.test_water_station_drafting import samara
from tests.test_water_station_review import common, client
from app.pz.rules import calc_head_paths
from app.pz.water_station_review import review_station


def test_trace_is_canonical_balance_and_does_not_change_project(common):
    before=deepcopy(asdict(common))
    report=review_station(common)
    trace=report['head_balance']
    assert trace['status']=='current' and trace['saved_matches_current']
    assert trace['governing']=='T3'
    expected=calc_head_paths(common.source,common.meters,hws_type='central',apartment_meter_required=True)
    for row,path in zip(trace['paths'],expected.paths):
        assert row['components']==[dict(label=k,value_m=v) for k,v in path.head.components]
        assert row['pump_head_m']==path.head.h_pump_m
    cold,hot=trace['paths']
    assert (cold['required_head_m'],cold['pump_head_m'])==(75.63,45.63)
    assert (hot['required_head_m'],hot['pump_head_m'])==(80.25,50.25)
    assert (cold['meter_loss_m'],hot['meter_loss_m'])==(5.613,6.921)
    assert (cold['heater_loss_m'],hot['heater_loss_m'])==(0,3)
    assert not trace['new_pipework_covered'] and trace['new_pipework_loss_m'] is None
    assert not report['hydraulic_capacity_confirmed']
    assert asdict(common)==before


def test_meters_belong_to_paths_not_to_all_inlets_or_both_branches(common):
    trace=review_station(common)['head_balance']
    # One common + one branch + one apartment meter per path. No second inlet
    # multiplier, cold/hot branch summation or local-loss factor on meters.
    assert trace['paths'][0]['meter_loss_m']==round(1.451+3.479+0.683,3)
    assert trace['paths'][1]['meter_loss_m']==round(1.451+4.703+0.767,3)
    common.source.inputs_count=1
    assert review_station(common)['head_balance']['paths']==trace['paths']


def test_local_allowance_is_already_in_section_totals(common):
    trace=review_station(common)['head_balance']
    assert len(trace['sections'])==8
    assert all(s['local_loss_factor']==0.3 for s in trace['sections'])
    v1=[s for s in trace['sections'] if s['system']=='В1']
    assert round(sum(s['total_loss_m'] for s in v1 if s['role']=='input'),3)==common.source.h_vvod_m==0.06
    assert round(sum(s['total_loss_m'] for s in v1 if s['role']=='internal'),3)==common.source.h_il_m==1.761
    assert common.source.il_dict_m is None and common.source.il_vvod_m is None
    assert trace['paths'][0]['dynamic_loss_m']==7.43
    assert trace['paths'][1]['dynamic_loss_m']==12.05


@pytest.mark.parametrize('field,value', [('h_tepl_m',4),('guaranteed_head_m',29),('h_il_m',2)])
def test_changed_source_shows_current_trace_not_old_approval(common,field,value):
    setattr(common.source,field,value)
    report=review_station(common)
    assert report['head_balance']['status']=='stale'
    assert not report['head_balance']['saved_matches_current']
    assert next(r for r in report['hydraulic'] if r['id']=='existing_duty_check')['status']=='missing'
    assert all('устарел' in r['note'] for r in report['hydraulic'] if r['id'].startswith('head_balance_'))


@pytest.mark.parametrize('field', ['guaranteed_head_m','h_il_hot_m','h_apartment_h_meter_m'])
def test_missing_data_never_looks_like_complete_head(common,field):
    setattr(common.source,field,None)
    trace=review_station(common)['head_balance']
    assert trace['governing'] is None
    assert any(p['pump_head_m'] is None and p['missing'] for p in trace['paths'])
    assert trace['new_pipework_loss_m'] is None


def test_missing_saved_balance_is_not_a_confirmed_cache(common):
    common.head_paths=None
    trace=review_station(common)['head_balance']
    assert trace['saved_matches_current'] is None and trace['status']=='not_saved'
    assert trace['paths'][0]['pump_head_m']==45.63


def test_http_studio_emits_trace_without_hidden_assistant_data(client):
    state=client.post('/studio/api/draft').json()
    response=client.post('/studio/api/calculate',json=dict(revision=state['revision'],answers=dict(
        residents=20,apartments=8,consumer_code='residential_full_bath',floors=2,
        building_height_m=6.6,fire_height_m=4.8,hws_type='central',inputs_count=2,
        guaranteed_head_m=5,h_geom_m=6,pressure_loss_mode='ready',h_il_m=3,h_vvod_m=1,
        t3_loss_mode='ready',h_il_hot_m=4,hws_heater_in_scope='no')))
    assert response.status_code==200
    trace=response.json()['project_calculation']['water_station_review']['head_balance']
    assert trace['status']=='current' and len(trace['paths'])==2
    assert trace['sections']==[]  # Ready losses are not fake calculated lengths.
    assert trace['new_pipework_loss_m'] is None and not trace['new_pipework_covered']


def test_pump_document_keeps_project_context_and_canonical_balance(common):
    from pathlib import Path
    from app.pz.generator import generate_pump_selection_html
    before=deepcopy(asdict(common))
    html=generate_pump_selection_html(common)
    assert 'Увязка ВУ и насосной' in html
    assert 'Новая обвязка Г.1 этой проверкой не подтверждается' in html
    assert '75,63' in html and '80,25' in html and '50,25' in html
    css=Path('app/pz/templates/pump_document.css').read_text()
    assert 'table.head-paths th, table.head-paths td {' in css
    assert 'border: 0.3mm solid #000' in css.split('table.head-paths th, table.head-paths td {',1)[1].split('}',1)[0]
    assert asdict(common)==before

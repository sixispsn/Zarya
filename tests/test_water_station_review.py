from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest

from tests.test_water_station_drafting import samara
from tests.test_studio import client
from app.pz.water_station_review import connected_network, review_station, evaluate_control
from app.pz.maintenance_engine import assess_removal
from app.pz.metering_modes import operating_paths
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


@pytest.fixture
def common(samara):
    samara.metering_detail.inlet_metering_mode = 'common'
    samara.metering_detail.common_topology = 'gost_g1'
    return samara


def test_connected_graph_has_no_fictitious_sources_at_vu_outputs(common):
    n = connected_network(common)
    assert next(x for x in n.nodes if x.id == 'g1_building_1').kind == 'component'
    assert next(x for x in n.nodes if x.id == 'station_building').kind == 'source'
    r = review_station(common)
    assert len(r['scenarios']) == 2
    for s in r['scenarios']:
        assert s['delivery_path_exists']
        assert s['target'] not in s['delivery_path']
        assert s['removal']['isolation'] == 'checked'
        assert s['removal']['drainage'] == 'blocked'
        assert s['removal']['pressure_relief'] == 'blocked'
        assert s['removal']['air_admission'] == 'blocked'
        assert not s['removal']['safe_to_remove']
        assert not s['hydraulic_capacity_confirmed']


def test_check_valve_and_stopped_pump_not_repair_boundaries(common):
    n = connected_network(common)
    result = assess_removal(n,'station_pump_1',closed_valves={'station_in_1'})
    assert result.isolation == 'blocked'
    assert any('station_building' in p for p in result.source_paths)
    with pytest.raises(ValueError):
        assess_removal(n,'station_pump_1',closed_valves={'station_check_1'})
    broken = replace(n,links=tuple(e for e in n.links if 'station_pump_2' not in (e.a,e.b)))
    paths=operating_paths(broken,'supply_source_1',{'station_in_1','station_out_1','g1_bypass_1','g1_bypass_2'})
    assert 'station_building' not in paths


@pytest.mark.parametrize('count',[(2,1),(0,0),(1,0)])
def test_other_arrangements_are_not_invented(common,count):
    common.pumps.working_units,common.pumps.reserve_units=count
    common.pumps.count_note=''
    r=review_station(common)
    assert not r['supported'] and not r['scenarios'] and not r['automation']
    assert r['service'] is None


def test_separate_meter_assemblies_not_collapsed_to_single(common):
    common.metering_detail.inlet_metering_mode='per_inlet'
    assert connected_network(common) is None
    assert not review_station(common)['supported']


def test_single_inlet_and_merge_keep_their_graph(common):
    common.metering_detail.common_topology='merge_before'
    assert review_station(common)['supported']
    common.source.inputs_count=1
    r=review_station(common)
    assert r['supported'] and all(s['delivery_path_exists'] for s in r['scenarios'])


def control(**changes):
    args=dict(demand=True,suction_ok=True,sensor_ok=True,power_ok=True,
              ready={1:True,2:True},failed={1:False,2:False})
    args.update(changes)
    return evaluate_control(**args)


def test_control_replaces_duty_never_adds_reserve_or_maintenance_pump():
    assert control()['run']==(1,)
    assert control(failed={1:True,2:False})['run']==(2,)
    assert control(maintenance=(1,))['run']==(2,)
    assert control(failed={1:True,2:False},maintenance=(2,))['run']==()
    assert control(ready={1:None,2:False})['run']==()
    assert control(demand=False)['state']=='standby'
    assert control(failed={1:False,2:True})['alarm']==('Отказ Н2',)


@pytest.mark.parametrize('field',['suction_ok','sensor_ok','power_ok','demand'])
@pytest.mark.parametrize('value',[False,None])
def test_missing_permissives_never_start_reserve(field,value):
    assert not control(**{field:value},failed={1:True,2:False})['run']


def test_invalid_control_states_rejected():
    with pytest.raises(ValueError): control(suction_ok=1)
    with pytest.raises(ValueError): control(ready={1:True})
    with pytest.raises(ValueError): control(preferred=True)


def test_hydraulic_unknowns_do_not_become_zero_or_change_calculation(common):
    before=deepcopy(asdict(common))
    r=review_station(common)
    assert not r['hydraulic_capacity_confirmed']
    assert next(x for x in r['hydraulic'] if x['id']=='new_losses')['value']=='Не подтверждены'
    assert next(x for x in r['hydraulic'] if x['id']=='bypass_dn')['value']=='Не задан'
    assert asdict(common)==before and review_station(common)==r
    common.source.guaranteed_head_m=4.99
    assert any(x['id']=='receiving_tank' for x in review_station(common)['hydraulic'])
    common.source.guaranteed_head_m=5
    assert not any(x['id']=='receiving_tank' for x in review_station(common)['hydraulic'])


def test_drawing_and_pdf_audits_are_fully_gridded(common):
    pages=build_pump_zone_scheme_pages(common,include_review=True)
    assert len(pages)>3
    for b in review_station(common)['branches']:
        for key in ('inlet','outlet','check'):
            assert f'data-component="{b[key]}"' in pages[0]
        assert b['inlet_mark'] in pages[0] and b['outlet_mark'] in pages[0]
    assert 'PS1' in pages[0] and 'PS2' in pages[0]
    for page in pages[3:]:
        assert any(e.get('data-vu-table-grid') for e in ET.fromstring(page).iter())


def test_pbs_spec_no_second_purchase_of_factory_equipment(common):
    from app.pz.spec import build_specification
    rows=[r for sec in build_specification(common).sections for r in sec.rows]
    assert sum(r.qty for r in rows if 'station_assembly' in r.component_ids)==1
    assert not any('Клапан обратный на напорном патрубке насоса' in r.name for r in rows)
    assert not any('Кран шаровой запорный у насоса' in r.name for r in rows)
    assert not any(r.note=='насосная установка; вне ВУ' for r in rows)
    assert any('манометры, отсечки насосов и обратные клапаны в комплекте PBS' in r.note for r in rows)
    for b in review_station(common)['branches']:
        for key in ('pump', 'inlet', 'check', 'outlet'):
            assert sum(b[key] in row.component_ids for row in rows)==1


def test_pz_contains_same_modes_and_no_unknown_threshold(common):
    from app.pz.generator import generate_pz_html
    html=generate_pz_html(common)
    assert 'НЗ1, НЗ2' in html and 'НЗ3, НЗ4' in html
    assert 'Задание по автоматизации В1' in html
    assert 'Потери новой переключающей обвязки не подтверждены' in html


def test_studio_without_assistant_produces_review_and_preserves_numbers():
    from app.intake.studio_project import calculate_project
    from tests.test_studio_apartment_meters import draft
    d=draft(inputs_count=2)
    r=calculate_project(d)
    assert 'water_station_review' in r
    before=deepcopy(r['head'])
    d['common_vu_topology']='gost_g1'
    new=calculate_project(d)
    assert new['head']==before
    if new['pumps']['required']:
        assert new['water_station_review'] is not None


def test_http_studio_calculation_contains_station_review(client):
    response=client.post('/studio/api/draft')
    assert response.status_code==200
    state=response.json()
    response=client.post('/studio/api/calculate',json=dict(revision=state['revision'],answers=dict(
        residents=20,apartments=8,consumer_code='residential_full_bath',floors=2,
        building_height_m=6.6,fire_height_m=4.8,hws_type='central',inputs_count=2,
        guaranteed_head_m=5,h_geom_m=6,pressure_loss_mode='ready',h_il_m=3,h_vvod_m=1,
        t3_loss_mode='ready',h_il_hot_m=4,hws_heater_in_scope='no')))
    assert response.status_code==200
    result=response.json()['project_calculation']
    assert result['can_preview']
    assert result['water_station_review']['supported']
    assert len(result['water_station_review']['scenarios'])==2
    assert not result['water_station_review']['hydraulic_capacity_confirmed']

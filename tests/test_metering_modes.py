"""G.1 mode checks: failures cannot become an instruction or green approval."""
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from tests.test_metering_g1_switching import project, graph
from app.pz.metering_modes import build_modes, check_positions, operating_paths, valves_for
from app.pz.metering_detail import build_metering_detail_pages
from app.pz.metering_maintenance import audit_metering_maintenance
from app.pz.maintenance_engine import ServiceLink, ServiceNode


def report(p=None):
    p = p or project()
    s, _, n = graph(p)
    return n, build_modes(p,s,n)


def mode(r, ident):
    return next(m for m in r['modes'] if m['id']==ident)


def test_normal_has_two_open_inlets_closed_sealed_bypasses_and_explicit_crossfeed():
    n,r=report(); normal=mode(r,'normal')
    assert normal['positions']['supply_valve_1']==normal['positions']['supply_valve_2']=='open'
    assert normal['positions']['g1_bypass_1']==normal['positions']['g1_bypass_2']=='closed'
    assert normal['checks']['supplied'] and not normal['checks']['unmetered_paths']
    assert len(normal['checks']['crossfeed_paths'])==2
    assert normal['status']=='needs_data' and not normal['operation_approved']
    assert 'INLET_CROSSFEED_POSSIBLE' in normal['checks']['pending']
    assert not any(row['operation_approved'] for row in r['modes'])
    assert not any(row['hydraulic_capacity_confirmed'] for row in r['modes'])


@pytest.mark.parametrize('i',[1,2])
def test_each_inlet_outage_preserves_metering_and_isolation(i):
    n,r=report(); row=mode(r,f'inlet_{i}_off')
    assert row['positions'][f'supply_valve_{i}']=='closed'
    assert row['positions'][f'supply_valve_{3-i}']=='open'
    assert row['checks']['supplied'] and not row['checks']['failures']
    assert not row['checks']['backfeed_paths']
    unsafe={**row['positions'],f'supply_valve_{i}':'open'}
    checks=check_positions(n,unsafe,active_sources=(f'supply_source_{3-i}',),
                           unavailable_sources=(f'supply_source_{i}',))
    assert 'UNAVAILABLE_INLET_CONNECTED' in checks['failures']


def test_unmetered_bypass_and_live_service_are_rejected():
    n,r=report(); positions=mode(r,'normal')['positions']
    opened={**positions,'g1_bypass_1':'open'}
    checks=check_positions(n,opened)
    assert checks['topology_status']=='blocked'
    assert 'UNMETERED_PATH' in checks['failures']
    assert checks['unmetered_paths']
    checks=check_positions(n,{**positions,'control_cock_1':'open'})
    assert 'LIVE_SERVICE_PORT' in checks['failures']


def test_unknown_bypass_not_treated_as_closed_or_open_proof():
    n,r=report(); positions={**mode(r,'normal')['positions'],'g1_bypass_1':'unknown'}
    result=check_positions(n,positions)
    assert not result['unmetered_paths']
    assert 'UNMETERED_PATH' in result['pending']
    assert result['topology_status']=='needs_data'
    result=check_positions(n,{**mode(r,'normal')['positions'],'control_cock_1':'unknown'})
    assert 'LIVE_SERVICE_PORT' in result['pending'] and not result['failures']


@pytest.mark.parametrize('target',['meter','filter'])
def test_service_paths_exclude_removed_body_and_do_not_claim_dry(target):
    n,r=report(); row=mode(r,'service_'+target)
    checks=row['checks']
    assert checks['supplied'] and checks['unmetered_paths']
    assert not checks['failures']
    assert all(target not in path for paths in checks['paths'].values() for path in paths.values())
    assert checks['maintenance']['isolation']=='checked'
    assert not checks['maintenance']['safe_to_remove']
    assert row['status']=='needs_data'
    assert 'SERVICE_NOT_CONFIRMED' in checks['pending']
    # Bypass water must not reach the disconnected insert from the building.
    unsafe={**row['positions'],'g1_switch_out_1':'open'}
    assert 'TARGET_NOT_ISOLATED' in check_positions(n,unsafe,target=target,metered=False)['failures']


def test_fire_before_meter_does_not_open_domestic_bypasses():
    n,r=report(); row=mode(r,'fire')
    assert row['positions']['g1_bypass_1']==row['positions']['g1_bypass_2']=='closed'
    assert row['positions']['supply_fire_valve_1']=='open'
    assert row['checks']['supplied']
    assert row['status']=='needs_data'


def test_combined_fire_uses_existing_requirement_without_inventing_an_algorithm():
    p=project(); p.fire.network_topology='combined'
    p.fire.topology_basis='Явное условие проверки';p.meters.rows[0].need_bypass=True
    n,r=report(p); row=mode(r,'fire')
    assert 'supply_fire_valve_1' not in row['positions']
    assert row['positions']['g1_bypass_1']=='open'
    assert row['checks']['supplied'] and not row['operation_approved']


@pytest.mark.parametrize('ident',['power_failure','drive_failure'])
def test_drive_failures_keep_unknown_positions(ident):
    n,r=report(); row=mode(r,ident)
    assert row['positions']['supply_fire_valve_1']=='unknown'
    assert row['status']=='needs_data'
    assert not row['operation_approved']
    assert not row['checks']['supplied']
    assert row['output_scope']=='В1 и В2'
    assert 'SUPPLY_NOT_PROVEN' in row['checks']['pending']


def test_no_fire_no_drives_does_not_add_fake_fire_or_fail_modes():
    p=project(); p.fire.required=False
    n,r=report(p)
    for ident in ('fire','power_failure','drive_failure'):
        assert mode(r,ident)['status']=='not_applicable'
        assert mode(r,ident)['checks'] is None


def test_every_removable_valve_has_its_own_cut_not_itself_or_a_check():
    n,r=report()
    assert {row['target'] for row in r['service_modes']} == {
        node.id for node in n.nodes if node.kind in ('check','isolation')}
    checks={node.id for node in n.nodes if node.kind=='check'}
    for row in r['service_modes']:
        cut=set(row['maintenance']['close_valves'])
        assert row['target'] not in cut and not cut & checks
        assert not row['operation_approved']
    target=next(row for row in r['service_modes'] if row['target']=='supply_valve_1')
    assert target['checks']['topology_status']=='blocked'  # No upstream shutoff in the building model.


def test_boundaries_cannot_be_used_as_unmodelled_transit_or_checks_reversed():
    n,r=report(); edges=(*n.links, ServiceLink('g1_building_1','supply_source_2'))
    mutated=replace(n,links=edges)
    paths=operating_paths(mutated,'supply_source_1',{'g1_switch_in_2','supply_valve_2'})
    assert 'supply_source_2' not in paths  # Must not traverse building_1.
    forward=operating_paths(n,'g1_right_1',{'g1_switch_out_1','supply_valve_1','g1_switch_in_1'})
    assert 'g1_bypass_1' not in forward


def test_missing_unknown_or_unlabelled_valves_fail_loudly():
    n,r=report(); normal=mode(r,'normal')['positions']
    with pytest.raises(ValueError):
        check_positions(n,{k:v for k,v in normal.items() if k!='valve_before'})
    with pytest.raises(ValueError):
        check_positions(n,{**normal,'valve_before':'half_open'})
    with pytest.raises(ValueError):
        check_positions(n,{**normal,'valve_before':'removed'})
    with pytest.raises(ValueError):
        valves_for(replace(n,nodes=(*n.nodes,ServiceNode('surprise_valve',kind='isolation'))))


def test_scheme_tags_matrix_and_service_share_same_ids_without_duplicates():
    p=project(); p.metering_detail.maintenance_layout='serviceable'
    n,r=report(p); pages=build_metering_detail_pages(p)
    root=ET.fromstring(pages[0])
    shown=[e for e in root.iter() if e.get('data-operating-tag')]
    assert len(shown)==len(r['valves'])
    assert {e.get('data-operating-component'):e.get('data-operating-tag') for e in shown}=={
        v['id']:v['mark'] for v in r['valves']}
    tables=[e for page in pages for e in ET.fromstring(page).iter() if e.get('data-vu-mode-table')]
    assert {e.get('data-vu-mode-table') for e in tables}=={'mode-tags','mode-matrix','mode-conditions'}
    for table in tables:
        assert any(e.get('data-vu-table-grid') for e in table.iter())
    assert any(ET.fromstring(page).get('data-meter-modes')=='true' for page in pages)
    audit=audit_metering_maintenance(p)
    assert audit['operating_modes']==r
    assert next(row for row in audit['scenarios'] if row['target']=='valve_before')['operating_mark']=='З11'


def test_report_is_deterministic_nonmutating_and_present_in_pz():
    from app.pz.metering_presentation import metering_presentation
    p=project(); before=deepcopy(asdict(p)); _,r=report(p)
    assert report(p)[1]==r and asdict(p)==before
    text=metering_presentation(p)['modes_notice']
    assert 'З7/З8' in text and 'Связь двух вводов' in text and 'В2 отбирается до учёта' in text


def test_studio_produces_modes_without_assistant_and_preserves_calculation():
    from app.intake.studio_project import calculate_project
    from tests.test_studio_apartment_meters import draft
    data=draft(inputs_count=2)
    old=calculate_project(data)
    data['common_vu_topology']='gost_g1'
    current=calculate_project(data)
    assert current['metering_layout']['maintenance']['operating_modes']['modes']
    for key in ('flows','head','hydraulics','hot_hydraulics','pumps','meters'):
        assert old[key]==current[key]

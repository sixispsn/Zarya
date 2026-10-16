"""Approved G.1 topology, not merely similar paper coordinates."""
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET
import pytest

from tests.test_metering_common_inlets import common_project, chain_for
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_switching import external_graph, component_ids, operating_path_check
from app.pz.metering_supply import extend_service_network
from app.pz.metering_maintenance import network_from_chain, audit_metering_maintenance
from app.pz.maintenance_engine import assess_removal, ServiceLink


def project():
    p=common_project()
    p.metering_detail.common_topology='gost_g1'
    return p


def graph(p):
    s,c=chain_for(p)
    n=extend_service_network(network_from_chain(p.metering_detail,c),s)
    n.validate()
    return s,c,n


def test_only_explicit_new_topology_changes_existing_common_graph():
    old=common_project()
    assert not drawing_state(old).switching_bridge
    assert 'bypass' in {p.id for p in chain_for(old)[1].paths}
    d=MeteringDetailData(**asdict(project().metering_detail))
    assert d.common_topology=='gost_g1' and not d.validate()
    assert MeteringDetailData().common_topology=='merge_before'
    assert replace(d,common_topology='made_up').validate()


def test_two_through_mains_one_insert_and_no_third_bypass():
    p=project();s,c,n=graph(p)
    assert s.bypass and not s.core_bypass and c.instances==1
    assert 'bypass' not in {p.id for p in c.paths}
    assert 'inlet_valve' not in {n.id for n in c.nodes}
    assert {n.id for n in n.nodes if n.kind=='source'} == {
        'supply_source_1','supply_source_2','g1_building_1','g1_building_2',
        'supply_fire_outlet_1','supply_fire_outlet_2'}
    assert operating_path_check(n)['passed']
    assert not operating_path_check(n)['hydraulic_capacity_confirmed']
    for i in (1,2):
        path=next(p for p in external_graph(s)[1] if p.id==f'g1_main_{i}')
        assert path.nodes.index(f'g1_left_{i}') < path.nodes.index(f'g1_bypass_{i}')
        assert path.nodes.index(f'g1_bypass_{i}') < path.nodes.index(f'g1_check_{i}') < path.nodes.index(f'g1_right_{i}')


def test_routing_audit_detects_unmetered_shortcut_and_broken_insert():
    p=project();_,_,n=graph(p)
    shortcut=replace(n,links=(*n.links,ServiceLink('g1_left_1','g1_right_1')))
    assert not operating_path_check(shortcut)['passed']
    broken=replace(n,links=tuple(e for e in n.links if 'meter' not in (e.a,e.b)))
    assert not operating_path_check(broken)['passed']


def test_spec_quantities_cover_all_components_once_without_pipe_lengths():
    p=project();s,c,_=graph(p);before=deepcopy(asdict(p))
    rows=build_metering_spec_section(p).rows
    ids=[i for r in rows for i in r.component_ids]
    assert len(ids)==len(set(ids))
    assert set(ids)=={n.id for n in c.nodes}|component_ids(s)
    quantities={r.diagram_pos:r.qty for r in rows if r.diagram_pos!='—'}
    assert quantities['7']==1 and quantities['ВВ']==quantities['ВВых']==2
    assert quantities['ВПк']==4 and quantities['ОБ']==quantities['КО']==2
    assert all(r.qty is None for r in rows if r.unit=='м')
    assert asdict(p)==before


def test_unknown_dn_is_not_borrowed_from_reference_or_inlet():
    p=project();p.metering_detail.bypass_dn=None
    row=next(r for r in build_metering_spec_section(p).rows if r.diagram_pos=='ОБ')
    assert row.qty==2 and 'DN уточнить' in row.name
    assert drawing_state(p).missing


def test_service_includes_both_building_sources_and_all_switching_valves():
    p=project();_,_,n=graph(p)
    # Check valves do not provide service isolation even if flow is one-way.
    row=assess_removal(n,'g1_check_1')
    assert row.isolation=='checked'
    assert 'g1_check_1' not in row.close_valves
    assert 'g1_out_valve_1' in row.close_valves
    report=audit_metering_maintenance(p)
    assert report['switching_check']['passed'] and not report['safe_to_remove']
    ids={r['target'] for r in report['scenarios']}
    assert {f'g1_{kind}_{i}' for kind in ('switch_in','switch_out','bypass','check','out_valve') for i in (1,2)}<=ids
    assert all(not r['safe_to_remove'] for r in report['scenarios'])


@pytest.mark.parametrize('axis',['horizontal_dial_up','vertical_up','vertical_down'])
def test_sheet_matches_graph_for_all_insert_axes(axis):
    p=project();p.metering_detail.assembly_orientation=axis
    p.metering_detail.meter_mounting=axis
    s,c,_=graph(p);before=deepcopy(asdict(p))
    root=ET.fromstring(build_metering_detail_pages(p)[0])
    ids=[e.get('data-vu-component') for e in root.iter() if e.get('data-vu-component')]
    assert ids.count('meter')==1 and 'bypass_valve' not in ids
    assert component_ids(s)<=set(ids)
    actual={tuple(e.get('data-supply-edge').split(':')) for e in root.iter() if e.get('data-supply-edge')}
    expected={(a,b) for path in external_graph(s)[1] for a,b in zip(path.nodes,path.nodes[1:])}
    assert actual==expected
    main_edges={tuple(e.get('data-chain-edge').split(':')) for e in root.iter() if e.get('data-chain-edge')}
    assert main_edges==set(zip(c.paths[0].nodes,c.paths[0].nodes[1:]))
    assert sum(e.get('data-wall-crossing') is not None for e in root.iter())==2
    assert asdict(p)==before


def test_new_draft_marker_old_migration_and_request_roundtrip(tmp_path):
    from app.intake.studio_store import StudioStore
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request,load_request
    from tests.test_studio_apartment_meters import draft
    store=StudioStore(tmp_path);ident,new=store.create()
    assert new['common_vu_topology']=='gost_g1'
    new.pop('common_vu_topology');store._write(store.folder(ident),new)
    assert store.load(ident)['common_vu_topology']=='merge_before'
    data=draft(inputs_count=2);data['common_vu_topology']='gost_g1'
    req=load_request(dump_request(build_handoff_request(data)))
    assert req.metering_detail.common_topology=='gost_g1'


def test_pz_and_pump_connection_use_same_two_outputs():
    from app.pz.metering_presentation import metering_presentation
    from app.pz.water_station_drafting import build_pump_zone_scheme_pages
    p=project()
    text=metering_presentation(p)['inlet']
    assert 'на перемычке' in text and 'Вводы объединяются до' not in text
    svg=build_pump_zone_scheme_pages(p)[0]
    assert 'g1_building_1' in svg and 'g1_building_2' in svg
    assert 'От ВУ-1 · выход 1' in svg and 'От ВУ-1 · выход 2' in svg


def test_studio_calculates_new_topology_without_assistant_preparation():
    from app.intake.studio_project import calculate_project
    from tests.test_studio_apartment_meters import draft
    data=draft(inputs_count=2)
    previous=calculate_project(data)
    data['common_vu_topology']='gost_g1'
    current=calculate_project(data)
    assert current['metering_layout']['common_topology']=='gost_g1'
    assert current['metering_layout']['maintenance']['switching_check']['passed']
    for key in ('flows','head','hydraulics','hot_hydraulics','pumps','meters'):
        assert previous[key]==current[key],key

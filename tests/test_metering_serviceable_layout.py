"""Service topology is opt-in, shared with SO, never inferred from SVG."""
from copy import deepcopy
from dataclasses import asdict, replace
from math import dist
from xml.etree import ElementTree as ET

import pytest

from app.intake.studio_intake import answer_field, IntakeError
from app.intake.studio_project import calculate_project
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_detail import drawing_state
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_hot_node import hot_meter_view
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_maintenance import audit_metering_maintenance, network_from_chain
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from scripts.preview_metering_vertical_reference import review_project
from tests.test_studio_apartment_meters import draft
from tests.test_studio_metering_nodes import project
from tests import test_studio as studio_tests

client = studio_tests.client


def graph(p, *, bypass=None):
    state = drawing_state(p)
    if bypass is not None:
        state = replace(state,bypass=bypass)
    selection = resolve_metering_products(p,state.meter,bypass=state.bypass,electric_bypass=state.electric_bypass)
    return state, selection, build_metering_chain(p.metering_detail,state,selection)


def rows(p):
    return {r['target']: r for r in audit_metering_maintenance(p)['scenarios']}


def test_existing_project_not_silently_rearranged(tmp_path):
    p = review_project(tmp_path)
    assert p.metering_detail.maintenance_layout == 'existing'
    assert 'outlet_valve' not in {n.id for n in graph(p)[2].nodes}
    assert rows(p)['meter']['drainage'] == 'blocked'
    assert rows(p)['check_valve']['isolation'] == 'blocked'


def test_upward_low_point_and_check_boundaries_are_fixed(tmp_path):
    p = review_project(tmp_path,maintenance_layout='serviceable')
    chain = graph(p)[2]; main = chain.paths[0].nodes
    assert main.index('valve_before') < main.index('maintenance_in') < main.index('filter')
    assert main.index('valve_after') < main.index('service_after') < main.index('bypass_end')
    assert main.index('check_valve') < main.index('maintenance_out') < main.index('outlet_valve')
    r = rows(p)
    for target in ('meter','filter'):
        assert r[target]['isolation'] == 'checked'
        assert r[target]['close_valves'] == ('valve_after','valve_before')
        assert r[target]['drainage'] == 'needs_data'
        assert target not in r[target]['trapped_nodes']
        assert 'maintenance_in' in r[target]['drain_ports']
    assert r['check_valve']['isolation'] == 'checked'
    assert r['check_valve']['close_valves'] == ('bypass_valve','outlet_valve','valve_after')
    assert not r['check_valve']['source_paths']
    assert {'control_2','maintenance_out'} <= set(r['check_valve']['relief_ports'])
    assert not any(v['safe_to_remove'] for v in r.values())
    assert r['inlet_valve']['isolation'] == r['outlet_valve']['isolation'] == 'blocked'


def test_bypass_remains_available_when_meter_is_isolated(tmp_path):
    p=review_project(tmp_path,maintenance_layout='serviceable')
    chain=graph(p)[2]; closed=set(rows(p)['meter']['close_valves'])
    adj={n.id:set() for n in chain.nodes}
    for a,b in chain.links:
        if a not in closed and b not in closed:
            adj[a].add(b);adj[b].add(a)
    reached={'inlet'};todo=['inlet']
    for n in todo:
        for other in adj[n]-reached:
            reached.add(other);todo.append(other)
    assert 'outlet' in reached and 'meter' not in reached
    assert 'bypass_valve' in reached


@pytest.mark.parametrize('axis',['horizontal_dial_up','vertical_up','vertical_down'])
@pytest.mark.parametrize('bypass',[False,True])
def test_profile_retains_normative_ports_and_protected_meter_ends(axis,bypass,tmp_path):
    p=project(draft(vu_orientation=axis,vu_maintenance_layout='serviceable',vu_drawing_scale='10'),tmp_path)
    state,sel,chain=graph(p,bypass=bypass)
    main=chain.paths[0].nodes
    i=main.index('meter')
    assert main[i-1:i+2] == ('kit_in','meter','kit_out')
    assert main.index('kit_out') < main.index('service_before') < main.index('valve_after')
    assert main.index('valve_after') < main.index('service_after')
    assert {'control_1','control_2','maintenance_in','maintenance_out'} <= {v.id for v in chain.paths}
    network=network_from_chain(p.metering_detail,chain)
    if axis=='horizontal_dial_up':
        assert all(e.gravity=='unknown' and e.air_passable is None for e in network.links)
    report=audit_metering_maintenance(p,state,selection=sel,chain=chain)
    assert not report['all_design_checks_passed']


@pytest.mark.parametrize('scale',[5,10,20])
def test_scaled_layout_bom_and_audit_have_same_items(scale,tmp_path):
    p=review_project(tmp_path,maintenance_layout='serviceable');p.metering_detail.mounting.scale=scale
    before=deepcopy(asdict(p));layout=build_metering_layout(p)
    assert layout.parts and not layout.issues
    spec=build_metering_spec_section(p).rows
    owned=[i for r in spec for i in r.component_ids]
    assert len(owned)==len(set(owned))==len(layout.parts)
    assert set(owned)=={n.id for n in graph(p)[2].nodes}
    for name in ('outlet_valve','maintenance_cock_in','maintenance_cock_out','gauge_cock'):
        part=layout.part(name)
        assert dist(*part.points)*scale==pytest.approx(part.length_mm)
        assert any(name in row.component_ids and row.catalogue_id==part.catalogue_id for row in spec)
    quantities={r.diagram_pos:r.qty for r in spec if r.diagram_pos!='—'}
    assert quantities['1.3']==1 and quantities['4.3']==quantities['4.4']==2
    assert quantities['4.1']==quantities['4.2']==2
    assert asdict(p)==before
    pages=layout_contents(p)
    root=ET.fromstring('<svg>'+pages[0]+'</svg>')
    assert all(float(t.get('y',0))<233 for t in root.findall('.//text'))
    # No duplicate dimensions in crowded service branch rows.
    dims={g.get('data-body-dimension') for g in root.findall('.//g')}
    assert 'maintenance_cock_in' in dims and 'maintenance_cock_out' not in dims


def test_mixed_profile_does_not_get_a_fake_drain_grade(tmp_path):
    p=project(draft(vu_orientation='vertical_up',vu_filter_layout='valtec_vt192_vtr090',
                    vu_maintenance_layout='serviceable',vu_drawing_scale='10'),tmp_path)
    network=network_from_chain(p.metering_detail,graph(p)[2])
    assert all(e.gravity=='unknown' for e in network.links)
    assert not audit_metering_maintenance(p)['all_design_checks_passed']


def test_profile_through_studio_does_not_change_hydraulics_or_hot_node(tmp_path):
    d=draft();before=calculate_project(d)
    answer_field(d,'vu_maintenance_layout','serviceable');after=calculate_project(d)
    for key in ('flows','head','hydraulics','hot_hydraulics','pumps','fire','meters'):
        assert before[key]==after[key]
    p=project(d,tmp_path)
    assert p.metering_detail.maintenance_layout=='serviceable'  # survived YAML
    assert hot_meter_view(p).metering_detail.maintenance_layout=='existing'
    assert after['metering_layout']['maintenance']['layout']=='serviceable'


@pytest.mark.parametrize('failure',['origin','pressure','dn','manual'])
def test_outlet_and_services_cannot_bypass_product_validation(failure,tmp_path):
    p=review_project(tmp_path,maintenance_layout='serviceable');d=p.metering_detail
    if failure=='origin':d.russian_equipment_only=True
    if failure=='pressure':d.design_pressure_bar=100
    if failure=='dn':d.inlet_dn=100
    if failure=='manual':d.catalogue_items['outlet_valve']='missing-id'
    state,sel,chain=graph(p)
    assert sel.selected('outlet_valve') is None
    assert chain.node('outlet_valve').catalogue_id is None
    row=next(r for r in build_metering_spec_section(p).rows if 'outlet_valve' in r.component_ids)
    assert not row.catalogue_id


def test_invalid_mode_is_not_coerced():
    d=draft()
    with pytest.raises(IntakeError):answer_field(d,'vu_maintenance_layout','yes')
    assert MeteringDetailData(maintenance_layout='yes').validate()


def test_paper_scale_cannot_change_maintenance_result(tmp_path):
    p=review_project(tmp_path,maintenance_layout='serviceable');before=audit_metering_maintenance(p)
    p.metering_detail.mounting.scale=20
    assert audit_metering_maintenance(p)==before


@pytest.mark.parametrize('axis',['horizontal_dial_up','vertical_up'])
def test_complete_document_does_not_use_obsolete_internals(axis,tmp_path):
    from app.pz.metering_detail import build_metering_detail_pages
    p=project(draft(vu_orientation=axis,vu_maintenance_layout='serviceable',vu_drawing_scale='10'),tmp_path)
    p.metering_detail.mounting.enabled=False
    pages=build_metering_detail_pages(p)
    assert any('data-vu-component="outlet_valve"' in body for body in pages)
    assert '1.3' in pages[0]
    if axis=='horizontal_dial_up':
        assert 'data-vu-service-reference="true"' in pages[0]
        assert 'data-control-cock=' not in pages[0]


def test_http_calculate_and_reload_preserve_mode(client):
    state=studio_tests.new(client)
    d=draft(vu_maintenance_layout='serviceable')
    response=client.post('/studio/api/calculate',json={'revision':state['revision'],
        'answers':{k:v['value'] for k,v in d['answers'].items()}})
    assert response.status_code==200
    result=response.json()['project_calculation']['metering_layout']['maintenance']
    assert result['layout']=='serviceable'
    assert next(r for r in result['scenarios'] if r['target']=='check_valve')['isolation']=='checked'
    saved=client.get('/studio/api/draft').json()
    assert saved['project_calculation']['metering_layout']['maintenance']==result

from copy import deepcopy
from dataclasses import asdict
import json
import xml.etree.ElementTree as ET
import pytest

from app.data.metering_supports import PRODUCTS, fingerprint
from app.pz.metering_supports import support_report, studio_supports, validate_supports
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_layout import build_metering_layout
from app.pz.metering_support_drawing import support_contents
from app.pz.metering_detail import drawing_state
from scripts.preview_metering_detail import catalogue_review_project, review_project
from tests.test_studio_apartment_meters import draft


def selected(product='termoclip-09105002', **extra):
    return dict(product_id=product, fingerprint=fingerprint(product), basis='Явная точка контрольного примера', **extra)


def case(**points):
    p=catalogue_review_project(); p.metering_detail.mounting.supports=points
    return p


def test_published_limits_are_not_mass_or_dn_derived():
    from app.pz.equipment_origin import origin
    assert PRODUCTS['kromber-osvu1'].end_load_n is None
    assert PRODUCTS['kromber-osvu1'].height_range_mm==(500,800)
    assert PRODUCTS['termoclip-09105103'].end_load_n==250
    assert len(PRODUCTS)==4
    assert all(len(fingerprint(k))==64 for k in PRODUCTS)
    assert all(origin(k)['country']=='RU' for k in PRODUCTS)
    assert origin('kromber-osvu2')['country']=='unknown'


@pytest.mark.parametrize('product,limit',[('termoclip-09105001',1060),('termoclip-09105002',540),('termoclip-09105103',250)])
def test_exact_load_boundary_and_overload(product,limit):
    p=case(inlet=selected(product,load_case='end',reaction_n=limit,reaction_basis='Явно заданная реакция'))
    r=support_report(p); assert r['rows'][0]['load_status']=='component_limit_only'
    assert not r['installation_ready'] and not r['safe_to_remove']
    p.metering_detail.mounting.supports['inlet']['reaction_n']+=.01
    r=support_report(p); assert r['rows'][0]['load_status']=='overload'
    assert not r['rows'][0]['active'] and r['rows'][0]['quantity'] is None


@pytest.mark.parametrize('height,active',[(499,False),(500,True),(800,True),(801,False)])
def test_floor_height_range(height,active):
    p=case(inlet=selected('kromber-osvu1',height_mm=height))
    r=support_report(p)['rows'][0]
    assert r['active'] is active and r['load_status']=='needs_data'


@pytest.mark.parametrize('orientation',['vertical_up','vertical_down'])
def test_floor_stand_is_not_rotated_to_hold_vertical_pipe(orientation):
    p=case(inlet=selected('kromber-osvu1',height_mm=600))
    p.metering_detail.assembly_orientation=orientation
    assert not support_report(p)['rows'][0]['active']
    p.metering_detail.mounting.supports['inlet']=selected()
    r=support_report(p)['rows'][0]
    assert r['active'] and any('Осевое удержание' in s for s in r['pending'])


def test_wrong_dn_stale_product_and_missing_bypass_are_rejected():
    p=case(inlet=selected('kromber-osvu1'))
    p.metering_detail.inlet_dn=100
    assert not support_report(p)['rows'][0]['active']
    p=case(inlet=selected()); p.metering_detail.mounting.supports['inlet']['fingerprint']='old'
    assert not support_report(p)['rows'][0]['active']
    p=review_project(2); p.metering_detail.mounting.supports={'bypass':selected()}
    assert not support_report(p)['rows'][0]['active']


@pytest.mark.parametrize('extra',[{'reaction_n':float('nan')},{'reaction_n':True},
    {'reaction_n':100,'reaction_basis':123},{'height_mm':-1},{'load_case':'interpolated'}, {'rogue':0}])
def test_invalid_support_input_does_not_crash_or_pass(extra):
    assert validate_supports({'inlet':selected(**extra)})


def test_no_automatic_supports_and_no_combined_aggregate():
    assert studio_supports({})=={} and studio_supports({'vu_support_inlet':'none'})=={}
    p=case(); assert support_report(p)['rows']==[]
    p.metering_detail.mounting.support_count=2; p.metering_detail.mounting.support_basis='Явно'
    p.metering_detail.mounting.supports={'inlet':selected()}
    assert p.metering_detail.mounting.validate()
    with pytest.raises(ValueError,match='одновременно'):
        support_report(p)


def test_spec_owns_whole_stand_kit_once_and_scales_by_real_instances():
    p=review_project(2); p.metering_detail.mounting.supports={'inlet':selected('kromber-osvu1',height_mm=600)}
    rows=build_metering_spec_section(p).rows
    support=[r for r in rows if r.quantity_basis=='explicit_vu_support_points']
    assert len(support)==1 and support[0].qty==2 and support[0].catalogue_id=='kromber-osvu1'
    assert not any(r.name=='Опоры и крепления трубопровода ВУ' for r in rows)
    assert not any('support_fixings' in i for r in rows for i in r.component_ids)
    p.metering_detail.mounting.supports={'inlet':selected()}
    rows=build_metering_spec_section(p).rows
    assert next(r for r in rows if r.diagram_pos=='ОП1.К').qty is None
    assert next(r for r in rows if r.diagram_pos=='ОП1').qty==2


def test_removal_coverage_uses_graph_not_drawing_and_does_not_prove_stability():
    p=review_project(2)
    p.metering_detail.mounting.supports={'inlet':selected()}
    r=support_report(p)
    assert next(s for s in r['scenarios'] if s['target']=='meter')['uncovered']
    p.metering_detail.mounting.supports['outlet']=selected()
    r=support_report(p)
    assert next(s for s in r['scenarios'] if s['target']=='meter')['coverage']=='points_present'
    assert not any(s['stability_confirmed'] for s in r['scenarios'])
    from app.pz.metering_maintenance import audit_metering_maintenance
    audit=audit_metering_maintenance(p)
    assert next(s for s in audit['scenarios'] if s['target']=='meter')['support_coverage']['coverage']=='points_present'
    assert not audit['safe_to_remove']


def test_drawing_points_are_on_pipes_and_all_text_above_stamp():
    p=case(inlet=selected(),outlet=selected(),bypass=selected(),bypass_after=selected())
    before=deepcopy(asdict(p)); layout=build_metering_layout(p)
    pages=support_contents(p,drawing_state(p),layout)
    assert pages and asdict(p)==before
    roots=[ET.fromstring('<svg>'+s+'</svg>') for s in pages]
    assert len(roots[0].findall('.//*[@data-support-point]'))==4
    assert all(float(t.get('y',0))<236 for r in roots for t in r.findall('.//text'))
    assert 'data-support-network' in pages[0]


def test_studio_roundtrip_changes_no_hydraulics_and_does_not_copy_to_hot(tmp_path):
    from app.intake.studio_intake import build_handoff_request, public_draft
    from app.intake.yaml_io import dump_request,load_request
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    from app.intake.studio_project import calculate_project
    from app.pz.metering_hot_node import hot_meter_view
    d=draft(vu_support_inlet='termoclip-09105002',vu_support_outlet='termoclip-09105002')
    req=load_request(dump_request(build_handoff_request(d)))
    assert set(req.metering_detail.mounting.supports)=={'inlet','outlet'}
    p=design_ios2(build_project(req),output_dir=tmp_path,render_documents=False).project
    hot=hot_meter_view(p)
    assert not hot.metering_detail.mounting.supports
    a,b=calculate_project(draft()),calculate_project(d)
    for key in ('flows','head','meters','pumps','hydraulics','hot_hydraulics','fire'):
        assert a[key]==b[key]
    json.dumps(b)
    assert len(b['metering_layout']['supports']['rows'])==2
    assert all(not f['required'] for f in public_draft(d)['fields'] if f['key'].startswith('vu_support_'))


def test_http_choice_survives_save(client):
    from tests import test_studio as helpers
    state=helpers.new(client)
    d=draft(vu_support_inlet='termoclip-09105002')
    response=client.post('/studio/api/calculate',json={'revision':state['revision'],
        'answers':{k:r['value'] for k,r in d['answers'].items()}})
    assert response.status_code==200, response.text
    assert response.json()['project_calculation']['metering_layout']['supports']['rows'][0]['product']['id']=='termoclip-09105002'
    saved=client.get('/studio/api/draft').json()
    assert helpers.values(saved)['vu_support_inlet']['value']=='termoclip-09105002'


from tests.test_studio import client

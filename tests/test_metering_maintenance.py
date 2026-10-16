from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest
from app.intake.studio_metering import layout_summary
from app.pz.metering_maintenance import audit_metering_maintenance, maintenance_contents, network_from_chain
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_hot_node import hot_meter_view
from tests.test_studio_apartment_meters import draft
from tests.test_studio_metering_nodes import project
from tests import test_studio as studio_tests

client = studio_tests.client


def scenarios(report):
    return {s['target']:s for s in report['scenarios']}


def test_upward_meter_has_isolators_but_no_low_drain(tmp_path):
    p = project(draft(vu_orientation='vertical_up',vu_filter_layout='valtec_vt386'),tmp_path)
    rows = scenarios(audit_metering_maintenance(p))
    for key in ('meter','filter'):
        r = rows[key]
        assert r['isolation']=='checked'
        assert r['close_valves']==('valve_after','valve_before')
        assert r['drainage']=='blocked' and key in r['trapped_nodes']
        assert any('нужен нижний слив внутри отсечек' in m for m in r['messages'])
        assert not r['safe_to_remove']
    assert rows['check_valve']['isolation']=='blocked'
    assert any(path[-1]=='outlet' for path in rows['check_valve']['source_paths'])


@pytest.mark.parametrize('axis',['horizontal_dial_up','vertical_up','vertical_down'])
def test_audit_read_only_no_new_bom_or_hydraulics(axis,tmp_path):
    p = project(draft(vu_orientation=axis),tmp_path)
    before = deepcopy(asdict(p))
    spec = deepcopy(build_metering_spec_section(p))
    report = audit_metering_maintenance(p)
    assert not report['hydraulic_calculation_changed'] and not report['safe_to_remove']
    assert asdict(p)==before
    assert build_metering_spec_section(p)==spec
    assert 'Слив' in ''.join(maintenance_contents(p))


def test_meter_mounting_does_not_invent_mixed_geometry(tmp_path):
    p = project(draft(vu_orientation='vertical_up',vu_filter_layout='valtec_vt192_vtr090'),tmp_path)
    state = drawing_state(p)
    selection = resolve_metering_products(p,state.meter,bypass=state.bypass,electric_bypass=state.electric_bypass)
    network = network_from_chain(p.metering_detail,build_metering_chain(p.metering_detail,state,selection))
    assert all(e.gravity=='unknown' for e in network.links)
    assert scenarios(audit_metering_maintenance(p))['meter']['drainage']=='needs_data'


def test_cold_drain_orientation_not_copied_to_hot(tmp_path):
    p = project(draft(vu_orientation='vertical_up',vu_hot_orientation='horizontal_dial_up'),tmp_path)
    report = layout_summary(p)
    cold = scenarios(report['maintenance'])['meter']
    hot = scenarios(report['hot_drawing']['maintenance'])['meter']
    assert cold['drainage']=='blocked'
    assert hot['drainage']=='needs_data'
    assert 'inlet_valve' not in scenarios(report['hot_drawing']['maintenance'])
    assert 'ГВС' in report['hot_drawing']['maintenance']['scope']


def test_bypass_stays_in_model_for_its_own_replacement(tmp_path):
    p = project(draft(),tmp_path)
    r = scenarios(audit_metering_maintenance(p))['bypass_valve']
    assert 'bypass_valve' not in r['close_valves']
    assert r['isolation']=='blocked'  # no building-side external cut specified


def test_removing_automatic_bypass_also_requires_automation_coordination(tmp_path):
    p = project(draft(),tmp_path)
    state = replace(drawing_state(p),electric_bypass=True)
    r = scenarios(audit_metering_maintenance(p,state))['bypass_valve']
    assert any('режим автоматики' in m for m in r['messages'])


def test_svg_is_paginated_and_has_every_scenario_without_fake_table_rules(tmp_path):
    p = project(draft(vu_orientation='vertical_up'),tmp_path)
    bodies = maintenance_contents(p)
    targets = []
    for body in bodies:
        root = ET.fromstring('<svg>'+body+'</svg>')
        assert not root.findall('.//line')
        assert all(float(el.get('y','0')) < 228 for el in root.findall('.//text'))
        targets += [el.get('data-maintenance-target') for el in root.findall('.//g')]
    assert set(targets)==set(scenarios(audit_metering_maintenance(p)))
    pages = build_metering_detail_pages(p)
    assert sum('data-maintenance-target="meter"' in pg for pg in pages)==2  # cold + hot
    assert 'Обслуживание водомерного узла' in ''.join(pages)


def test_api_and_reload_expose_current_audit_without_new_mandatory_answers(client):
    state = studio_tests.new(client)
    d = draft(vu_orientation='vertical_up',vu_filter_layout='valtec_vt386')
    response = client.post('/studio/api/calculate',json={'revision':state['revision'],
        'answers':{k:v['value'] for k,v in d['answers'].items()}})
    assert response.status_code==200
    calculated = response.json()['project_calculation']
    report = calculated['metering_layout']['maintenance']
    assert scenarios(report)['meter']['drainage']=='blocked'
    saved = client.get('/studio/api/draft').json()['project_calculation']
    assert saved['metering_layout']['maintenance']==report
    assert saved['flows']==calculated['flows']


def test_no_hidden_geometry_from_mounting_scale(tmp_path):
    p = project(draft(vu_orientation='vertical_up',vu_drawing_scale='5'),tmp_path)
    before = audit_metering_maintenance(p)
    p.metering_detail.mounting = replace(p.metering_detail.mounting,scale=20)
    assert audit_metering_maintenance(p)==before

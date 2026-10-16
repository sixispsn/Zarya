"""Independent node passports and explicit mixed family through real intake."""
from copy import deepcopy
from dataclasses import asdict
from math import dist

import pytest

from app.intake.studio_intake import answer_field, build_handoff_request, IntakeError
from app.intake.studio_project import calculate_project
from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request
from app.pz.ios2_orchestrator import design_ios2
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_layout import build_metering_layout
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_detail_data import MeteringDetailData
from tests.test_studio_apartment_meters import draft
from tests import test_studio as studio_tests

client = studio_tests.client


def project(d, tmp_path):
    req = load_request(dump_request(build_handoff_request(d)))
    return design_ios2(build_project(req), output_dir=tmp_path, render_documents=False).project


@pytest.mark.parametrize('local', [False, True])
def test_node_minima_do_not_leak_between_nodes(local, tmp_path):
    d = draft(hws_heater_in_scope='yes' if local else 'no',
              vu_orientation='vertical_down', vu_cold_orientation='horizontal_dial_up',
              vu_hot_orientation='vertical_up', meter_min_cold_m3h=.04,
              meter_min_cold_source='Контрольный график')
    p = project(d, tmp_path)
    rows = {r.product['node']: r for r in p.meters.rows}
    assert rows['cold'].q_min_passport_m3h == .03 and rows['cold'].ok_v is True
    assert rows['hot'].q_min_passport_m3h == .06
    assert 'vertical_up' in rows['hot'].passport_reference
    if local:
        assert rows['total'].dn == 20 and rows['total'].q_min_passport_m3h == .10
        assert p.metering_detail.assembly_orientation == 'vertical_down'
    else:
        assert p.metering_detail.assembly_orientation == 'horizontal_dial_up'
    assert build_metering_layout(p).parts
    before = calculate_project(d)
    answer_field(d, 'vu_hot_orientation', 'horizontal_dial_up')
    after = calculate_project(d)
    for key in ('flows', 'head', 'hydraulics', 'hot_hydraulics', 'pumps', 'fire'):
        assert before[key] == after[key]
    assert before['meters'][0] == after['meters'][0]


@pytest.mark.parametrize('direction', ['vertical_up', 'vertical_down'])
@pytest.mark.parametrize('residents,dn,a', [(20,15,23), (200,25,37), (500,40,53)])
def test_mixed_studio_family_matches_layout_and_spec(direction, residents, dn, a, tmp_path):
    d = draft(residents=residents, apartments=residents//2, vu_orientation=direction,
              vu_hot_orientation='horizontal_dial_up', vu_drawing_scale='10',
              vu_filter_layout='valtec_vt192_vtr090')
    p = project(d, tmp_path); before = deepcopy(asdict(p))
    layout = build_metering_layout(p)
    assert layout.parts and not layout.issues
    meter, filt = layout.part('meter'), layout.part('filter')
    assert meter.points[0][0] == meter.points[-1][0]
    assert filt.points[0][1] == filt.points[-1][1]
    assert filt.catalogue_id == f'valtec-vt192-dn{dn}'
    for key in ('filter_turn_in','filter_turn_out'):
        elbow = layout.part(key)
        assert elbow.catalogue_id == f'valtec-vtr090-dn{dn}'
        assert elbow.center_to_face_mm == a
        assert dist(elbow.points[0], elbow.points[1])*10 == pytest.approx(a)
    rows = build_metering_spec_section(p).rows
    ids = [i for r in rows for i in r.component_ids]
    assert len(ids) == len(set(ids)) == len(layout.parts)
    for part in (meter, filt, layout.part('filter_turn_in'), layout.part('filter_turn_out')):
        assert any(part.id in r.component_ids and r.catalogue_id == part.catalogue_id for r in rows)
    assert all(r.qty == 1 for r in rows if r.diagram_pos in ('О1','О2'))
    assert layout.overall_length_mm is None
    assert 'data-vu-orientation' in build_metering_detail_pages(p)[0]
    assert asdict(p) == before  # Derived family IDs are never sticky assignments.


@pytest.mark.parametrize('mode', ['origin','dn','horizontal','manual','magnetic','revision','pressure'])
def test_family_does_not_bypass_conflicts(mode, tmp_path):
    d = draft(vu_orientation='vertical_up', vu_filter_layout='valtec_vt192_vtr090')
    if mode == 'origin': answer_field(d, 'russian_equipment_only', 'yes')
    if mode == 'dn': answer_field(d, 'residents', 5000)
    if mode == 'horizontal': answer_field(d, 'vu_orientation', 'horizontal_dial_up')
    p = project(d, tmp_path)
    if mode == 'manual': p.metering_detail.fitting_items['filter_turn_in'] = 'valtec-vtr090-dn50'
    if mode == 'magnetic': p.metering_detail.enhancements['magnetic_filter'] = 'vodopribor_fmf_replace'
    if mode == 'revision': p.metering_detail.catalogue_revision = 'old'
    if mode == 'pressure': p.metering_detail.design_pressure_bar = 100
    l = build_metering_layout(p)
    assert not l.parts and l.issues


def test_removing_offset_removes_both_elbows_from_spec(tmp_path):
    d = draft(vu_orientation='vertical_down', vu_filter_layout='valtec_vt192_vtr090')
    p = project(d, tmp_path)
    assert any(r.diagram_pos == 'О1' for r in build_metering_spec_section(p).rows)
    answer_field(d, 'vu_filter_layout', 'inline')
    p = project(d, tmp_path)
    assert not any(r.diagram_pos in ('О1','О2') for r in build_metering_spec_section(p).rows)
    assert not p.metering_detail.fitting_items and not p.metering_detail.catalogue_items


def test_manual_primary_axis_conflict_is_not_drawn(tmp_path):
    p = project(draft(), tmp_path)
    p.metering_detail.meter_orientations['cold'] = 'vertical_up'
    assert not build_metering_layout(p).parts
    state = drawing_state(p)
    s = resolve_metering_products(p,state.meter,bypass=state.bypass,electric_bypass=state.electric_bypass)
    assert any('ориентаци' in e.lower() for e in s.errors)


@pytest.mark.parametrize('key,value', [('vu_cold_orientation','vertical'),
    ('vu_hot_orientation',True), ('vu_filter_layout','auto')])
def test_invalid_answers_do_not_mutate_draft(key, value):
    d = draft(); before = deepcopy(d)
    with pytest.raises(IntakeError): answer_field(d,key,value)
    assert d == before


def test_new_model_inputs_validate_and_old_defaults_remain():
    assert MeteringDetailData().meter_orientations == {}
    assert MeteringDetailData(meter_orientations={'pump':'vertical_up'}).validate()
    assert MeteringDetailData(meter_orientations={'hot':'vertical'}).validate()
    assert MeteringDetailData(filter_offset_family='unknown').validate()


@pytest.mark.parametrize('direction', ['vertical_up', 'vertical_down'])
def test_elbow_dimensions_extend_away_from_vertical_leg(direction, tmp_path):
    import re
    from app.pz.metering_vertical_drawing import vertical_contents
    p = project(draft(vu_orientation=direction, vu_filter_layout='valtec_vt192_vtr090'), tmp_path)
    layout = build_metering_layout(p)
    svg = vertical_contents(p, drawing_state(p), layout)
    for ident, value in re.findall(r'data-bend-horizontal-dimension="([^"]+)" data-paper-y="([^"]+)"', svg):
        a, c, b = layout.part(ident).points
        vertical_end = a if a[0] == c[0] else b
        assert (float(value)-c[1]) * (vertical_end[1]-c[1]) < 0
    assert svg.count('data-bend-horizontal-dimension=') == 2


def test_http_node_choices_persist_and_clear_old_outputs(client):
    state = studio_tests.new(client)
    d = draft(vu_orientation='vertical_up', vu_cold_orientation='vertical_down',
              vu_hot_orientation='horizontal_dial_up', vu_filter_layout='valtec_vt192_vtr090')
    response = client.post('/studio/api/calculate', json={'revision':state['revision'],
        'answers':{k:v['value'] for k,v in d['answers'].items()}})
    assert response.status_code == 200
    state = response.json()
    layout = state['project_calculation']['metering_layout']
    assert layout['drawing_available'] and layout['orientation'] == 'vertical_down'
    assert {n['node']:n['orientation'] for n in layout['nodes']} == {
        'cold':'vertical_down', 'hot':'horizontal_dial_up'}
    restored = studio_tests.values(client.get('/studio/api/draft').json())
    assert restored['vu_filter_layout']['value'] == 'valtec_vt192_vtr090'
    assert restored['vu_cold_orientation']['value'] == 'vertical_down'
    state = studio_tests.answer(client, state, 'vu_cold_orientation', None)
    assert state['project_calculation'] is None and state['preview'] is None and state['package'] is None

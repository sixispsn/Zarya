"""Studio orientation -> current passports -> drawing/SO, without new hydraulics."""
from copy import deepcopy
from dataclasses import asdict
from math import dist

import pytest

from app.intake.studio_intake import answer_field, build_handoff_request, public_draft, IntakeError
from app.intake.studio_metering import VU_ORIENTATIONS, catalogue_proposal, layout_summary
from app.intake.studio_project import calculate_project, STUDIO_HANDOFF_VERSION
from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request
from app.pz.metering_detail import build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_layout import build_metering_layout
from app.pz.metering_spec import build_metering_spec_section
from app.pz.ios2_orchestrator import design_ios2
from scripts.preview_metering_mixed import mixed_review_project
from tests.test_studio_apartment_meters import draft
from tests import test_studio as studio_tests

client = studio_tests.client


@pytest.mark.parametrize('orientation', VU_ORIENTATIONS)
def test_studio_choice_reaches_yaml_drawing_and_current_passport(orientation, tmp_path):
    d = draft(vu_orientation=orientation, vu_drawing_scale='10')
    req = load_request(dump_request(build_handoff_request(d)))
    assert req.metering_detail.assembly_orientation == orientation
    assert req.metering_detail.meter_mounting == orientation
    project = design_ios2(build_project(req), output_dir=tmp_path, render_documents=False).project
    layout = build_metering_layout(project)
    assert layout.parts and not layout.issues
    meter = layout.part('meter')
    assert dist(meter.points[0], meter.points[-1]) * 10 == pytest.approx(meter.length_mm)
    if orientation != 'horizontal_dial_up':
        assert (meter.points[-1][1] > meter.points[0][1]) == (orientation == 'vertical_down')
        assert f'data-vu-orientation="{orientation}"' in build_metering_detail_pages(project)[0]
    rows = build_metering_spec_section(project).rows
    assert any('meter' in r.component_ids and r.catalogue_id == meter.catalogue_id for r in rows)
    before = calculate_project(draft())
    after = calculate_project(d)
    for key in ('flows', 'head', 'pumps', 'hydraulics', 'hot_hydraulics', 'fire'):
        assert after[key] == before[key]
    assert [(r['dn'], r['h_a']) for r in after['meters']] == [(r['dn'], r['h_a']) for r in before['meters']]
    assert all(orientation in r['passport_reference'] for r in after['meters'])
    assert not after['metering_layout']['installation_ready']
    assert not after['can_release']


def test_vertical_class_minimum_is_rechecked_not_carried_from_horizontal():
    d = draft(meter_min_cold_m3h=.04, meter_min_cold_source='ТЕСТ: подтверждённый график ХВС')
    cold = lambda p: next(r for r in p['meters'] if r['product']['node'] == 'cold')
    horizontal = cold(calculate_project(d))
    assert horizontal['ok_v'] is True and horizontal['q_min_passport_m3h'] == .03
    answer_field(d, 'vu_orientation', 'vertical_up')
    vertical = cold(calculate_project(d))
    assert vertical['ok_v'] is False and vertical['q_min_passport_m3h'] == .06
    assert vertical['dn'] == horizontal['dn'] and vertical['h_a'] == horizontal['h_a']


def test_forbidden_vertical_down_cannot_be_drawn_as_horizontal_fallback():
    p = calculate_project(draft(residents=5000, apartments=1000,
                                vu_orientation='vertical_down', vu_drawing_scale='20'))
    assert p['state'] == 'calculated' and p['can_preview']
    assert p['flows']['q_day_tot'] > 0
    assert not p['metering_layout']['drawing_available']
    assert any('паспорт не разрешает' in e for e in p['metering_layout']['issues'])
    assert all(not row['product']['id'] for row in p['meters'])
    assert not p['can_release']


def test_default_and_clear_preserve_existing_horizontal_behavior():
    d = draft()
    field = next(r for r in public_draft(d)['fields'] if r['key'] == 'vu_orientation')
    assert not field['required'] and field['value'] is None
    assert all('vu_orientation' not in step['fields'] for step in public_draft(d)['next_steps'])
    default = asdict(build_handoff_request(d).metering_detail)
    answer_field(d, 'vu_orientation', 'vertical_up')
    answer_field(d, 'vu_orientation', None)
    assert asdict(build_handoff_request(d).metering_detail) == default


@pytest.mark.parametrize('value', ['vertical', 'guess', True, {}, 15])
def test_unknown_choice_is_not_silently_defaulted(value):
    d = draft(); before = deepcopy(d)
    with pytest.raises(IntakeError):
        answer_field(d, 'vu_orientation', value)
    assert d == before


def test_catalogue_proposals_do_not_erase_existing_mixed_axes_or_assignments():
    detail = mixed_review_project().metering_detail
    before = asdict(detail)
    copied = catalogue_proposal(detail)
    assert asdict(detail) == before
    assert copied.meter_mounting == copied.assembly_orientation == 'vertical_up'
    assert copied.component_orientations == {'filter': 'horizontal_dial_up'}
    assert copied.fitting_items == detail.fitting_items
    assert copied.catalogue_items == detail.catalogue_items
    assert catalogue_proposal(MeteringDetailData()).meter_mounting == 'horizontal_dial_up'
    with pytest.raises(ValueError):
        catalogue_proposal(detail, orientation='vertical')


def test_connection_summary_does_not_turn_generic_nipples_into_selected_products():
    project = mixed_review_project(); before = asdict(project)
    summary = layout_summary(project)
    assert summary['drawing_available']
    assert summary['unselected_connectors'] == 3
    assert summary['connections']['unresolved'] > 0
    assert not summary['installation_ready']
    assert asdict(project) == before


@pytest.mark.parametrize('scale', ['25', '50'])
def test_larger_valid_scales_are_available_without_automatic_rescaling(scale):
    d = draft(vu_drawing_scale=scale)
    assert build_handoff_request(d).metering_detail.mounting.scale == int(scale)


def test_http_choice_persists_and_invalidates_previous_outputs(client):
    state = studio_tests.new(client)
    answers = {k: r['value'] for k, r in draft(vu_orientation='vertical_up')['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision': state['revision'], 'answers': answers})
    assert response.status_code == 200, response.text
    state = response.json()
    result = state['project_calculation']
    assert result['handoff_version'] == STUDIO_HANDOFF_VERSION
    assert result['metering_layout']['orientation'] == 'vertical_up'
    restored = client.get('/studio/api/draft').json()
    assert studio_tests.values(restored)['vu_orientation']['value'] == 'vertical_up'
    state = studio_tests.answer(client, state, 'vu_orientation', 'vertical_down')
    assert state['project_calculation'] is None and state['preview'] is None and state['package'] is None

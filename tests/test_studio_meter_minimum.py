"""Minimum-flow evidence via ordinary Studio; no defaults or new formulas."""
from copy import deepcopy

import pytest

from app.intake.studio_intake import answer_field, build_handoff_request, public_draft, IntakeError
from app.intake.studio_project import calculate_project
from app.intake.studio_metering import MINIMUM_NODES
from app.intake.yaml_io import dump_request, load_request
from tests.test_studio_apartment_meters import draft
from tests import test_studio as studio_tests

client = studio_tests.client


def supplied():
    # Deliberately synthetic evidence, not a minimum assigned to Samara.
    return {f"meter_min_{n}_{key}": value for n in MINIMUM_NODES
            for key, value in (("m3h", .2), ("source", f"ТЕСТ: график {n}, лист 1, редакция 2"))}


def test_no_required_fields_no_fake_minimum():
    d = draft()
    req = build_handoff_request(d)
    assert not req.source_data.meter_minimum_checks
    state = public_draft(d)
    fields = [r for r in state['fields'] if r['key'].startswith('meter_min_')]
    assert len(fields) == 6 and all(r['value'] is None and not r['required'] for r in fields)
    assert all(not k.startswith('meter_min_') for step in state['next_steps'] for k in step['fields'])
    p = calculate_project(d)
    assert p['can_preview'] and not p['can_release']
    assert all(r['ok_v'] is None for r in p['meters'])


def test_supplied_evidence_reaches_yaml_and_current_product_without_changing_hydraulics():
    before = calculate_project(draft())
    d = draft(**supplied())
    req = build_handoff_request(d)
    assert load_request(dump_request(req)).source_data.meter_minimum_checks == req.source_data.meter_minimum_checks
    for n, e in req.source_data.meter_minimum_checks.items():
        assert e['dn_mm'] is None and e['q_min_passport_m3h'] is None
        assert e['q_min_hourly_m3h'] == .2 and n in e['flow_reference']
    after = calculate_project(d)
    for key in ('flows', 'head', 'pumps', 'hydraulics', 'hot_hydraulics', 'fire'):
        assert before[key] == after[key]
    assert all(r['ok_v'] is True for r in after['meters'])
    assert [r['dn'] for r in before['meters']] == [r['dn'] for r in after['meters']]
    assert [r['h_a'] for r in before['meters']] == [r['h_a'] for r in after['meters']]
    assert not after['can_release']  # A minimum check isn't a project approval.


def test_partial_evidence_zero_and_removal_are_not_silently_filled():
    d = draft(meter_min_cold_m3h=.2)
    p = calculate_project(d)
    assert all(r['ok_v'] is None for r in p['meters'])
    answer_field(d, 'meter_min_cold_source', 'ТЕСТ: явный нулевой минимум')
    answer_field(d, 'meter_min_cold_m3h', 0)
    p = calculate_project(d)
    cold = next(r for r in p['meters'] if r['product']['node'] == 'cold')
    assert cold['q_min_hourly_m3h'] == 0 and cold['ok_v'] is False
    assert all(r['ok_v'] is None for r in p['meters'] if r['product']['node'] != 'cold')
    answer_field(d, 'meter_min_cold_m3h', None)
    assert all(r['ok_v'] is None for r in calculate_project(d)['meters'])


def test_changed_demand_rechecks_new_meter_instead_of_reusing_green_status():
    d = draft(**supplied())
    assert all(r['ok_v'] is True for r in calculate_project(d)['meters'])
    answer_field(d, 'residents', 1000)
    rows = calculate_project(d)['meters']
    assert all(r['dn'] == 50 and r['q_min_passport_m3h'] == .45 for r in rows)
    assert all(r['q_min_hourly_m3h'] == .2 and r['ok_v'] is False for r in rows)


@pytest.mark.parametrize('value', [-1, True, 'nan', 'inf', {}, []])
def test_invalid_minimum_preserves_answers(value):
    d = draft(); before = deepcopy(d)
    with pytest.raises(IntakeError):
        answer_field(d, 'meter_min_cold_m3h', value)
    assert d == before


def test_http_persistence_and_invalidation(client):
    state = studio_tests.new(client)
    answers = {k: r['value'] for k, r in draft(**supplied())['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision': state['revision'], 'answers': answers})
    assert response.status_code == 200, response.text
    state = response.json()
    assert all(r['ok_v'] is True for r in state['project_calculation']['meters'])
    restored = client.get('/studio/api/draft').json()
    assert {r['key']: r['value'] for r in restored['fields'] if r['key'].startswith('meter_min_')} == supplied()
    state = studio_tests.answer(client, state, 'meter_min_cold_source', None)
    assert state['project_calculation'] is None and state['preview'] is None and state['package'] is None

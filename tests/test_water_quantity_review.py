"""Accepted apartment scope and real riser quantities, not drawing takeoff."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from app.intake import samara_study
from app.intake.studio_intake import accepted_values, answer_field, build_handoff_request, IntakeError
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.pz.apartment_water_units import ApartmentWaterUnits
from app.pz.spec import build_water_specification
from app.pz.water_regulation_plan import branch_regulation_plan
from tests.test_studio_apartment_meters import draft
from tests import test_studio as studio_tests

client = studio_tests.client


def rows(p):
    return [r for s in build_water_specification(p).sections for r in s.rows]


@pytest.fixture(scope='module')
def samara(tmp_path_factory):
    d = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(d, None)
    return d, samara_study.build(d, tmp_path_factory.mktemp('quantities'), render=False)[0].project


def test_samara_choice_uses_ordinary_adapter_and_never_changes_hydraulics(samara):
    d, p = samara
    req, _, station, _ = samara_study.inputs(d)
    ordinary = deepcopy(d); ordinary.pop('study')
    assert req.apartment_water_units == build_handoff_request(ordinary).apartment_water_units == ApartmentWaterUnits('one_per_apartment', design_residents=3)
    assert load_request(dump_request(req)) == req
    assert d['answers']['apartment_units_mode']['source']['kind'] == 'study_assumption'
    base = load_request(samara_study.load_case()['payload']['request_yaml'])
    assert replace(req, apartment_water_units=base.apartment_water_units,
        wastewater_presentation=base.wastewater_presentation, metering_detail=base.metering_detail) == base
    assert station == samara_study.load_case()['payload']['result']
    assert (p.flows.q_day_tot, p.flows.q_sec_tot) == (63, 3.185)
    assert (p.pumps.q_design_m3h, p.pumps.h_design_m) == pytest.approx((11.466, 50.25))
    assert [r.dn for r in p.meters.rows] == [50, 32, 32]
    assert [r.h_a for r in p.meters.rows] == [1.451, 3.479, 4.703]
    assert not d['project_calculation']['can_release']


def test_exact_components_and_floor_sum_not_illustration(samara):
    _, p = samara
    before = deepcopy(asdict(p))
    rr = rows(p)
    apartment = [r for r in rr if r.quantity_basis == 'apartment_schedule']
    assert len(apartment) == 10 and all(r.qty == 143 for r in apartment)
    assert sum(r.unit == 'шт.' for r in apartment) == 8
    assert sum(r.unit == 'компл.' for r in apartment) == 2
    rd = [r for r in rr if r.quantity_basis == 'stage_p_regulation_schedule']
    assert len(rd) == 2 and all(r.qty == 8 + 10*9 == 98 for r in rd)
    assert all('граница предварительная' in r.note and 'уставка по подбору' in r.note for r in rd)
    assert all(r.code == 'OR.224.G.04' for r in rd)
    assert branch_regulation_plan(p).floors == tuple(range(1,12))
    assert asdict(p) == before
    assert all(getattr(p.building,k) == 0 for k in ('risers_v1','risers_t3','risers_t4'))
    for key in ('v1-riser-valve','t3-riser-valve','t4-riser-valve'):
        r = next(r for r in rr if r.component_ids == (key,))
        assert r.qty is None and 'Число стояков' in r.quantity_source
    assert next(r for r in rr if r.component_ids == ('circulation-balance',)).qty is None
    estimates = [r for r in rr if r.quantity_basis == 'area_estimate']
    assert len(estimates) == 8 and all('Оценка по площади' in r.quantity_note for r in estimates)


@pytest.mark.parametrize('change', ['no_choice','partial','wrong_sum','fraction','boolean','custom','wrong_key'])
def test_partial_floor_or_feed_information_does_not_allocate_regulators(samara,change):
    p = deepcopy(samara[1])
    if change == 'no_choice': p.apartment_water_units = ApartmentWaterUnits()
    elif change == 'partial': p.building.apartments_by_floor.pop(3)
    elif change == 'wrong_sum': p.building.apartments_by_floor[1] = 9
    elif change == 'fraction': p.building.apartments_by_floor[1] = 8.0
    elif change == 'boolean': p.building.apartments_by_floor[1] = True
    elif change == 'wrong_key': p.building.apartments_by_floor['1'] = p.building.apartments_by_floor.pop(1)
    else: p.apartment_water_units = ApartmentWaterUnits('explicit_counts', 143, 143)
    rd = [r for r in rows(p) if r.name.startswith('Регулятор давления квартирного')]
    assert len(rd) == 2 and all(r.qty is None for r in rd)


def test_changed_basis_or_answer_revokes_study(samara,tmp_path,monkeypatch):
    d = deepcopy(samara[0])
    with pytest.raises(IntakeError): answer_field(d,'apartment_units_mode','unspecified')
    d['answers']['apartment_units_mode']['value'] = 'unspecified'
    with pytest.raises(IntakeError): samara_study.inputs(d)
    path = tmp_path/'review.json'
    data = json.loads(samara_study.QUANTITY_REVIEW.read_text())
    data['basis'] += ' Изменённое основание.'
    path.write_text(json.dumps(data,ensure_ascii=False))
    monkeypatch.setattr(samara_study,'QUANTITY_REVIEW',path)
    with pytest.raises(IntakeError): samara_study.inputs(samara[0])


def test_riser_counts_ordinary_studio_independent_hvs_hot_and_return():
    d = draft(risers_v1=12, risers_t3=10, risers_t4=5, hws_balance_mode='riser_returns')
    req = build_handoff_request(d)
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    expected = {'v1-riser-valve':12, 't3-riser-valve':10, 't4-riser-valve':5, 'circulation-balance':5}
    rr = rows(p)
    for key, n in expected.items():
        found = [r for r in rr if r.component_ids == (key,)]
        assert len(found) == 1 and found[0].qty == n and f'× {n} ' in found[0].quantity_source
    answer_field(d,'risers_t4',None)
    p = build_project(build_handoff_request(d))
    assert next(r for r in rows(p) if r.component_ids == ('circulation-balance',)).qty is None
    # Even a known count gives neither a Т4 diameter nor Kv/settings/pipe metres.
    assert all(r.qty is None for r in rows(p) if r.component_ids == ('t4-network',))


@pytest.mark.parametrize('value', [True, -1, 1.1, 'nan', 'inf', 1_000_001])
def test_no_rounding_invalid_riser_quantity(value):
    with pytest.raises(IntakeError): draft(risers_t4=value)
    req = build_handoff_request(draft())
    req.risers_t4 = value
    assert any('risers_t4:' in s for s in req.validate())


def test_stale_hot_counts_do_not_create_central_system():
    req = build_handoff_request(draft(risers_v1=8,risers_t3=8,risers_t4=4,hws_type='none'))
    assert (req.risers_v1, req.risers_t3, req.risers_t4) == (8,0,0)
    assert not any(r.component_ids == ('circulation-balance',) for r in rows(build_project(req)))


@pytest.mark.parametrize('value', [True, -1, 1.1, float('nan'), float('inf'), 1_000_001])
def test_yaml_never_truncates_or_coerces_riser_counts(value):
    import yaml
    from app.intake.yaml_io import YamlFormatError
    data = yaml.safe_load(dump_request(build_handoff_request(draft())))
    data['building']['risers_t4'] = value
    with pytest.raises(YamlFormatError, match='risers_t4'):
        load_request(yaml.safe_dump(data))


def test_risers_http_persistence_optional_inputs_and_preview_revocation(client):
    state = studio_tests.new(client)
    answers = {k:r['value'] for k,r in draft(risers_v1=12, risers_t3=10, risers_t4=5)['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision':state['revision'],'answers':answers})
    assert response.status_code == 200, response.text
    state = response.json()
    restored = client.get('/studio/api/draft').json()
    fields = {r['key']:r for r in restored['fields']}
    for key,n in (('risers_v1',12),('risers_t3',10),('risers_t4',5)):
        assert fields[key]['value'] == n and not fields[key]['required']
    state = studio_tests.answer(client,state,'risers_t4',None)
    assert state['project_calculation'] is None and state['preview'] is None and state['package'] is None

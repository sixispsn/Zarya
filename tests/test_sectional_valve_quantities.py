"""Explicit layout quantities, never an invented percentage of risers."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
import subprocess

import pytest
import yaml

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, build_handoff_request, IntakeError
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.spec import build_water_specification
from app.pz.spec_quantity_review import water_spec_quantity_review
from tests.test_studio_apartment_meters import draft
from tests.test_studio import client, new, answer
from tests.test_apartment_accessories import samara


COUNT = 'v1_sectional_valves_count'
BASIS = 'v1_sectional_valves_basis'
SOURCE = 'Принятая компоновка магистрали В1, лист 2, редакция 1; вне кранов узлов'


def sectional(p):
    return next(r for s in build_water_specification(p).sections for r in s.rows
                if r.component_ids == ('v1-sectional-valves',))


@pytest.mark.parametrize('risers', [0, 1, 9, 100, 500])
def test_unknown_does_not_disappear_and_never_uses_riser_percentage(risers):
    p = build_project(build_handoff_request(draft()))
    p.building.risers_v1 = risers
    before = deepcopy(asdict(p))
    row = sectional(p)
    assert row.qty is None and row.quantity_basis == 'needs_layout'
    assert '11.8' in row.quantity_source and '0,3' not in row.quantity_source
    assert asdict(p) == before
    assert any(a['id'] == 'sectional_valves' for a in water_spec_quantity_review(p)['actions'])


@pytest.mark.parametrize('count', [0, 1, 7])
def test_explicit_quantity_yaml_roundtrip_no_other_model_changes(count):
    baseline = build_handoff_request(draft())
    req = build_handoff_request(draft(**{COUNT: str(count), BASIS: SOURCE}))
    assert replace(req, **{COUNT: None, BASIS: ''}) == baseline
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    before = asdict(build_project(baseline))
    after = asdict(p)
    assert [k for k in before if before[k] != after[k]] == ['building']
    row = sectional(p)
    assert row.qty == count and row.quantity_basis == 'project_input'
    assert row.quantity_source == SOURCE and 'Без повторного учёта' in row.note
    assert not any(a['id'] == 'sectional_valves' for a in water_spec_quantity_review(p)['actions'])
    for n in (2, 9, 100):
        p.building.risers_v1 = n
        assert sectional(p).qty == count


@pytest.mark.parametrize('count,basis', [(0,''), (4,''), (4,'   '), (None,SOURCE)])
def test_incomplete_layout_stays_pending_not_zero_or_hydraulic_block(count,basis):
    req = replace(build_handoff_request(draft()), **{COUNT: count, BASIS: basis})
    assert not req.validate()
    assert sectional(build_project(req)).qty is None


def test_old_yaml_has_no_added_keys_and_explicit_zero_is_not_lost():
    req = build_handoff_request(draft())
    assert COUNT not in yaml.safe_load(dump_request(req))['building']
    zero = replace(req, **{COUNT: 0, BASIS: SOURCE})
    raw = yaml.safe_load(dump_request(zero))
    assert raw['building'][COUNT] == 0
    assert load_request(dump_request(zero)) == zero


@pytest.mark.parametrize('bad', [True, -1, 1.5, 1_000_001, float('nan'), float('inf')])
def test_invalid_count_rejected_in_studio_dto_yaml_and_direct_spec(bad):
    with pytest.raises(IntakeError):
        answer_field(draft(), COUNT, bad)
    req = replace(build_handoff_request(draft()), **{COUNT: bad, BASIS: SOURCE})
    assert any(COUNT in message for message in req.validate())
    with pytest.raises(YamlFormatError):
        load_request(dump_request(req))
    p = build_project(build_handoff_request(draft()))
    setattr(p.building, COUNT, bad)
    with pytest.raises(ValueError, match='Секционные краны'):
        sectional(p)


def test_typed_input_does_not_truncate_strings_or_fractional_values():
    req = replace(build_handoff_request(draft()), **{COUNT: '2'})
    assert any(COUNT in message for message in req.validate())
    with pytest.raises(YamlFormatError):
        load_request(dump_request(req))
    for value in (True, ['лист 1'], 'x' * 201):
        req = replace(req, **{COUNT: 2, BASIS: value})
        assert any(BASIS in message for message in req.validate())
        with pytest.raises(YamlFormatError):
            load_request(dump_request(req))


def test_active_samara_has_no_adopted_layout_and_preserves_hydraulics(samara):
    before = deepcopy(asdict(samara))
    assert sectional(samara).qty is None
    assert samara.building.risers_v1 == 0
    assert (samara.flows.q_day_tot, samara.flows.q_sec_tot) == (63, 3.185)
    assert (samara.pumps.q_design_m3h, samara.pumps.h_design_m) == pytest.approx((11.466, 50.25))
    assert asdict(samara) == before


def test_http_optional_inputs_and_clear_revoke_outputs_without_changing_hydraulics(client):
    state = new(client)
    answers = {k:r['value'] for k,r in draft()['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision':state['revision'], 'answers':answers})
    assert response.status_code == 200, response.text
    state = response.json()
    baseline = state['project_calculation']
    assert baseline['can_preview']
    for count, basis, pending in [(4, None, True), (4, SOURCE, False), (0, SOURCE, False), (None, SOURCE, True)]:
        state = answer(client, state, COUNT, count)
        state = answer(client, state, BASIS, basis)
        assert state['project_calculation'] is None and state['preview'] is None
        response = client.post('/studio/api/calculate', json={'revision':state['revision']})
        assert response.status_code == 200, response.text
        state = response.json()
        result = state['project_calculation']
        assert result['can_preview']
        assert any(a['id']=='sectional_valves' for a in result['spec_quantity_review']['actions']) == pending
        for key in ('flows', 'head', 'meters', 'pumps'):
            assert result[key] == baseline[key]
        assert client.get('/studio/api/draft').json()['project_calculation'] == result


def test_ui_fields_are_optional_collapsed_and_review_opens_them():
    code = """global.window={};
    require('./app/web/static/studio_configurator.js');
    require('./app/web/static/studio_spec_review.js');
    console.log(JSON.stringify(window.ZaryaConfigurator.groups));"""
    r = subprocess.run([os.environ['NODE_BINARY'], '-e', code], text=True, capture_output=True, check=True)
    groups = json.loads(r.stdout)
    assert all(COUNT not in g['primary'] and BASIS not in g['primary'] for g in groups)
    consumers = next(g for g in groups if g['id']=='consumers')
    assert [COUNT, BASIS] in [s[1] for s in consumers['sections']]

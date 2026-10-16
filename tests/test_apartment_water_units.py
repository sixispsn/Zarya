"""Feed quantities use accepted Studio inputs, never schematic repetition."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
import subprocess

import pytest
import yaml

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, build_handoff_request, public_draft, IntakeError
from app.intake.studio_project import calculate_project
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.apartment_water_units import ApartmentWaterUnits
from app.pz.spec import build_water_specification, format_spec_qty
from app.pz.water_apartment_assembly import apartment_components
from tests.test_studio_apartment_meters import draft
from tests import test_studio as studio_tests

client = studio_tests.client


def project(**values):
    return build_project(build_handoff_request(draft(**values)))


def rows(p):
    return [r for s in build_water_specification(p).sections for r in s.rows
            if any(c.startswith('apartment-') and '-connection-' not in c for c in r.component_ids)]


def test_default_is_unknown_not_a_new_required_question():
    d = draft()
    p = build_project(build_handoff_request(d))
    assert len(rows(p)) == 10 and all(r.qty is None for r in rows(p))
    state = public_draft(d)
    assert all(not r['required'] for r in state['fields'] if r['key'].startswith('apartment_units_'))
    assert not any(k.startswith('apartment_units_') for s in state['next_steps'] for k in s['fields'])
    assert 'apartment_water_units:' not in dump_request(build_handoff_request(d))


@pytest.mark.parametrize('apartments', [8, 143, 500])
def test_explicit_one_per_apartment_not_per_floor_or_symbol(apartments):
    p = project(apartments=apartments, apartment_units_mode='one_per_apartment')
    before = deepcopy(asdict(p))
    rr = rows(p)
    assert len(rr) == 10
    for r in rr:
        assert r.qty == apartments and format_spec_qty(r.qty, r.unit) == str(apartments)
        assert r.quantity_basis == 'apartment_schedule' and str(apartments) in r.quantity_source
        assert 'DN15' in r.type_mark and r.catalogue_id.endswith('-dn15')
        assert ('Предварительное предложение' in r.note if r.unit == 'шт.' else
                'повторно не закупать' in r.note)
    assert asdict(p) == before
    p.building.floors = 16
    assert [r.qty for r in rows(p)] == [apartments] * 10
    for system in ('В1', 'Т3'):
        assert set(c.key for c in apartment_components(p, system)) <= {c for r in rr for c in r.component_ids}


def test_custom_counts_partial_zero_and_mode_changes():
    d = draft(apartment_units_mode='explicit_counts', apartment_units_cold_count=12)
    p = build_project(build_handoff_request(d))
    assert [r.qty for r in rows(p)] == [12] * 5 + [None] * 5
    answer_field(d, 'apartment_units_hot_count', 0)
    assert [r.qty for r in rows(build_project(build_handoff_request(d)))] == [12] * 5 + [0] * 5
    answer_field(d, 'apartment_units_mode', 'one_per_apartment')
    req = build_handoff_request(d)
    assert req.apartment_water_units == ApartmentWaterUnits('one_per_apartment')
    assert [r.qty for r in rows(build_project(req))] == [8] * 10
    answer_field(d, 'apartment_units_mode', 'unspecified')
    assert all(r.qty is None for r in rows(build_project(build_handoff_request(d))))


def test_no_apartment_count_is_not_zero():
    req = build_handoff_request(draft(apartment_units_mode='one_per_apartment'))
    p = build_project(replace(req, apartments=0))
    assert all(r.qty is None for r in rows(p))


def test_no_second_meter_when_meter_not_in_shared_composition():
    p = project(apartment_units_mode='one_per_apartment')
    p.meters.has_apartment_meters = False
    rr = rows(p)
    assert len(rr) == 6 and all(r.qty == 8 for r in rr)
    assert not any('Счётчик' in r.name for r in rr)


@pytest.mark.parametrize('change', ['local_hws', 'zones', 'public', 'fixtures'])
def test_unsupported_layout_does_not_get_an_invented_assembly(change):
    from app.pz.project import BuildingPurpose, HwsType
    p = project(apartment_units_mode='one_per_apartment')
    if change == 'local_hws': p.building.hws_type = HwsType.LOCAL
    elif change == 'zones': p.building.zones = 2
    elif change == 'public': p.building.purpose = BuildingPurpose.PUBLIC
    else: p.fixtures = [object()]
    assert not apartment_components(p, 'В1') and not apartment_components(p, 'Т3')


def test_yaml_and_builder_roundtrip_and_other_rows_unchanged():
    before = build_handoff_request(draft())
    after = build_handoff_request(draft(apartment_units_mode='explicit_counts',
                                       apartment_units_cold_count=12, apartment_units_hot_count=10))
    assert load_request(dump_request(after)) == after
    assert replace(after, apartment_water_units=before.apartment_water_units) == before
    a, b = build_project(before), build_project(after)
    assert b.apartment_water_units == after.apartment_water_units
    def other(p):
        return [asdict(r) for s in build_water_specification(p).sections for r in s.rows
                if not any(c.startswith('apartment-') for c in r.component_ids)]
    assert other(a) == other(b)


def test_hydraulics_and_preview_readiness_not_affected():
    a = calculate_project(draft())
    b = calculate_project(draft(apartment_units_mode='one_per_apartment'))
    for key in ('flows', 'head', 'pumps', 'hydraulics', 'hot_hydraulics', 'fire', 'meters', 'can_release', 'can_preview'):
        assert a[key] == b[key], key
    assert not b['can_release'] and b['can_preview']


@pytest.mark.parametrize('value', [-1, 1.5, True, 'nan', 'inf', {}, [], 1_000_001])
def test_invalid_studio_count_does_not_mutate(value):
    d = draft(); before = deepcopy(d)
    with pytest.raises(IntakeError):
        answer_field(d, 'apartment_units_cold_count', value)
    assert d == before


@pytest.mark.parametrize('bad', [dict(mode='bad'), dict(mode='explicit_counts', cold_count=1.5),
    dict(mode='explicit_counts', hot_count=True), dict(mode='explicit_counts', cold_count=-1),
    dict(mode='explicit_counts', cold_count='12'), dict(mode='one_per_apartment', cold_count=12),
    dict(mode='explicit_counts', other=12), [], 1, 'bad'])
def test_invalid_yaml_rejected(bad):
    data = yaml.safe_load(dump_request(build_handoff_request(draft())))
    data['apartment_water_units'] = bad
    with pytest.raises(YamlFormatError):
        load_request(yaml.safe_dump(data, allow_unicode=True))


def test_http_persistence_and_cache_invalidation(client):
    state = studio_tests.new(client)
    answers = {k: r['value'] for k, r in draft(apartment_units_mode='one_per_apartment')['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision': state['revision'], 'answers': answers})
    assert response.status_code == 200, response.text
    state = response.json()
    restored = client.get('/studio/api/draft').json()
    assert next(r for r in restored['fields'] if r['key'] == 'apartment_units_mode')['value'] == 'one_per_apartment'
    state = studio_tests.answer(client, state, 'apartment_units_mode', 'unspecified')
    assert state['project_calculation'] is None and state['preview'] is None and state['package'] is None


def test_manual_fields_only_visible_for_custom_counts():
    script = "global.window={};require('./app/web/static/studio_configurator.js');console.log(JSON.stringify(['unspecified','one_per_apartment','explicit_counts'].map(mode=>['apartment_units_cold_count','apartment_units_hot_count'].map(k=>window.ZaryaConfigurator.fanFieldVisible(k,{apartment_units_mode:mode})))));"
    result = subprocess.run([os.environ['NODE_BINARY'], '-e', script], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == [[False, False], [False, False], [True, True]]


def test_old_editor_preserves_choice_it_does_not_edit(tmp_path, monkeypatch):
    import asyncio
    from starlette.datastructures import FormData
    from app.intake.project_store import ProjectStore
    from app.web import wizard
    from tests.test_wizard_fan_inputs import request
    store = ProjectStore(str(tmp_path))
    req = build_handoff_request(draft(apartment_units_mode='explicit_counts',
                                      apartment_units_cold_count=12, apartment_units_hot_count=10))
    # Isolate persistence from independent hydraulic snapshot protections.
    req.source_data.apartment_meter_basis = ''
    pid = store.save(req)
    monkeypatch.setattr(wizard, '_STORE', store)
    monkeypatch.setattr(wizard, 'design_request_response', lambda request, req, pid: req)
    r = request()
    r._form = FormData({'project_id': pid})
    assert asyncio.run(wizard.wizard_design(r)).apartment_water_units == req.apartment_water_units

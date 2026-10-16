from copy import deepcopy
from dataclasses import asdict

import pytest
from pydantic import ValidationError

from app.intake.studio_intake import IntakeError
from app.intake.studio_suction import (
    StudioSuctionInput, evaluate, project_context, save_check, saved_view,
)
from tests import test_studio as studio_fixtures
from tests import test_water_station_review as station_fixtures

client = studio_fixtures.client
samara = station_fixtures.samara
common = station_fixtures.common


def payload(context, **updates):
    route = context['routes'][0]
    return StudioSuctionInput.model_validate({
        'revision': 0, 'fingerprint': context['fingerprint'], 'route_id': route['id'],
        'path_basis': 'Синтетическая проверка последовательного режима; не данные Самары',
        'balance': dict(pressure_kind='absolute', pressure_bar=1, source_elevation_m=0,
            pump_elevation_m=2, vapor_head_m=.2, max_flow_m3h=12, temperature_c=10,
            basis='Арифметический тест, все исходные явно заданы', npshr_m=6.5,
            npshr_basis='Тест сравнения при 12 м³/ч', safety_margin_m=.5),
        'losses': [dict(id='test', covers=route['required_components'], loss_m=1,
            flow_m3h=12, temperature_c=10, basis='Готовый тестовый результат всего пути')],
        **updates})


def test_samara_context_preserves_project_and_alternative_paths(common):
    before = deepcopy(asdict(common))
    context = project_context(common, dependencies='test')
    assert len(context['routes']) == 8
    assert len({r['id'] for r in context['routes']}) == 8
    assert all(set(r['components']) == set(r['required_components']) for r in context['routes'])
    assert asdict(common) == before
    assert project_context(common, dependencies='test')['fingerprint'] == context['fingerprint']
    result = evaluate(context, payload(context))
    assert result['balance']['available_m'] == pytest.approx(7)
    assert result['losses']['total_loss_m'] == 1
    assert asdict(common) == before


def test_geometry_and_catalogue_change_invalidate_same_ids(common):
    context = project_context(common, dependencies='before')
    draft = {}
    save_check(draft, context, payload(context))
    assert saved_view(draft, context)['status'] == 'current'
    common.source.h_vvod_m += .1
    changed = project_context(common, dependencies='before')
    assert changed['routes'] == context['routes']
    assert saved_view(draft, changed)['status'] == 'stale'
    assert saved_view(draft, changed)['result'] is None
    with pytest.raises(IntakeError, match='изменились'):
        evaluate(changed, payload(context))
    with pytest.raises(IntakeError, match='перепроверьте'):
        save_check(draft, changed, payload(changed))
    save_check(draft, changed, payload(changed, reviewed=True))
    assert saved_view(draft, changed)['status'] == 'current'
    catalogue = project_context(common, dependencies='new-catalogue')
    assert saved_view(draft, catalogue)['result'] is None


def test_new_loss_mode_requires_matching_ready_results(common):
    context = project_context(common, dependencies='test')
    p = payload(context)
    p.balance.max_flow_m3h = 13
    result = evaluate(context, p)
    assert result['losses']['total_loss_m'] is None
    assert result['balance']['available_m'] is None
    p = payload(context, losses=[])
    assert evaluate(context, p)['balance']['available_m'] is None
    p = payload(context)
    p.losses.append(p.losses[0])
    with pytest.raises(ValueError, match='повторный'):
        evaluate(context, p)


def test_explicit_pump_axis_change_keeps_ids_but_rejects_old_balance(common):
    old = project_context(common, dependencies='test')
    common.source.station_suction_elevation_m = -1.5
    current = project_context(common, dependencies='test')
    assert current['routes'] == old['routes']
    assert current['fingerprint'] != old['fingerprint']
    with pytest.raises(IntakeError, match='Ось всасывания'):
        evaluate(current, payload(current))


def test_pipe_length_change_invalidates_unchanged_component_ids(common):
    old = project_context(common, dependencies='test')
    draft = {}
    save_check(draft, old, payload(old))
    common.v1_sections[0].length_m += 1
    current = project_context(common, dependencies='test')
    assert current['routes'] == old['routes']
    assert saved_view(draft, current)['result'] is None


@pytest.mark.parametrize('change', ['foreign_route', 'foreign_component', 'ready_hf', 'fake_path'])
def test_client_cannot_replace_current_graph(common, change):
    context = project_context(common, dependencies='test')
    p = payload(context)
    if change == 'foreign_route':
        p.route_id = '0' * 64
    elif change == 'foreign_component':
        p.losses[0].covers.append('node:station_discharge')
    elif change == 'ready_hf':
        p.balance.suction_losses_m = 1
    else:
        from app.schemas.pump_suction import SuctionPathRequest
        p.balance.suction_path = SuctionPathRequest(required_components=['anything'])
    with pytest.raises(ValueError):
        evaluate(context, p)


def ordinary(client):
    state = client.post('/studio/api/draft').json()
    r = client.post('/studio/api/calculate', json=dict(revision=state['revision'], answers=dict(
        residents=20, apartments=8, consumer_code='residential_full_bath', floors=2,
        building_height_m=6.6, fire_height_m=4.8, hws_type='central', inputs_count=2,
        guaranteed_head_m=5, h_geom_m=6, pressure_loss_mode='ready', h_il_m=3, h_vvod_m=1,
        t3_loss_mode='ready', h_il_hot_m=4, hws_heater_in_scope='no')))
    assert r.status_code == 200, r.text
    return r.json()


def test_http_save_reload_stale_and_concurrent_edit(client):
    original = ordinary(client)
    r = client.get('/studio/api/suction')
    assert r.status_code == 200, r.text
    state = r.json()
    assert state['saved']['status'] == 'not_saved'
    p = payload(state['context'], revision=state['revision']).model_dump()
    r = client.post('/studio/api/suction', json=p)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved['saved']['result']['balance']['available_m'] == pytest.approx(7)
    assert client.post('/studio/api/suction', json=p).status_code == 409
    reloaded = client.get('/studio/api/suction').json()
    assert reloaded['saved'] == saved['saved']
    after = client.get('/studio/api/draft').json()
    assert after['project_calculation']['suction_check']['status'] == 'current'
    assert {k: v for k, v in after['project_calculation'].items() if k != 'suction_check'} == {
        k: v for k, v in original['project_calculation'].items() if k != 'suction_check'}
    assert after['calculation'] == original['calculation']
    r = client.patch('/studio/api/answer', json=dict(revision=saved['revision'],
                                                    field='h_vvod_m', value=2))
    assert r.status_code == 200
    stale = client.get('/studio/api/suction').json()
    assert stale['saved']['status'] == 'stale' and stale['saved']['result'] is None
    p.update(revision=stale['revision'])
    assert client.post('/studio/api/suction', json=p).status_code == 422
    p.update(fingerprint=stale['context']['fingerprint'])
    assert client.post('/studio/api/suction', json=p).status_code == 422
    p.update(reviewed=True, losses=[])
    r = client.post('/studio/api/suction', json=p)
    assert r.status_code == 200, r.text
    assert r.json()['saved']['result']['balance']['available_m'] is None


def test_http_private_and_mutation_protection(client):
    ordinary(client)
    state = client.get('/studio/api/suction').json()
    p = payload(state['context'], revision=state['revision']).model_dump()
    assert client.post('/studio/api/suction', json=p, headers={'X-Zarya-Studio':'0'}).status_code == 403
    client.cookies.clear()
    assert client.get('/studio/api/suction').status_code == 404
    assert client.post('/studio/api/suction', json=p).status_code == 404


def test_numeric_boolean_rejected(common):
    p = payload(project_context(common, dependencies='test')).model_dump()
    p['balance']['pressure_bar'] = True
    with pytest.raises(ValidationError):
        StudioSuctionInput.model_validate(p)

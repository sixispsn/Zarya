"""Persistence and output are evidence, not a new pump selection algorithm."""
from copy import deepcopy
from dataclasses import asdict
import os

import pytest

from app.intake.pilot_objects import calculation_stamp, make_snapshot
from app.intake.project_builder import build_project
from app.intake.project_store import ProjectStore
from app.intake.yaml_io import dump_request, load_request
from app.pz.generator import generate_pump_selection_html, generate_pz_html
from app.pz.ios2_orchestrator import design_ios2
from app.pz import suction_check
from app.schemas.pump_suction import persisted_suction
from tests import test_studio_suction as fixtures
from tests import test_pilot_access as pilot_fixtures

client = fixtures.client
samara = fixtures.samara
common = fixtures.common
pilot = pilot_fixtures.pilot


def attach(project, **updates):
    context = suction_check.project_context(project)
    payload = fixtures.payload(context, **updates)
    project.suction_check = persisted_suction({'suction_check': {'inputs': payload.model_dump()}})
    return project.suction_check


def test_optional_and_no_self_invalidation(common):
    assert suction_check.review_suction(common) is None
    assert 'Проверка всасывания В1:' not in generate_pump_selection_html(common)
    attach(common)
    before = deepcopy(asdict(common))
    r = suction_check.review_suction(common)
    assert r['status'] == 'current' and r['result']['balance']['available_m'] == pytest.approx(7)
    assert r['result']['balance']['check_ok'] is False  # unrounded 6.999... < 7
    assert asdict(common) == before
    common.document.cipher = 'Переименование не меняет гидравлику'
    common.document.sheet_total = '99'
    assert suction_check.review_suction(common)['status'] == 'current'


@pytest.mark.parametrize('change', ['loss', 'axis', 'size', 'pump', 'catalogue'])
def test_stale_results_never_reach_output(common, monkeypatch, change):
    attach(common)
    if change == 'loss':
        common.source.h_vvod_m += 1
    elif change == 'axis':
        common.source.station_suction_elevation_m = -1
    elif change == 'size':
        common.v1_sections[0].length_m += 1
    elif change == 'pump':
        common.pumps.model = 'Другая модель'
    else:
        monkeypatch.setattr(suction_check, 'dependency_stamp', lambda: 'changed')
    r = suction_check.review_suction(common)
    assert r['status'] == 'stale' and r['result'] is None
    for render in (generate_pump_selection_html, generate_pz_html):
        html = render(common)
        assert 'Проверка устарела' in html
        assert 'suction-result' not in html
        assert 'Условие выполнено' not in html


def test_unsupported_or_corrupted_input_has_no_result(common):
    attach(common)
    common.pumps.required = False
    assert suction_check.review_suction(common)['status'] == 'invalid'
    assert 'Проверка не подтверждена' in generate_pump_selection_html(common)
    common.suction_check['result'] = {'check_ok': True}
    assert suction_check.review_suction(common)['result'] is None


def test_complete_failed_and_incomplete_output(common):
    data = attach(common)
    data['balance']['npshr_m'] = 6
    assert suction_check.review_suction(common)['result']['balance']['check_ok'] is True
    for render in (generate_pump_selection_html, generate_pz_html):
        html = render(common)
        assert 'Условие выполнено' in html
        assert 'не изменяются' in html
        assert 'Готовый тестовый результат всего пути' in html
    data['balance']['npshr_m'] = 8
    assert 'Условие не выполнено' in generate_pump_selection_html(common)
    data['losses'] = []
    html = generate_pump_selection_html(common)
    assert 'Проверка не завершена' in html and 'Нулевыми не приняты' in html
    assert 'Условие выполнено' not in html
    data['balance']['basis'] = '<script>unsafe</script>'
    assert '<script>unsafe</script>' not in generate_pump_selection_html(common)


def saved_request(client):
    fixtures.ordinary(client)
    state = client.get('/studio/api/suction').json()
    p = fixtures.payload(state['context'], revision=state['revision']).model_dump()
    p['balance']['npshr_m'] = 6
    saved = client.post('/studio/api/suction', json=p)
    assert saved.status_code == 200, saved.text
    handoff = client.post('/studio/api/handoff', json={'revision': saved.json()['revision']})
    assert handoff.status_code == 200, handoff.text
    project_id = handoff.json()['next_url'].rsplit('/', 1)[-1]
    return ProjectStore(os.environ['ZARYA_PROJECTS_DIR']).load(project_id), project_id


def test_studio_yaml_project_roundtrip_and_new_handoff(client, tmp_path):
    req, first_id = saved_request(client)
    saved = deepcopy(req.suction_check)
    assert saved and 'reviewed' not in saved and 'revision' not in saved and 'result' not in saved
    loaded = load_request(dump_request(req))
    assert loaded.suction_check == saved
    project = design_ios2(build_project(loaded), output_dir=str(tmp_path), render_documents=False).project
    r = suction_check.review_suction(project)
    assert r['status'] == 'current', r
    assert r['result']['balance']['check_ok'] is True
    assert 'Условие выполнено' in generate_pump_selection_html(project)
    assert req.suction_check == saved
    state = client.get('/studio/api/suction').json()
    payload = state['saved']['inputs']
    payload['revision'] = state['revision']
    payload['balance']['max_flow_m3h'] = 13
    response = client.post('/studio/api/suction', json=payload)
    assert response.status_code == 200, response.text
    r = client.post('/studio/api/handoff', json={'revision': response.json()['revision']})
    assert r.json()['next_url'].rsplit('/', 1)[-1] != first_id
    assert ProjectStore(os.environ['ZARYA_PROJECTS_DIR']).load(first_id).suction_check == saved


def test_old_yaml_and_fake_cached_result(client):
    req, _ = saved_request(client)
    req.suction_check = None
    assert 'suction_check:' not in dump_request(req)
    assert load_request(dump_request(req)).suction_check is None
    req.suction_check = {'check_ok': True}
    assert any('suction_check' in p for p in req.validate())
    with pytest.raises(ValueError):
        dump_request(req)


def test_pilot_stamp_and_document_invalidation(client, monkeypatch):
    from app.web.studio import documents_current, DOCUMENT_RENDER_VERSION, STUDIO_HANDOFF_VERSION
    saved_request(client)
    public = client.get('/studio/api/draft').json()
    from app.intake.studio_store import StudioStore
    draft = StudioStore(os.environ['ZARYA_STUDIO_DIR']).load(public['project_id'])
    stamp = calculation_stamp(draft)
    snapshot = make_snapshot(draft)
    assert snapshot['results']['state'] == 'current'
    assert snapshot['results']['project']['suction_check']['status'] == 'current'
    assert any(row['key'] == 'suction_check' for row in snapshot['inputs'])
    document = dict(stamp=stamp, render_version=DOCUMENT_RENDER_VERSION, handoff_version=STUDIO_HANDOFF_VERSION)
    assert documents_current(document, draft)
    draft['suction_check']['inputs']['revision'] += 10
    assert calculation_stamp(draft) == stamp
    draft['suction_check']['inputs']['balance']['max_flow_m3h'] = 14
    assert not documents_current(document, draft)
    assert make_snapshot(draft)['results']['project'] is None
    monkeypatch.setattr(suction_check, 'dependency_stamp', lambda: 'new-code')
    assert not documents_current(document, draft)


def test_full_editor_preserves_inputs_without_reconfirming(client, monkeypatch):
    import asyncio
    from app.web import wizard
    from tests.test_wizard import _request
    req, pid = saved_request(client)
    before = deepcopy(req.suction_check)
    monkeypatch.setattr(wizard, '_STORE', ProjectStore(os.environ['ZARYA_PROJECTS_DIR']))
    received = []
    monkeypatch.setattr(wizard, 'design_request_response', lambda request, data, pid: received.append(data))
    form = {'project_id': pid, 'floors': '3', 'apartments': str(req.apartments),
            'hws_type': req.hws_type}
    for i, consumer in enumerate(req.consumers, 1):
        form.update({f'consumer{i}_name': consumer.name, f'consumer{i}_code': consumer.code,
                     f'consumer{i}_count': str(consumer.count)})
    response = asyncio.run(wizard.wizard_design(_request(form)))
    assert len(received) == 1, getattr(response, 'context', {}).get('errors')
    assert received[0].suction_check == before


def test_suction_save_creates_opt_in_immutable_pilot_version(pilot):
    from tests.test_pilot_admin import accept
    _, users, _ = pilot
    alice = pilot_fixtures.client_for(users['alice'][1])
    alice.headers.update(pilot_fixtures.WRITE)
    accept(alice)
    original = fixtures.ordinary(alice)
    first = original['pilot_archive']
    assert first['state'] == 'saved'
    response = alice.get('/studio/api/suction')
    assert response.status_code == 200, response.text
    state = response.json()
    payload = fixtures.payload(state['context'], revision=state['revision']).model_dump()
    result = alice.post('/studio/api/suction', json=payload)
    assert result.status_code == 200, result.text
    saved = alice.get('/studio/api/draft').json()['pilot_archive']
    assert saved['state'] == 'saved' and saved['version'] > first['version']
    assert saved['object_id'] == first['object_id']
    assert alice.get(saved['url']).status_code == 200
    assert alice.get(first['url']).status_code == 200
    bob = pilot_fixtures.client_for(users['bob'][1])
    accept(bob)
    headers = {**pilot_fixtures.WRITE, 'X-Zarya-Draft': original['project_id']}
    # The selected-draft guard rejects another user's ID before looking up files.
    assert bob.get('/studio/api/suction', headers=headers).status_code == 409
    assert bob.post('/studio/api/suction', headers=headers, json=payload).status_code == 409
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app, base_url=pilot_fixtures.ORIGIN).get('/studio/api/suction').status_code == 401
    assert alice.post('/studio/api/suction', headers={'Origin': 'https://foreign.invalid'},
                      json=payload).status_code == 403

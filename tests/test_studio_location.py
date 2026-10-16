"""Reference map must not become engineering input or a cross-user proxy."""
from copy import deepcopy
import sqlite3
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest

from app.intake.site_location import Geography, GeographyUnavailable, map_config
from app.intake.studio_intake import accepted_values
from app.intake.studio_store import StudioStore
from app.main import app
from tests import test_pilot_access as pilot_tests, test_studio as studio_tests

pilot = pilot_tests.pilot
client = studio_tests.client
client_for, draft, WRITE, ORIGIN = pilot_tests.client_for, pilot_tests.draft, pilot_tests.WRITE, pilot_tests.ORIGIN
residential_project = studio_tests.residential_project

POINT = {"latitude": 55.75, "longitude": 37.62, "label": "Москва", "source": "manual"}


def put(client, state, point=POINT, **extra):
    return client.patch('/studio/api/location', headers={**WRITE, 'X-Zarya-Draft': state['project_id']},
                        json={"revision": state['revision'], "location": point, **extra})


def test_private_location_revision_and_preserved_results(pilot, monkeypatch):
    access, users, root = pilot
    alice = client_for(users['alice'][1])
    state = draft(alice)
    # A deliberately poisoned optional map never participates in input selection.
    store = StudioStore(root / 'studio' / '_users' / users['alice'][0])
    original = store.load(state['project_id'])
    original['preview'] = {'id': 'c' * 32, 'state': 'ready', 'documents': []}
    original['package'] = {'state': 'blocked', 'sentinel': 'keep'}
    store._write(store.folder(state['project_id']), original)
    monkeypatch.setattr(Geography, 'fetch', lambda *a: pytest.fail('No consent: no external calls'))
    result = put(alice, state)
    assert result.status_code == 200, result.text
    saved = store.load(state['project_id'])
    assert saved['revision'] == original['revision'] + 1
    assert saved['site_location']['elevation']['metres'] is None
    assert saved['site_location']['reference_only'] is True
    assert {k: v for k, v in saved.items() if k not in {'revision', 'site_location'}} == {k: v for k, v in original.items() if k != 'revision'}


def test_calc_and_accepted_inputs_unchanged(client, monkeypatch):
    state = residential_project(client)
    state = client.post('/studio/api/calculate', json={'revision': state['revision']}).json()
    monkeypatch.setattr(Geography, 'elevation', lambda *a: {'status': 'available', 'metres': 987., 'source': 'SRTM', 'reference_only': True})
    result = client.patch('/studio/api/location', json={'revision': state['revision'], 'location': POINT,
                          'external_consent': True, 'lookup_elevation': True})
    assert result.status_code == 200, result.text
    saved = client.get('/studio/api/draft').json()
    assert saved['site_location']['elevation']['metres'] == 987
    for key in ('fields', 'calculation', 'project_calculation', 'can_calculate', 'head_missing', 'storm_missing', 'next_steps'):
        assert saved[key] == state[key], key
    again = client.post('/studio/api/calculate', json={'revision': saved['revision']}).json()
    assert again['calculation'] == state['calculation']
    assert again['project_calculation'] == state['project_calculation']
    assert again['site_location'] == saved['site_location']


def test_user_and_object_isolation_and_stale_tab(pilot):
    access, users, root = pilot
    alice, bob = client_for(users['alice'][1]), client_for(users['bob'][1])
    state = draft(alice)
    draft(bob)
    assert put(alice, state).status_code == 200
    assert bob.get('/studio/api/draft').json()['site_location'] is None
    assert put(bob, state).status_code == 409
    assert put(alice, state).status_code == 409
    newer = alice.post('/studio/api/projects', json={'request_id': uuid.uuid4().hex, 'title': 'Второй'}, headers=WRITE)
    assert newer.status_code == 200, newer.text
    assert alice.get('/studio/api/draft').json()['site_location'] is None
    assert put(alice, state).status_code == 409
    assert client_for(users['alice'][1]).get('/studio/api/draft').json()['site_location'] is None


@pytest.mark.parametrize('point', [{**POINT, 'latitude': True}, {**POINT, 'longitude': 181}, {**POINT, 'latitude': -91}, {**POINT, 'elevation': 100}, {**POINT, 'source': 'survey'}])
def test_bad_coordinates_and_spoofed_elevation_rejected(pilot, point):
    alice = client_for(pilot[1]['alice'][1])
    state = draft(alice)
    assert put(alice, state, point).status_code == 422
    assert alice.get('/studio/api/draft').json()['revision'] == state['revision']


def test_elevation_requires_consent_and_failure_saves_point(pilot, monkeypatch):
    alice = client_for(pilot[1]['alice'][1])
    state = draft(alice)
    assert put(alice, state, lookup_elevation=True).status_code == 422
    def unavailable(*args):
        raise GeographyUnavailable('Provider unavailable')
    monkeypatch.setattr(Geography, 'elevation', unavailable)
    result = put(alice, state, lookup_elevation=True, external_consent=True)
    assert result.status_code == 200
    state |= result.json()
    assert state['site_location']['elevation']['metres'] is None
    assert state['site_location']['elevation']['status'] == 'unavailable'
    assert put(alice, state, None).json()['site_location'] is None


def test_no_elevation_or_geology_in_handoff():
    from app.intake.studio_intake import answer_field
    draft = {'answers': {}, 'revision': 0, 'documents': []}
    for key, value in {'residents': 20, 'floors': 2, 'consumer_code': 'residential_full_bath', 'hws_type': 'central'}.items():
        answer_field(draft, key, value)
    before = deepcopy(accepted_values(draft))
    draft['site_location'] = {**POINT, 'elevation': {'metres': 500}, 'permafrost': True, 'h_geom_m': 42, 'storm_city': 'Москва'}
    assert accepted_values(draft) == before


def test_auth_and_search_consent(pilot, monkeypatch):
    anon = TestClient(app, base_url=ORIGIN)
    assert anon.get('/studio/api/location/config').status_code == 401
    assert anon.post('/studio/api/location/search', headers=WRITE, json={'query': 'Москва', 'external_consent': True}).status_code == 401
    alice = client_for(pilot[1]['alice'][1])
    draft(alice)
    monkeypatch.setattr(Geography, 'search', lambda *a: [POINT])
    assert alice.post('/studio/api/location/search', headers=WRITE, json={'query': 'Москва'}).status_code == 422
    assert alice.post('/studio/api/location/search', headers={**WRITE, 'Origin': 'https://other.test'}, json={'query': 'Москва', 'external_consent': True}).status_code == 403
    assert alice.post('/studio/api/location/search', headers=WRITE, json={'query': 'Москва', 'external_consent': True}).json()['results'] == [POINT]


def test_north_null_zero_and_invalid_heights_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv('ZARYA_GEO_DIR', str(tmp_path))
    geo = Geography()
    monkeypatch.setattr(geo, 'fetch', lambda *a: pytest.fail('No SRTM coverage: no request'))
    assert geo.elevation(65., 40.)['status'] == 'no_coverage'
    for number in [None, 0, 148.6, True, float('nan'), 10000]:
        monkeypatch.setattr(geo, 'fetch', lambda *a, n=number: {'status': 'OK', 'results': [{'dataset': 'srtm30m', 'elevation': n}]})
        if number is True or (number is not None and (number != number or number > 9000)):
            with pytest.raises(GeographyUnavailable):
                geo.elevation(55., 37.)
        else:
            result = geo.elevation(55., 37.)
            assert result['metres'] == number
            assert result['status'] == ('available' if number is not None else 'no_coverage')


def test_cache_limits_timeout_and_switchable_provider(tmp_path, monkeypatch):
    from app.intake import site_location as module
    monkeypatch.setenv('ZARYA_GEO_DIR', str(tmp_path))
    real_client = httpx.Client
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers['user-agent'].startswith('Zarya/')
        return httpx.Response(200, json={'features': []})
    monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    geo = Geography()
    assert geo.search('Москва') == []
    assert Geography().search('Москва') == []
    assert len(requests) == 1
    with pytest.raises(GeographyUnavailable):
        Geography().search('Самара')
    with sqlite3.connect(geo.path) as db:
        db.execute('UPDATE quota SET next_at=0, used=500')
    with pytest.raises(GeographyUnavailable):
        geo.search('Самара')
    assert geo.path.stat().st_mode & 0o777 == 0o600
    assert 'Москва' not in geo.path.read_text(errors='ignore')  # hashed search key
    monkeypatch.setenv('ZARYA_GEO_ENABLED', '0')
    with pytest.raises(GeographyUnavailable):
        map_config()
    with pytest.raises(GeographyUnavailable):
        geo.search('Москва')


def test_lookup_does_not_overwrite_concurrent_edit(pilot, monkeypatch):
    access, users, root = pilot
    alice = client_for(users['alice'][1])
    state = draft(alice)
    store = StudioStore(root / 'studio' / '_users' / users['alice'][0])
    def concurrent(*args):
        with store.edit(state['project_id'], state['revision']) as updated:
            updated['concurrent_marker'] = 'keep'
        return {'status': 'available', 'metres': 140.}
    monkeypatch.setattr(Geography, 'elevation', concurrent)
    result = put(alice, state, lookup_elevation=True, external_consent=True)
    assert result.status_code == 409
    saved = store.load(state['project_id'])
    assert saved.get('site_location') is None and saved['concurrent_marker'] == 'keep'


def test_provider_timeout_is_bounded_and_not_cached(tmp_path, monkeypatch):
    from app.intake import site_location as module
    monkeypatch.setenv('ZARYA_GEO_DIR', str(tmp_path))
    real_client = httpx.Client
    def handle(request):
        raise httpx.ReadTimeout('timeout', request=request)
    monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    geo = Geography()
    with pytest.raises(GeographyUnavailable):
        geo.search('Москва')
    with sqlite3.connect(geo.path) as db:
        assert db.execute('SELECT COUNT(*) FROM cache').fetchone()[0] == 0


def test_search_output_is_small_and_never_treated_as_markup(tmp_path, monkeypatch):
    monkeypatch.setenv('ZARYA_GEO_DIR', str(tmp_path))
    geo = Geography()
    monkeypatch.setattr(geo, 'fetch', lambda *a: {'features': [
        {'geometry': {'coordinates': [37., 55.]}, 'properties': {'name': '<script>no</script>', 'city': 'Москва'}},
        {'geometry': {'coordinates': [999, 999]}, 'properties': {}},
    ]})
    assert geo.search('Москва') == [{'latitude': 55., 'longitude': 37., 'label': '<script>no</script>, Москва', 'source': 'search'}]

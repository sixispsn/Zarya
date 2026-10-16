"""Catalogue release smoke: isolated writes; production owner draft read-only."""
import os
from pathlib import Path
import re

import httpx


def check_interface(client):
    page = client.get('/studio?view=project')
    assert page.status_code == 200
    assert '/static/studio.js?v=27' in page.text
    assert '/static/studio.css?v=19' in page.text
    js = client.get('/static/studio.js?v=27').text
    assert "vu_leak_monitoring:'Нет'" in js
    assert 'equipmentCards' in js
    state = client.get('/studio/api/draft').json()
    for key in ('leak_monitoring', 'tamper_monitoring', 'valve_feedback', 'magnetic_filter'):
        options = state['options']['vu_' + key]
        assert next(r['label'] for r in options if r['value'] == 'requested') == 'Да — подобрать оборудование'
        assert all('рассмотр' not in r['label'].lower() for r in options)
    assert 'saures_nbiot_point' in state['metering_catalogue']['choices']['vu_leak_monitoring']
    return state


def main():
    live = os.environ.get('ZARYA_EXTRAS_LIVE') == '1'
    if live:
        keys = set(re.findall(r'zarya_[A-Za-z0-9_-]{43}', Path(os.environ['ZARYA_OWNER_KEY_FILE']).read_text()))
        assert len(keys) == 1
        key = keys.pop()
        base = 'https://zaryaproekt.ru'
    else:
        assert os.environ.get('ZARYA_DEPLOY_SMOKE') == '1'
        assert os.environ.get('ZARYA_PROJECTS_DIR') == '/tmp/zarya-smoke/projects'
        from app.intake.pilot_access import AccessStore
        _, key = AccessStore().issue('Extras isolated smoke', days=1)
        base = 'http://127.0.0.1:8000'
    with httpx.Client(base_url=base, timeout=90, headers={'Origin': base, 'X-Zarya-Access':'1', 'X-Zarya-Studio':'1'}) as client:
        assert client.get('/studio/api/draft').status_code == 401
        login = client.post('/access/login', json={'key':key, 'remember_device':True})
        assert login.status_code == 200
        if live:
            assert all(s in login.headers['set-cookie'] for s in ('Secure','HttpOnly','SameSite=strict','Max-Age='))
        try:
            if not live:
                assert client.post('/studio/api/draft').status_code == 200
            before = client.get('/studio/api/draft').json()
            check_interface(client)
            if live:
                assert client.get('/access/admin').status_code == 200
                assert client.get('/studio/api/location/config').status_code == 200
                assert client.get('/studio/api/draft').json() == before
                assert client.post('/studio/api/draft', headers={'Origin':'https://invalid.example'}).status_code == 403
            else:
                client.headers['X-Zarya-Draft'] = before['project_id']
                answers = dict(residents=20, apartments=8, floors=2, consumer_code='residential_full_bath',
                    hws_type='central', building_height_m=6.6, fire_height_m=4.8, guaranteed_head_m=5,
                    h_geom_m=6, hws_heater_in_scope='no', roof_type='flat_non_accessible',
                    storm_city='moscow', storm_roof_area_m2=252, storm_walls_area_m2=0,
                    floor_height_m=3.3, basement_kind='basement', basement_floor_m=-3.1,
                    section_drainage='internal')
                r = client.post('/studio/api/calculate', json={'revision':before['revision'], 'answers':answers})
                assert r.status_code == 200
                state = r.json()
                baseline = state['project_calculation']
                extras = dict(vu_leak_monitoring='saures_nbiot_point', vu_telemetry='saures_r7')
                r = client.post('/studio/api/calculate', json={'revision':state['revision'], 'answers':extras})
                assert r.status_code == 200
                result = r.json()['project_calculation']
                for k in ('flows','meters','head','pumps','fire','storm'):
                    assert result[k] == baseline[k], k
                items = result['metering_equipment']['items']
                assert {p['id'] for p in items} == {'saures-r7-din','gidrolock-wsp-plus'}
                assert all(p['qty'] == 1 for p in items)
                state = client.get('/studio/api/draft').json()
                values = {f['key']:f['value'] for f in state['fields']}
                assert all(values[k] == v for k,v in extras.items())
        finally:
            assert client.post('/access/logout').status_code == 303
        assert client.get('/studio/api/draft').status_code == 401
    print('PASS: catalogue/choices/assets, private login, unchanged hydraulics or production draft, logout; live=' + str(live))


if __name__ == '__main__':
    main()

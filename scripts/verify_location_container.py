"""Disposable server smoke; real user drafts and keys are never accessed."""
import os
import time

import httpx

from app.intake.pilot_access import AccessStore
from app.intake.site_location import Geography


def main():
    assert os.environ.get("ZARYA_DEPLOY_SMOKE") == "1"
    assert os.environ.get("ZARYA_PILOT_DIR") == "/tmp/zarya-smoke/projects/_pilot"
    base = "http://127.0.0.1:8000"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(base + "/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    access = AccessStore()
    _, key = access.issue("Location smoke")
    with httpx.Client(base_url=base, timeout=30, headers={"Origin": base, "X-Zarya-Access": "1", "X-Zarya-Studio": "1"}) as client:
        assert client.get('/studio/api/location/config').status_code == 401
        assert client.post('/access/login', json={'key': key}).status_code == 200
        state = client.post('/studio/api/draft').json()
        client.headers['X-Zarya-Draft'] = state['project_id']
        assert 'site-location-dialog' in client.get('/studio').text
        for asset in ('studio_location.js', 'studio_location.css', 'vendor/leaflet/leaflet.js', 'vendor/leaflet/leaflet.css'):
            assert client.get('/static/' + asset).status_code == 200
        assert client.get('/studio/api/location/config').json()['tiles'] == 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
        response = client.patch('/studio/api/location', json={'revision': state['revision'],
            'location': {'latitude': 55.75, 'longitude': 37.62, 'label': 'Synthetic smoke', 'source': 'manual'}})
        assert response.status_code == 200, response.status_code
        saved = client.get('/studio/api/draft').json()
        assert saved['fields'] == state['fields'] and saved['calculation'] == state['calculation']
        assert saved['site_location']['latitude'] == 55.75
        assert client.post('/access/logout').status_code == 303
        assert client.get('/studio/api/location/config').status_code == 401
    if os.environ.get('ZARYA_GEO_LIVE_SMOKE') == '1':
        # One deliberately public city query / elevation point; never project data.
        geo = Geography()
        assert geo.search('Москва')
        assert geo.elevation(55.75, 37.62)['status'] == 'available'
        print('PASS: both reference services reachable from server (public test point only).')
    print('PASS: private map API, saved point, unchanged engineering inputs, local assets, logout.')


if __name__ == '__main__':
    main()

"""Read-only production map verification, except one isolated login/logout."""
import os
from pathlib import Path
import re

import httpx


def main():
    secret = Path(os.environ['ZARYA_OWNER_KEY_FILE']).read_text()
    keys = re.findall(r'zarya_[A-Za-z0-9_-]{43}', secret)
    if len(set(keys)) != 1:
        raise SystemExit('Owner key format not recognized; no request sent.')
    base = 'https://zaryaproekt.ru'
    with httpx.Client(base_url=base, timeout=30, headers={'Origin': base, 'X-Zarya-Access': '1'}) as client:
        assert client.get('/studio/api/location/config').status_code == 401
        result = client.post('/access/login', json={'key': keys[0]})
        assert result.status_code == 200, 'Owner login failed'
        cookie = result.headers.get('set-cookie', '')
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        try:
            before = client.get('/studio/api/draft').json()
            page = client.get('/studio?view=project')
            assert page.status_code == 200 and 'site-location-dialog' in page.text
            assert '/static/studio.js?v=24' in page.text
            for asset in ('studio_location.js', 'studio_location.css', 'vendor/leaflet/leaflet.js', 'vendor/leaflet/leaflet.css'):
                assert client.get('/static/' + asset).status_code == 200
            config = client.get('/studio/api/location/config')
            assert config.status_code == 200
            assert config.json()['tiles'] == 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
            assert client.get('/studio/api/draft').json() == before
            assert client.post('/studio/api/location/search', json={'query': 'Москва', 'external_consent': True}, headers={'Origin': 'https://invalid.example'}).status_code == 403
        finally:
            assert client.post('/access/logout').status_code == 303
        assert client.get('/studio/api/location/config').status_code == 401
    print('PASS: external HTTPS, personal login, map assets/config, unchanged draft, CSRF rejection, logout. No search/location write on production.')


if __name__ == '__main__':
    main()

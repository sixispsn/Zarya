"""HTTP acceptance for the scoped VU release; disposable accounts only.

No invitation secrets in logs. Existing objects are never opened. All issued
keys are revoked even on failure. The first run must use an isolated container.
"""
import argparse
from io import BytesIO
import json
import os
import time
from pathlib import Path

import httpx
from pypdf import PdfReader

RELEASE = '20261014-metering-nodes'
INPUTS = dict(residents=200, apartments=80, consumer_code='residential_full_bath',
    floors=10, building_height_m=33, fire_height_m=31, fire_corridor_length_m=10,
    fire_topology='separate', hws_type='central', guaranteed_head_m=30, h_geom_m=33,
    pressure_loss_mode='ready', h_il_m=3, h_vvod_m=1, t3_loss_mode='ready',
    h_il_hot_m=4, hws_heater_in_scope='no', vu_orientation='vertical_up',
    vu_hot_orientation='horizontal_dial_up', vu_filter_layout='valtec_vt192_vtr090',
    vu_drawing_scale='10')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert os.environ['ZARYA_BUILD_COMMIT'] == RELEASE
    assert os.environ['ZARYA_PILOT_ENABLED'] == '1'
    assert os.environ['ZARYA_PROJECTS_DIR'] == ('/data/projects' if args.live else '/tmp/zarya-smoke/projects')
    if not args.live: assert os.environ['ZARYA_DEPLOY_SMOKE'] == '1'
    base = 'https://zaryaproekt.ru' if args.live else 'http://127.0.0.1:8000'
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get(base + '/health', timeout=2).status_code == 200: break
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline: raise RuntimeError('Server did not become ready')
        time.sleep(.2)
    args.out.mkdir(parents=True, exist_ok=False, mode=0o700)
    from app.intake.pilot_access import AccessStore
    store = AccessStore()
    before = {u['id']: u for u in store.list_users()}
    issued = []
    report = dict(release=RELEASE, live=args.live, pages={})
    try:
        for name in ('A', 'B'):
            issued.append(store.issue('Автопроверка ВУ 14.10 · временный ' + name, days=1))
        headers = {'Origin': base, 'X-Zarya-Studio': '1', 'X-Zarya-Access': '1'}
        with httpx.Client(base_url=base, headers=headers, timeout=240) as a, \
                httpx.Client(base_url=base, headers=headers, timeout=30) as b:
            assert a.get('/health').status_code == 200
            for client, (_, key) in zip((a, b), issued):
                assert client.get('/studio/api/draft').status_code == 401
                login = client.post('/access/login', json={'key':key, 'remember_device':True})
                assert login.status_code == 200
                assert 'HttpOnly' in login.headers['set-cookie']
                assert 'SameSite=strict' in login.headers['set-cookie']
                if args.live: assert 'Secure' in login.headers['set-cookie']
                assert client.get('/access/admin').status_code == 403
                assert client.get('/wizard/projects').status_code == 403
            def call(method, path, **kwargs):
                response = a.request(method, path, **kwargs)
                assert response.status_code == 200, (path, response.status_code)
                return response
            page = call('GET', '/studio').text
            assert all(v in page for v in ('30-metering-nodes', '21-metering-nodes', '50-metering-nodes'))
            assert a.post('/studio/api/draft', headers={'Origin':'https://invalid.example'}).status_code == 403
            state = call('POST', '/studio/api/draft').json()
            a.headers['X-Zarya-Draft'] = state['project_id']
            state = call('POST', '/studio/api/calculate', json={'revision':state['revision'], 'answers':INPUTS}).json()
            calc = state['project_calculation']
            layout = calc['metering_layout']
            assert layout['drawing_available'] and layout['orientation'] == 'vertical_up'
            assert {n['node']:n['orientation'] for n in layout['nodes']} == {
                'cold':'vertical_up', 'hot':'horizontal_dial_up'}
            assert not layout['installation_ready'] and not calc['can_release']
            assert layout['filter_layout'] == 'valtec_vt192_vtr090'
            assert layout['connections']['incompatible'] == 0
            assert calc['meters'][0]['dn'] == 25
            assert calc['meters'][0]['q_min_passport_m3h'] == .14
            unchanged = {k:calc[k] for k in ('flows','head','hydraulics','hot_hydraulics','pumps','fire')}
            state = call('POST', '/studio/api/preview', json={'revision':state['revision']}).json()
            urls = []
            for kind in ('metering_scheme_pdf', 'spec_pdf', 'pz_pdf'):
                doc = next(d for d in state['preview']['documents'] if d['kind'] == kind)
                url = f'/studio/api/preview/{state["preview"]["id"]}/files/{doc["name"]}'
                urls.append(url)
                response = call('GET', url)
                assert b.get(url).status_code == 404
                pdf = PdfReader(BytesIO(response.content))
                assert pdf.pages
                report['pages'][kind] = len(pdf.pages)
                if kind == 'metering_scheme_pdf':
                    assert pdf.outline
                    assert all(abs(float(p.mediabox.width)-420/25.4*72)<.1 for p in pdf.pages)
                    assert all(abs(float(p.mediabox.height)-297/25.4*72)<.1 for p in pdf.pages)
                (args.out / (kind + '.pdf')).write_bytes(response.content)
            # Current answers persist; changed orientation invalidates the old PDF.
            restored = call('GET', '/studio/api/draft').json()
            assert next(f for f in restored['fields'] if f['key'] == 'vu_hot_orientation')['value'] == 'horizontal_dial_up'
            state = call('POST', '/studio/api/calculate', json={'revision':state['revision'],
                'answers':{'vu_orientation':'vertical_down'}}).json()
            assert state['preview'] is None and all(a.get(url).status_code == 404 for url in urls)
            assert state['project_calculation']['metering_layout']['drawing_available']
            assert all(state['project_calculation'][k] == v for k,v in unchanged.items())
            # Origin restriction is explicit and must not silently retain VALTEC.
            state = call('POST', '/studio/api/calculate', json={'revision':state['revision'],
                'answers':{'russian_equipment_only':'yes'}}).json()
            assert not state['project_calculation']['metering_layout']['drawing_available']
            assert not state['project_calculation']['can_release']
            state = call('POST', '/studio/api/package', json={'revision':state['revision']}).json()
            assert state['package']['state'] == 'blocked'
            for client in (a,b):
                assert client.post('/access/logout').status_code == 303
                assert client.get('/studio/api/draft').status_code == 401
        report.update(status='PASS', private_pdfs=True, stale_links_revoked=True,
                      orientation_preserves_hydraulics=True, origin_guard=True)
    finally:
        for uid, _ in issued: store.revoke(uid)
        after = {u['id']: u for u in store.list_users()}
        assert all(after[k] == value for k,value in before.items())
    report['temporary_users_revoked'] = True
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()

"""Meter release via ordinary HTTP and disposable accounts; no owner projects."""
import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import time

import httpx
from pypdf import PdfReader, PdfWriter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('answers', type=Path)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    assert os.environ['ZARYA_BUILD_COMMIT'] == 'meter-products-20261005'
    assert os.environ['ZARYA_PILOT_ENABLED'] == '1'
    assert os.environ['ZARYA_PROJECTS_DIR'] == ('/data/projects' if args.live else '/tmp/zarya-smoke/projects')
    if not args.live:
        assert os.environ['ZARYA_DEPLOY_SMOKE'] == '1'
    base = 'https://zaryaproekt.ru' if args.live else 'http://127.0.0.1:8000'
    for _ in range(100):
        try:
            if httpx.get(base + '/health', timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(.2)
    else:
        raise AssertionError('Server unavailable')
    from app.intake.pilot_access import AccessStore
    from app.intake.studio_intake import FIELD_MAP
    answers = {k: v for k, v in json.loads(args.answers.read_text()).items() if k in FIELD_MAP}
    access = AccessStore()
    before = {u['id']: u for u in access.list_users()}
    issued = []
    out = Path('/tmp/zarya-meter-qa'); out.mkdir(mode=0o700, exist_ok=True)
    summary = {}
    try:
        for name in ('A', 'B'):
            issued.append(access.issue('Автопроверка водомеров — временный доступ ' + name, days=1))
        headers = {'Origin': base, 'X-Zarya-Studio': '1', 'X-Zarya-Access': '1'}
        with httpx.Client(base_url=base, headers=headers, timeout=240) as a, httpx.Client(base_url=base, headers=headers, timeout=30) as b:
            for client, (_, key) in zip((a, b), issued):
                assert client.get('/studio/api/draft').status_code == 401
                r = client.post('/access/login', json={'key': key, 'remember_device': True})
                assert r.status_code == 200
                assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
                if args.live:
                    assert 'Secure' in r.headers['set-cookie']
                assert client.get('/wizard/projects').status_code == 403
                assert client.get('/access/admin').status_code == 403
            def call(method, url, **kwargs):
                r = a.request(method, url, **kwargs)
                assert r.status_code == 200, (url, r.status_code, r.text[:150])
                return r
            page = call('GET', '/studio').text
            assert 'studio.js?v=39-meter-loss-basis' in page and 'studio.css?v=25-meter-products' in page
            assert 'Модели и паспорта' in call('GET', '/static/studio.js?v=39-meter-loss-basis').text
            assert a.post('/studio/api/draft', headers={'Origin': 'https://invalid.example'}).status_code == 403
            state = call('POST', '/studio/api/draft').json()
            a.headers['X-Zarya-Draft'] = state['project_id']
            state = call('POST', '/studio/api/calculate', json={'revision': state['revision'], 'answers': answers}).json()
            calc = state['project_calculation']; meters = calc['meters']
            assert [(r['dn'], r['h_a']) for r in meters] == [(50, 1.451), (32, 3.479), (32, 4.703)]
            assert [r['q_min_passport_m3h'] for r in meters] == [.45, .12, .12]
            assert all(r['ok_v'] is None and r['q_min_hourly_m3h'] is None for r in meters)
            assert [r['product']['hydraulic_evidence']['at_flow_m3h'] for r in meters] == [30, 12, 12]
            assert all(r['product']['hydraulic_evidence']['exact_loss_m'] is None for r in meters)
            pressure = calc['fire_station']['pressure_review']
            assert pressure['minimum_pass_count'] == pressure['scenario_count'] == 45
            assert not calc['can_release']
            (out / 'calculation.json').write_text(json.dumps(calc, ensure_ascii=False, indent=2))
            state = call('POST', '/studio/api/preview', json={'revision': state['revision']}).json()
            docs = {d['kind']: d for d in state['preview']['documents']}
            urls = []; pages = {}; writer = PdfWriter()
            parts = [('pz_pdf', 'ИОС2. Пояснительная записка и расчёты'),
                     ('scheme_pdf', 'ИОС2. Принципиальная схема В1 / Т3 / Т4'),
                     ('metering_scheme_pdf', 'ИОС2. Вводы и водомерные узлы'),
                     ('pump_zone_scheme_pdf', 'ИОС2. Насосы, зоны и ГВС'),
                     ('fire_station_scheme_pdf', 'ИОС2. В2: насосная, стояки и узлы'),
                     ('spec_pdf', 'ИОС2. Спецификация')]
            for kind, title in parts:
                d = docs[kind]
                url = f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}'
                urls.append(url); response = call('GET', url)
                assert b.get(url).status_code == 404
                pdf = PdfReader(BytesIO(response.content))
                text = ' '.join(p.extract_text() or '' for p in pdf.pages)
                normalized = ''.join(text.split())
                if kind in ('pz_pdf', 'metering_scheme_pdf', 'spec_pdf'):
                    assert 'ВСКМ90ДГ' in normalized
                if kind in ('pz_pdf', 'metering_scheme_pdf'):
                    assert 'Δp≤0,1МПа' in normalized and '12.15' in normalized
                if kind == 'pz_pdf':
                    assert 'Расчётный расход хозяйственно-бытовых стоков' not in text
                (out / d['name']).write_bytes(response.content)
                writer.append(pdf, outline_item=title, import_outline=True)
                pages[kind] = len(pdf.pages)
            with (out / 'ИОС2_проверка_сайта.pdf').open('wb') as stream:
                writer.write(stream)
            # Linux font metrics move the final V1 summary onto one extra page.
            # The 46-page server reference was rendered and inspected separately
            # from the 45-page macOS reference; hydraulic values stay identical.
            assert len(writer.pages) == 46
            state = call('POST', '/studio/api/package', json={'revision': state['revision']}).json()
            assert state['package']['state'] == 'blocked'
            state = call('PATCH', '/studio/api/answer', json={'revision': state['revision'], 'field': 'fire_station_model', 'value': None}).json()
            assert all(a.get(url).status_code == 404 for url in urls)
            if not args.live:
                state = call('POST', '/studio/api/study', json={'revision': state['revision'], 'kind': 'samara'}).json()
                a.headers['X-Zarya-Draft'] = state['project_id']
                state = call('POST', '/studio/api/preview', json={'revision': state['revision']}).json()
                d = next(d for d in state['preview']['documents'] if d['kind'] == 'vk_package_pdf')
                pdf = PdfReader(BytesIO(call('GET', f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}').content))
                assert len(pdf.pages) == 52
                summary['frozen_vk_pages'] = len(pdf.pages)
            for client in (a, b):
                assert client.post('/access/logout').status_code == 303
                assert client.get('/studio/api/draft').status_code == 401
            summary.update(status='PASS', live=args.live, pages=pages, ios2_pages=46,
                           scenarios=45, meter_losses_unchanged=True, private_pdfs=True, revocation=True)
    finally:
        for uid, _ in issued:
            access.revoke(uid)
        after = {u['id']: u for u in access.list_users()}
        assert all(after[k] == value for k, value in before.items()), 'Existing participants changed'
    summary['temporary_users_revoked'] = True
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

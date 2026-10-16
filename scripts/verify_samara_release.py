"""Real authenticated HTTP/PDF checks, only in a disposable server container."""
from io import BytesIO
import json
import math
import os
import re
import time
from pathlib import Path

import httpx
from pypdf import PdfReader


def main():
    assert os.environ.get('ZARYA_DEPLOY_SMOKE') == '1'
    assert os.environ.get('ZARYA_PROJECTS_DIR') == '/tmp/zarya-smoke/projects'
    from app.intake.pilot_access import AccessStore
    from app.intake.samara_study import load_case
    access = AccessStore()
    aid, akey = access.issue('Samara release QA A', days=45)
    bid, bkey = access.issue('Samara release QA B', days=45)
    base = 'http://127.0.0.1:8000'
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get(base+'/health', timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        assert time.monotonic() < deadline, 'Isolated server did not start'
        time.sleep(.2)
    headers = {'Origin':base, 'X-Zarya-Studio':'1', 'X-Zarya-Access':'1'}
    qa = Path('/tmp/zarya-smoke/qa')
    qa.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=240) as a, httpx.Client(base_url=base, headers=headers, timeout=30) as b:
            for client, key in ((a,akey),(b,bkey)):
                assert client.get('/studio/api/draft').status_code == 401
                login = client.post('/access/login', json={'key':key,'remember_device':True})
                assert login.status_code == 200
                age = int(re.search(r'Max-Age=(\d+)',login.headers['set-cookie']).group(1))
                assert 2591995 <= age <= 2592000
            def call(method, url, **kwargs):
                r = a.request(method,url,**kwargs)
                assert r.status_code == 200, (url,r.status_code,r.text[:300])
                return r
            page = call('GET','/studio').text
            assert 'data-kind="samara"' in page and 'studio.js?v=34-samara' in page
            assert 'studio_configurator.js?v=7' in page # unrelated local UI not published
            original = call('POST','/studio/api/draft').json()
            original_id = original['project_id']
            a.headers['X-Zarya-Draft'] = original_id
            state = call('POST','/studio/api/study',json={'kind':'samara','revision':original['revision']}).json()
            a.headers['X-Zarya-Draft'] = state['project_id']
            calc = state['project_calculation']
            assert calc.get('ios2') and calc['can_preview'] and not calc['can_release'], calc
            station = calc['fire_station']
            assert station['model'] == 'CNP CDM32-3'
            assert station['duty_units'] == station['reserve_units'] == 1
            assert math.isclose(station['q_min_m3h'],18.978962,abs_tol=1e-5)
            assert math.isclose(station['head_m'],48.923882,abs_tol=1e-5)
            changed = a.post('/studio/api/calculate',json={'revision':state['revision'],'answers':{'residents':351}})
            assert changed.status_code == 422
            state = call('GET','/studio/api/draft').json()
            state = call('POST','/studio/api/preview',json={'revision':state['revision']}).json()
            preview = state['preview']
            docs = {d['kind']:d for d in preview['documents']}
            assert len(docs) == 8 and len({d['model_hash'] for d in docs.values()}) == 1
            readers = {}
            urls = []
            for kind, doc in docs.items():
                url = f'/studio/api/preview/{preview["id"]}/files/{doc["name"]}'
                urls.append(url)
                r = call('GET',url)
                assert r.headers['x-zarya-preview'] == 'true' and r.content.startswith(b'%PDF')
                assert b.get(url).status_code == 404
                (qa/doc['name']).write_bytes(r.content)
                readers[kind] = PdfReader(BytesIO(r.content))
            combined = readers['ios2_package_pdf']
            text = '\n'.join(p.extract_text() for p in combined.pages)
            assert len(combined.pages) == 37, len(combined.pages)
            assert len([b for b in combined.outline if not isinstance(b,list)]) == 6
            for phrase in ('CDM32-3','3,263','48,924','512/512','Автоматизация','Диафрагма'):
                assert phrase in text, phrase
            assert 'Hydro MX-A CR15-9' not in text and 'PFFS 2 CDM15-5' not in text
            assert len(readers['fire_station_scheme_pdf'].pages) == 2
            assert len(readers['fire_station_design_pdf'].pages) == 5
            bound = load_case()
            assert all(bound['payload']['parity'][k] for k in
                       ('demand_parity','k1_parity','meter_parity','rain_parity','branch_parity'))
            summary = dict(pages=len(combined.pages),bookmarks=6,documents=len(docs),
                           station=station,payload_sha256=bound['payload_sha256'])
            (qa/'samara-verified.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
            state = call('POST','/studio/api/package',json={'revision':state['revision']}).json()
            assert state['package']['state'] == 'blocked'
            state = call('POST','/studio/api/study/exit',json={'revision':state['revision']}).json()
            a.headers['X-Zarya-Draft'] = original_id
            assert state['project_id'] == original_id
            assert state['study'] is None
            assert all(a.get(url).status_code == 404 for url in urls)
            for c in (a,b):
                assert c.post('/access/logout').status_code == 303
                assert c.get('/studio/api/draft').status_code == 401
        print('PASS: Samara HTTP, 8 private PDFs, 37 pages/6 bookmarks, 1+1, immutable inputs, original project restored, release blocked',flush=True)
    finally:
        access.revoke(aid)
        access.revoke(bid)


if __name__ == '__main__':
    main()

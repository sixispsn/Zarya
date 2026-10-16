"""Production HTTPS check with a one-day disposable participant, always revoked.

Run inside the deployed app. Does not read keys, open owner projects, edit
existing objects or archive the educational example as a tester submission.
"""
from io import BytesIO
import json
import os
from pathlib import Path

import httpx
from pypdf import PdfReader


def main():
    assert os.environ.get('ZARYA_BUILD_COMMIT') == 'samara-ios2-20261004'
    assert os.environ.get('ZARYA_PROJECTS_DIR') == '/data/projects'
    assert os.environ.get('ZARYA_PILOT_ENABLED') == '1'
    from app.intake.pilot_access import AccessStore
    access = AccessStore()
    users_before = {u['id']:u for u in access.list_users()}
    uid, key = access.issue('Автопроверка выкладки Самара 05.10 — временный доступ', days=1)
    base = 'https://zaryaproekt.ru'
    out = Path('/tmp/zarya-samara-live')
    out.mkdir(mode=0o700)
    headers = {'Origin':base, 'X-Zarya-Studio':'1', 'X-Zarya-Access':'1'}
    try:
        with httpx.Client(base_url=base,headers=headers,timeout=240) as c:
            assert c.get('/health').status_code == 200
            assert c.get('/studio/api/draft').status_code == 401
            r = c.post('/access/login',json={'key':key,'remember_device':True})
            assert r.status_code == 200
            assert all(s in r.headers['set-cookie'] for s in ('Secure','HttpOnly','SameSite=strict','Max-Age='))
            try:
                def call(method,url,**kwargs):
                    result=c.request(method,url,**kwargs)
                    assert result.status_code == 200, (url,result.status_code)
                    return result
                page=call('GET','/studio').text
                assert 'data-kind="samara"' in page and 'studio.js?v=34-samara' in page
                assert 'CNP CDM32-3' not in page # rendered from case, not a global hard-coded result
                js=call('GET','/static/studio.js?v=34-samara').text
                assert "draft.study?.kind==='samara'" in js
                assert c.get('/access/admin').status_code == 403
                assert c.get('/wizard/projects').status_code == 403
                assert c.post('/studio/api/draft',headers={'Origin':'https://invalid.example'}).status_code == 403
                state=call('POST','/studio/api/draft').json()
                original_id=state['project_id']
                c.headers['X-Zarya-Draft']=original_id
                state=call('POST','/studio/api/study',json={'revision':state['revision'],'kind':'samara'}).json()
                c.headers['X-Zarya-Draft']=state['project_id']
                assert state['project_calculation']['can_preview'] and not state['project_calculation']['can_release']
                state=call('POST','/studio/api/preview',json={'revision':state['revision']}).json()
                p=state['preview']
                doc=next(d for d in p['documents'] if d['kind']=='ios2_package_pdf')
                url=f'/studio/api/preview/{p["id"]}/files/{doc["name"]}'
                r=call('GET',url)
                assert r.headers['x-zarya-preview']=='true'
                pdf=PdfReader(BytesIO(r.content))
                assert len(pdf.pages)==37
                text='\n'.join(page.extract_text() for page in pdf.pages)
                assert all(v in text for v in ('CDM32-3','48,924','3,263','512/512'))
                assert 'Hydro MX-A CR15-9' not in text
                path=out/doc['name']
                path.write_bytes(r.content)
                state=call('POST','/studio/api/study/exit',json={'revision':state['revision']}).json()
                c.headers['X-Zarya-Draft']=original_id
                assert state['project_id']==original_id and c.get(url).status_code==404
            finally:
                assert c.post('/access/logout').status_code==303
            assert c.get('/studio/api/draft').status_code==401
    finally:
        access.revoke(uid)
        users_after={u['id']:u for u in access.list_users()}
        assert all(users_after[k]==v for k,v in users_before.items()), 'Existing access records changed'
    print(json.dumps(dict(status='PASS',pages=37,pdf=str(path),temporary_user=uid,
                          temporary_user_revoked=True,existing_users_unchanged=True),ensure_ascii=False))


if __name__ == '__main__':
    main()

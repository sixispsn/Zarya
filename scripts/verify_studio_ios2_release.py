"""Authenticated ordinary Studio smoke; disposable users, never owner projects."""
from io import BytesIO
from pathlib import Path
import argparse
import json
import os
import time

import httpx
from pypdf import PdfReader


def main():
    p=argparse.ArgumentParser();p.add_argument('answers',type=Path);p.add_argument('--live',action='store_true')
    args=p.parse_args()
    assert os.environ['ZARYA_BUILD_COMMIT']=='studio-ios2-20261005'
    assert os.environ['ZARYA_PILOT_ENABLED']=='1'
    assert os.environ['ZARYA_PROJECTS_DIR']==('/data/projects' if args.live else '/tmp/zarya-smoke/projects')
    if not args.live: assert os.environ['ZARYA_DEPLOY_SMOKE']=='1'
    base='https://zaryaproekt.ru' if args.live else 'http://127.0.0.1:8000'
    deadline=time.monotonic()+30
    while True:
        try:
            if httpx.get(base+'/health',timeout=2).status_code==200: break
        except httpx.HTTPError:
            pass
        assert time.monotonic()<deadline,'Server did not start'
        time.sleep(.2)
    from app.intake.pilot_access import AccessStore
    from app.intake.samara_study import load_case
    assert load_case()
    access=AccessStore();before={u['id']:u for u in access.list_users()}
    issued=[];summary={}
    answers=json.loads(args.answers.read_text())
    # Sewer intake is deliberately held at the live version in this release.
    from app.intake.studio_intake import FIELD_MAP
    answers={k:v for k,v in answers.items() if k in FIELD_MAP}
    out=Path('/tmp/zarya-ios2-qa');out.mkdir(mode=0o700,exist_ok=True)
    try:
        for name in ('A','B'):
            issued.append(access.issue('Автопроверка ИОС2 05.10 — временный доступ '+name,days=1))
        headers={'Origin':base,'X-Zarya-Studio':'1','X-Zarya-Access':'1'}
        with httpx.Client(base_url=base,headers=headers,timeout=240) as a, httpx.Client(base_url=base,headers=headers,timeout=30) as b:
            for client,(_,key) in zip((a,b),issued):
                assert client.get('/health').status_code==200
                assert client.get('/studio/api/draft').status_code==401
                r=client.post('/access/login',json={'key':key,'remember_device':True})
                assert r.status_code==200
                assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
                if args.live: assert 'Secure' in r.headers['set-cookie']
                assert client.get('/wizard/projects').status_code==403
                assert client.get('/access/admin').status_code==403
            def call(method,url,**kwargs):
                r=a.request(method,url,**kwargs)
                assert r.status_code==200,(url,r.status_code,r.text[:250])
                return r
            page=call('GET','/studio').text
            assert 'studio.js?v=37-ios2-check' in page and 'studio_fire_station.js?v=4' in page
            assert call('GET','/static/studio_fire_station.js?v=4').status_code==200
            assert a.post('/studio/api/draft',headers={'Origin':'https://invalid.example'}).status_code==403
            state=call('POST','/studio/api/draft').json()
            a.headers['X-Zarya-Draft']=state['project_id']
            state=call('POST','/studio/api/calculate',json={'revision':state['revision'],'answers':answers}).json()
            calc=state['project_calculation'];station=calc['fire_station']
            assert station['pressure_review']['minimum_pass_count']==station['pressure_review']['scenario_count']==45
            assert station['pump_geometry']['fittings_coverage']['included']
            assert not calc['can_release']
            gate=next(g for g in calc['quality']['gates'] if g['gate_id']=='documentation')
            assert gate['state']=='blocked' and any(f['source']=='normative_audit' for f in gate['findings'])
            state=call('POST','/studio/api/preview',json={'revision':state['revision']}).json()
            docs={d['kind']:d for d in state['preview']['documents']}
            urls=[];pages={}
            for kind in ('pz_pdf','fire_station_input_pdf','fire_station_scheme_pdf','pump_selection_pdf','spec_pdf'):
                d=docs[kind];url=f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}'
                urls.append(url);r=call('GET',url)
                assert b.get(url).status_code==404
                pdf=PdfReader(BytesIO(r.content));text=' '.join(p.extract_text() or '' for p in pdf.pages)
                assert 'CNP CDM32-3' in text
                if kind!='spec_pdf':
                    normalized=text.replace(',','.');assert '20.810' in normalized and '50.393' in normalized
                if kind=='pz_pdf':
                    assert 'должно соответствовать' in text
                    assert 'Расчётный расход хозяйственно-бытовых стоков' not in text
                (out/d['name']).write_bytes(r.content);pages[kind]=len(pdf.pages)
            assert pages['fire_station_scheme_pdf']==5
            state=call('POST','/studio/api/package',json={'revision':state['revision']}).json()
            assert state['package']['state']=='blocked'
            state=call('PATCH','/studio/api/answer',json={'revision':state['revision'],'field':'fire_station_model','value':None}).json()
            assert all(a.get(url).status_code==404 for url in urls)
            if not args.live:
                state=call('POST','/studio/api/study',json={'revision':state['revision'],'kind':'samara'}).json()
                a.headers['X-Zarya-Draft']=state['project_id']
                assert state['project_calculation']['can_preview']
                state=call('POST','/studio/api/preview',json={'revision':state['revision']}).json()
                d=next(d for d in state['preview']['documents'] if d['kind']=='vk_package_pdf')
                r=call('GET',f'/studio/api/preview/{state["preview"]["id"]}/files/{d["name"]}')
                pdf=PdfReader(BytesIO(r.content));text=' '.join(p.extract_text() or '' for p in pdf.pages)
                assert all(s in text for s in ('512/512','48,924','63,000'))
                summary['frozen_vk_pages']=len(pdf.pages)
            for c in (a,b):
                assert c.post('/access/logout').status_code==303
                assert c.get('/studio/api/draft').status_code==401
            summary.update(status='PASS',live=args.live,pages=pages,scenarios=45,
                private_pdfs=True,revocation=True,gost_blockers_visible=True)
    finally:
        for uid,_ in issued: access.revoke(uid)
        after={u['id']:u for u in access.list_users()}
        assert all(after[k]==v for k,v in before.items()),'Existing participants changed'
    summary['temporary_users_revoked']=True
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()

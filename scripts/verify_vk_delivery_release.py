"""Real HTTP/PDF acceptance using disposable participants, revoked in finally.

Run in the candidate container with --base http://127.0.0.1:8000, then in the
deployed container with --base https://zaryaproekt.ru. Never prints login keys.
Existing participant projects are not opened or modified.
"""
import argparse
from io import BytesIO
import json
import os
import time
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter

from check_water_studio_delivery import TWO_FLOOR_INPUTS, download_checked_preview, state


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    assert os.environ.get('ZARYA_BUILD_COMMIT')=='20261007-vk-delivery'
    assert os.environ.get('ZARYA_PILOT_ENABLED')=='1'
    assert args.base in ('http://127.0.0.1:8000','https://zaryaproekt.ru')
    if args.base.startswith('http:'):
        assert os.environ.get('ZARYA_DEPLOY_SMOKE')=='1'
        assert os.environ.get('ZARYA_PROJECTS_DIR')=='/tmp/zarya-smoke/projects'
    else:
        assert os.environ.get('ZARYA_PROJECTS_DIR')=='/data/projects'
    from app.intake.pilot_access import AccessStore
    access=AccessStore();issued=[];reports=[];sheets=[]
    args.out.mkdir(parents=True,exist_ok=False,mode=0o700)
    headers={'Origin':args.base,'X-Zarya-Studio':'1','X-Zarya-Access':'1'}
    deadline=time.monotonic()+30
    while True:
        try:
            if httpx.get(args.base+'/health',timeout=3).status_code==200: break
        except httpx.HTTPError:
            pass
        if time.monotonic()>=deadline: raise RuntimeError('Server did not become ready')
        time.sleep(.2)
    try:
        for name in ('A','B'):
            issued.append(access.issue(f'Автопроверка К1/ИОС2 07.10 {name} · временный доступ',days=1))
        with httpx.Client(base_url=args.base,headers=headers,timeout=240) as client, \
             httpx.Client(base_url=args.base,headers=headers,timeout=240) as other:
            assert client.get('/health').status_code==200
            assert client.get('/studio/api/draft').status_code==401
            for c,(_,key) in zip((client,other),issued):
                login=c.post('/access/login',json={'key':key,'remember_device':True})
                assert login.status_code==200
                assert 'HttpOnly' in login.headers['set-cookie']
                if args.base.startswith('https:'): assert 'Secure' in login.headers['set-cookie']
            page=client.get('/studio').text
            assert 'v=45-water-delivery' in page and 'v=16-horizontal-sewage' in page
            assert other.get('/access/admin').status_code==403
            assert client.post('/studio/api/draft',headers={'Origin':'https://invalid.example'}).status_code==403
            current=state(client.post('/studio/api/draft'))
            client.headers['X-Zarya-Draft']=current['project_id']
            inputs=dict(TWO_FLOOR_INPUTS,section_k1_flow_basis='whole_building',
                section_k1_fixtures_count=32,section_k1_receiving_length_m=10,
                section_k1_dn_mm=100,section_k1_slope=.01,
                section_k1_outer_diameter_mm=110,section_k1_wall_thickness_mm=3.4,
                section_k1_material='pp',section_k1_manning_n=.011,
                section_k1_roughness_source='Контрольное значение, не паспорт изделия',
                section_k1_source_ref='Синтетический приёмочный расчёт, не реальный объект')
            current=state(client.post('/studio/api/calculate',json={'revision':current['revision'],'answers':inputs}))
            assert current['calculation']['total']['q_hr']==1.268
            assert current['calculation']['sewage_flow']==2.293
            current,pdf,report=download_checked_preview(client,current)
            reports.append(dict(case='ordinary',**report));sheets.append(pdf)
            preview=current['preview']
            doc=next(d for d in preview['documents'] if d['kind']=='wastewater_calculation_pdf')
            url=f'/studio/api/preview/{preview["id"]}/files/{doc["name"]}'
            r=client.get(url);assert r.status_code==200
            text=' '.join('\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages).split())
            assert all(s in text for s in ('1,104','1,268','0,47','формула (7)'))
            (args.out/'К1_расчёт_с_сервера.pdf').write_bytes(r.content)
            assert other.get(url).status_code==404
            assert not current['project_calculation']['can_release']
            current=state(client.post('/studio/api/calculate',json={'revision':current['revision'],
                                                                  'answers':{'residents':21}}))
            assert current['preview'] is None and client.get(url).status_code==404
            current=state(client.post('/studio/api/study',json={'revision':current['revision'],'kind':'samara'}))
            client.headers['X-Zarya-Draft']=current['project_id']
            current,pdf,report=download_checked_preview(client,current)
            reports.append(dict(case='samara',**report));sheets.append(pdf)
            assert not current['project_calculation']['can_release']
            assert client.post('/access/logout').status_code==303
            assert client.get('/studio/api/draft').status_code==401
        writer=PdfWriter()
        for title,pdf in zip(('Studio · 2 этажа','Самара · контрольная секция'),sheets):
            writer.append(PdfReader(BytesIO(pdf)),outline_item=title)
        with (args.out/'Вода_из_Studio_с_сервера.pdf').open('wb') as f: writer.write(f)
        result=dict(status='PASS',base=args.base,water=reports,horizontal_lps=1.104,
                    private_download=True,stale_links_revoked=True,incomplete_release_blocked=True)
        (args.out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        for uid,_ in issued: access.revoke(uid)
    print(json.dumps(dict(result,temporary_users_revoked=True),ensure_ascii=False),flush=True)


if __name__=='__main__':main()

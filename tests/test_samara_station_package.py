"""The reviewed case must survive the real Studio API, not only a CLI annex."""
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.intake import samara_study
from app.intake.studio_intake import IntakeError, answer_field
from app.pz.fire_station_binding import digest, station_spec_rows, validate_design
from tests.test_studio import client, new


def draft():
    d=dict(revision=0,answers={},documents=[])
    samara_study.initialize(d,None)
    assert d['project_calculation']['can_preview'], d['project_calculation']
    return d


def test_json_hash_is_stable_for_numeric_floor_keys():
    d={1:'one',10:'ten',2:'two'}
    assert digest(d)==digest(json.loads(json.dumps(d)))


def test_fixed_case_requires_same_answers_source_and_engine(monkeypatch):
    d=draft()
    with pytest.raises(IntakeError,match='фиксированные'):
        answer_field(d,'residents',400)
    d['answers']['residents']['value']=400
    state=samara_study.calculate(d)
    assert not state['can_preview'] and not state['can_release']
    monkeypatch.setattr(samara_study,'engine_fingerprint',lambda:'changed')
    with pytest.raises(IntakeError,match='устарел'):samara_study.load_case()


def test_hidden_signed_fields_cannot_be_changed(monkeypatch):
    from app.intake import studio_intake
    d = draft()
    key = 'section_fan_mode'
    monkeypatch.setattr(studio_intake, 'FIELDS', tuple(f for f in studio_intake.FIELDS if f.key != key))
    monkeypatch.setattr(samara_study, 'FIELD_MAP', {k:v for k,v in samara_study.FIELD_MAP.items() if k != key})
    assert samara_study.calculate(d)['can_preview']
    d['answers'][key]['value'] = 'unresolved'
    assert not samara_study.calculate(d)['can_preview']


def test_one_bound_model_in_text_spec_and_drawing(tmp_path):
    from app.pz.generator import generate_pz_html, generate_pump_selection_html
    from app.pz.spec import build_specification
    from app.pz.fire_station_design_scheme import build_design_sheets
    d=draft();b,_=samara_study.build(d,tmp_path)
    p=b.project;r=p.fire_pumps.station_design
    assert p.fire_pumps.model=='CNP CDM32-3' and not p.fire_pumps.top3
    assert p.fire_pumps.working_units==p.fire_pumps.reserve_units==1
    assert p.fire_pumps.sp10_compliant is None
    assert p.fire.required_head_m is None # no stale fixed-Q head in PZ
    assert p.fire.q_total==5.2 # table 7.3 minimum is not secretly altered
    for html in (generate_pz_html(p),generate_pump_selection_html(p)):
        assert 'CDM32-3' in html and '48,924' in html and '3,263' in html
        assert 'Hydro MX' not in html and 'PFFS 2 CDM15-5' not in html
        assert 'характерных стояков' in html
    text=generate_pz_html(p)
    assert 'хозяйственно-питьевых насосных' in text
    assert 'не распространяются автоматически' in text
    assert 'Предварительная спецификация оборудования' in text
    assert 'В составе данного раздела не разрабатывается (приводится в рабочей документации)' not in text
    rows=station_spec_rows(r)
    by_id={row['id']:row for row in rows}
    assert by_id['pumps']['qty']==2 and by_id['discharge-check']['qty']==2
    assert by_id['pressure']['qty']==4
    assert sum(x['qty'] for x in rows if x['unit']=='м')==4
    assert all(x['qty'] is None for x in rows if x['id'].startswith('diaphragm-'))
    assert by_id['suction-fittings']['qty'] is None
    assert by_id['diaphragm-15']['mark']=='Отверстие 21 мм'
    assert by_id['diaphragm-13']['name'].endswith('13-14')
    sheets=build_design_sheets(p,b.fire_station_result)
    components=[n.get('data-component') for n in ET.fromstring(sheets[0]).iter() if n.get('data-component')]
    assert components.count('pumps')==2 and components.count('pressure')==4
    assert components.count('suction-valve-100')==1
    assert components.count('discharge-valve-65')==2
    spec=build_specification(p,scope='water')
    names=' '.join(row.name+' '+row.type_mark for section in spec.sections for row in section.rows)
    assert 'CDM32-3' in names and 'Hydro MX' not in names
    assert not any(s.startswith('fire_pump: подобран') for s in b.status)


def test_stale_result_is_rejected_not_silently_relabelled(tmp_path):
    d=draft();b,_=samara_study.build(d,tmp_path)
    _,station,r,_=samara_study.inputs(d)
    changed=deepcopy(r);changed['required_q_m3h']*=2
    with pytest.raises(ValueError,match='changed'):validate_design(changed,b.project,station)
    b.project.fire_network.risers[0].length_m+=1
    with pytest.raises(ValueError,match='stale'):validate_design(r,b.project,station)


def test_ios3_uses_shared_flows_and_no_fire_review_or_empty_tables(tmp_path):
    import re
    from app.pz.generator import generate_wastewater_calculation_html, generate_wastewater_pz_html
    d=draft();b,_=samara_study.build(d,tmp_path)
    summary=samara_study.wastewater_summary(b.project)
    from app.pz.wastewater_ugo import project_legend_definitions
    keys={row.key for row in project_legend_definitions(b.project)}
    assert {'sink','bath','washbasin','toilet','trap','revision','cleanout',
            'roof_funnel_heated','system_k1','system_k2','transition'} <= keys
    assert 'system_k3' not in keys
    assert summary['q_k1_lps']==4.785 and summary['q_k2_lps']==11.518
    assert summary['q_day_m3']==63 and summary['preliminary'] and summary['missing']
    calc=generate_wastewater_calculation_html(b.project)
    assert 'Расходы магистралей получены' not in calc
    for html in (calc,generate_wastewater_pz_html(b.project)):
        assert 'В2: проверены характерные' not in html
        for body in re.findall(r'<tbody\b[^>]*>(.*?)</tbody>',html,re.S):
            assert '<tr' in body, 'Empty table in IOS3'
    b.project.flows.sewage_l_per_s+=1
    with pytest.raises(IntakeError,match='расходятся'):
        samara_study.wastewater_summary(b.project)


def test_actual_studio_preview_full_pdf_and_private_access(client):
    original=new(client)
    old_id=client.cookies.get('zarya_studio_draft')
    response=client.post('/studio/api/study',json={'revision':original['revision'],'kind':'samara'})
    assert response.status_code==200,response.text
    state=response.json()
    assert state['study']['kind']=='samara' and state['project_calculation']['can_preview']
    assert not state['project_calculation']['can_release']
    response=client.post('/studio/api/preview',json={'revision':state['revision']})
    assert response.status_code==200,response.text
    state=response.json();preview=state['preview']
    package=next(d for d in preview['documents'] if d['kind']=='ios2_package_pdf')
    assert len({d['model_hash'] for d in preview['documents']})==1
    url=f"/studio/api/preview/{preview['id']}/files/{package['name']}"
    response=client.get(url)
    assert response.status_code==200
    pdf=PdfReader(BytesIO(response.content));text='\n'.join(p.extract_text() for p in pdf.pages)
    assert len(pdf.pages)>10 and len(pdf.outline)>=6
    for phrase in ('CDM32-3','3,263','48,924','512/512','Автоматизация','Диафрагма','13824','0,211609'):
        assert phrase in text,phrase
    assert 'Hydro MX-A CR15-9' not in text and 'PFFS 2 CDM15-5' not in text
    assert '481/512' in text # historical comparison remains explicitly labelled
    assert response.headers['X-Zarya-Preview']=='true'
    # Pump inventory pages must retain their own system heading after merging.
    station_pages=[p.extract_text() for p in pdf.pages
                   if 'Насос вертикальный многоступенчатый' in p.extract_text()]
    assert station_pages and all('В2 — внутренний противопожарный водопровод' in t for t in station_pages)
    docs={d['kind']:d for d in preview['documents']}
    assert len(docs)==16
    def read(kind):
        response=client.get(f"/studio/api/preview/{preview['id']}/files/{docs[kind]['name']}")
        assert response.status_code==200
        return PdfReader(BytesIO(response.content))
    sewer=read('ios3_package_pdf');whole=read('vk_package_pdf')
    sewer_text='\n'.join(p.extract_text() for p in sewer.pages)
    assert all(v in sewer_text for v in ('4,785','11,518','63,000','КК-1','ДК-1'))
    assert 'В2: проверены характерные' not in sewer_text
    assert len(whole.pages)==len(pdf.pages)+len(sewer.pages)
    assert len([b for b in whole.outline if not isinstance(b,list)])==2
    assert len([b for b in sewer.outline if not isinstance(b,list)])==4
    assert state['project_calculation']['ios3']
    # Current draft alone can access its generated file.
    client.cookies.set('zarya_studio_draft',old_id,path='/studio')
    assert client.get(url).status_code==404

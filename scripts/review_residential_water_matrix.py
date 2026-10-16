"""Repeatable graphical stress fixtures, NOT designs for three new buildings.

Run from repository root. Input geometry is explicit test data, not hydraulic
selection. Current Samara is audited separately, without changing its snapshot.
Only the combined three-sheet visual review is a deliverable; PZ/spec probes
are QA intermediates. No OCR, network access, deployment or source migration.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from html.parser import HTMLParser
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
from pypdf import PdfReader, PdfWriter

from app.calc.t3_hydraulics import T3SectionInput
from app.intake.project_builder import build_project
from app.intake.request_dto import (
    ConsumerGroupRequest, DocumentRequest, IOS2Request, SourceDataRequest, V1SectionRequest,
)
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.generator import generate_scheme_result, generate_pz_html, generate_spec_html
from app.pz.spec import build_specification
from app.pz.water_document_binding import water_material_context
from app.pz.water_pipe_binding import bind_v1_pipes, bind_t3_pipes
from app.pz.water_residential_section import residential_water_layout


# Explicit test values, isolated from real projects/defaults. Even a known D×s
# here is not a claim that this diameter is suitable for this building height.
CASES = (
    dict(floors=2, height=3.3, basement=-3.1, inlet=-2.1, apartments=8,
         residents=20, area=460, risers=4, main=(42,3), riser=(32,2.8),
         apartment=(20,2), internal_heater=True),
    dict(floors=9, height=3.0, basement=-2.8, inlet=-1.6, apartments=36,
         residents=90, area=2700, risers=6, main=(60,3), riser=(42,3),
         apartment=(25,2.3), internal_heater=False),
    dict(floors=25, height=3.0, basement=-4.2, inlet=-3.2, apartments=100,
         residents=250, area=7500, risers=10, main=(89,4), riser=(60,3),
         apartment=(20,2), internal_heater=True),
)


class DocumentFields(HTMLParser):
    """Read only our tagged rows/spans; no extra parsing dependency."""
    def __init__(self, html):
        super().__init__()
        self.values={};self.active=[]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        for name in ('data-pipe-key','data-apartment-component'):
            if name in attrs:
                key=(name,attrs[name]);self.values[key]=''
                self.active.append((tag,key))

    def handle_endtag(self, tag):
        self.active=[item for item in self.active if item[0]!=tag]

    def handle_data(self, text):
        for _,key in self.active:self.values[key]+=text

    def get(self, attribute, key):
        return self.values.get((attribute,key))


def build_case(case):
    n, height = case['floors'], case['height']
    basis = 'Явные данные графического теста; не расчёт и не подбор системы здания'
    geometry = [('Подвод', (110,6.6), 'ПЭ', 'input'),
                ('Магистраль',case['main'],'Стальная','internal'),
                ('Стояк',case['riser'],'Стальная','internal'),
                ('Квартира',case['apartment'],'PE-X','internal')]
    cold, hot = [], []
    for name,(outer,wall),material,role in geometry:
        # These short sections are test records for checking source bindings,
        # not lengths recovered from a drawing or the house's bill of pipes.
        material = f'{material} {outer:g}×{wall:g}'
        cold.append(V1SectionRequest('В1-'+name,1,outer-2*wall,.1,.01,
                                     role=role,material=material))
        if role != 'input':
            hot.append(T3SectionInput('Т3-'+name,1,outer-2*wall,.01,.1,
                                      basis=basis,material=material))
    if case['internal_heater']:
        hot.append(T3SectionInput('В1-к-водонагревателю',1,54,.01,.1,
                                 basis=basis,material='Стальная 60×3'))
    request = IOS2Request(
        document=DocumentRequest(f'КОНТРОЛЬ-{n}-ИОС2',f'Графический контроль: {n} этажей','ЗАРЯ'),
        building_type='residential',floors=n,building_height_m=n*height,
        fire_height_m=(n-1)*height+.5,fire_category='residential_f13',
        floors_below=1,apartments=case['apartments'],residents=case['residents'],
        floor_elevations_m={-1:case['basement'],**{f:(f-1)*height for f in range(1,n+1)}},
        total_area_m2=case['area'],risers_v1=case['risers'],risers_t3=case['risers'],risers_t4=case['risers'],
        consumers=[ConsumerGroupRequest('residential_full_bath',case['residents'])],
        source_data=SourceDataRequest(inputs_count=1,hws_heater_in_scope=case['internal_heater'],
            elev_header_m=case['inlet'],elev_fixture_m=(n-1)*height+1,
            lowest_fixture_elevation_m=1,lowest_fixture_basis=basis),
        metering_detail=MeteringDetailData(inlet_elevation_m=case['inlet']),
        v1_sections=cold,t3_sections=hot,
        wastewater_roof_kind='flat_non_accessible',wastewater_floor_height_m=height,
        wastewater_roof_relative_elevation_m=n*height,
    )
    p=build_project(request)
    p.document.review_notes=(basis,)+(
        ('25 этажей: не подтверждает достаточность одной зоны давления.',) if n==25 else ())
    return p


def domestic_sheet(project):
    p=deepcopy(project)
    # Same sheet separation as production IOS2 orchestration. This is not
    # deletion or a change to the required fire system of the source project.
    p.fire.required=False
    p.fire_pumps.required=False
    return generate_scheme_result(p)


def audit_documents(project):
    before=deepcopy(asdict(project))
    result=domestic_sheet(project)
    root=ET.fromstring(result.svg)
    assert root.get('data-residential-water-section')=='approval'
    pz=generate_pz_html(project)
    html=DocumentFields(pz)
    spec=build_specification(project,scope='water')
    rows=[row for section in spec.sections for row in section.rows]
    materials=water_material_context(project)
    bindings={'В1':bind_v1_pipes(project),'Т3':bind_t3_pipes(project)}
    verified=[]
    for row in materials['cold_rows']+materials['hot_rows']:
        source=bindings[row.system][row.key.split('-')[1]]
        assert source.pipe is not None
        annotations=[node for node in root.iter() if node.get('data-pipe-binding')==row.key]
        assert annotations and all(row.size in ET.tostring(node,encoding='unicode') for node in annotations),row.key
        pz_row=html.get('data-pipe-key',row.key)
        assert pz_row and row.size in pz_row
        candidates=[r for r in rows if r.unit=='м' and
                    (r.name.startswith('Труба ') or r.name.startswith('Трубы '))]
        if row.system=='Т3':
            candidates=[r for r in candidates if r.component_ids==('t3-'+source.role,)]
        else:
            candidates=[r for s in spec.sections if s.title.startswith('В1 — хозяйственно') for r in s.rows
                        if r.name.startswith('Труба ') and r.unit=='м']
        assert any(row.size in (r.name+' '+r.type_mark) for r in candidates),row.key
        verified.append(dict(key=row.key,size=row.size,material=row.material,source=source.source_ids))
    visible={e.get('data-apartment-component') for e in root.iter() if e.get('data-apartment-component')}
    for ident in visible:
        assert html.get('data-apartment-component',ident)
        matches=[r for r in rows if ident in r.component_ids]
        system='В1' if ident.startswith('apartment-v1-') else 'Т3'
        qty=project.apartment_water_units.quantity(system,project.building.apartments)
        assert len(matches)==1 and matches[0].qty==qty
        assert matches[0].quantity_basis==('apartment_schedule' if qty is not None else 'apartment_principle')
    assert visible=={item.key for item in materials['apartment_rows']}
    assert 'Т4 DN не задан' in result.svg
    assert html.get('data-pipe-key','Т4-network')
    t4=next(r for r in rows if r.component_ids==('t4-network',))
    assert t4.qty is None and 'по расчёту Т4' in t4.type_mark
    balances=[r for r in rows if r.component_ids==('circulation-balance',)]
    assert len(balances)==1
    assert balances[0].qty==project.building.water_service_layout.balance_quantity(project.building)
    assert 'К1 —' not in ' '.join(s.title for s in spec.sections)
    assert 'К2 —' not in ' '.join(s.title for s in spec.sections)
    assert asdict(project)==before
    return dict(floors=project.building.floors_above,
        shown=residential_water_layout(project).floors,read_only=True,
        sizes=verified,apartment_components=sorted(visible),
        t4_quantity=balances[0].qty,source_inlets=project.source.inputs_count,
        warnings=result.warnings),result,pz,generate_spec_html(project)


def main():
    from app.intake import samara_study
    from app.pz.generator import generate_pz_pdf,generate_spec_pdf
    scratch=ROOT/'tmp/pdfs/water-residential-matrix'
    out=ROOT/'output/pdf/water-residential-matrix'
    scratch.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    writer=PdfWriter();reviews=[]
    for case in CASES:
        p=build_case(case)
        report,result,pz,spec=audit_documents(p)
        name=f'{case["floors"]}-floors'
        (scratch/(name+'.svg')).write_text(result.svg,encoding='utf-8')
        (scratch/(name+'-pz.html')).write_text(pz,encoding='utf-8')
        (scratch/(name+'-spec.html')).write_text(spec,encoding='utf-8')
        pdf=scratch/(name+'.pdf')
        cairosvg.svg2pdf(bytestring=result.svg.encode(),write_to=str(pdf))
        writer.append(PdfReader(pdf),outline_item=f'{case["floors"]} этажей - графический контроль')
        reviews.append(report)
    # Audit the actual reviewed example independently; never change its floor
    # count and carry the old pump/calculation into another test building.
    c=samara_study.load_case()
    d=dict(answers=deepcopy(c['payload']['answers']),documents=[],study=dict(snapshot=c['payload_sha256']))
    with TemporaryDirectory() as tmp:p=samara_study.build(d,tmp,render=False)[0].project
    report,result,_,_=audit_documents(p)
    report['snapshot']=c['payload_sha256'];reviews.append(report)
    generate_pz_pdf(p,str(scratch/'samara-pz.pdf'))
    generate_spec_pdf(p,str(scratch/'samara-spec.pdf'))
    cairosvg.svg2pdf(bytestring=result.svg.encode(),write_to=str(scratch/'samara-scheme.pdf'))
    target=out/'Вода_контроль_2_9_25_этажей.pdf'
    writer.add_metadata({'/Title':'ЗАРЯ: контроль оформления В1, Т3, Т4',
                         '/Subject':'Графические тесты, не проектные решения для выпуска'})
    writer.write(target)
    (scratch/'audit.json').write_text(json.dumps(reviews,ensure_ascii=False,indent=2),encoding='utf-8')
    print(target)
    print('Cases verified:',len(reviews),'(including unchanged Samara)')


if __name__=='__main__':main()

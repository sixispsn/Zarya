"""Cross-document and actual-PDF checks beyond the first Samara screenshot."""
from copy import deepcopy
from dataclasses import asdict,replace
from xml.etree import ElementTree as ET

import cairosvg
import pymupdf
import pytest

from scripts.review_residential_water_matrix import CASES,build_case,audit_documents,domestic_sheet
from app.pz.generator import generate_pz_html
from app.pz.spec import build_specification
from app.pz.water_apartment_assembly import apartment_components


@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['floors']))
def test_drawing_pz_spec_share_current_sizes_and_components(case):
    p=build_case(case)
    report,result,pz,spec=audit_documents(p)
    assert report['shown']==((1,2) if case['floors']==2 else (1,2,case['floors']))
    assert len(report['sizes'])==7
    assert len(report['apartment_components'])==8
    # These graphical fixtures specify risers, not the accepted valve layout.
    assert report['t4_quantity'] is None
    assert ('data-pipe="cold-to-hws"' in result.svg)==case['internal_heater']
    assert ('Узел нагрева ГВС' in result.svg)==case['internal_heater']


@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['floors']))
def test_every_printed_word_fits_sheet_and_known_datums_survive(case):
    p=build_case(case);result=domestic_sheet(p)
    pdf=pymupdf.open(stream=cairosvg.svg2pdf(bytestring=result.svg.encode()),filetype='pdf')
    page=pdf[0];mm=72/25.4
    safe=pymupdf.Rect(20*mm,5*mm,589*mm,415*mm)
    assert len(pdf)==1 and not page.get_images()
    for word in page.get_text('words'):
        assert safe.contains(pymupdf.Rect(word[:4])),word
    assert '\ufffd' not in page.get_text()
    root=ET.fromstring(result.svg)
    controls={e.get('data-control-datum'):e.get('data-value') for e in root.iter() if e.get('data-control-datum')}
    assert float(controls['dictating'])==p.source.elev_fixture_m
    assert float(controls['lowest'])==1
    if case['floors']>3:
        assert f'Не показано этажей: {case["floors"]-3}' in page.get_text()
    assert any('OpenGOST' in font[3] for font in page.get_fonts())


def test_edited_diameters_propagate_to_all_documents_not_a_cached_samara_template():
    p=build_case(CASES[1])
    for i,section in enumerate(p.v1_sections):
        if 'Стояк' in section.section_id:
            p.v1_sections[i]=replace(section,material='Стальная 48×3,5',inner_diameter_mm=41)
    p.t3_sections=[replace(s,material='Стальная 76×3,5',inner_diameter_mm=69)
                   if 'Стояк' in s.section_id else s for s in p.t3_sections]
    report,*_=audit_documents(p)
    sizes={r['key']:r['size'] for r in report['sizes']}
    assert sizes['В1-riser']=='Ø48×3,5' and sizes['Т3-riser']=='Ø76×3,5'


def test_apartment_quantities_are_not_number_of_symbols_or_apartments():
    p=build_case(CASES[2])
    for apartment_count in (100,500):
        p.building.apartments=apartment_count
        rows=[r for s in build_specification(p,scope='water').sections for r in s.rows
              if any(key.startswith('apartment-') for key in r.component_ids)]
        # The eight principal symbols now also have kits and pipe connectors.
        # None of their quantities may be inferred from the drawing/apartments.
        principal={c.key for system in ('В1','Т3') for c in apartment_components(p,system)}
        main_rows=[r for r in rows if principal.intersection(r.component_ids)]
        assert len(main_rows)==8 and all(r.unit=='шт.' for r in main_rows)
        assert all(r.qty is None for r in rows)
        assert any('meter-kit' in k for r in rows for k in r.component_ids)
    assert not any(key.startswith('apartment-') for s in build_specification(p,scope='wastewater').sections
                   for r in s.rows for key in r.component_ids)


def test_meter_toggle_removes_same_component_from_drawing_text_and_spec():
    p=build_case(CASES[0]);p.meters.has_apartment_meters=False
    report,*_=audit_documents(p)
    assert len(report['apartment_components'])==6
    assert not any(key.endswith('-meter') for key in report['apartment_components'])


@pytest.mark.parametrize('change',['local','none','mixed','fixtures','public','zones','hws_zones','stage_r'])
def test_no_apartment_composition_invented_outside_supported_profile(change):
    from app.pz.project import HwsType,BuildingPurpose,Stage
    p=build_case(CASES[0])
    if change in ('local','none'):p.building.hws_type=HwsType(change)
    elif change=='mixed':p.consumer_groups.append(('hospital',10))
    elif change=='fixtures':p.fixtures=[object()]
    elif change=='zones':p.building.zones=2
    elif change=='hws_zones':p.hws_stage_p=replace(p.hws_stage_p,enabled=True,zones=2)
    elif change=='stage_r':p.document.stage=Stage.R
    else:p.building.purpose=BuildingPurpose.PUBLIC
    assert not apartment_components(p,'В1') and not apartment_components(p,'Т3')


def test_unconfirmed_lower_datum_does_not_look_confirmed():
    p=build_case(CASES[0]);p.source.lowest_fixture_basis=''
    root=ET.fromstring(domestic_sheet(p).svg)
    node=next(e for e in root.iter() if e.get('data-control-datum')=='lowest')
    assert node.get('data-value')=='None' and 'не задана' in ''.join(node.itertext())


def test_current_samara_cross_document_audit_does_not_change_approved_calculations(tmp_path):
    from app.intake import samara_study
    d=dict(revision=0,answers={},documents=[])
    samara_study.initialize(d,None)  # includes the separately accepted K1 review
    p=samara_study.build(d,tmp_path,render=False)[0].project
    before=deepcopy(asdict(p))
    report,*_=audit_documents(p)
    assert p.flows.q_day_tot==63 and p.flows.q_sec_tot==3.185
    assert report['source_inlets']==2 and report['t4_quantity'] is None
    assert asdict(p)==before and p.fire.required

from copy import deepcopy
from dataclasses import asdict
import xml.etree.ElementTree as ET

import pytest

from app.data.metering_products import get_metering_catalogue
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_mounting import MeteringMounting, resolve_mounting, mounting_contents
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.equipment_origin import origin, review_equipment_origin
from app.pz.commission import build_commission_report
from app.intake.studio_intake import build_handoff_request, answer_field
from app.intake.studio_project import calculate_project
from app.intake.yaml_io import load_request, dump_request
from app.intake.project_builder import build_project
from scripts.preview_metering_detail import catalogue_review_project, review_project
from tests.test_studio_apartment_meters import draft


def test_modern_meter_has_own_envelope_and_not_a_mechanical_curve():
    from app.data.metering_extras import catalogue_option_details
    c=get_metering_catalogue()
    p=c.products['pulsar-m2-e1-t105-rs485-dn32']
    assert p.body_length_mm == 180 and p.dimension_basis == 'maximum'
    assert p.flows_m3h['qmin_C'] == .06 and 'qmin_B' not in p.flows_m3h
    assert p.pressure_loss_limit is None and p.kit_pipe_thread is None
    assert p.country_of_manufacture == 'RU'
    assert origin(p.id)['sources']
    assert '9-30' in p.remote_interface
    assert c.products['ld47-vv-m02-dn32'].body_length_mm == 68
    assert c.products['ld47-vv-m02-dn32'].full_bore is False
    assert c.thread_connectors['ld-67-501-50'].body_length_mm == 39
    assert 'ld-67-501-32' not in c.thread_connectors  # conflicting manufacturer values
    card=catalogue_option_details()['choices']['vu_technology']['pulsar_m2_us32'][0]
    assert card['id']==p.id and card['checked_on']=='2026-10-12'
    assert '180' in card['facts'][0]


def test_russian_candidates_never_infer_origin_from_brand():
    c=get_metering_catalogue()
    assert {p.id for p in c.candidates('meter',32,russian_only=True,technology='mechanical')} == {
        'decast-vskm90-dn32','decast-vskm90-dg-dn32'}
    assert not c.candidates('check',50,russian_only=True)
    assert origin('unknown')['country'] == 'unknown'
    p=catalogue_review_project(); before=deepcopy(asdict(p.meters))
    p.metering_detail.russian_equipment_only=True
    s=drawing_state(p)
    selected=resolve_metering_products(p,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    assert selected.selected('meter').id == 'decast-vskm90-dg-dn32'
    assert selected.selected('inlet_valve') is None and selected.selected('check_valve') is None
    assert any('Российское' in e for e in selected.errors)
    assert asdict(p.meters)==before
    assert all(not x.connector for x in selected.connections)
    assert all(not x.part for x in selected.reducers)
    report=review_equipment_origin(p)
    assert report['enabled'] and not report['ready']
    assert any(not r['ready'] for r in report['rows'])
    assert next(c for c in build_commission_report(p).checks if c.code=='EQUIP-RU').blocking


def test_studio_origin_and_scale_roundtrip_does_not_change_hydraulics():
    d=draft(); before=calculate_project(d)
    answer_field(d,'russian_equipment_only','yes')
    answer_field(d,'vu_drawing_scale','10')
    req=build_handoff_request(d)
    copied=load_request(dump_request(req))
    assert copied.metering_detail.russian_equipment_only is True
    assert copied.metering_detail.mounting == MeteringMounting(enabled=True,scale=10)
    p=build_project(copied)
    p.metering_detail.mounting.spans['anything']={}
    assert not copied.metering_detail.mounting.spans
    after=calculate_project(d)
    for key in ('flows','head','pumps','fire','storm'):
        assert after[key]==before[key]
    assert after['equipment_origin']['enabled'] and not after['can_release']
    answer_field(d,'russian_equipment_only','no')
    assert not calculate_project(d)['equipment_origin']['enabled']


@pytest.mark.parametrize('value',[0,3,True,1.5,'5'])
def test_invalid_scale_is_not_silently_changed(value):
    assert MeteringMounting(scale=value).validate()


def test_unknown_assembly_never_gets_a_total_length_or_inferred_pipe_cuts():
    p=catalogue_review_project(); before=deepcopy(asdict(p))
    r=resolve_mounting(p)
    assert not r.dimensions_complete and r.issues
    assert r.pipe_lengths_m == {} and r.support_count is None
    assert all(c.length_mm is None for c in r.chains)
    assert asdict(p)==before
    m=r.chains[0]
    assert next(s.length_mm for s in m.spans if s.id=='meter')==260
    assert next(s.length_mm for s in m.spans if s.id=='kit_in') is None


def test_dimensioned_geometry_uses_mm_and_fixed_paper_text_size():
    p=catalogue_review_project(); p.metering_detail.mounting.enabled=True
    for scale in (5,10):
        p.metering_detail.mounting.scale=scale
        pages=mounting_contents(p,drawing_state(p))
        assert f'1:{scale}' in pages[0]
        root=ET.fromstring('<svg>'+''.join(pages)+'</svg>')
        lines=[e for e in root.iter() if e.tag=='line' and e.get('stroke-width')=='.6']
        # SVG helper normalizes stroke width as 0.6.
        lines += [e for e in root.iter() if e.tag=='line' and e.get('stroke-width')=='0.6']
        assert any(abs(float(e.get('x2'))-float(e.get('x1'))-260/scale)<.001 for e in lines)
    svgs=build_metering_detail_pages(p)
    assert any('data-meter-mounting' in s for s in svgs)
    for s in svgs: ET.fromstring(s)


def test_stale_nodes_and_invalid_insertions_are_detected():
    p=catalogue_review_project()
    p.metering_detail.mounting.spans={'absent':{'length_mm':5,'source':'test'}}
    p.metering_detail.mounting.joints={'check_valve>outlet_thread':{'overlap_mm':100,'source':'test'}}
    errors=resolve_mounting(p).issues
    assert any('отсутствует' in e for e in errors)
    assert any('поглощает' in e for e in errors)
    p.metering_detail.mounting.joints['check_valve>outlet_thread']['overlap_mm']=float('nan')
    assert p.metering_detail.validate()

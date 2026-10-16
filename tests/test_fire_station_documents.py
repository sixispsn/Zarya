from copy import deepcopy
from itertools import product

import pytest

from app.calc.fire_station_documents import check_reserve_protections, review_station_documents
from app.data.fire_station_documents import PFFS32_ROW


@pytest.mark.parametrize('values',list(product((None,False,True), repeat=3)))
def test_reserve_unknown_is_not_off_and_off_is_not_approval(values):
    r=check_reserve_protections(**dict(zip(('dry_run_stop','current_trip','thermal_trip'),values)))
    expected='conflict' if True in values else ('needs_data' if None in values else 'settings_only')
    assert r['status']==expected
    assert not r['station_approved']


@pytest.mark.parametrize('value',[0,1,'off','False',[],float('nan')])
def test_settings_must_not_be_coerced(value):
    with pytest.raises(ValueError):
        check_reserve_protections(dry_run_stop=value,current_trip=None,thermal_trip=None)


def test_catalog_row_cannot_create_an_order_code_or_station_curve():
    r=PFFS32_ROW
    assert r['pumps']==2 and r['power_per_motor_kw']==5.5 and r['connection_dn']==100
    assert r['dimensions_mm']==dict(H=1213,H1=205,H2=1465,L=968,L1=778,B1=628,B2=428,B=1056,C=1623)
    assert r['full_order_code'] is None and r['selected_pressure_rating_bar'] is None
    assert r['header_material'] is None and len(r['material_conflict'])==3
    assert not r['station_curve_includes_internal_losses']
    assert r['guaranteed_assembled_station_curve'] is None and not r['selection_confirmed']
    assert all(type(row['quantity']) is int for row in r['included_components'])
    assert len({x['id'] for x in r['included_components']})==len(r['included_components'])


@pytest.fixture(scope='module')
def current_study(tmp_path_factory):
    from scripts.build_samara_diaphragm_apertures import calculate_apertures
    from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    b=load_basis();station=make_fire_station(b)
    bundle=design_ios2(build_project(make_request(make_draft(b))),
        output_dir=str(tmp_path_factory.mktemp('station')),fire_station=station,render_documents=False)
    before=deepcopy(bundle.project)
    a=calculate_apertures(b,bundle)
    assert bundle.project==before
    return b,station,bundle,a


def test_bound_to_current_hydraulics_but_no_false_station_approval(current_study,tmp_path):
    from pypdf import PdfReader
    from scripts.build_samara_station_passport import render_station_review,verify_sources
    b,station,bundle,a=current_study
    before=deepcopy(a)
    r=review_station_documents(b,bundle.fire_station_result,station,a)
    assert a==before
    assert r['required_q_m3h']==pytest.approx(18.9789621486)
    assert r['required_station_boost_m']==pytest.approx(45.6611607114)
    assert r['maximum_pump_shutoff_m']==pytest.approx(60.2881192661)
    assert r['static_pressure_lowest_cabinet_mpa']==pytest.approx(.86774355)
    assert r['static_headroom_m']==pytest.approx(3.2881192661)
    assert r['screen']['nominal_bounds_met']
    assert r['duty_pumps']==r['reserve_pumps']==1 and not r['reserve_in_flow_sum']
    assert r['scenario_count_per_variant']==512 and r['checked_variants']==3
    assert r['flow_range_m3h'][0]>18.72 and r['flow_range_m3h'][1]<40
    assert r['internal_station_loss_m'] is None and r['guaranteed_station_curve'] is None
    assert not r['selection_confirmed'] and not r['release_ready'] and not r['production_modified']
    assert r['factory_control_check']['status']=='conflict'
    assert r['product_control_check']['status']=='needs_data'
    assert not r['evidence']['selection_confirmed']
    verify_sources()
    path=tmp_path/'station.pdf';render_station_review(path,r)
    pdf=PdfReader(path);assert len(pdf.pages)==3
    text=' '.join(' '.join(p.extract_text() for p in pdf.pages).split())
    for phrase in ['не отправлен','не комплект ИОС2','не учтена','Материал оставлен неопределённым',
                   'не разрешение на монтаж','Полный заказной код']:
        assert phrase in text


@pytest.mark.parametrize('mutation',['basis','curve','curve_source','station','missing_variant',
                                    'missing_case','duplicate_case','failure','nan'])
def test_stale_incomplete_and_failed_studies_rejected(current_study,mutation):
    b,station,bundle,original=current_study
    a=deepcopy(original)
    v=next(x for x in a['variants'] if x['name']=='next_size')
    if mutation=='basis':a['input_basis_sha256']='old'
    elif mutation=='curve':a['pump']['curve']=[(0,100),(40,50)]
    elif mutation=='curve_source':a['pump']['curve_sha256']='old'
    elif mutation=='station':a['pump']['station_model']='unrelated station'
    elif mutation=='missing_variant':a['variants'].remove(v)
    elif mutation=='missing_case':v['scenarios'].pop()
    elif mutation=='duplicate_case':v['scenarios'][-1]=deepcopy(v['scenarios'][0])
    elif mutation=='failure':v['scenarios'][0]['result']['status']='insufficient_at_cabinet'
    elif mutation=='nan':v['scenarios'][0]['result']['pump_head_m']=float('nan')
    with pytest.raises(ValueError):review_station_documents(b,bundle.fire_station_result,station,a)

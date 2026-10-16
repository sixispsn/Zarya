"""Pass 1: passport installation data, not fabricated drawings or new hydraulics."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.water_meters import router
from app.data.engineering_catalogue import get_engineering_catalogue
from app.data.metering_products import get_metering_catalogue
from app.pz.meter_products import bind_meter_products, primary_meter
from app.pz.metering_orientation import check_product_orientation
from app.pz.metering_flexible import FlexibleConnectionChoice, check_flexible_connection
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_layout import build_metering_layout
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from tests.test_meter_products import proposal


@pytest.mark.parametrize('dn,a,b', [(15,.06,.03),(20,.10,.05),(25,.14,.07),
                                  (32,.24,.12),(40,.40,.20),(50,1.20,.45)])
def test_decast_vertical_class_a_not_inferred_from_legacy(dn,a,b):
    p = get_metering_catalogue().products[f'decast-vskm90-dg-dn{dn}']
    for direction in ('vertical_up','vertical_down'):
        c = check_product_orientation(p,direction)
        assert c.allowed is True and c.qmin_m3h == a and c.metrological_class == 'A'
        assert '5.5' in c.reference
    assert check_product_orientation(p,'horizontal_dial_up').qmin_m3h == b
    assert check_product_orientation(p,'vertical').qmin_m3h is None


@pytest.mark.parametrize('dn', [65,80,100,125,150,200,250])
def test_tvm_up_only_class_not_transferred_from_decast(dn):
    p = get_metering_catalogue().products[f'tvm-vshnd-dn{dn}']
    c = check_product_orientation(p,'vertical_up')
    assert c.allowed is True and c.metrological_class == 'B'
    assert c.qmin_m3h == p.flows_m3h['qmin_B']
    assert check_product_orientation(p,'vertical_down').errors


def test_changed_mounting_rechecks_passport_without_changing_hydraulics():
    p = proposal()
    p.source.meter_minimum_checks = {'cold':dict(dn_mm=32,q_min_hourly_m3h=.2,flow_reference='Test')}
    bind_meter_products(p)
    r = primary_meter(p)
    before = (r.dn,r.s_resist,r.h_a,r.h_b,r.qexpl,r.need_bypass)
    assert r.ok_v is True and r.q_min_passport_m3h == .12
    p.metering_detail.assembly_orientation = 'vertical_up'
    p.metering_detail.meter_mounting = 'vertical_up'
    # Re-export without binding must reject stale 'passed' row evidence.
    svg = build_metering_detail_pages(p)[0]
    assert 'модель, класс A' in svg and '0,240' in svg
    assert 'не пройдена' in svg and 'модель, класс B' not in svg
    bind_meter_products(p)
    assert r.q_min_passport_m3h == .24 and r.ok_v is False
    assert before == (r.dn,r.s_resist,r.h_a,r.h_b,r.qexpl,r.need_bypass)
    assert 'класс A' in r.passport_reference


def test_filter_not_rotated_into_upflow():
    p = proposal()
    d = p.metering_detail
    d.catalogue_items['filter'] = 'valtec-vt192-dn32'
    d.assembly_orientation = 'vertical_up'
    d.meter_mounting = 'vertical_up'
    r = primary_meter(p)
    selected = resolve_metering_products(p,r,bypass=False,electric_bypass=False)
    assert selected.selected('meter') and selected.selected('filter') is None
    assert any('паспорт не разрешает' in e for e in selected.errors)
    d.component_orientations['filter'] = 'horizontal_dial_up'
    selected = resolve_metering_products(p,r,bypass=False,electric_bypass=False)
    assert selected.selected('filter')
    # Mixed geometry needs explicit elbows, never hidden automatic fittings.
    layout = build_metering_layout(p)
    assert not layout.parts and layout.issues and layout.special_layout_pending
    assert 'горизонтальный шаблон не применён' in ''.join(build_metering_detail_pages(p))


def test_catalogue_api_separates_forbidden_from_unconfirmed():
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    body = client.get('/meters/assembly-catalogue?dn=32&orientation=vertical_up').json()
    assert 'valtec-vt192-dn32' in body['coverage']['orientation_rejected']['filter']
    meter = next(p for p in body['equipment'] if p['id'] == 'decast-vskm90-dg-dn32')
    assert meter['installation']['minima']['vertical_up']['qmin_m3h'] == .24
    assert client.get('/meters/assembly-catalogue?orientation=sideways').status_code == 422


def choice(dn=80, pn=16):
    c = get_engineering_catalogue()
    ident = f'rushwork-{501 if pn == 16 else 500}-dn{dn}'
    return FlexibleConnectionChoice(ident,c.fingerprint(ident),2,0,0,0,'Test KR',
                                    '11','B',2 if dn == 80 else 1)


def check(value=None,**kwargs):
    args = dict(dn=80,material='steel',orientation='horizontal_dial_up',pressure_bar=8,temperature_c=20)
    args.update(kwargs)
    return check_flexible_connection(value or choice(),**args)


def test_twenty_exact_flex_sizes_and_distinct_pn_drilling():
    c = get_engineering_catalogue()
    assert len(c.search(kind='flexible_connection')) == 20
    assert c.require('rushwork-501-dn32').dimensions_mm['L'] == 95
    assert c.require('rushwork-500-dn200').ports[0].bolt_count == 8
    assert c.require('rushwork-501-dn200').ports[0].bolt_count == 12
    a,b = c.require('rushwork-500-dn250'), c.require('rushwork-501-dn250')
    assert a.ports[0].bolt_circle_mm == 350 and b.ports[0].bolt_circle_mm == 355
    assert a.native['movement_limits']['angular_deg'] == 15
    assert b.native['movement_limits']['angular_deg'] == 5
    assert not c.search(kind='flexible_connection',dn=300)
    assert not c.search(kind='flexible_connection',russian_only=True)


def test_flex_api_returns_versioned_choice_without_inventing_movements():
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    body = client.get('/meters/engineering-catalogue/rushwork-501-dn80/flexible-selection').json()
    value = FlexibleConnectionChoice(**body['choice'])
    assert value.catalogue_fingerprint == choice().catalogue_fingerprint
    assert value.extension_mm is None and value.angular_deg is None
    assert check(value)['status'] == 'needs_data'
    assert client.get('/meters/engineering-catalogue/decast-vskm90-dg-dn32/flexible-selection').status_code == 422


@pytest.mark.parametrize('changes,word', [
    ({'compression_mm':13},'превышено'),({'extension_mm':6},'превышено'),
    ({'angular_deg':6},'превышено'),({'lateral_mm':6},'превышено'),
    ({'compression_mm':float('nan')},'конечное'),({'extension_mm':-1},'неотрицательное'),
    ({'extension_mm':True},'конечное'),({'catalogue_fingerprint':'stale'},'карточка'),
    ({'extension_mm':1,'lateral_mm':1},'одновременное'),
    ({'mating_flange_type':'01'},'фланец'),({'mating_flange_series':1},'фланец'),
])
def test_flex_rejects_unusable_choices(changes,word):
    r = check(replace(choice(),**changes))
    assert r['status'] == 'incompatible' and any(word in e for e in r['errors'])
    assert not r['installation_approved']


@pytest.mark.parametrize('kwargs', [dict(dn=65),dict(material='pe'),dict(material='ppr'),
    dict(pressure_bar=17),dict(pressure_bar=-1),dict(pressure_bar=float('nan')),
    dict(temperature_c=100),dict(russian_only=True),dict(orientation='unknown')])
def test_flex_never_substitutes_size_material_pressure_or_orientation(kwargs):
    assert check(**kwargs)['status'] == 'incompatible'


def test_flex_pending_is_not_approved_seismic_solution():
    r = check(orientation='vertical_up')
    assert not r['errors'] and r['status'] == 'needs_data'
    assert any('стержни' in n for n in r['pending'])
    assert not r['seismic_approved'] and r['dimension_length_mm'] == 135
    r = check(replace(choice(),angular_deg=1))
    assert not r['errors'] and any('сочетания' in n for n in r['pending'])
    r = check(replace(choice(),extension_mm=None,movement_basis=''))
    assert any('явный ноль' in n for n in r['pending'])


def test_new_data_roundtrip_validation_and_current_project_recheck():
    from app.intake.yaml_io import load_request, dump_request
    from app.intake.studio_intake import build_handoff_request
    from tests.test_studio_apartment_meters import draft
    req = build_handoff_request(draft())
    d = req.metering_detail
    d.assembly_orientation = d.meter_mounting = 'vertical_up'
    d.component_orientations = {'filter':'horizontal_dial_up'}
    d.flexible_connections = {'inlet':choice()}
    restored = load_request(dump_request(req))
    assert asdict(restored.metering_detail) == asdict(d)
    bad = MeteringDetailData(flexible_connections={'inlet':{'unexpected':1}})
    assert bad.validate()
    p = proposal(); d = p.metering_detail
    d.flexible_connections = {'inlet':choice()}
    before = deepcopy(asdict(p))
    state = drawing_state(p)
    s = resolve_metering_products(p,state.meter,bypass=state.bypass,electric_bypass=state.electric_bypass)
    assert s.flexible_connections and any('DN' in e for e in s.errors)
    assert asdict(p) == before
    from app.pz.metering_spec import build_metering_spec_section
    rows = build_metering_spec_section(p).rows
    requirement = next(r for r in rows if 'Гибкое соединение ВУ' in r.name)
    assert requirement.qty is None and not requirement.catalogue_id
    assert 'выбор отклонён' in requirement.name

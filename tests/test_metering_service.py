from copy import deepcopy
from dataclasses import asdict, replace
import math

import pytest

from app.data.metering_products import get_metering_catalogue
from app.pz.metering_detail import drawing_state
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_joint_audit import audit_direct_joints, _port
from app.pz.metering_service import check_service_components
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_mounting import resolve_mounting, product_dimension_contents
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.intake.studio_metering import catalogue_proposal
from scripts.preview_metering_detail import catalogue_review_project


def example():
    p = catalogue_review_project()
    p.metering_detail.service_selection_mode = 'catalogue_proposal'
    return p


def selection(p):
    s = drawing_state(p)
    return resolve_metering_products(p, s.meter, bypass=s.bypass, electric_bypass=s.electric_bypass)


def by_role(p):
    return {c.role: c for c in selection(p).services}


def test_manual_default_and_optin_are_nonmutating():
    p = catalogue_review_project()
    assert all(s.part is None for s in selection(p).services)
    original = deepcopy(asdict(p))
    d = catalogue_proposal(p.metering_detail)
    assert d.service_selection_mode == 'catalogue_proposal'
    assert asdict(p) == original
    p = example(); original = deepcopy(asdict(p))
    r = by_role(p)
    assert r['control_cocks'].part.id == 'valtec-vt214-dn15'
    assert r['control_caps'].part.body_length_mm == 14
    assert r['gauge'].part.range_bar == 10
    assert r['gauge_cock'].part.id == 'valtec-vt806-0404'
    assert all(c.proposed for c in r.values())
    assert asdict(p) == original


@pytest.mark.parametrize('pressure,mode,expected', [(3,'variable',6), (6,'variable',10),
    (7,'constant',10), (7,'variable',16), (16,'variable',25), (17,'variable',None)])
def test_gauge_range_uses_maximum_pressure_and_manufacturer_duty(pressure, mode, expected):
    p=example(); d=p.metering_detail
    d.design_pressure_bar=pressure; d.gauge_pressure_mode=mode
    r=by_role(p)['gauge']
    assert (r.part.range_bar if r.part else None) == expected


def test_equality_at_variable_limit_is_included():
    p=example(); p.metering_detail.design_pressure_bar=10 * (2/3)
    assert by_role(p)['gauge'].part.range_bar == 10


@pytest.mark.parametrize('field', ['design_pressure_bar','water_temperature_c'])
def test_no_guess_from_guaranteed_head_when_pt_is_missing(field):
    p=example(); setattr(p.metering_detail,field,None)
    assert all(c.part is None for c in selection(p).services)


@pytest.mark.parametrize('role,ident', [('gauge','not-a-product'),
    ('gauge','valtec-vt214-dn15'), ('control_cocks','valtec-vt214-dn25'),
    ('control_caps','valtec-vtr583-plug-dn25'), ('gauge_cock','rosma-tm510r-g12-10bar')])
def test_bad_manual_assignments_never_fall_back(role,ident):
    p=example(); p.metering_detail.service_items[role]=ident
    c=by_role(p)[role]
    assert c.errors and c.part is None


def test_stale_pressure_invalidates_manual_gauge():
    p=example(); d=p.metering_detail
    d.service_items['gauge']='rosma-tm510r-g12-10bar'
    assert by_role(p)['gauge'].part
    d.design_pressure_bar=8
    assert by_role(p)['gauge'].part is None
    row=next(r for r in build_metering_spec_section(p).rows if 'gauge' in r.component_ids)
    assert row.catalogue_id == '' and row.qty==1


def test_catalogue_revision_and_russian_filter_are_not_bypassed():
    p=example(); p.metering_detail.russian_equipment_only=True
    assert all(c.part is None for c in selection(p).services)
    assert any(c.errors for c in selection(p).services)
    p=example(); p.metering_detail.catalogue_revision='old'
    p.metering_detail.service_items['gauge']='rosma-tm510r-g12-10bar'
    assert all(c.part is None for c in selection(p).services)
    assert by_role(p)['gauge'].errors


def test_current_meter_type_controls_both_cocks_and_caps():
    p=example(); s=drawing_state(p); catalog=get_metering_catalogue()
    turbine=replace(s.meter,dn=65,type_label='турбинный')
    r={c.role:c for c in check_service_components(p.metering_detail,turbine,catalog,revision_ok=True)}
    assert r['control_cocks'].part.dn==25 and r['control_caps'].part.dn==25
    assert r['control_caps'].part.body_length_mm is None
    unknown=replace(s.meter,type_label='неизвестно')
    r={c.role:c for c in check_service_components(p.metering_detail,unknown,catalog,revision_ok=True)}
    assert r['control_cocks'].part is None and r['control_caps'].part is None


def test_manufacturer_dimension_conflicts_are_retained_not_rounded():
    c=get_metering_catalogue()
    assert c.service_products['valtec-vtr583-plug-dn15'].body_length_mm==14
    for ident in ['valtec-vtr583-plug-dn25']:
        part=c.service_products[ident]
        assert part.dimension_status=='conflict' and part.body_length_mm is None
        assert part.source_ids and part.notes


def test_gauge_cock_passport_length_is_explicit_not_an_average_or_mounting_approval():
    part=get_metering_catalogue().service_products['valtec-vt806-0404']
    assert part.body_length_mm == 75
    assert part.dimension_status == part.dimension_basis == 'passport_nominal'
    assert part.dimension_source_id == 'vu-service-vt806'
    assert '75,1' in part.notes[0] and 'Не усреднение' in part.notes[0]
    assert 'монтажную длину уточнить' in ' '.join(by_role(example())['gauge_cock'].pending)
    assert any('паспортный размер принят только для компоновки' in s
               for s in resolve_mounting(example()).issues)
    from app.data.engineering_catalogue import get_engineering_catalogue
    item=get_engineering_catalogue().require(part.id,verified=False)
    assert item.status=='conflict' and item.dimensions_mm['L']==75
    assert item.native['dimension_status']=='passport_nominal'
    with pytest.raises(ValueError,match='размеры не подтверждены'):
        get_engineering_catalogue().require(part.id)


def test_terminal_ports_and_gauge_sealing_do_not_invent_a_confirmed_assembly():
    p=example(); s=drawing_state(p); c=get_metering_catalogue()
    chain=build_metering_chain(p.metering_detail,s,selection(p))
    checks={j.id:j for j in audit_direct_joints(chain,c)}
    for n in (1,2):
        assert checks[f'control_cock_{n}>control_cap_{n}'].status=='ports_match'
        assert _port(chain.node(f'control_cap_{n}'),c,'out',50) is None
    assert _port(chain.node('gauge'),c,'out',50) is None
    gauge=checks['gauge_cock>gauge']
    assert gauge.status=='unresolved' and gauge.left.seal==gauge.right.seal=='flat_gasket'
    assert checks['service_before>control_cock_1'].status=='unresolved'
    assert not chain.installation_complete
    assert not resolve_mounting(p).dimensions_complete


def test_spec_quantity_identity_and_no_extra_supplied_gasket():
    p=example(); before=deepcopy(asdict(p.meters))
    rows=build_metering_spec_section(p).rows
    for mark,quantity in [('4.1',2),('4.2',2),('3.1',1),('3.2',1)]:
        r=next(r for r in rows if r.diagram_pos==mark)
        assert r.qty==quantity and r.unit=='шт.' and r.catalogue_id
    assert 'прокладка' in next(r.note for r in rows if r.diagram_pos=='3.2')
    assert not any('прокладка' in r.name.lower() for r in rows)
    assert asdict(p.meters)==before
    assert {i for r in rows for i in r.component_ids}=={n.id for n in build_metering_layout(p).parts}


@pytest.mark.parametrize('scale',[5,10,20])
def test_service_layout_uses_real_lengths_but_no_gauge_through_length(scale):
    p=example(); p.metering_detail.mounting.scale=scale
    layout=build_metering_layout(p)
    assert not layout.issues
    for ident,length in [('control_cock_1',47.5),('control_cap_1',14),('gauge_cock',75)]:
        part=layout.part(ident)
        assert math.dist(*part.points)*scale==pytest.approx(length)
    assert layout.part('gauge').length_mm is None
    assert layout.part('gauge').gauge_diameter_mm==100
    assert layout.part('gauge').gauge_center_height_mm==85
    assert layout.part('gauge_cock').length_mm == 75
    text=''.join(layout_contents(p))
    assert 'VT.806.N.0404' in text and 'VTr.583.N.0004' in text and 'ТМ-510Р' in text
    assert 'Терминальный прибор' in ''.join(product_dimension_contents(p,drawing_state(p)))


@pytest.mark.parametrize('data',[{'service_items':[]},{'service_items':{'bad':'x'}},
    {'service_items':{'gauge':None}},{'service_selection_mode':'auto'}, {'gauge_pressure_mode':'guess'}])
def test_service_inputs_are_validated(data):
    assert MeteringDetailData(**data).validate()


def test_service_settings_dataclass_roundtrip():
    d=MeteringDetailData(service_items={'gauge':'rosma-tm510r-g12-10bar'},
        service_selection_mode='catalogue_proposal',gauge_pressure_mode='variable')
    assert asdict(MeteringDetailData(**asdict(d)))==asdict(d)


def test_normal_pdf_path_contains_service_audit_not_only_preview():
    from app.pz.metering_detail import build_metering_detail_pages
    p=example()
    text=''.join(build_metering_detail_pages(p))
    assert 'VT.806.N.0404' in text and 'VTr.583.N.0004' in text
    assert '75,1' in text and 'ТМ-510Р' in text
    assert '2/3 шкалы' in text and 'торцевое' in text.lower()
    p.metering_detail.catalogue_items={}
    assert 'VT.806.N.0404' in ''.join(build_metering_detail_pages(p))

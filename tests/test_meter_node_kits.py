from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import pytest

from app.pz import metering_accessories as accessories
from app.pz import metering_spec
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.spec import build_water_specification
from tests.test_apartment_accessories import samara
from scripts.preview_metering_detail import catalogue_review_project


def section(p):
    return next(s for s in build_water_specification(p).sections if s.title == 'В1 — Водомерный узел')


def kits(p):
    return [r for s in build_water_specification(p).sections for r in s.rows
            if any(k in ('kit_in','meter_cold_kit','hot:kit_in') for k in r.component_ids)]


def test_samara_all_meters_have_one_kit_not_two_per_end_or_inlet(samara):
    before = deepcopy(asdict(samara))
    rows = kits(samara)
    assert [r.qty for r in rows] == [2,1,1]
    assert [r.catalogue_id for r in rows] == ['decast-vskm90-kit-dn50',
        'decast-vskm90-kit-dn32', 'decast-vskm90-kit-dn32']
    assert all(r.unit == 'компл.' and 'повторно не закупать' in r.note for r in rows)
    assert all('не на каждый ввод' in r.quantity_source for r in rows[1:])
    assert all(r.qty is None for r in section(samara).rows if r.unit in ('м','кг'))
    assert asdict(samara) == before
    state = drawing_state(samara)
    selection = resolve_metering_products(samara,state.meter,bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    graph = build_metering_chain(samara.metering_detail,state,selection)
    # Two mating interfaces reference ONE factory kit; quantity is owned by SO.
    assert graph.node('kit_in').catalogue_id == graph.node('kit_out').catalogue_id == rows[0].catalogue_id
    assert rows[0].component_ids == ('kit_in', 'kit_out') and rows[0].qty == state.inputs_count
    assert rows[0].component_ids == ('kit_in','kit_out')
    assert selection.assembly_length_mm is None
    svg = ' '.join(' '.join(ET.fromstring(svg).itertext()) for svg in build_metering_detail_pages(samara))
    assert 'Комплект присоединительных частей ДЕКАСТ ВСКМ 90 DN50' in svg
    assert '448 мм СПРАВОЧНО' in svg


@pytest.mark.parametrize('count',[1,2,3])
def test_only_common_kit_quantity_follows_inlets(samara,count):
    samara.source.inputs_count = samara.meters.inputs_count = count
    samara.v1_network = None
    assert [r.qty for r in kits(samara)] == [count,1,1]


@pytest.mark.parametrize('change',['missing','duplicate','thread','status','source','meter_id'])
def test_bad_kit_never_deletes_need_or_chooses_first(samara,monkeypatch,change):
    cat = metering_spec.get_metering_catalogue()
    variants = dict(cat.connection_kits)
    key = 'decast-vskm90-kit-dn32'
    old = variants[key]
    if change == 'missing': del variants[key]
    elif change == 'duplicate': variants['duplicate'] = replace(old,id='duplicate')
    elif change == 'thread': variants[key] = replace(old,meter_thread='2')
    elif change == 'status': variants[key] = replace(old,status='conflict')
    elif change == 'source': variants[key] = replace(old,source_ids=('missing',))
    else: variants[key] = replace(old,meter_ids=('another-meter',))
    monkeypatch.setattr(metering_spec,'get_metering_catalogue',lambda:replace(cat,connection_kits=variants))
    # The hot kit now belongs to a real assembly resolver, not a loose row.
    from app.pz import metering_product_selection
    monkeypatch.setattr(metering_product_selection,'get_metering_catalogue',lambda:replace(cat,connection_kits=variants))
    a,b,c = kits(samara)
    assert a.catalogue_id.endswith('dn50')
    assert b.qty == c.qty == 1 and not b.catalogue_id and not c.catalogue_id


@pytest.mark.parametrize('change',['revision','model','dn','technology'])
def test_current_meter_revalidated_without_saved_row_cache(samara,change):
    if change == 'revision': samara.metering_detail.catalogue_revision = 'old'
    elif change == 'technology': samara.metering_detail.enhancements['technology']='ultrasonic'
    elif change == 'model': samara.metering_detail.meter_products['cold']='unknown'
    else:
        cold = next(r for r in samara.meters.rows if 'ХВС' in r.label)
        cold.dn = 40
    by_id={r.component_ids:r for r in kits(samara)}
    cold = by_id[('meter_cold_kit',)]
    assert cold.qty == 1
    if change == 'dn': assert cold.catalogue_id.endswith('dn40')
    else: assert not cold.catalogue_id
    if change == 'model': assert by_id[('hot:kit_in','hot:kit_out')].catalogue_id.endswith('dn32')


def test_explicit_wrong_main_kit_not_replaced_but_branch_kits_independent(samara):
    samara.metering_detail.catalogue_items['meter_connections']='decast-vskm90-kit-dn15'
    rows=kits(samara)
    assert rows[0].qty == 2 and not rows[0].catalogue_id
    assert all(r.catalogue_id.endswith('dn32') for r in rows[1:])
    assert samara.metering_detail.catalogue_items['meter_connections'].endswith('dn15')


def test_cold_primary_is_not_duplicated_and_manual_mode_not_auto_proposal():
    p = catalogue_review_project()
    # Source review has a cold-only main meter, not a fictitious total node.
    rows=kits(p)
    assert [r.qty for r in rows] == [1,1]
    assert rows[0].catalogue_id.endswith('dn32')
    assert rows[1].component_ids == ('hot:kit_in','hot:kit_out') and not rows[1].catalogue_id
    p.meters.rows = p.meters.rows[:1]
    assert len(kits(p)) == 1


def test_no_kit_matched_to_flanged_or_unverified_body():
    cat=metering_spec.get_metering_catalogue()
    meter=cat.products['decast-vskm90-dg-dn50']
    for mutant in (replace(meter,connection_standard='flange'),
                   replace(meter,connection_sex='female'),
                   replace(meter,dimension_status='conflict')):
        assert accessories.propose_connection_kit(cat,mutant) is None

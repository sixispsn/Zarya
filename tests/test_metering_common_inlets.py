"""Common VU is a design choice; inlet duty and hydraulic algorithms stay put."""
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.intake.studio_intake import FIELD_MAP, field_state, answer_field
from app.intake.studio_metering import studio_layout_choices
from app.intake.studio_store import StudioStore
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_maintenance import audit_metering_maintenance, network_from_chain
from app.pz.metering_supply import extend_service_network
from app.pz.metering_presentation import metering_presentation
from app.pz.metering_rules import evaluate_metering_rules
from app.pz.metering_hot_node import hot_meter_view, hot_drawing_state, hot_spec_section
from scripts.preview_metering_detail import review_project


def common_project():
    p = review_project(2)
    p.metering_detail.inlet_metering_mode = "common"
    # Deliberate drawing input of this fixture, not a production default.
    p.metering_detail.bypass_dn = 50
    return p


def chain_for(p):
    s = drawing_state(p)
    selection = resolve_metering_products(p,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    return s, build_metering_chain(p.metering_detail,s,selection)


def test_new_studio_default_and_existing_draft_migration(tmp_path):
    store = StudioStore(tmp_path)
    ident, draft = store.create()
    assert field_state(draft,FIELD_MAP['vu_per_inlet'])['value'] == 'no'
    assert studio_layout_choices(MeteringDetailData(),{}).inlet_metering_mode == 'common'
    # Persisted pre-feature draft keeps the former per-inlet design.
    draft.pop('metering_default')
    store._write(store.folder(ident),draft)
    old = store.load(ident)
    assert field_state(old,FIELD_MAP['vu_per_inlet'])['value'] == 'yes'
    answer_field(old,'vu_per_inlet','no')
    assert field_state(old,FIELD_MAP['vu_per_inlet'])['value'] == 'no'


def test_choice_roundtrip_and_bad_value():
    d = studio_layout_choices(MeteringDetailData(), {'vu_per_inlet':'yes'})
    assert d.inlet_metering_mode == 'per_inlet'
    assert MeteringDetailData(**asdict(d)).inlet_metering_mode == 'per_inlet'
    assert MeteringDetailData(**asdict(replace(d,inlet_metering_mode='common'))).inlet_metering_mode == 'common'
    assert replace(d,inlet_metering_mode='bad').validate()
    assert MeteringDetailData().inlet_metering_mode == 'per_inlet'  # legacy YAML


@pytest.mark.parametrize('mode,units', [('common',1),('per_inlet',2)])
def test_meter_and_support_quantities_not_inlet_count(mode,units):
    p = common_project()
    p.metering_detail.inlet_metering_mode = mode
    p.metering_detail.mounting.support_count = 2
    p.metering_detail.mounting.support_basis = 'Две опоры на один ВУ'
    before = deepcopy(asdict(p))
    s,chain = chain_for(p)
    assert s.inputs_count == 2 and s.assemblies_count == units and chain.instances == units
    rows = build_metering_spec_section(p).rows
    meter = next(r for r in rows if r.component_ids == ('meter',))
    assert meter.qty == units
    assert next(r for r in rows if r.quantity_basis == 'explicit_vu_supports').qty == 2*units
    assert len([r for r in rows if 'supply_valve_1' in r.component_ids]) == (mode=='common')
    assert asdict(p) == before


def test_common_bypass_does_not_mutate_hydraulic_result_or_auto_electric():
    p = common_project()
    before = deepcopy(asdict(p.meters))
    s = drawing_state(p)
    assert not p.meters.has_bypass and s.bypass and not s.electric_bypass
    assert asdict(p.meters) == before
    assert s.meter.h_a == review_project(2).meters.rows[0].h_a
    rules = evaluate_metering_rules(p,s.meter,inputs_count=2,bypass=s.bypass)
    assert any(r.code=='VU-COMMON-INLETS' for r in rules)
    assert not any('отсутствие обводной допустимо' in r.message for r in rules)
    assert 'один общий ВУ' in metering_presentation(p)['inlet']
    assert 'не делится пополам' in metering_presentation(p)['inlet']
    s.meter.need_bypass = True
    assert drawing_state(p).electric_bypass


def test_actual_sources_and_isolation_in_common_network():
    p = common_project()
    s,chain = chain_for(p)
    net = extend_service_network(network_from_chain(p.metering_detail,chain),s)
    net.validate()
    assert {n.id for n in net.nodes if n.kind=='source'} == {
        'supply_source_1','supply_source_2','outlet','supply_fire_outlet_1','supply_fire_outlet_2'}
    # All real feed shutoffs are retained; one closed feed cannot isolate the header.
    from app.pz.maintenance_engine import assess_removal
    header = assess_removal(net,'inlet')
    assert {'supply_valve_1','supply_valve_2'} <= set(header.close_valves)
    report = audit_metering_maintenance(p)
    assert report['instances']==1 and not report['safe_to_remove']
    assert {'supply_valve_1','supply_valve_2'} <= {r['target'] for r in report['scenarios']}


def test_two_wall_crossings_one_vu_and_hot_node_stays_independent():
    p = common_project()
    svg = build_metering_detail_pages(p)[0]
    root = ET.fromstring(svg)
    assert len([e for e in root.iter() if e.get('data-wall-crossing')]) == 2
    assert not any(e.get('data-common-vu-reference') for e in root.iter())
    assert len([e for e in root.iter() if e.get('data-vu-component') == 'meter']) == 1
    assert 'ВУ-2' not in svg and 'data-pre-meter-fire="true"' in svg
    assert svg.count('data-pre-meter-fire="true"') == 2
    assert 'fire_takeoff' not in {n.id for n in chain_for(p)[1].nodes}
    hot = hot_meter_view(p)
    assert hot_drawing_state(hot).assemblies_count == 1
    assert not hot_drawing_state(hot).bypass
    assert next(r.qty for r in hot_spec_section(p).rows if r.component_ids==('hot:meter',)) == 1


def test_single_inlet_choice_has_no_quantity_effect():
    p = review_project(1)
    p.metering_detail.inlet_metering_mode = 'common'
    s = drawing_state(p)
    assert s.inputs_count == s.assemblies_count == 1 and not s.common_inlets
    assert not any('supply_' in i for r in build_metering_spec_section(p).rows for i in r.component_ids)


def test_unknown_bypass_dn_is_not_inferred_from_inlet():
    p = common_project()
    p.metering_detail.bypass_dn = None
    assert 'DN обводной линии не задан' in drawing_state(p).missing
    row = next(r for r in build_metering_spec_section(p).rows if r.component_ids==('bypass_valve',))
    assert 'DN уточнить' in row.name


@pytest.mark.parametrize('mode', ['common', 'per_inlet'])
def test_pz_and_calculation_sheet_agree_on_metering_arrangement(mode):
    from app.pz.generator import generate_pz_html, generate_v1_calculation_html
    p = common_project()
    p.metering_detail.inlet_metering_mode = mode
    for render in (generate_pz_html, generate_v1_calculation_html):
        html = render(p)
        assert ('Принят один общий вводной ВУ для 2 вводов' in html) == (mode == 'common')
        assert ('Приняты 2 одинаковых вводных узла учёта' in html) == (mode == 'per_inlet')
        assert ('Обводная общего ВУ предусмотрена для обслуживания' in html) == (mode == 'common')


def test_ordinary_studio_handoff_and_calculation_do_not_split_flow(tmp_path):
    from tests.test_studio_apartment_meters import draft
    from app.intake.studio_project import calculate_project
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    d = draft(inputs_count=2)
    req = load_request(dump_request(build_handoff_request(d)))
    assert req.metering_detail.inlet_metering_mode == 'common'
    common = calculate_project(d)
    answer_field(d,'vu_per_inlet','yes')
    separate = calculate_project(d)
    assert common['metering_layout']['assemblies_count'] == 1
    assert separate['metering_layout']['assemblies_count'] == 2
    for key in ('flows','head','hydraulics','hot_hydraulics','pumps','meters'):
        assert common[key] == separate[key],key

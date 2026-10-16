from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from tests.test_water_station_drafting import samara
from tests.test_water_station_review import common
from app.data.booster_service import booster_service
from app.pz.water_station_review import branches, connected_network, review_station
from app.pz.maintenance_engine import assess_removal
from app.pz.water_station_drafting import build_pump_zone_scheme_pages


def test_exact_service_source_and_selected_identity(common):
    ref = booster_service(common.pumps)
    assert ref and 'рис. 7-Н' in ref['source']
    assert 'поз. 28' in ref['drain'] and 'поз. 36' in ref['vent']
    assert len(ref['source_sha256']) == 64
    assert not ref['live_maintenance_approved']
    common.pumps.top3 = []
    assert booster_service(common.pumps) is None


@pytest.mark.parametrize('model', ['CNP / Aikon PBS CDM15-5 extra', 'CNP / Aikon PBS CDM15-7', 'Other CDM15-5'])
def test_service_not_inherited_from_similar_or_stale_model(common, model):
    common.pumps.model = model
    assert booster_service(common.pumps) is None
    assert not any(n.id.startswith('station_pump_drain_') for n in connected_network(common).nodes)


def test_factory_ports_are_not_common_collector_or_fake_air_valves(common):
    n = connected_network(common)
    svg = build_pump_zone_scheme_pages(common)[0]
    for b in branches(common):
        for k in ('drain','vent'):
            port = next(p for p in n.ports if p.id == b[k])
            assert port.node != b['pump']
            assert any({e.a,e.b} == {b['pump'],port.node} for e in n.links)
            assert not port.discharge_basis  # receiving arrangement not guessed
            assert f'data-component="{b[k]}"' in svg
            assert b[k+'_mark'] in svg
        r = assess_removal(n,b['pump'],closed_valves={b['inlet'],b['outlet']})
        assert b['drain'] in r.drain_ports and b['vent'] in r.air_ports
        assert 'station_common_drain' not in r.drain_ports
        assert r.isolation == 'checked' and not r.safe_to_remove
        assert r.pressure_relief == r.drainage == r.air_admission == 'blocked'
        assert b['pocket'] in r.trapped_nodes


def test_even_confirmed_pump_drain_does_not_empty_check_pocket(common):
    n = connected_network(common)
    b = branches(common)[0]
    # Evidence for the body alone must not propagate through a passive check.
    n = replace(n,
        nodes=tuple(replace(x,body_drainable=True) if x.id == b['pump'] else x for x in n.nodes),
        ports=tuple(replace(p,discharge_basis='Контрольный приёмник, явно заданный в тесте')
                    if p.id in (b['drain'],b['vent']) else p for p in n.ports))
    r = assess_removal(n,b['pump'],closed_valves={b['inlet'],b['outlet']})
    assert b['pump'] not in r.trapped_nodes and b['pump'] not in r.unknown_drain_nodes
    assert b['pocket'] in r.trapped_nodes
    assert r.pressure_relief == r.drainage == 'blocked'
    assert not r.safe_to_remove


def test_service_never_permits_live_work_and_changes_no_calculation(common):
    before = deepcopy(asdict(common))
    r = review_station(common)
    assert all(s['delivery_path_exists'] and not s['live_maintenance_approved'] for s in r['scenarios'])
    assert all('НОК' in s['pocket_note'] and 'НЗ' in s['pocket_note'] for s in r['scenarios'])
    assert not r['operation_approved']
    assert asdict(common) == before


def test_existing_duty_checked_but_never_approves_new_losses(common):
    def check():
        report = review_station(common)
        assert not report['hydraulic_capacity_confirmed']
        assert next(x for x in report['hydraulic'] if x['id']=='new_losses')['value'] == 'Не подтверждены'
        return next(x for x in report['hydraulic'] if x['id']=='existing_duty_check')
    assert check()['status'] == 'verified'
    common.source.h_tepl_m += 1
    assert check()['status'] == 'missing'
    assert 'изменились' in check()['note']


def test_stale_pump_curve_not_hidden_by_valid_service_hardware(common):
    common.pumps.wp_h += 1
    r = review_station(common)
    assert r['service']
    assert next(x for x in r['hydraulic'] if x['id']=='existing_duty_check')['status'] == 'fail'


def test_spec_one_factory_owner_no_duplicate_purchase_and_pz(common):
    from app.pz.spec import build_specification
    from app.pz.generator import generate_pz_html
    rows = [r for sec in build_specification(common).sections for r in sec.rows]
    for b in branches(common):
        for k in ('drain','vent'):
            owners = [r for r in rows if b[k] in r.component_ids]
            assert len(owners)==1 and 'station_assembly' in owners[0].component_ids
            assert 'штатные части насосов' in owners[0].note
    html = generate_pz_html(common)
    assert 'СВ1/2' in html and 'НОК1 - НЗ2' in html
    assert 'Пара Q/H подтверждена' in html and 'РЭ Aikon PBS' in html

"""Service nodes and circulation-layout takeoff, never hydraulic inventions."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
import subprocess

import pytest
import yaml

from app.intake.project_builder import build_project
from app.intake.studio_intake import answer_field, build_handoff_request, IntakeError
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.spec import build_water_specification, build_wastewater_specification
from app.pz.water_service_assemblies import WaterServiceLayout, SERVICE_COUNTS
from tests.test_studio_apartment_meters import draft
from tests.test_apartment_accessories import samara
from tests.test_studio import client, new, answer


def rows(p):
    return {key: row for s in build_water_specification(p).sections for row in s.rows for key in row.component_ids}


def project(**answers):
    return build_project(build_handoff_request(draft(**answers)))


def test_unknown_requirements_persist_for_all_three_systems():
    p = project(risers_v1=9, risers_t3=9, risers_t4=2)
    before = deepcopy(asdict(p))
    rr = rows(p)
    for system in ('v1', 't3', 't4'):
        for key in ('air-collector', 'air-isolation', 'air-vent', 'drain-valve'):
            row = rr[system + '-' + key]
            assert row.qty is None and row.unit == 'шт.' and row.quantity_basis == 'needs_layout'
            assert '11.17' in row.note and 'DN15' not in row.type_mark and 'Ду15' not in row.name
    assert rr['circulation-balance'].qty is None
    assert asdict(p) == before


def test_selected_per_riser_composition_and_riser_return_balancing():
    d = draft(risers_v1=9, risers_t3=9, risers_t4=2,
              water_service_mode='per_riser', hws_balance_mode='riser_returns')
    req = build_handoff_request(d)
    assert not req.validate()
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    rr = rows(p)
    for system, n in (('v1', 9), ('t3', 9), ('t4', 2)):
        for key in ('air-collector', 'air-isolation', 'air-vent', 'drain-valve'):
            r = rr[system+'-'+key]
            assert r.qty == n and r.quantity_basis == 'project_input'
            assert 'на стояк' in r.quantity_source
        # Drains/air isolation do not replace the separately counted base valves.
        assert rr[system+'-riser-valve'].qty == n
    assert rr['circulation-balance'].qty == 2
    assert rr['circulation-balance'].type_mark == 'DN, Kv и настройка по расчёту'
    answer_field(d, 'risers_t4', None)
    rr = rows(build_project(build_handoff_request(d)))
    assert rr['t4-air-vent'].qty is None and rr['circulation-balance'].qty is None


@pytest.mark.parametrize('mode', ['collection_branches', 'floor_loops', 'towel_rail_returns'])
def test_balance_by_connections_not_floors_apartments_or_risers(mode):
    p = project(risers_t4=99, apartments=500, hws_balance_mode=mode)
    assert rows(p)['circulation-balance'].qty is None
    p.building.water_service_layout = replace(p.building.water_service_layout, balance_count=7)
    rr = rows(p)
    assert rr['circulation-balance'].qty == 7
    assert '7' not in rr['circulation-balance'].type_mark
    if mode == 'towel_rail_returns':
        assert rr['circulation-balance-collectors'].qty is None
        p.building.water_service_layout = replace(p.building.water_service_layout, balance_collector_count=2)
        rr = rows(p)
        assert rr['circulation-balance'].qty == 7 and rr['circulation-balance-collectors'].qty == 2
        assert '10.7' in rr['circulation-balance'].note


def test_independent_upper_lower_counts_and_zero_roundtrip():
    req = build_handoff_request(draft(water_service_mode='explicit',
        water_service_v1_upper=2, water_service_v1_lower=5,
        water_service_t3_upper=0, water_service_t4_lower=3))
    assert load_request(dump_request(req)) == req
    rr = rows(build_project(req))
    for k in ('v1-air-collector', 'v1-air-isolation', 'v1-air-vent'):
        assert rr[k].qty == 2
    assert rr['v1-drain-valve'].qty == 5
    assert rr['t3-air-vent'].qty == 0 and 'проверить' in rr['t3-air-vent'].note
    assert rr['t3-drain-valve'].qty is None
    assert rr['t4-drain-valve'].qty == 3 and rr['t4-air-vent'].qty is None


@pytest.mark.parametrize('bad', [True, -1, 1.5, 1_000_001, float('nan'), float('inf'), '2'])
def test_strict_dto_yaml_and_direct_spec_counts(bad):
    layout = WaterServiceLayout(mode='explicit', v1_upper=bad)
    req = replace(build_handoff_request(draft()), water_service_layout=layout)
    assert any('v1_upper' in s for s in req.validate())
    with pytest.raises(YamlFormatError):
        load_request(dump_request(req))
    p = project()
    p.building.water_service_layout = layout
    with pytest.raises(ValueError):
        rows(p)
    if bad != '2':  # Studio deliberately accepts typed numeric text.
        with pytest.raises(IntakeError):
            answer_field(draft(), 'water_service_v1_upper', bad)


def test_inactive_modes_do_not_reuse_stale_counts():
    req = build_handoff_request(draft(water_service_mode='per_riser', water_service_v1_upper=99,
                                    hws_balance_mode='riser_returns', hws_balance_count=99))
    assert req.water_service_layout.v1_upper is None and req.water_service_layout.balance_count is None
    assert WaterServiceLayout(v1_upper=2).validate()
    assert WaterServiceLayout(balance_mode='riser_returns', balance_count=2).validate()
    assert WaterServiceLayout(balance_mode='floor_loops', balance_collector_count=2).validate()


@pytest.mark.parametrize('kind', ['none', 'local'])
def test_no_hot_service_nodes_or_balancers_for_absent_central_hws(kind):
    p = project(hws_type=kind, water_service_mode='explicit', water_service_v1_upper=3,
        water_service_t3_upper=99, hws_balance_mode='towel_rail_returns', hws_balance_count=99)
    rr = rows(p)
    assert rr['v1-air-vent'].qty == 3
    assert not any(k.startswith(('t3-air-', 't4-air-', 'circulation-balance')) for k in rr)
    assert p.building.water_service_layout.balance_mode == 'unspecified'


def test_old_yaml_samara_hydraulics_and_wastewater_are_unchanged(samara):
    req = build_handoff_request(draft())
    assert 'water_service_layout' not in yaml.safe_load(dump_request(req))['building']
    assert load_request(dump_request(req)) == req
    before = deepcopy(asdict(samara))
    old_k = asdict(build_wastewater_specification(samara))
    rr = rows(samara)
    assert rr['v1-air-vent'].qty is None and rr['circulation-balance'].qty is None
    assert asdict(samara) == before
    p = deepcopy(samara)
    p.building.water_service_layout = WaterServiceLayout(mode='per_riser', balance_mode='riser_returns')
    assert asdict(build_wastewater_specification(p)) == old_k
    assert (p.flows.q_day_tot, p.flows.q_sec_tot) == (63, 3.185)
    assert (p.pumps.q_design_m3h, p.pumps.h_design_m) == pytest.approx((11.466, 50.25))


def test_http_optional_choices_recalculate_only_quantities_and_revoke_preview(client):
    state = new(client)
    answers = {k:r['value'] for k,r in draft(risers_v1=9, risers_t3=9, risers_t4=2)['answers'].items()}
    response = client.post('/studio/api/calculate', json={'revision':state['revision'], 'answers':answers})
    assert response.status_code == 200, response.text
    state = response.json()
    baseline = state['project_calculation']
    assert baseline['can_preview']
    for mode, balance in [('per_riser','riser_returns'), ('unspecified','unspecified')]:
        state = answer(client,state,'water_service_mode',mode)
        state = answer(client,state,'hws_balance_mode',balance)
        assert state['project_calculation'] is None and state['preview'] is None
        response = client.post('/studio/api/calculate', json={'revision':state['revision']})
        assert response.status_code == 200, response.text
        state = response.json()
        result = state['project_calculation']
        assert result['can_preview']
        for key in ('flows', 'head', 'meters', 'pumps'):
            assert result[key] == baseline[key]
        missing = result['spec_quantity_review']['counts']['missing']
        assert baseline['spec_quantity_review']['counts']['missing'] - missing == (13 if mode == 'per_riser' else 0)
        assert client.get('/studio/api/draft').json()['project_calculation'] == result


def test_optional_ui_hides_inactive_counts_and_keeps_three_main_groups():
    code = """global.window={}; require('./app/web/static/studio_configurator.js');
    const c=window.ZaryaConfigurator;
    console.log(JSON.stringify({groups:c.groups, visible:[
      c.fanFieldVisible('water_service_t3_upper',{water_service_mode:'explicit',hws_type:'none'}),
      c.fanFieldVisible('water_service_v1_upper',{water_service_mode:'per_riser'}),
      c.fanFieldVisible('hws_balance_count',{hws_type:'central',hws_balance_mode:'riser_returns'}),
      c.fanFieldVisible('hws_balance_collector_count',{hws_type:'central',hws_balance_mode:'floor_loops'}),
      c.fanFieldVisible('hws_balance_collector_count',{hws_type:'central',hws_balance_mode:'towel_rail_returns'})]}));"""
    out = subprocess.run([os.environ['NODE_BINARY'], '-e', code], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    assert data['visible'] == [False, False, False, False, True]
    assert len(data['groups']) == 3
    keys = {'water_service_mode', 'hws_balance_mode', 'hws_balance_count', 'hws_balance_collector_count',
            *('water_service_'+s for s in SERVICE_COUNTS)}
    assert not keys.intersection(k for g in data['groups'] for k in g['primary'])
    assert keys.issubset(k for g in data['groups'] for _, fields in g['sections'] for k in fields)


@pytest.mark.parametrize('mode', ['collection_branches', 'floor_loops', 'towel_rail_returns'])
def test_alternative_takeoff_does_not_draw_a_false_roof_short_circuit(samara, mode):
    from app.pz.hws_building_drafting import can_draw_hws_section, build_hws_section
    from app.pz.water_residential_section import can_draw_residential_water_section
    from app.pz.water_station_drafting import build_pump_zone_scheme_pages
    samara.building.water_service_layout = WaterServiceLayout(balance_mode=mode, balance_count=7)
    assert not can_draw_hws_section(samara) and not can_draw_residential_water_section(samara)
    with pytest.raises(ValueError, match='компоновки'):
        build_hws_section(samara, 3, 3)
    pages = build_pump_zone_scheme_pages(samara)
    assert len(pages) == 2 and 'В1.' in pages[0]
    assert 'переданы в спецификацию' in pages[1] and 'требует дополнения' in pages[1]
    assert 'data-pipe="representative-circulation"' not in pages[1]
    assert 'data-component="circulation-balance"' not in pages[1]


@pytest.mark.parametrize('mode', ['collection_branches', 'floor_loops', 'towel_rail_returns'])
def test_full_scheme_routing_keeps_v1_and_does_not_restore_false_t4_in_fallback(mode):
    from tests.test_water_unified_section import project as example
    from app.pz.generator import generate_scheme_result
    p = example()
    p.building.water_service_layout = WaterServiceLayout(balance_mode=mode, balance_count=7)
    result = generate_scheme_result(p)
    assert 'data-water-section="unified"' in result.svg
    assert 'В1. Принципиальная схема здания' in result.svg
    assert 'компоновка выбранной циркуляции требует дополнения' in result.svg
    assert 'data-system="Т4"' not in result.svg and 'data-system="Т3"' not in result.svg
    assert any('Т3/Т4:' in w for w in result.warnings)

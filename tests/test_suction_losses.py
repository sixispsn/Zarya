from copy import deepcopy
from dataclasses import asdict, replace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.pumps import router
from app.calc.suction_losses import SuctionLoss, bind_suction_losses
from app.calc.v1_hydraulics import V1SectionInput, calculate_v1_hydraulics
from app.pz.water_station_suction import suction_path_manifest
from app.pz.water_station_review import connected_network, review_station
from tests.test_water_station_drafting import samara
from tests.test_water_station_review import common
from tests.test_pump_suction import example


def bind(rows=(), required=('input', 'meter', 'filter', 'suction'), **updates):
    return bind_suction_losses(required, rows, **{
        **dict(max_flow_m3h=12, temperature_c=10, path_basis='Явный последовательный контрольный путь'),
        **updates})


def loss(id='pipe', covers=('input', 'suction'), **updates):
    return replace(SuctionLoss(id, covers, .3, 12, 10, 'Контрольное готовое значение'), **updates)


def rows():
    return (loss(), loss('meter', ('meter',), loss_m=.5), loss('filter', ('filter',), loss_m=.2))


def test_independent_total_no_second_local_allowance_or_reserve_multiplier():
    result = bind(rows())
    assert result.status == 'bound' and result.total_loss_m == 1
    assert result.known_loss_m == 1 and not result.missing_components


def test_current_pipe_result_used_verbatim_with_its_local_allowance():
    # Actual canonical calculation, not a second implementation of Darcy/SP30.
    data = V1SectionInput('inlet', 10, 50, 12 / 3.6, .01, role='input')
    pipe = calculate_v1_hydraulics([data], water_temperature_c=10, network_kind='domestic').sections[0]
    result = bind((loss(loss_m=pipe.total_loss_m), *rows()[1:]))
    assert pipe.local_loss_factor == .3
    assert result.total_loss_m == pytest.approx(pipe.total_loss_m + .5 + .2)
    assert result.rows[0]['loss_m'] == pipe.total_loss_m


def test_unknown_filter_and_partial_total_never_become_complete_hf():
    result = bind(rows()[:2])
    assert result.status == 'needs_data' and result.total_loss_m is None
    assert result.known_loss_m == .8 and result.missing_components == ['filter']
    assert bind().total_loss_m is None


@pytest.mark.parametrize('field,value', [('loss_m', None), ('flow_m3h', None),
    ('temperature_c', None), ('basis', ''), ('flow_m3h', 11.466), ('temperature_c', 20)])
def test_incomplete_or_other_mode_record_does_not_confirm_path(field, value):
    result = bind((replace(rows()[0], **{field: value}), *rows()[1:]))
    assert result.total_loss_m is None
    assert result.missing_components == ['input', 'suction']
    assert result.rows[0]['status'] == 'needs_data'


@pytest.mark.parametrize('change', [{'max_flow_m3h': None}, {'temperature_c': None}, {'path_basis': ''}])
def test_missing_path_mode_or_basis_blocks_final_total(change):
    result = bind_suction_losses(('input', 'meter', 'filter', 'suction'), rows(),
        **{**dict(max_flow_m3h=12, temperature_c=10, path_basis='Контрольный путь'), **change})
    assert result.total_loss_m is None and result.issues


def test_zero_is_explicit_with_basis_not_default_and_no_rounding():
    result = bind([loss(covers=('input',), loss_m=0)], required=('input',))
    assert result.status == 'bound' and result.total_loss_m == 0
    tiny = bind([loss(covers=('input',), loss_m=1e-10)], required=('input',))
    assert tiny.total_loss_m == 1e-10
    result = bind([loss(covers=('input',), flow_m3h=(12 / 3.6) * 3.6)], required=('input',))
    assert result.status == 'bound'


@pytest.mark.parametrize('bad_rows', [
    (*rows(), loss('extra', ('suction',))),  # group + local fitting twice
    (*rows(), loss('other', ('apartment_meter',))),  # downstream of pump
    (*rows(), rows()[0]),
    (loss(covers=()),), (loss(covers=('input', 'input')),),
    (loss(loss_m=-1),), (loss(flow_m3h=0),), (loss(id=' '),),
    (loss(loss_m=float('inf')),), (loss(loss_m=float('nan')),),
    (loss(temperature_c=True),),
])
def test_invalid_or_duplicate_bindings_are_rejected(bad_rows):
    with pytest.raises(ValueError):
        bind(bad_rows)


@pytest.mark.parametrize('required', [(), ('',), ('a', 'a')])
def test_invalid_scope_rejected(required):
    with pytest.raises(ValueError):
        bind(required=required)


def test_overflow_rejected():
    with pytest.raises(ValueError, match='Переполнение'):
        bind([loss('a', ('input',), loss_m=1e308), loss('b', ('suction',), loss_m=1e308)],
             required=('input', 'suction'))


def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def request():
    return {**asdict(example(suction_losses_m=None, temperature_c=10)), 'suction_path': dict(
        required_components=['input', 'meter', 'filter', 'suction'],
        losses=[asdict(r) for r in rows()], path_basis='Контрольный последовательный путь')}


def test_http_path_to_balance_complete_then_incomplete_does_not_reuse_old_result():
    c, data = client(), request()
    first = c.post('/pumps/npsha', json=data)
    assert first.status_code == 200
    assert first.json()['available_m'] == pytest.approx(7)
    assert first.json()['effective_suction_losses_m'] == 1
    assert first.json()['inputs']['suction_losses_m'] is None  # original preserved
    data['suction_path']['losses'].pop()
    second = c.post('/pumps/npsha', json=data)
    assert second.status_code == 200 and second.json()['available_m'] is None
    assert second.json()['suction_path']['missing_components'] == ['filter']
    assert second.json()['effective_suction_losses_m'] is None


def test_http_refuses_ready_hf_plus_breakdown_and_outside_component():
    data = request()
    data['suction_losses_m'] = 0
    assert client().post('/pumps/npsha', json=data).status_code == 400
    data['suction_losses_m'] = None
    data['suction_path']['losses'][0]['covers'] += ('another_inlet',)
    assert client().post('/pumps/npsha', json=data).status_code == 400


def test_samara_actual_g1_paths_exclude_bypasses_reserve_and_downstream(common):
    before = deepcopy(asdict(common))
    report = review_station(common)
    manifest = report['suction_paths']
    assert manifest['complete'] and manifest['status'] == 'needs_data'
    assert len(manifest['routes']) == 8  # 2 inlets x 2 downstream mains x 2 pumps
    assert 'g1_bypass_1' in manifest['closed_components']
    assert 'g1_bypass_2' in manifest['closed_components']
    for route in manifest['routes']:
        assert route['metered'] and route['nodes'][-1] == route['pump']
        assert len([n for n in route['nodes'] if n.startswith('station_pump_')]) == 1
        assert not any(n.startswith(('station_check_', 'station_out_')) for n in route['nodes'])
        assert route['total_loss_m'] is None
        assert not any('apartment' in n for n in route['required_components'])
        # Entire graph route is required, not just its water meter.
        assert 'node:meter' in route['required_components']
        partial = bind([loss('meter', ('node:meter',))], route['required_components'])
        assert partial.total_loss_m is None and partial.missing_components
    assert asdict(common) == before


def test_single_inlet_route_and_unavailable_inlet_are_not_halved(common):
    common.source.inputs_count = 1
    r = review_station(common)['suction_paths']
    assert r['complete'] and len(r['routes']) == 2
    assert all(p['source'] == 'inlet' for p in r['routes'])
    common.source.inputs_count = 2
    network = connected_network(common)
    closed = set(review_station(common)['suction_paths']['closed_components']) | {'supply_valve_2'}
    r = suction_path_manifest(network, ('station_pump_1', 'station_pump_2'), closed)
    assert len(r['routes']) == 4 and all(p['source'] == 'supply_source_1' for p in r['routes'])


def test_route_cuts_and_bounded_search_do_not_become_success(common):
    network = connected_network(common)
    closed = set(review_station(common)['suction_paths']['closed_components'])
    cut = suction_path_manifest(network, ('station_pump_1', 'station_pump_2'), closed | {'meter'})
    assert not cut['routes'] and cut['status'] == 'unsupported'
    truncated = suction_path_manifest(network, ('station_pump_1',), closed, search_limit=1)
    assert not truncated['complete'] and truncated['status'] == 'unsupported'
    assert suction_path_manifest(None, (), ())['status'] == 'unsupported'


def test_samara_route_manifest_can_be_bound_and_calculated_by_public_api(common):
    before = deepcopy(asdict(common))
    route = review_station(common)['suction_paths']['routes'][0]
    data = request()
    # Explicit test values ONLY; no assignment to the Samara project.
    data['suction_path'] = dict(required_components=route['required_components'],
        losses=[asdict(loss('test-path', tuple(route['required_components']), loss_m=1))],
        path_basis='Арифметический тест одного пути; не гидравлическое подтверждение Самары')
    result = client().post('/pumps/npsha', json=data)
    assert result.status_code == 200 and result.json()['available_m'] == pytest.approx(7)
    assert asdict(common) == before

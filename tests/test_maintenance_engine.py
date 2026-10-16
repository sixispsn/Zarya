"""Pressure reachability and gravity are distinct; no drawing-based evidence."""
from dataclasses import replace
import pytest
from app.pz.maintenance_engine import (
    ServiceNode as N, ServiceLink as E, ServicePort as P,
    ServiceNetwork as Network, assess_removal,
)


def example():
    # Explicit VERIFIED fixture, not defaults for a customer's assembly.
    nodes = (N('supply',kind='source'),N('a',kind='isolation'),
             N('low',body_drainable=True),N('meter',body_drainable=True),
             N('high',body_drainable=True),N('b',kind='isolation'),N('building',kind='source'))
    ids = [n.id for n in nodes]
    edges = tuple(E(a,b,'b_to_a',True,'Test: straight upward pipe, air passage verified')
                  for a,b in zip(ids,ids[1:]))
    return Network(nodes,edges,(P('drain','low',relief=True,drain=True,discharge_basis='Test: safe receiver'),
                                P('vent','high',air=True)))


def test_isolated_drained_vented_is_design_pass_not_work_permit():
    r = assess_removal(example(),'meter')
    assert r.close_valves == ('a','b')
    assert r.status == 'checked'
    assert not r.safe_to_remove
    assert r.isolation == r.pressure_relief == r.drainage == r.air_admission == 'checked'
    assert not r.source_paths


def test_manual_single_valve_leaves_building_backfeed():
    r = assess_removal(example(),'meter',closed_valves=('a',))
    assert r.isolation == 'blocked'
    assert r.source_paths == (('meter','high','b','building'),)


def test_check_valve_never_isolates_backfeed_even_when_gravity_verified():
    n = example()
    n = replace(n,nodes=tuple(replace(x,kind='check',forward_to='building',
                                    gravity_passage_verified=True) if x.id=='b' else x for x in n.nodes))
    r = assess_removal(n,'meter')
    assert r.isolation == 'blocked' and 'b' not in r.close_valves


def test_ring_and_bypass_paths_are_not_lost():
    n = example()
    n = replace(n,nodes=(*n.nodes,N('c',kind='isolation')),
                links=(*n.links,E('low','c'),E('c','building')))
    assert assess_removal(n,'meter').close_valves == ('a','b','c')
    r = assess_removal(n,'meter',closed_valves=('a','b'))
    assert r.isolation == 'blocked'
    assert r.source_paths[0] == ('meter','low','c','building')


def test_removing_isolator_requires_other_isolators():
    r = assess_removal(example(),'a')
    assert 'a' not in r.close_valves
    assert r.isolation == 'blocked'
    with pytest.raises(ValueError):
        assess_removal(example(),'a',closed_valves=('a','b'))


def test_spring_check_creates_two_relief_compartments():
    n = example()
    n = replace(n,nodes=tuple(replace(x,kind='check',forward_to='high') if x.id=='meter' else x for x in n.nodes))
    r = assess_removal(n,'meter')
    assert r.isolation == 'checked'
    assert r.pressure_relief == 'blocked'  # tap below cannot relieve the high side
    assert r.drainage == 'blocked'
    assert r.air_admission == 'blocked'


def test_drain_above_meter_can_release_pressure_but_cannot_empty_it():
    n = example()
    n = replace(n,ports=(P('drain','high',relief=True,drain=True,discharge_basis='safe receiver'),))
    r = assess_removal(n,'meter')
    assert r.pressure_relief == 'checked'
    assert r.drainage == 'blocked' and 'meter' in r.trapped_nodes


def test_unknown_profile_does_not_get_paper_elevations():
    n = example()
    n = replace(n,links=tuple(replace(e,gravity='unknown',basis='Air route only') for e in n.links))
    assert assess_removal(n,'meter').drainage == 'needs_data'


@pytest.mark.parametrize('body,status', [(None,'needs_data'),(False,'blocked')])
def test_body_pocket_not_ignored(body,status):
    n = example()
    n = replace(n,nodes=tuple(replace(x,body_drainable=body) if x.id=='meter' else x for x in n.nodes))
    assert assess_removal(n,'meter').drainage == status


def test_air_required_even_with_open_low_drain():
    n = example()
    n = replace(n,ports=n.ports[:1])
    r = assess_removal(n,'meter')
    assert r.drainage == 'checked' and r.air_admission == 'blocked'
    assert r.status == 'blocked'


def test_unknown_air_route_not_success():
    n = example()
    n = replace(n,links=tuple(replace(e,air_passable=None) for e in n.links))
    assert assess_removal(n,'meter').air_admission == 'needs_data'


def test_discharge_receiver_must_be_defined():
    n = example()
    n = replace(n,ports=tuple(replace(p,discharge_basis='') for p in n.ports))
    r = assess_removal(n,'meter')
    assert r.pressure_relief == r.drainage == 'needs_data'


def test_port_on_removed_component_cannot_prepare_its_own_removal():
    n = replace(example(),ports=(P('drain','meter',True,True,True,'receiver'),))
    r = assess_removal(n,'meter')
    assert not r.drain_ports and r.status == 'blocked'


def test_no_source_boundaries_is_not_proof_of_no_water():
    n = example()
    n = replace(n,nodes=tuple(replace(x,kind='component') if x.kind=='source' else x for x in n.nodes))
    assert assess_removal(n,'meter').isolation == 'needs_data'


@pytest.mark.parametrize('mode', ['duplicate','self_link','unknown_node','no_basis','body_bool',
                                 'air_bool','port_bool','check_direction','port_id'])
def test_invalid_data_rejected(mode):
    n = example()
    if mode=='duplicate': n = replace(n,nodes=(*n.nodes,n.nodes[0]))
    if mode=='self_link': n = replace(n,links=(*n.links,E('meter','meter')))
    if mode=='unknown_node': n = replace(n,links=(*n.links,E('meter','missing')))
    if mode=='no_basis': n = replace(n,links=(E('a','meter','level'),))
    if mode=='body_bool': n = replace(n,nodes=(*n.nodes,N('bad',body_drainable=1)))
    if mode=='air_bool': n = replace(n,links=(E('a','meter',air_passable='yes',basis='bad'),))
    if mode=='port_bool': n = replace(n,ports=(P('bad','low',drain='yes'),))
    if mode=='check_direction': n = replace(n,nodes=tuple(replace(x,kind='check',forward_to='supply') if x.id=='meter' else x for x in n.nodes))
    if mode=='port_id': n = replace(n,ports=(P('','low'),))
    with pytest.raises(ValueError):
        assess_removal(n,'meter')


def test_unknown_removed_node_or_closing_a_check_rejected():
    with pytest.raises(ValueError): assess_removal(example(),'missing')
    with pytest.raises(ValueError): assess_removal(example(),'supply')
    with pytest.raises(ValueError): assess_removal(example(),'meter',closed_valves=('meter',))

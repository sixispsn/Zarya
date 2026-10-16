from dataclasses import replace
from math import hypot

import pytest

from app.intake.studio_study import initialize_study, build_study
from app.pz.network_takeoff import NetworkPoint, NetworkTakeoff, QuantityRoute
from app.pz.small_residential_takeoff import (
    EDUCATIONAL_APARTMENT_ROUTE, build_residential_takeoff, educational_residential_takeoff,
)


@pytest.fixture
def case():
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "two", None)
    _, model, calc, *_ = build_study(draft)
    return model, calc, educational_residential_takeoff(model, calc)


def test_hand_check_all_apartments_and_shared_runs(case):
    model, calc, network = case
    rows = network.rows()
    lengths = {(r.system, r.size.split(';')[0]): r.quantity for r in rows if r.unit == 'м'}
    # 8 apartments: 3.4 m projected DN50 branch + 3 fixture connections.
    assert lengths['K1', '50 x 1.8'] == pytest.approx(8*(hypot(3.4, 3.4*.03)+.45+.25+.45))
    # Shared risers are measured only once from lower axis to roof + 0.2.
    k1_risers = sum(6.8-calc.basement.axis_at(s) for s in calc.basement.junction_chainages_m)
    k1_other = hypot(9, 9*.02)+(-.98-(-2.2))+1.2
    assert lengths['K1', '110 x 2.7'] == pytest.approx(8*(hypot(.6,.6*.02)+.2)+k1_risers+k1_other)
    k2_risers = sum(6.6-calc.rain_axis_at(s) for s in calc.rain_chainages_m)
    assert lengths['K2', '110 x 3.5'] == pytest.approx(k2_risers+hypot(6,6*.015)+(-1.22-(-2.25))+1.2)
    assert sum(c.quantity for c in network.components if c.kind == 'fixture') == 32
    assert sum(c.quantity for c in network.components if c.kind == 'funnel') == 4
    assert len([r for r in network.routes if r.role == 'ventilation']) == 4
    assert not network.purchase_ready


def test_component_instances_match_all_original_floor_and_lower_assemblies(case):
    model, _, network = case
    expected = {f'{a.assembly.assembly_id}:{f.fitting_id}' for a in model.apartments for f in a.assembly.fittings}
    expected |= {f'{n.assembly_id}:{f.fitting_id}' for n in (*model.lower_nodes,*model.roof.lower_nodes) for f in n.fittings}
    actual = [c.source_element_id for c in network.components]
    assert len(actual) == len(set(actual))
    assert expected <= set(actual)
    for row in network.rows():
        if row.unit == 'шт':
            assert type(row.quantity) is int


def test_projection_collapse_has_no_effect_on_quantities(case, monkeypatch):
    from app.pz import small_residential_section
    model, calc, network = case
    projection = small_residential_section.build_section_projection(model)
    assert len(projection.visible_apartments) == 4 < len(model.apartments)
    monkeypatch.setattr(small_residential_section, 'build_section_projection', lambda *_: None)
    assert educational_residential_takeoff(model, calc) == network


def test_graphic_fitting_coordinates_do_not_supply_length(case):
    model, calc, network = case
    # Presentation position changes never become measured metres.
    apt = model.apartments[0]
    fitting = apt.assembly.fittings[0]
    moved = replace(fitting, point=replace(fitting.point, x_mm=fitting.point.x_mm+100))
    changed = replace(apt, assembly=replace(apt.assembly, fittings=(moved, *apt.assembly.fittings[1:])))
    other = replace(model, apartments=(changed, *model.apartments[1:]))
    assert educational_residential_takeoff(other, calc).rows() == network.rows()


def test_unknown_length_is_visible_not_a_zero_or_fallback(case):
    model, calc, _ = case
    network = build_residential_takeoff(model, calc, apartment_route=EDUCATIONAL_APARTMENT_ROUTE,
        outlet_lengths_m=(None,None), outlet_source='План не предоставлен')
    missing = [rid for r in network.rows() for rid in r.unknown_ids]
    assert set(missing) == {'K1:outlet-route','K2:outlet-route'}


def test_changed_route_changes_only_its_own_quantities_and_hash(case):
    model, calc, original = case
    changed = build_residential_takeoff(model, calc,
        apartment_route=replace(EDUCATIONAL_APARTMENT_ROUTE, fixture_connections_m=(.65,.25,.45,.20)),
        outlet_lengths_m=(1.2,1.2), outlet_source='Основание')
    old, new = original.rows(), changed.rows()
    for a,b in zip(old,new,strict=True):
        assert b.quantity-a.quantity == pytest.approx(1.6 if a.system == 'K1' and a.kind == 'route'
                                                      and a.size.startswith('50 ') else 0)
    assert changed.fingerprint != original.fingerprint


@pytest.mark.parametrize('length',[float('nan'),float('inf'),-1,0,True])
def test_bad_lengths_fail(case,length):
    network = case[2]
    with pytest.raises(ValueError, match='length'):
        replace(network, routes=(replace(network.routes[0],length_m=length),*network.routes[1:])).validate()


def test_shared_instance_cannot_be_counted_twice(case):
    network = case[2]
    with pytest.raises(ValueError,match='duplicate'):
        replace(network,routes=(*network.routes,network.routes[0])).validate()


def test_mixed_systems_or_missing_discharge_fail(case):
    network = case[2]
    route = next(r for r in network.routes if r.route_id == 'K2:outlet-route')
    for end, message in [('K1:outlet','cross-system'),('K2:drop-top','disconnected|acyclic')]:
        with pytest.raises(ValueError,match=message):
            replace(network,routes=tuple(replace(r,end=end) if r is route else r for r in network.routes)).validate()


def test_cap_cannot_close_a_passing_junction(case):
    network = case[2]
    cap = next(c for c in network.components if c.kind == 'cap')
    with pytest.raises(ValueError,match='through-flow'):
        replace(network,components=tuple(replace(c,point_id='K1:base-1') if c is cap else c
                                         for c in network.components)).validate()


def test_grouped_fixtures_are_not_silently_treated_as_one_route(case):
    model,calc,_ = case
    apt = model.apartments[0]
    changed = replace(apt,assembly=replace(apt.assembly,fixtures=(replace(apt.assembly.fixtures[0],quantity=2),
                                                               *apt.assembly.fixtures[1:])))
    with pytest.raises(ValueError,match='physical branch'):
        educational_residential_takeoff(replace(model,apartments=(changed,*model.apartments[1:])),calc)


def test_three_dimensional_route_counts_height_once(case):
    r = case[2].routes[0]
    route = QuantityRoute.from_polyline(points_m=((0,0,0),(3,4,0),(3,4,3.3)),route_id='3d',
        start=r.start,end=r.end,pipe=r.pipe,role=r.role,basis=r.basis,mode=r.mode)
    assert route.length_m == pytest.approx(8.3)
    assert route.polyline_m == ((0,0,0),(3,4,0),(3,4,3.3))
    with pytest.raises(ValueError,match='3D'):
        QuantityRoute.from_polyline(points_m=((0,0,0),(0,float('nan'),1)),route_id='x')


def test_quantity_core_supports_500_sources_without_multiplying_shared_main(case):
    pipe, basis = case[2].routes[0].pipe, case[2].routes[0].basis
    points = tuple(NetworkPoint(f'apt-{i}', 'K1', 'source') for i in range(500))
    points += (NetworkPoint('main','K1','junction'),NetworkPoint('outlet','K1','outlet'))
    routes = tuple(QuantityRoute(f'branch-{i}', f'apt-{i}', 'main', pipe, 4., 'branch', basis) for i in range(500))
    routes += (QuantityRoute('shared-main','main','outlet',pipe,10.,'main',basis),)
    network = NetworkTakeoff(points,routes,(),('Synthetic quantity test, not an engineered 500-apartment design',))
    assert network.rows()[0].quantity == 2010


def test_different_product_families_do_not_merge(case):
    network = case[2]
    component = next(c for c in network.components if c.kind == 'elbow_45' and c.product_family == 'PP HT')
    changed = replace(network, components=tuple(replace(c,product_family='Other selected series')
                      if c is component else c for c in network.components))
    assert len(changed.rows()) == len(network.rows())+1


def test_takeoff_change_invalidates_studio_fingerprint(monkeypatch):
    from app.pz import small_residential_takeoff
    draft = {'revision':0,'answers':{},'documents':[]}
    initialize_study(draft,'two',None)
    before = build_study(draft)
    monkeypatch.setattr(small_residential_takeoff, 'EDUCATIONAL_APARTMENT_ROUTE',
                        replace(EDUCATIONAL_APARTMENT_ROUTE, fixture_connections_m=(.65,.25,.45,.20)))
    after = build_study(draft)
    assert before[-1] != after[-1]
    assert before[3:5] == after[3:5]  # demand/rain algorithms unaffected

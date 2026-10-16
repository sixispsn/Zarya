from dataclasses import asdict, replace
from math import hypot

import pytest

from app.analysis.architecture_pdf import ArchitecturePdfSurvey
from app.analysis.plan_route_measurement import (
    PlanRouteTrace, PlanRouteVertex, apply_plan_measurements, measure_plan_route,
    measurement_context, trace_from_mapping,
)
from app.data.sewer_pipe_catalog import sewer_pipe_geometry
from app.pz.network_takeoff import NetworkPoint, NetworkTakeoff, QuantityBasis, QuantityRoute
from tests.test_architecture_confirmation import _input, _page


@pytest.fixture
def context():
    architecture = _input()
    survey = ArchitecturePdfSurvey('Планы.pdf','a'*64,(_page(),),())
    _, version = measurement_context(architecture,survey,1)
    trace = PlanRouteTrace('K1:route','K1',1,version,'start','end',
        (PlanRouteVertex(0,0),PlanRouteVertex(75,0),PlanRouteVertex(75,100)),
        'unknown')
    return architecture, survey, trace


def test_plan_3_plus_4_is_seven_not_straight_five(context):
    a,s,t = context
    m = measure_plan_route(t,a,s)
    assert m.plan_length_m == 7
    assert m.spatial_length_m is None and not m.points_m
    assert m.metres_per_point == .04
    assert trace_from_mapping(asdict(t)) == t


def test_slope_and_vertical_dimensions_are_counted_once(context):
    a,s,t = context
    m = measure_plan_route(replace(t, vertical_mode='slope', start_elevation_m=1., slope=.02),a,s)
    assert m.spatial_length_m == pytest.approx(hypot(7,.14))
    assert m.points_m[-1][2] == pytest.approx(.86)
    points = (PlanRouteVertex(0,0,3.3),PlanRouteVertex(75,0,3.3),PlanRouteVertex(75,100,3.3),PlanRouteVertex(75,100,0))
    m = measure_plan_route(replace(t,vertices=points,vertical_mode='vertices'),a,s)
    assert m.plan_length_m == 7 and m.spatial_length_m == pytest.approx(10.3)


def test_measured_route_updates_quantity_without_changing_hydraulic_method(context):
    a,s,t = context
    pipe=sewer_pipe_geometry('ostendorf_ht_pp',50)
    route=QuantityRoute('K1:route','start','end',pipe,None,'branch',QuantityBasis('proposed','Нет обмера'))
    network=NetworkTakeoff((NetworkPoint('start','K1','source'),NetworkPoint('end','K1','outlet')),
                          (route,),(),('Test',))
    m=measure_plan_route(replace(t,vertical_mode='level',start_elevation_m=.2,reviewed=True),a,s)
    changed=apply_plan_measurements(network,(m,),a,s)
    assert changed.routes[0].length_m == 7 and changed.routes[0].basis.status == 'confirmed'
    assert changed.routes[0].polyline_m == m.points_m
    assert 'SHA-256' in changed.routes[0].basis.source
    assert network.routes[0].length_m is None
    assert changed.components == network.components and not changed.purchase_ready
    with pytest.raises(ValueError,match='совпадает с пересчётом'):
        apply_plan_measurements(network,(replace(m,spatial_length_m=99),),a,s)
    with pytest.raises(ValueError,match='проверьте трассу'):
        unreviewed=measure_plan_route(t,a,s)
        apply_plan_measurements(network,(unreviewed,),a,s)


@pytest.mark.parametrize('change',['scale','floor','pdf'])
def test_context_edits_revoke_old_measurements(context,change):
    a,s,t=context
    if change=='scale':
        f=a.floors[0]
        a=replace(a,floors=(replace(f,scale=replace(f.scale,real_distance_m=5)),))
    elif change=='floor':
        a=replace(a,floors=(replace(a.floors[0],elevation_m=3.3),))
    else:
        s=replace(s,sha256='b'*64)
    with pytest.raises(ValueError,match='изменил'):
        measure_plan_route(t,a,s)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,-1,301])
def test_bad_or_out_of_page_coordinates_are_rejected(context,value):
    a,s,t=context
    with pytest.raises(ValueError,match='вне листа'):
        measure_plan_route(replace(t,vertices=(PlanRouteVertex(value,0),PlanRouteVertex(75,100))),a,s)


def test_missing_height_conflicts_and_uphill_are_rejected(context):
    a,s,t=context
    for overrides in [dict(vertical_mode='level'),dict(vertical_mode='slope',start_elevation_m=0),
                      dict(vertical_mode='vertices'),dict(start_elevation_m=0),
                      dict(vertical_mode='slope',start_elevation_m=0,slope=-.02)]:
        with pytest.raises(ValueError):
            measure_plan_route(replace(t,**overrides),a,s)
    with pytest.raises(ValueError,match='поднимается'):
        measure_plan_route(replace(t,vertical_mode='vertices',vertices=(PlanRouteVertex(0,0,0),PlanRouteVertex(75,100,1))),a,s)


def test_scale_is_a_measurement_not_pdf_print_size(context):
    a,s,t=context
    f=a.floors[0]
    scale=replace(f.scale,first=replace(f.scale.first,x_pt=0,y_pt=0),second=replace(f.scale.second,x_pt=0,y_pt=100))
    a=replace(a,floors=(replace(f,scale=scale),))
    _,version=measurement_context(a,s,1)
    assert measure_plan_route(replace(t,context_hash=version),a,s).plan_length_m==7


def test_common_node_must_meet_in_same_calibrated_frame(context):
    a,s,t=context
    pipe=sewer_pipe_geometry('ostendorf_ht_pp',50)
    basis=QuantityBasis('proposed','Proposed')
    n=NetworkTakeoff((NetworkPoint('a','K1','source'),NetworkPoint('b','K1','junction'),NetworkPoint('c','K1','outlet')),
        (QuantityRoute('first','a','b',pipe,1,'branch',basis),QuantityRoute('second','b','c',pipe,1,'branch',basis)),(),())
    first=replace(t,route_id='first',start_node='a',end_node='b',vertices=(PlanRouteVertex(0,0),PlanRouteVertex(75,0)),
                  vertical_mode='level',start_elevation_m=.2,reviewed=True)
    second=replace(first,route_id='second',start_node='b',end_node='c',vertices=(PlanRouteVertex(76,0),PlanRouteVertex(75,100)))
    with pytest.raises(ValueError,match='Общий узел'):
        apply_plan_measurements(n,tuple(measure_plan_route(x,a,s) for x in (first,second)),a,s)


def test_pdf_measurement_changes_one_physical_route_not_all_eight_apartments(context):
    from app.intake.studio_study import initialize_study, build_study
    from app.pz.small_residential_takeoff import educational_residential_takeoff

    a,s,t=context
    draft={'revision':0,'answers':{},'documents':[]}
    initialize_study(draft,'two',None)
    _,model,calc,*_=build_study(draft)
    network=educational_residential_takeoff(model,calc)
    original=next(r for r in network.routes if r.mode=='drain')
    system=next(p.system for p in network.points if p.point_id==original.start)
    trace=replace(t,route_id=original.route_id,start_node=original.start,end_node=original.end,
                  system=system,vertical_mode='level',start_elevation_m=.2,reviewed=True)
    changed=apply_plan_measurements(network,(measure_plan_route(trace,a,s),),a,s)
    assert len(changed.routes)==len(network.routes)==102
    assert changed.points==network.points and changed.components==network.components
    for old,new in zip(network.routes,changed.routes,strict=True):
        if old.route_id==original.route_id:
            assert new.length_m==7 and new.basis.status=='confirmed'
        else:
            assert new==old
    before=sum(row.quantity for row in network.rows() if row.unit=='м')
    after=sum(row.quantity for row in changed.rows() if row.unit=='м')
    assert after-before==pytest.approx(7-original.length_m)
    assert not changed.purchase_ready
    assert apply_plan_measurements(network,(),a,s)==network

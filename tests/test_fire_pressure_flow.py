from copy import deepcopy
from dataclasses import replace
from math import sqrt

import pytest

from app.calc.fire_hydraulics import (
    FireCabinetNode, FireNetwork, HydraulicNode, HydraulicSource, PipeSegment, SourceKind, MPA_TO_M)
from app.calc.fire_pressure_flow import (
    CabinetCharacteristic, FixedLossCharacteristic, handbook_characteristic, solve_pressure_flows,
    required_common_header, check_pump_operating_point)


@pytest.fixture
def symmetric():
    # Both ring ports held at the same head, outlet on each one, zero ring flow.
    # Each terminal branch loses 0.5*q²; outlet characteristic loses 2*q².
    net = FireNetwork(
        {k:HydraulicNode(k,z) for k,z in [('a',0),('b',0),('c',0),('d',0),('p1',10),('p2',10)]},
        [PipeSegment(f'{a}{b}',a,b,1,.1) for a,b in [('a','b'),('b','c'),('c','d'),('d','a')]]+
        [PipeSegment('branch1','a','p1',5,.1),PipeSegment('branch2','c','p2',5,.1)],
        [FireCabinetNode('pc1','p1'),FireCabinetNode('pc2','p2')],
        HydraulicSource('a',SourceKind.CITY_MAIN,50),
        HydraulicSource('c',SourceKind.CITY_MAIN,50))
    chars = [CabinetCharacteristic(f'pc{i}',2/MPA_TO_M,2,8,
        'Analytical test fixture, not product data','handbook_study') for i in (1,2)]
    return net,chars


def test_closed_form_symmetry_and_conservation(symmetric):
    net,chars=symmetric
    before=deepcopy(net)
    out=solve_pressure_flows(net,chars,50)
    assert net==before
    assert out.total_flow_lps==pytest.approx(8,abs=2e-6)
    assert all(c.flow_lps==pytest.approx(4,abs=1e-6) for c in out.cabinets)
    assert out.energy_residual_m<1e-3
    assert out.supply_balance_residual_lps<1e-5
    assert not out.product_verified


def test_fixed_loss_closed_form_and_no_pressure_cap(symmetric):
    net,chars=symmetric
    device=FixedLossCharacteristic(1.5,'Explicit analytical test resistance','required_characteristic_study')
    devices={c.cabinet_id:device for c in chars}
    before=deepcopy(net)
    out=solve_pressure_flows(net,chars,50,fixed_losses=devices)
    assert net==before
    assert not out.ideal_controls and out.fixed_controls and not out.product_verified
    for c in out.cabinets:
        assert c.flow_lps==pytest.approx(sqrt(40/(.5+2+1.5)),abs=1e-6)
        assert c.outlet_head_m==pytest.approx(20,abs=1e-5)
        assert c.control_drop_m==pytest.approx(15,abs=1e-5)
        assert c.control_drop_m==pytest.approx(device.head_loss(c.flow_lps),abs=1e-5)
    higher=solve_pressure_flows(net,chars,90,fixed_losses=devices)
    assert higher.cabinets[0].outlet_head_m==pytest.approx(40,abs=1e-5)
    assert higher.cabinets[0].control_drop_m==pytest.approx(30,abs=1e-5)
    assert device.head_loss(0)==0  # never static protection
    assert out.energy_residual_m<1e-3 and out.supply_balance_residual_lps<1e-5


def test_fixed_device_range_and_evidence_do_not_become_product_approval(symmetric):
    net,chars=symmetric
    chars=[replace(c,evidence='technical_documentation',maximum_head_m=100) for c in chars]
    study=FixedLossCharacteristic(1.5,'Explicit study target','required_characteristic_study',10)
    assert not solve_pressure_flows(net,chars,50,
        fixed_losses={c.cabinet_id:study for c in chars}).product_verified
    documented=replace(study,evidence='technical_documentation',maximum_flow_lps=2.5)
    result=check_pump_operating_point(net,chars,[(0,50),(36,30)],
        suction_static_head_m=10,supply_resistance=.01,
        fixed_losses={c.cabinet_id:documented for c in chars})
    assert result.status=='outside_characteristic_range'
    assert not result.operating.product_verified
    assert all(c.within_device_range is False for c in result.operating.cabinets)


@pytest.mark.parametrize('kind',['unknown_id','no_source','nan','zero','negative','no_range',
    'negative_range','nan_range','bad_evidence','ideal_same_cabinet','not_characteristic'])
def test_fixed_devices_fail_closed(symmetric,kind):
    net,chars=symmetric
    device=FixedLossCharacteristic(1.5,'Test fixture','required_characteristic_study')
    ideal={}
    key='pc1'
    if kind=='unknown_id': key='unknown'
    if kind=='no_source': device=replace(device,source='')
    if kind=='nan': device=replace(device,resistance_head_per_lps2=float('nan'))
    if kind=='zero': device=replace(device,resistance_head_per_lps2=0)
    if kind=='negative': device=replace(device,resistance_head_per_lps2=-1)
    if kind=='no_range': device=replace(device,evidence='technical_documentation')
    if kind=='negative_range': device=replace(device,maximum_flow_lps=-1)
    if kind=='nan_range': device=replace(device,maximum_flow_lps=float('nan'))
    if kind=='bad_evidence': device=replace(device,evidence='selected')
    if kind=='ideal_same_cabinet': ideal={'pc1':8}
    if kind=='not_characteristic': device=1.5
    with pytest.raises(ValueError):
        solve_pressure_flows(net,chars,50,fixed_losses={key:device},ideal_outlet_heads=ideal)


@pytest.mark.parametrize('flow',[-1,float('nan'),float('inf')])
def test_fixed_loss_rejects_invalid_discharge(flow):
    device=FixedLossCharacteristic(1.5,'Test fixture','required_characteristic_study')
    with pytest.raises(ValueError): device.head_loss(flow)


def test_different_elevations_produce_different_flows(symmetric):
    net,chars=symmetric
    net.nodes['p2'].elevation_m=30
    out=solve_pressure_flows(net,chars,50)
    assert out.cabinets[0].flow_lps==pytest.approx(4,abs=1e-6)
    assert out.cabinets[1].flow_lps==pytest.approx(sqrt(20/2.5),abs=1e-6)
    assert out.total_flow_lps!=4*2


def test_zero_and_partial_no_discharge(symmetric):
    net,chars=symmetric
    assert solve_pressure_flows(net,chars,0).total_flow_lps==0
    net.nodes['p2'].elevation_m=60
    out=solve_pressure_flows(net,chars,50)
    assert out.cabinets[1].flow_lps==0
    assert not out.cabinets[1].meets_minimum


def test_datum_shift_does_not_change_flows(symmetric):
    net,chars=symmetric
    old=solve_pressure_flows(net,chars,50)
    for n in net.nodes.values(): n.elevation_m+=150
    assert solve_pressure_flows(net,chars,50).total_flow_lps==pytest.approx(old.total_flow_lps)


def test_ideal_regulator_reduces_but_never_boosts(symmetric):
    net,chars=symmetric
    out=solve_pressure_flows(net,chars,50,ideal_outlet_heads={'pc1':8,'pc2':80})
    assert out.cabinets[0].flow_lps==pytest.approx(2)
    assert out.cabinets[0].control_drop_m==pytest.approx(30)
    assert out.cabinets[1].flow_lps==pytest.approx(4,abs=1e-6)
    assert out.cabinets[1].control_drop_m==0
    assert out.ideal_controls and not out.product_verified


def test_minimum_pressure_and_flow_checked_independently(symmetric):
    net,chars=symmetric
    chars=[replace(c,minimum_head_m=18) for c in chars]
    out=required_common_header(net,chars,ceiling_head_m=80)
    assert out.header_head_m==pytest.approx(32.5,abs=3e-5)
    assert all(c.flow_lps==pytest.approx(3,abs=3e-5) for c in out.cabinets)
    with pytest.raises(ValueError,match='Cannot meet'):
        required_common_header(net,chars,ceiling_head_m=20)


def test_actual_pump_intersection_not_fixed_demand(symmetric):
    net,chars=symmetric
    # H=50-2*Q(l/s), total outlet demand Q=2sqrt((H-10)/2.5).
    out=check_pump_operating_point(net,chars,[(0,50),(36,30)],
        suction_static_head_m=0,supply_resistance=0)
    expected=(-2+sqrt(4+4*.625*40))/(2*.625)
    assert out.pump_flow_m3h==pytest.approx(expected*3.6,abs=2e-5)
    assert abs(out.boundary_residual_lps)<1e-6
    # Zero suction is deliberately not accepted as NPSH evidence.
    assert out.status=='suction_unverified'


def test_no_extrapolation_or_false_success(symmetric):
    net,chars=symmetric
    out=check_pump_operating_point(net,chars,[(0,50),(3.6,40)],
        suction_static_head_m=10,supply_resistance=.1)
    assert out.status=='outside_published_curve'
    assert out.operating is None and out.pump_flow_m3h is None
    with pytest.raises(ValueError,match='non-increasing'):
        check_pump_operating_point(net,chars,[(0,50),(10,60)],
            suction_static_head_m=10,supply_resistance=.1)
    with pytest.raises(ValueError,match='converge'):
        solve_pressure_flows(net,chars,50,max_iterations=1)


@pytest.mark.parametrize('kind',['duplicate','missing','nan','negative','missing_source','shared','bad_control'])
def test_invalid_data_fail_closed(symmetric,kind):
    net,chars=symmetric
    kwargs={}
    if kind=='duplicate': chars.append(chars[0])
    if kind=='missing': chars.pop()
    if kind=='nan': net.segments[0].A=float('nan')
    if kind=='negative': net.segments[0].length_m=-1
    if kind=='missing_source': chars[0]=replace(chars[0],source='')
    if kind=='shared': net.cabinets[1].node_id='p1'
    if kind=='bad_control': kwargs['ideal_outlet_heads']={'unknown':10}
    with pytest.raises(ValueError): solve_pressure_flows(net,chars,50,**kwargs)


def test_handbook_is_explicit_and_does_not_replace_table():
    cab=FireCabinetNode('pc','n',dn=50,nozzle_mm=13,hose_m=20,jet_m=12)
    model=handbook_characteristic(cab,hose_material='rubber_lined',nozzle_kind='non_shutoff')
    assert model.resistance_mpa_per_lps2==pytest.approx((1/.588**2+.0065*20)/100)
    assert model.minimum_flow_lps==2.6
    assert model.minimum_head_m==pytest.approx(.21*MPA_TO_M)
    # Handbook flow at the mandatory tabular head differs; do not rewrite T73.
    assert sqrt(model.minimum_head_m/model.resistance_head)==pytest.approx(2.636,
        abs=.001)
    assert model.evidence=='handbook_study'
    with pytest.raises(ValueError,match='technical documentation'):
        handbook_characteristic(cab,hose_material='rubber_lined',nozzle_kind='shutoff')
    with pytest.raises(ValueError):
        handbook_characteristic(cab,hose_material='unknown',nozzle_kind='non_shutoff')


def test_documented_characteristic_range_does_not_become_false_pass(symmetric):
    net,chars=symmetric
    chars=[replace(c,evidence='technical_documentation',maximum_head_m=10) for c in chars]
    out=check_pump_operating_point(net,chars,[(0,50),(36,30)],
        suction_static_head_m=10,supply_resistance=.01)
    assert out.status=='outside_characteristic_range'
    assert not out.operating.product_verified
    assert any(c.within_characteristic_range is False for c in out.operating.cabinets)


def test_samara_pressure_driven_review_preserves_baseline(tmp_path):
    from scripts.build_samara_section_study import load_basis,make_draft,make_request,make_fire_station
    from scripts.build_samara_fire_flow_review import calculate_review,render_review
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    from pypdf import PdfReader
    b=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(b))),
        output_dir=str(tmp_path),fire_station=make_fire_station(b),render_documents=False)
    before=deepcopy(bundle.fire_station_result.network)
    old_pump=deepcopy(bundle.project.fire_pumps)
    review=calculate_review(b,bundle)
    assert bundle.fire_station_result.network==before
    assert bundle.project.fire_pumps==old_pump
    assert review['scenario_count']==512
    assert review['summary']['ideal_control']=={'meets_minimum':512}
    assert review['summary']['free']=={'outside_published_curve':264,
        'insufficient_at_cabinet':150,'meets_minimum':98}
    assert not review['release_ready'] and not review['normative_coverage_verified']
    assert review['minimum_header']['total_flow_lps']==pytest.approx(5.271934,abs=2e-6)
    assert review['minimum_boost_m']==pytest.approx(45.661161,abs=3e-5)
    pair=next(s for s in review['scenarios'] if s['floors']==[1,16]
        and s['boundary']=='one_supply_guaranteed')['free']
    assert pair['status']=='insufficient_at_cabinet'
    assert pair['operating']['cabinets'][0]['flow_lps']>4.2
    assert pair['operating']['cabinets'][1]['flow_lps']<1.8
    assert review['required_static_reduction_m']>36
    pdf=tmp_path/'review.pdf'
    render_review(pdf,review)
    reader=PdfReader(pdf)
    assert len(reader.pages)==6
    text='\n'.join(p.extract_text() for p in reader.pages)
    assert 'Не рабочий проект' in text
    assert '1,739' in text
    assert 'не дословная формула СП' in text
    assert 'реальные регуляторы' in text
    assert 'ограничение статики' in text
    regulators = review['regulator_review']
    assert regulators['selected_product'] is None
    assert not regulators['selection_confirmed']
    assert regulators['minimum_available_drop_bar'] == pytest.approx(.5361, abs=.001)
    assert not regulators['ridan_common_window_optimistic_zero_tolerance']['feasible']
    assert all(not row['cabinet_screen']['selection_confirmed'] for row in regulators['items'])

from copy import deepcopy
from math import isclose

import pytest

from app.calc.fire_diaphragm_graph import read_aperture,read_pressure_drop,read_flow,flow_domain,neighbouring_apertures
from app.calc.fire_hydraulics import (
    FireCabinetNode,FireNetwork,HydraulicNode,HydraulicSource,PipeSegment,SourceKind,MPA_TO_M)
from app.calc.fire_nomogram_flow import check_nomogram_operating_point
from app.calc.fire_pressure_flow import CabinetCharacteristic
from app.data.fire_diaphragm_nomogram import APOGEY_SOURCE


def test_printed_dashed_example_and_catalogue_are_not_approval():
    point=read_aperture(valve_dn=50,flow_lps=4.3,pressure_drop_mpa=.34)
    assert point.approximate_aperture_mm==pytest.approx(17,abs=.1)
    assert not point.selection_confirmed
    assert neighbouring_apertures(point,APOGEY_SOURCE['apertures_mm'])==(17,17.5)
    assert len(APOGEY_SOURCE['apertures_mm'])==27
    assert not APOGEY_SOURCE['selection_confirmed']
    assert APOGEY_SOURCE['obsolete_pressure_threshold_mpa_not_used']==.4


@pytest.mark.parametrize('q',[2.5,2.63596658,3,4,5])
@pytest.mark.parametrize('d',[13,14.5,16,18,22])
def test_ruler_round_trip_inside_domain(q,d):
    lo,hi=flow_domain(valve_dn=50,aperture_mm=d)
    if not lo<=q<=hi:
        with pytest.raises(ValueError):read_pressure_drop(valve_dn=50,flow_lps=q,aperture_mm=d)
        return
    pressure=read_pressure_drop(valve_dn=50,flow_lps=q,aperture_mm=d)
    assert read_aperture(valve_dn=50,flow_lps=q,pressure_drop_mpa=pressure).approximate_aperture_mm==pytest.approx(d,abs=1e-9)
    assert read_flow(valve_dn=50,aperture_mm=d,pressure_drop_mpa=pressure)==pytest.approx(q,abs=1e-9)


def test_no_guessed_quadratic_curve_and_monotonicity():
    p1=read_pressure_drop(valve_dn=50,flow_lps=2.6,aperture_mm=16)
    p2=read_pressure_drop(valve_dn=50,flow_lps=3.2,aperture_mm=16)
    assert p1==pytest.approx(.1348706575)
    assert p2==pytest.approx(.2295081806)
    assert not isclose(p2,p1*(3.2/2.6)**2,rel_tol=.05)
    for d in (13,14.5,16,18):
        low,high=flow_domain(valve_dn=50,aperture_mm=d)
        vals=[read_pressure_drop(valve_dn=50,flow_lps=low+(high-low)*i/20,aperture_mm=d) for i in range(21)]
        assert all(b>a for a,b in zip(vals,vals[1:]))


@pytest.mark.parametrize('changes',[{'valve_dn':65},{'flow_lps':2.4},{'flow_lps':10.1},
    {'pressure_drop_mpa':.01},{'pressure_drop_mpa':.71},{'flow_lps':float('nan')},
    {'axis_offset_px':3},{'axis_offset_px':float('nan')}])
def test_graph_fails_closed(changes):
    args=dict(valve_dn=50,flow_lps=4.3,pressure_drop_mpa=.34)
    args.update(changes)
    with pytest.raises(ValueError):read_aperture(**args)


@pytest.fixture
def constructed_network():
    net=FireNetwork({k:HydraulicNode(k,z) for k,z in [('a',0),('b',0),('c',0),('d',0),('p1',10),('p2',10)]},
        [PipeSegment(f'{a}{b}',a,b,1,.1) for a,b in [('a','b'),('b','c'),('c','d'),('d','a')]]+
        [PipeSegment('branch1','a','p1',5,.1),PipeSegment('branch2','c','p2',5,.1)],
        [FireCabinetNode('pc1','p1',dn=50),FireCabinetNode('pc2','p2',dn=50)],
        HydraulicSource('a',SourceKind.CITY_MAIN,50),HydraulicSource('c',SourceKind.CITY_MAIN,50))
    chars=[CabinetCharacteristic(f'pc{i}',2/MPA_TO_M,2.6,8,'Analytical test','handbook_study') for i in (1,2)]
    return net,chars


def test_joint_solution_at_constructed_operating_point(constructed_network):
    net,chars=constructed_network;before=deepcopy(net)
    loss=read_pressure_drop(valve_dn=50,flow_lps=3,aperture_mm=16)*MPA_TO_M
    header=10+(.5+2)*3**2+loss
    out=check_nomogram_operating_point(net,chars,[(0,header-10),(36,header-10)],
        suction_static_head_m=10,supply_resistance=0,apertures_mm={'pc1':16,'pc2':16})
    assert net==before
    assert out.status=='meets_minimum'
    assert out.pump_flow_m3h==pytest.approx(6*3.6,abs=1e-5)
    assert not out.operating.product_verified and not out.operating.ideal_controls
    for c in out.operating.cabinets:
        assert c.flow_lps==pytest.approx(3,abs=1e-6)
        assert c.outlet_head_m==pytest.approx(18,abs=1e-5)
        assert c.control_drop_m==pytest.approx(loss,abs=1e-5)
    assert out.operating.energy_residual_m<1e-3  # includes inner ring tolerance
    assert out.operating.supply_balance_residual_lps<1e-5


def test_unknown_data_or_no_convergence_is_not_a_pass(constructed_network):
    net,chars=constructed_network
    for apertures in [{'unknown':16},{'pc1':11},{'pc1':26}]:
        with pytest.raises(ValueError):check_nomogram_operating_point(net,chars,[(0,60),(36,40)],
            suction_static_head_m=10,supply_resistance=0,apertures_mm=apertures)
    out=check_nomogram_operating_point(net,chars,[(0,60),(36,40)],
        suction_static_head_m=10,supply_resistance=0,apertures_mm={'pc1':16,'pc2':16},max_iterations=1)
    assert out.status=='unresolved_within_nomogram_domain'
    assert out.operating is None and out.pump_flow_m3h is None


def test_samara_apertures_joint_check_and_pdf(tmp_path):
    from pypdf import PdfReader
    from scripts.build_samara_diaphragm_apertures import calculate_apertures,render_apertures,extract_nomogram
    from scripts.build_samara_section_study import load_basis,make_draft,make_request,make_fire_station
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    b=load_basis();bundle=design_ios2(build_project(make_request(make_draft(b))),
        output_dir=str(tmp_path),fire_station=make_fire_station(b),render_documents=False)
    before=deepcopy(bundle.fire_station_result.network);pump=deepcopy(bundle.project.fire_pumps)
    review=calculate_apertures(b,bundle)
    assert bundle.fire_station_result.network==before and bundle.project.fire_pumps==pump
    assert [g['upper_mm'] for g in review['groups']]==[13,13.5,14.5,15.5,18]
    assert [g['next_size_mm'] for g in review['groups']]==[13.5,14,15,16,18.5]
    near,upper,*sensitivity=review['variants']
    assert near['summary']=={'meets_minimum':477,'insufficient_at_cabinet':35}
    assert upper['summary']=={'meets_minimum':512}
    assert upper['p_range_mpa'][0]==pytest.approx(.2115492503,abs=1e-7)
    assert upper['p_range_mpa'][1]<.45
    assert not review['release_ready'] and not review['selection_confirmed']
    assert review['selected_product'] is None and not review['normative_coverage_verified']
    assert 16 not in upper['apertures_by_floor_mm']
    assert sensitivity[0]['summary']=={'meets_minimum':496,'insufficient_at_cabinet':16}
    assert sensitivity[1]['summary']=={'meets_minimum':512}
    for row in sensitivity[2:]:
        assert row['summary']=={'meets_minimum':512}
        assert row['p_range_mpa'][0]>.22
        assert not row['selection_confirmed']
    for variant in review['variants']:
        for s in variant['scenarios']:
            o=s['result']['operating']
            if o is None:
                assert s['result']['status']!='meets_minimum'
                continue
            assert not o['product_verified']
            assert o['energy_residual_m']<1e-3 and o['supply_balance_residual_lps']<1e-5
            for c in o['cabinets']:
                if c['cabinet_id'] not in s['apertures_mm']:continue
                dp=read_pressure_drop(valve_dn=50,flow_lps=c['flow_lps'],
                    aperture_mm=s['apertures_mm'][c['cabinet_id']],axis_offset_px=variant['axis_offset_px'])
                assert c['control_drop_m']==pytest.approx(dp*MPA_TO_M,abs=1e-7)
                assert c['within_device_range']
    image=extract_nomogram()
    pdf=tmp_path/'apertures.pdf';render_apertures(pdf,review,image)
    pages=PdfReader(pdf).pages
    assert len(pages)==3
    text=' '.join(' '.join(p.extract_text() for p in pages).split())
    for phrase in ['512/512','477/512','не утверждённая спецификация','НЕ нормативный допуск',
                   'не ограничивают статику','не комплект ИОС2']:
        assert phrase in text

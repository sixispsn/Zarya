from copy import deepcopy
from dataclasses import replace

import pytest

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_repair_flow import RepairNetwork, check_repair_operating_point
from app.calc.fire_nomogram_flow import check_nomogram_operating_point
from app.calc.fire_diaphragm_graph import read_pressure_drop
from app.calc.ring_hydraulics import solve_ring_scenario
from tests.test_fire_diaphragm_graph import constructed_network
from tests.test_ring_external_inlets import network


@pytest.mark.parametrize('closed', ['a', 'c'])
def test_one_header_port_closed_known_symmetric_ring(constructed_network, closed):
    net, _ = constructed_network; before = deepcopy(net)
    r = RepairNetwork(net, closed_port_ids=[closed]).solve({'pc1': 3., 'pc2': 3.}, 60)
    open_port = 'c' if closed == 'a' else 'a'
    near, far = ('pc2', 'pc1') if closed == 'a' else ('pc1', 'pc2')
    assert r.port_flows_lps == {open_port: 6.}
    assert r.cabinet_heads_m[near] == pytest.approx(60-10-.5*9)
    assert r.cabinet_heads_m[far] == pytest.approx(60-10-.5*9-.2*1.5**2)
    assert r.energy_residual_m < 1e-7 and r.balance_residual_lps < 1e-8
    assert net == before


@pytest.mark.parametrize('closed', ['ab', 'bc', 'cd', 'da'])
def test_cut_ring_two_ports_no_fictitious_double_loss(constructed_network, closed):
    net, _ = constructed_network
    r = RepairNetwork(net, closed_segment_ids=[closed]).solve({'pc1': 3., 'pc2': 3.}, 60)
    assert list(r.cabinet_heads_m.values()) == pytest.approx([45.5, 45.5])
    assert list(r.port_flows_lps.values()) == pytest.approx([3., 3.])
    assert closed not in r.segment_flows_lps


@pytest.mark.parametrize('q1,q2', [(2.6,2.6), (1.,4.), (0.,0.), (0.,3.), (8.,2.)])
def test_single_port_matches_existing_ring_energy_and_external_paths(q1, q2):
    net = network(); before = deepcopy(net)
    result = RepairNetwork(net, closed_port_ids=['S2']).solve({'PK1': q1,'PK2': q2}, 65)
    single = deepcopy(net); single.second_source = None
    if q1+q2:
        old = solve_ring_scenario(single, single.cabinets, {'PK1':q1,'PK2':q2}, {'PK1':10,'PK2':10})
        assert old.ring_result.converged
        for row in old.per_pk:
            assert result.cabinet_heads_m[row.cabinet_id] == pytest.approx(
                65-row.required_head_at_source_m+10, abs=1e-4)
    else:
        assert list(result.cabinet_heads_m.values()) == pytest.approx([18.,18.])
    assert result.segment_flows_lps['I1'] == pytest.approx(q1+q2)
    assert result.segment_flows_lps['I2'] == 0
    assert net == before


def test_two_unequal_header_paths_split_analytically():
    net = network(inlet2_length=80)
    # Remove ring L0; demand PK1 is now supplied through R2/R1.
    out = RepairNetwork(net,closed_segment_ids=['L0']).solve({'PK1':2.,'PK2':3.},65)
    assert sum(out.port_flows_lps.values()) == pytest.approx(5)
    assert out.port_flows_lps['S1'] > out.port_flows_lps['S2'] > 0
    assert out.energy_residual_m < 1e-7
    reversed_net = deepcopy(net)
    reversed_net.segments = [replace(s, from_node=s.to_node, to_node=s.from_node)
                             for s in reversed(net.segments)]
    reverse = RepairNetwork(reversed_net, closed_segment_ids=['L0']).solve({'PK1':2.,'PK2':3.},65)
    assert reverse.cabinet_heads_m == pytest.approx(out.cabinet_heads_m)
    assert reverse.segment_flows_lps == pytest.approx({k:-v for k,v in out.segment_flows_lps.items()})


@pytest.mark.parametrize('kwargs', [{}, {'closed_port_ids':['absent']}, {'closed_segment_ids':['absent']},
    {'closed_port_ids':['a','c']}, {'closed_segment_ids':['branch1']},
    {'closed_segment_ids':['ab','da','branch2'],'closed_port_ids':['a']}])
def test_invalid_isolation_or_disconnected_cabinets_never_dropped(constructed_network,kwargs):
    net, _ = constructed_network
    with pytest.raises(ValueError): RepairNetwork(net,**kwargs)


@pytest.mark.parametrize('attribute,value', [('A',0),('A',float('nan')),('length_m',-1),('equiv_length_m',-2)])
def test_invalid_pipe_data_fails(constructed_network,attribute,value):
    net, _ = constructed_network
    setattr(net.segments[0],attribute,value)
    with pytest.raises(ValueError): RepairNetwork(net,closed_port_ids=['a'])


@pytest.mark.parametrize('nomogram',[False,True])
def test_joint_repair_equations_match_constructed_point_and_intact(nomogram,constructed_network):
    net,chars=constructed_network; before=deepcopy(net)
    loss=read_pressure_drop(valve_dn=50,flow_lps=3,aperture_mm=16)*MPA_TO_M if nomogram else 0
    header=10+(.5+2)*9+loss
    rs,rd,supply,hs=.1,.2,.3,50.
    hp=header-hs+(rs+rd+supply)*36
    args=dict(suction_static_head_m=hs,supply_resistance=supply,
        station_suction_resistance=rs,station_discharge_resistance=rd,
        apertures_mm={'pc1':16,'pc2':16} if nomogram else {})
    new=check_repair_operating_point(net,chars,[(0,hp),(36,hp)],closed_segment_ids=['ab'],**args)
    old=check_nomogram_operating_point(net,chars,[(0,hp),(36,hp)],**args)
    assert new.status==old.status=='meets_minimum'
    assert new.pump_flow_m3h==pytest.approx(21.6,abs=1e-5)
    assert new.pump_flow_m3h==pytest.approx(old.pump_flow_m3h,abs=1e-5)
    assert new.operating.header_head_m==pytest.approx(header,abs=1e-5)
    assert new.suction_head_m==pytest.approx(hs-(supply+rs)*36,abs=1e-5)
    assert new.operating.energy_residual_m<1e-5
    assert not new.operating.product_verified and net==before


def test_convergence_range_and_insufficient_pressure_do_not_pass(constructed_network):
    net,chars=constructed_network
    args=dict(closed_port_ids=['a'],suction_static_head_m=0,supply_resistance=0,apertures_mm={})
    fail=check_repair_operating_point(net,chars,[(0,18),(40,18)],**args)
    assert fail.operating and any(not c.meets_minimum for c in fail.operating.cabinets)
    assert fail.status!='meets_minimum'
    fail=check_repair_operating_point(net,chars,[(0,70),(40,50)],max_iterations=1,**args)
    assert fail.status=='unresolved_within_nomogram_domain' and fail.operating is None
    fail=check_repair_operating_point(net,chars,[(0,70),(1,50)],**args)
    assert fail.status=='unresolved_within_nomogram_domain' and fail.operating is None
    with pytest.raises(ValueError):
        check_repair_operating_point(net,chars,[(0,70),(40,50)],**{**args,'apertures_mm':{'pc1':11}})


def test_unsupported_internal_check_valve_not_treated_as_open_pipe(constructed_network):
    from app.calc.fire_hydraulics import Valve, ValveKind
    net, _ = constructed_network
    net.segments[0].valves=[Valve('v',ValveKind.CHECK,1)]
    with pytest.raises(ValueError,match='check-valve'):
        RepairNetwork(net,closed_port_ids=['c'])


def test_samara_repairs_do_not_inherit_intact_pass_or_retune_controls(tmp_path):
    from scripts.build_samara_repair_review import calculate_repair_review, load_repair_baseline
    from app.intake.samara_study import load_case
    before=deepcopy(load_case())
    baseline=load_repair_baseline()
    r=calculate_repair_review()
    assert load_case()==before
    assert len(r['cases'])==8 and sum(v['scenario_count'] for c in r['cases'] for v in c['variants'])==12288
    assert not r['all_model_minima_met'] and not r['release_ready']
    assert not r['normative_sectioning_confirmed'] and not r['room_coverage_confirmed']
    assert r['duty_pumps']==r['reserve_pumps']==1 and not r['reserve_in_flow_sum']
    assert r['apertures_mm']=={int(k):v for k,v in baseline['payload']['result']['nominal_apertures_mm'].items()}
    for case in r['cases']:
        for variant in case['variants']:
            assert variant['complete'] and variant['all_dynamic_limits_met']
            assert len({(tuple(s['floors']),s['boundary']) for s in variant['scenarios']})==512
            if case['kind']=='header_port':
                fail={0.:27,-2.:29,2.:26}[variant['axis_offset_px']]
                assert variant['summary']=={'meets_minimum':512-fail,'insufficient_at_cabinet':fail}
            else:
                assert variant['all_minima_met'] and variant['summary']=={'meets_minimum':512}
            for s in variant['scenarios']:
                result=s['result'];op=result['operating'];q=result['pump_flow_m3h']/3.6
                assert op['header_head_m']==pytest.approx(result['suction_head_m']+result['pump_head_m']-r['pipework_resistances']['discharge']*q*q)
                assert op['supply_balance_residual_lps']<1e-5 and op['energy_residual_m']<1e-3
    compared=r['comparison']['cases']
    assert compared[0]['result']['status']=='meets_minimum'
    assert compared[1]['result']['status']=='insufficient_at_cabinet'
    assert compared[1]['result']['operating']['cabinets'][0]['outlet_head_m']/MPA_TO_M==pytest.approx(.2040170913,abs=1e-8)
    assert sum(r['comparison']['repair_network']['port_flows_lps'].values())==pytest.approx(compared[1]['result']['pump_flow_m3h']/3.6)
    from app.pz.fire_repair_review_report import render_repair_review
    from pypdf import PdfReader
    from tests.test_station_graphic_frames import qa_document, check_text_frames
    path=tmp_path/'repair.pdf';render_repair_review(path,r,document=qa_document())
    check_text_frames(path.read_bytes(),3)
    pdf=PdfReader(path)
    assert len(pdf.pages)==3 and len(pdf.outline)==3
    text=' '.join(' '.join(p.extract_text() for p in pdf.pages).split())
    for phrase in ['485 / 512','512 / 512','0,204017','12288','не складываются',
                   'границы реальной ремонтной секции','не является полным комплектом']:
        assert phrase in text

from copy import deepcopy
from dataclasses import replace
from math import pi

import pytest

from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_station_pipework import PipeworkElement, StationPipework, station_curve_samples
from app.data.fire_station_design import samara_pipework, AUTOMATION_ASSIGNMENT
from tests.test_fire_diaphragm_graph import constructed_network
from app.calc.fire_diaphragm_graph import read_pressure_drop
from app.calc.fire_nomogram_flow import check_nomogram_operating_point
from app.calc.fire_pressure_flow import check_pump_operating_point


def test_pipework_units_and_explicit_assumptions():
    model=samara_pipework();r=model.audit(18.978962148583935)
    assert r['total_loss_m']==pytest.approx(3.2627208566969577)
    assert r['losses_m']['discharge']>r['losses_m']['suction']>0
    assert r['zero_flow_loss_m']==0 and sum(model.losses(0).values())==0
    assert not r['manufacturer_confirmed'] and not r['reserve_in_flow_sum']
    assert sum(model.losses(2*r['q_m3h']).values())==pytest.approx(4*r['total_loss_m'])
    for row in model.elements:
        if row.method=='Kv':
            assert row.resistance()==pytest.approx(MPA_TO_M/10*(3.6/row.value)**2)
        elif row.method=='A_L':
            assert row.resistance()==pytest.approx(row.value*row.length_m)
        else:
            area=pi*(row.inner_mm/1000)**2/4
            assert row.resistance()==pytest.approx(row.value*(.001/area)**2/19.62)


@pytest.mark.parametrize('change',[dict(value=0),dict(value=float('nan')),dict(value=-1),
    dict(basis=''),dict(side='reserve'),dict(method='default'),dict(quantity_on_active_path=0),
    dict(quantity_on_active_path=1.5),dict(length_m=0)])
def test_invalid_pipework_rejected(change):
    with pytest.raises(ValueError):replace(samara_pipework().elements[0],**change).resistance()


def test_empty_duplicate_one_sided_and_invalid_flow_rejected():
    rows=samara_pipework().elements
    for el in [(),(rows[0],rows[0]),(rows[0],)]:
        with pytest.raises(ValueError):StationPipework(el,'test').resistances()
    for q in [-1,float('nan'),float('inf')]:
        with pytest.raises(ValueError):samara_pipework().losses(q)


def test_curve_is_single_pump_and_net_loss_is_exact_between_knots():
    model=samara_pipework();rows=station_curve_samples([(0,60),(40,20)],model,samples=5)
    assert rows[0]['q_m3h']==0 and rows[-1]['q_m3h']==40 # never doubled to 80
    assert rows[0]['station_net_boost_m']==60 # no fictitious static reduction
    for row in rows:
        assert row['single_pump_head_m']==pytest.approx(60-row['q_m3h'])
        assert row['station_net_boost_m']==pytest.approx(row['single_pump_head_m']-sum(model.losses(row['q_m3h']).values()))


@pytest.mark.parametrize('nomogram',[False,True])
def test_suction_discharge_balance_and_no_mutation(constructed_network,nomogram):
    net,chars=constructed_network;before=deepcopy(net)
    q_each=3.;q=q_each*2;rs=.1;rd=.2;supply=.3;hs=50.
    local=read_pressure_drop(valve_dn=50,flow_lps=q_each,aperture_mm=16)*MPA_TO_M if nomogram else 0.
    header=10+(.5+2)*q_each**2+local
    hp=header-hs+(supply+rs+rd)*q*q
    curve=[(0,hp),(36,hp)]
    result=check_nomogram_operating_point(net,chars,curve,suction_static_head_m=hs,supply_resistance=supply,
        apertures_mm={'pc1':16,'pc2':16} if nomogram else {},
        station_suction_resistance=rs,station_discharge_resistance=rd)
    assert net==before
    assert result.pump_flow_m3h==pytest.approx(q*3.6,abs=2e-5)
    assert result.suction_head_m==pytest.approx(hs-(supply+rs)*q*q,abs=2e-5)
    assert result.operating.header_head_m==pytest.approx(header,abs=2e-5)
    assert result.suction_head_m+result.pump_head_m-rd*(result.pump_flow_m3h/3.6)**2==pytest.approx(result.operating.header_head_m)
    assert not result.operating.product_verified


@pytest.mark.parametrize('key',['station_suction_resistance','station_discharge_resistance'])
@pytest.mark.parametrize('value',[-1,float('nan'),float('inf')])
def test_invalid_station_resistances_fail_both_solvers(constructed_network,key,value):
    net,chars=constructed_network
    for fn,extra in [(check_pump_operating_point,{}),(check_nomogram_operating_point,dict(apertures_mm={'pc1':16}))]:
        with pytest.raises(ValueError):fn(net,chars,[(0,60),(36,40)],suction_static_head_m=10,supply_resistance=0,**extra,**{key:value})


def test_automation_is_a_design_assignment_not_passport_approval():
    a=AUTOMATION_ASSIGNMENT
    assert a['status']=='project_requirement' and not a['manufacturer_confirmed']
    assert a['reserve_installed'] and a['duty_pumps']==a['reserve_pumps']==1
    assert not a['reserve_in_flow_sum'] and not a['awaiting_manufacturer_response']
    text=' '.join(a['requirements'])
    assert 'автоматически включается' in text and 'сухому ходу' in text
    assert 'не назначаются' in text


def test_samara_pipework_rechecks_old_and_revised_apertures_and_pdf(tmp_path):
    from pypdf import PdfReader
    from scripts.build_samara_station_design import calculate_station_design
    from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    from app.pz.fire_station_design_report import render_station_design
    b=load_basis();station=make_fire_station(b)
    bundle=design_ios2(build_project(make_request(make_draft(b))),output_dir=str(tmp_path),
        fire_station=station,render_documents=False)
    before=deepcopy(bundle.project);net_before=deepcopy(bundle.fire_station_result.network)
    r=calculate_station_design(b,bundle)
    assert bundle.project==before and bundle.fire_station_result.network==net_before
    assert r['adopted_assumptions_pass']
    assert r['previous_layout_check']['summary']=={'meets_minimum':481,'insufficient_at_cabinet':31}
    assert r['previous_apertures_mm'][15]==18.5 and r['nominal_apertures_mm'][15]==19.5
    assert r['nominal_apertures_mm'][12]==16.5
    assert r['required_bare_pump_head_m']==pytest.approx(48.9238815681)
    assert r['head_margin_at_required_q_m']==pytest.approx(2.8418968204)
    assert r['nominal_static_lowest_pc_mpa']==pytest.approx(.86774355)
    assert not r['release_ready'] and not r['station_product_confirmed']
    assert not r['external_reply_required_for_assignment'] and not r['external_request_sent']
    assert len(r['variants'])==9
    for v in r['variants']:
        assert v['scenario_count']==512
        assert len({(tuple(s['floors']),s['boundary']) for s in v['scenarios']})==512
        if v['loss_scale']==1:
            assert v['summary']=={'meets_minimum':512} and v['all_dynamic_limits_met']
        for s in v['scenarios']:
            result=s['result'];op=result['operating']
            if op is None:
                assert result['status']!='meets_minimum'
                continue
            q=result['pump_flow_m3h']/3.6
            rd=r['pipework']['resistances_m_per_lps2']['discharge']*v['loss_scale']
            assert op['header_head_m']==pytest.approx(result['suction_head_m']+result['pump_head_m']-rd*q*q)
            assert op['energy_residual_m']<1e-3 and op['supply_balance_residual_lps']<1e-5
    path=tmp_path/'station-design.pdf';render_station_design(path,r)
    pdf=PdfReader(path);assert len(pdf.pages)==5 and len(pdf.outline)==5
    text=' '.join(' '.join(page.extract_text() for page in pdf.pages).split())
    for phrase in ['Потери принятой обвязки','Задание на автоматизацию','512/512','481/512',
                   'не складываются','Изготовителю ничего не отправлено','16,5 / 19,5']:
        assert phrase in text
    assert 'Вопросы изготовителю' not in text and '80 м3/ч' not in text

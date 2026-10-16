from copy import deepcopy
from io import BytesIO
from math import ulp, nextafter, inf

import pytest

from app.data.fire_diaphragm_layout import diaphragm_groups, floor_label
from app.pz.fire_station_binding import digest, validate_design, station_spec_rows


def assert_repair_platform_parity(actual, stored):
    # Linux libm differs from the signed macOS result by exactly one ULP in
    # this one extremum (22.060048801277876 versus 22.060048801277873).
    # All other values, keys, types, signatures and flags remain digest-exact.
    # Normalize only a TEST copy; never re-sign or mutate either result.
    check=deepcopy(actual)
    path=check['cases'][0]['variants'][0]['flow_range_m3h']
    expected=stored['cases'][0]['variants'][0]['flow_range_m3h'][1]
    assert type(path[1]) is type(expected) is float
    assert abs(path[1]-expected)<=ulp(expected)
    path[1]=expected
    assert digest(check)==digest(stored)


@pytest.mark.parametrize('mutation',['one_ulp','two_ulps','other_value'])
def test_platform_parity_exception_is_one_ulp_at_one_explicit_leaf(mutation):
    stored={'cases':[{'variants':[{'flow_range_m3h':[1.,22.060048801277873]}]}]}
    actual=deepcopy(stored)
    values=actual['cases'][0]['variants'][0]['flow_range_m3h']
    values[1]=nextafter(values[1],inf)
    if mutation=='two_ulps':values[1]=nextafter(values[1],inf)
    if mutation=='other_value':values[0]=nextafter(values[0],inf)
    if mutation=='one_ulp':
        before=deepcopy(actual)
        assert_repair_platform_parity(actual,stored)
        assert actual==before
    else:
        with pytest.raises(AssertionError):assert_repair_platform_parity(actual,stored)


def test_groups_follow_actual_apertures_not_three_floor_template():
    groups=diaphragm_groups({'15':21,'13':19.5,'14':19.5,'10':16.5,'12':16.5,'11':16.5})
    assert [floor_label(g) for g in groups]==['10-12','13-14','15']
    assert [g['aperture_mm'] for g in groups]==[16.5,19.5,21]
    assert len(diaphragm_groups({1:14,3:14}))==2


@pytest.mark.parametrize('layout',[{0:14},{1:float('nan')},{1:-1},{1:14,'1':14}])
def test_invalid_aperture_presentation_does_not_hide_bad_data(layout):
    with pytest.raises(ValueError):diaphragm_groups(layout)


@pytest.fixture(scope='module')
def reviewed_case():
    from app.intake.samara_study import load_case
    from app.intake.project_builder import build_project
    from app.intake.yaml_io import load_request
    from scripts.build_samara_section_study import make_fire_station
    payload=load_case()['payload']
    return payload['result'],build_project(load_request(payload['request_yaml'])),make_fire_station(payload['basis'])


def test_correction_recomputes_every_case_without_changing_pump_or_pipes(reviewed_case):
    from scripts.build_samara_repair_review import calculate_repair_review, load_repair_baseline
    from scripts.build_samara_diaphragm_correction import compact_review
    r,_,_=reviewed_case;before=deepcopy(r)
    layout={int(f):d for f,d in r['nominal_apertures_mm'].items()}
    proof=calculate_repair_review(apertures_override=layout,include_intact=True)
    baseline=load_repair_baseline()['payload']['result']
    assert [f for f,d in layout.items() if d!=baseline['nominal_apertures_mm'][str(f)]]==[15]
    assert layout[15]==21 and layout[13]==layout[14]==19.5
    assert proof['pump']==baseline['pump'] and proof['pipework_resistances']==baseline['pipework']['resistances_m_per_lps2']
    assert proof['duty_pumps']==proof['reserve_pumps']==1 and not proof['reserve_in_flow_sum']
    variants=[v for c in proof['cases'] for v in c['variants']]
    assert len(variants)==27 and sum(v['scenario_count'] for v in variants)==13824
    for v in variants:
        assert v['complete'] and v['all_minima_met'] and v['all_dynamic_limits_met']
        assert v['summary']=={'meets_minimum':512}
    assert min(v['pressure_range_mpa'][0] for v in variants)==pytest.approx(.2116091625823,abs=1e-9)
    assert max(v['pressure_range_mpa'][1] for v in variants)==pytest.approx(.2906675583768,abs=1e-9)
    assert proof['nominal_static_lowest_pc_mpa']==baseline['nominal_static_lowest_pc_mpa']
    assert not proof['release_ready'] and not proof['room_coverage_confirmed'] and not proof['normative_sectioning_confirmed']
    stored={k:v for k,v in r['repair_review'].items() if k!='correction'}
    assert_repair_platform_parity(compact_review(proof),stored)
    assert r==before


def test_trials_explain_why_first_passing_size_not_selected(reviewed_case):
    r,_,_=reviewed_case
    trials={(t['scope'],t['diameter_mm']):t for t in r['repair_review']['correction']['trials']}
    assert len(trials)==6
    assert not trials['group',20.5]['all_minima_met']
    assert trials['group',21]['minimum_pressure_mpa']==pytest.approx(.2102006986,abs=1e-9)
    tight=trials['floor15',20.5]
    assert tight['all_minima_met'] and tight['minimum_pressure_mpa']==pytest.approx(.2100068619877,abs=1e-9)
    assert trials['floor15',21]['minimum_pressure_mpa']>tight['minimum_pressure_mpa']


def test_pump_tuples_before_serialization_match_json_lists(reviewed_case):
    r,p,s=reviewed_case;r=deepcopy(r)
    r['pump']['curve']=tuple(map(tuple,r['pump']['curve']))
    r['pump']['unresolved']=tuple(r['pump']['unresolved'])
    r['content_sha256']=digest({k:v for k,v in r.items() if k!='content_sha256'})
    validate_design(r,p,s)


@pytest.mark.parametrize('change',['aperture','pump','pipework','static','missing_case','missing_variant','failure','pressure'])
def test_even_resigned_inconsistent_repair_proof_is_rejected(reviewed_case,change):
    r,p,s=reviewed_case;r=deepcopy(r);proof=r['repair_review']
    if change=='aperture':proof['apertures_mm']['15']=19.5
    elif change=='pump':proof['pump']['curve'][0][1]+=1
    elif change=='pipework':proof['pipework_resistances']['discharge']+=.1
    elif change=='static':proof['nominal_static_lowest_pc_mpa']+=.1
    elif change=='missing_case':proof['cases'].pop()
    elif change=='missing_variant':proof['cases'][0]['variants'].pop()
    elif change=='failure':proof['cases'][0]['variants'][0]['summary']={'meets_minimum':511,'insufficient_at_cabinet':1}
    elif change=='pressure':proof['cases'][0]['variants'][0]['pressure_range_mpa'][1]=.46
    r['content_sha256']=digest({k:v for k,v in r.items() if k!='content_sha256'})
    with pytest.raises(ValueError,match='[Rr]epair'):validate_design(r,p,s)


def test_spec_and_report_preserve_single_floor_override(reviewed_case,tmp_path):
    from app.pz.fire_station_design_report import render_station_design
    from pypdf import PdfReader
    r,_,_=reviewed_case
    rows={x['id']:x for x in station_spec_rows(r)}
    assert rows['diaphragm-13']['name'].endswith('13-14')
    assert rows['diaphragm-13']['mark']=='Отверстие 19.5 мм'
    assert '4 шт.' in rows['diaphragm-13']['note']
    assert rows['diaphragm-15']['name'].endswith('этаж 15')
    assert rows['diaphragm-15']['mark']=='Отверстие 21 мм'
    assert '2 шт.' in rows['diaphragm-15']['note'] and rows['diaphragm-15']['qty'] is None
    path=tmp_path/'station.pdf';render_station_design(path,r)
    pdf=PdfReader(path);assert len(pdf.pages)==8 and len(pdf.outline)==8
    text=' '.join(' '.join(p.extract_text() for p in pdf.pages).split())
    for phrase in ['13-14 / 15','19,5 / 21','13824','0,211609','не складываются','512/512','паспортные допуски']:
        assert phrase in text

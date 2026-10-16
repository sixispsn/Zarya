from copy import deepcopy
import pytest

from app.calc.fire_diaphragm import prepare_nomogram_inputs
from app.calc.fire_hydraulics import MPA_TO_M
from scripts.build_samara_diaphragm_review import group_target_resistances


def point(**changes):
    values=dict(valve_dn=50,flow_lps=4.3,inlet_head_m=.55*MPA_TO_M,required_outlet_head_m=.21*MPA_TO_M)
    values.update(changes)
    return prepare_nomogram_inputs(**values)


def test_amendment_one_pressure_axis_is_difference_not_downstream_pressure():
    out=point()
    assert out.pressure_drop_mpa==pytest.approx(.34)
    assert out.pressure_axis_value==pytest.approx(34)
    assert out.pressure_axis_value!=pytest.approx(21)
    assert out.within_printed_axes
    assert 'изменения 1' in out.source
    assert out.aperture_mm is None and not out.selection_confirmed
    # Same pressure difference, different outlet pressure -> identical graph input.
    other=point(inlet_head_m=.65*MPA_TO_M,required_outlet_head_m=.31*MPA_TO_M)
    assert other.pressure_drop_mpa==pytest.approx(out.pressure_drop_mpa)


@pytest.mark.parametrize('drop',[.02,.70])
@pytest.mark.parametrize('flow',[2.5,10])
def test_nomogram_exact_printed_boundaries(drop,flow):
    assert point(flow_lps=flow,inlet_head_m=(.21+drop)*MPA_TO_M).within_printed_axes


def test_sources_are_identified_and_unchanged_when_available():
    from hashlib import sha256
    from pathlib import Path
    from app.calc.fire_diaphragm import NORMATIVE_SOURCES
    assert NORMATIVE_SOURCES[1]['pdf_page']==33
    for source in NORMATIVE_SOURCES:
        path=Path('/Users/antonpashkevich/Downloads')/source['file']
        if path.exists():
            assert sha256(path.read_bytes()).hexdigest()==source['sha256']


@pytest.mark.parametrize('changes',[{'flow_lps':2.4},{'flow_lps':10.1},
    {'inlet_head_m':.22*MPA_TO_M},{'inlet_head_m':.95*MPA_TO_M}])
def test_nomogram_outside_axes_is_not_clamped_or_selected(changes):
    out=point(**changes)
    assert not out.within_printed_axes and out.aperture_mm is None
    assert not out.selection_confirmed


@pytest.mark.parametrize('changes',[{'valve_dn':40},{'flow_lps':0},
    {'flow_lps':float('nan')},{'inlet_head_m':float('inf')},
    {'inlet_head_m':.20*MPA_TO_M},{'required_outlet_head_m':-1}])
def test_bad_nomogram_inputs_raise(changes):
    with pytest.raises(ValueError): point(**changes)


def test_explicit_group_target_is_frozen_and_not_claimed_as_sp_rule():
    data={1:9,2:8,3:7,4:6,5:5}
    old=deepcopy(data)
    groups=group_target_resistances(data,3)
    assert data==old
    assert groups==[dict(floors=[1,2,3],resistance_head_per_lps2=7),
                    dict(floors=[4,5],resistance_head_per_lps2=5)]
    for values,size in [({},3),({1:1,3:2},3),({1:-1},3),({1:1},2),({1:float('nan')},3)]:
        with pytest.raises(ValueError): group_target_resistances(values,size)


def test_samara_fixed_resistances_and_report_preserve_baseline(tmp_path):
    from pypdf import PdfReader
    from scripts.build_samara_diaphragm_review import calculate_diaphragm_review,render_review
    from scripts.build_samara_section_study import load_basis,make_draft,make_request,make_fire_station
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    b=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(b))),output_dir=str(tmp_path),
        fire_station=make_fire_station(b),render_documents=False)
    old_net=deepcopy(bundle.fire_station_result.network)
    old_pump=deepcopy(bundle.project.fire_pumps)
    out=calculate_diaphragm_review(b,bundle)
    assert bundle.fire_station_result.network==old_net
    assert bundle.project.fire_pumps==old_pump
    assert not out['release_ready'] and not out['selection_confirmed'] and out['selected_product'] is None
    assert not out['normative_coverage_verified'] and not out['static_protection_by_diaphragm']
    assert out['nominal_static_by_floor_mpa'][1]==pytest.approx(.86774355)
    a,c=out['variants']
    assert a['summary']=={'meets_minimum':512}
    assert c['summary']=={'meets_minimum':504,'insufficient_at_cabinet':8}
    assert c['pressure_range_mpa'][0]==pytest.approx(.209442019,abs=1e-7)
    assert a['pressure_range_mpa'][0]==pytest.approx(.21,abs=1e-7)
    for v in (a,c):
        assert v['complete_solution'] and v['dynamic_pressure_limit_met']
        by_floor={f:g['resistance_head_per_lps2'] for g in v['groups'] for f in g['floors']}
        assert 16 not in by_floor
        for g in v['groups']:
            assert g['nomogram_inputs']['within_printed_axes']
            assert g['nomogram_inputs']['aperture_mm'] is None
            assert not g['nomogram_inputs']['selection_confirmed']
        for s in v['scenarios']:
            op=s['result']['operating']
            assert not op['product_verified'] and not op['ideal_controls']
            assert op['energy_residual_m']<1e-3 and op['supply_balance_residual_lps']<1e-5
            assert abs(s['result']['boundary_residual_lps'])<=1e-6
            for floor,row in zip(s['floors'],op['cabinets']):
                if floor in by_floor:
                    d=s['fixed_cabinets'][row['cabinet_id']]
                    assert d['resistance_head_per_lps2']==by_floor[floor]
                    assert row['control_drop_m']==pytest.approx(by_floor[floor]*row['flow_lps']**2,abs=1e-3)
                else:
                    assert row['cabinet_id'] not in s['fixed_cabinets'] and row['control_drop_m']==0
    path=tmp_path/'diaphragms.pdf'
    render_review(path,out)
    pages=PdfReader(path).pages
    assert len(pages)==3
    text=' '.join(' '.join(p.extract_text() for p in pages).split())
    for phrase in ['512/512','504/512','0,209442','Целевые сопротивления',
                   'не окончательный подбор отверстий','не защищает','не комплект ИОС2']:
        assert phrase in text

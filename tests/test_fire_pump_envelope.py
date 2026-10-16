from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from app.calc.fire_pump_envelope import screen_pump_envelope
from app.data.fire_pump_study import STUDY_CANDIDATES


def screen(curve, **overrides):
    values = dict(required_q_m3h=20, required_boost_m=40,
                  maximum_suction_head_m=30, allowed_header_static_m=90)
    values.update(overrides)
    return screen_pump_envelope(curve, **values)


def test_checks_duty_and_shutoff_independently():
    result = screen([(0,80),(20,50),(30,20)])
    assert result.dynamic_margin_m == 10
    assert result.static_margin_m == -20
    assert result.failures == ('excessive_nominal_static_head',)
    assert not result.nominal_bounds_met
    result = screen([(0,55),(20,39),(30,20)])
    assert result.failures == ('insufficient_duty_head',)
    assert not result.nominal_bounds_met


def test_closed_boundaries_are_included_not_rounded():
    result = screen([(0,60),(20,40)])
    assert result.nominal_bounds_met
    assert result.dynamic_margin_m == result.static_margin_m == 0
    assert not result.selection_confirmed
    assert not screen([(0,60.0000001),(20,40)]).nominal_bounds_met
    assert not screen([(0,60),(20,39.9999999)]).nominal_bounds_met


def test_missing_shutoff_is_unknown_not_maximum_of_curve():
    result = screen([(5,58),(20,50),(30,20)])
    assert result.shutoff_head_m is None and result.static_margin_m is None
    assert result.missing == ('no_published_shutoff_head',)
    assert not result.nominal_bounds_met


def test_no_extrapolation_for_duty():
    result = screen([(0,55),(19,42)])
    assert result.duty_head_m is None and result.dynamic_margin_m is None
    assert result.missing == ('duty_outside_published_curve',)
    assert not result.nominal_bounds_met


@pytest.mark.parametrize('curve', [[], [(0,50)], [(0,50),(10,55)],
    [(0,50),(0,40)], [(0,float('nan')),(20,40)], [(0,50),(20,-1)]])
def test_invalid_curves_rejected(curve):
    with pytest.raises(ValueError): screen(curve)


@pytest.mark.parametrize('field', ['required_q_m3h','required_boost_m',
    'maximum_suction_head_m','allowed_header_static_m'])
@pytest.mark.parametrize('value', [-1, float('nan'), float('inf')])
def test_invalid_boundaries_rejected(field,value):
    with pytest.raises(ValueError): screen([(0,60),(20,40)], **{field:value})


def test_exact_source_rows_stay_separate_from_production():
    from app.data.pumps import list_pumps
    a,b = STUDY_CANDIDATES
    assert a.curve == ((0,55.5),(10,52.5),(12,51),(14,50),(16,49),(18,48),
                       (20,46),(22,44),(24,41),(26,37),(28,33),(29,31.5))
    assert b.curve == ((0,57),(16,54),(20,51),(24,48),(28,44),(32,40),(36,35),(40,27))
    assert (a.station_connection_dn,b.station_connection_dn) == (80,100)
    assert a.power_per_pump_kw == b.power_per_pump_kw == 5.5
    assert (a.curve_pdf_page,b.curve_pdf_page) == (31,33)
    assert (a.station_pdf_page,a.station_printed_page) == (38,39)
    assert (b.station_pdf_page,b.station_printed_page) == (40,40)
    assert all(not c.selection_confirmed and len(c.unresolved)>=5 for c in STUDY_CANDIDATES)
    assert all('CDM20-4' not in p.model and 'CDM32-3' not in p.model
               for p in list_pumps(include_current=True))


def test_source_hashes_when_user_catalogs_available():
    root=Path('/Users/antonpashkevich/Downloads')
    c=STUDY_CANDIDATES[0]
    for file,expected in [(c.curve_source,c.curve_sha256),(c.station_source,c.station_sha256)]:
        p=root/file
        if not p.exists(): pytest.skip('User-supplied PDFs not distributed with repository')
        assert sha256(p.read_bytes()).hexdigest() == expected


def test_samara_comparison_is_reproducible_and_not_a_release(tmp_path):
    from pypdf import PdfReader
    from scripts.build_samara_pump_comparison import calculate_comparison,render_comparison
    from scripts.build_samara_section_study import load_basis,make_draft,make_request,make_fire_station
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    b=load_basis()
    bundle=design_ios2(build_project(make_request(make_draft(b))), output_dir=str(tmp_path),
        fire_station=make_fire_station(b),render_documents=False)
    old_network=deepcopy(bundle.fire_station_result.network)
    old_pump=deepcopy(bundle.project.fire_pumps)
    out=calculate_comparison(b,bundle)
    assert bundle.fire_station_result.network == old_network
    assert bundle.project.fire_pumps == old_pump
    assert out['selected_product'] is None and not out['release_ready']
    assert out['maximum_pump_shutoff_m'] == pytest.approx(60.28811927)
    assert out['required_q_m3h'] == pytest.approx(18.97896215)
    assert out['required_boost_m'] == pytest.approx(45.66116071)
    assert out['baseline']['screen']['failures'] == ('excessive_nominal_static_head',)
    a,c=out['candidates']
    assert a['ideal_control_floors'] == list(range(1,15))
    assert c['ideal_control_floors'] == list(range(1,16))
    assert a['screen']['dynamic_margin_m'] == pytest.approx(1.35987714)
    assert c['screen']['dynamic_margin_m'] == pytest.approx(6.10461768)
    assert c['screen']['static_margin_m'] == pytest.approx(3.28811927)
    assert c['static_by_floor_mpa'][1] == pytest.approx(.86774355)
    assert c['summary']['free'] == {'meets_minimum':504,'insufficient_at_cabinet':8}
    assert a['summary']['free'] == {'meets_minimum':421,'insufficient_at_cabinet':60,'outside_published_curve':31}
    for row in out['candidates']:
        assert row['scenario_count']==512 and row['complete_ideal_solution']
        assert row['summary']['ideal_selective'] == {'meets_minimum':512}
        assert row['maximum_ideal_outlet_mpa'] < .45
        assert row['minimum_control_drop_bar'] < 1.5
        assert not row['selection_confirmed']
        assert row['regulator_screens'][0]['failures']==('insufficient_control_drop',)
        assert all(not r['selection_confirmed'] for r in row['regulator_screens'])
        for s in row['scenarios']:
            o=s['ideal_selective']['operating']
            assert abs(s['ideal_selective']['boundary_residual_lps']) <= 1e-6
            assert o['energy_residual_m'] < 1e-3
            assert o['supply_balance_residual_lps'] < 1e-5
            assert not o['product_verified']
            assert all(x['meets_minimum'] for x in o['cabinets'])
    top=next(s for s in c['scenarios'] if s['floors']==[16,16]
             and s['boundary']=='one_supply_guaranteed')
    assert top['controlled_cabinets']==[]
    assert top['free']['pump_flow_m3h']==pytest.approx(20.615,abs=.001)
    mixed=next(s for s in c['scenarios'] if s['floors']==[1,16]
               and s['boundary']=='one_supply_guaranteed')
    assert mixed['free']['status']=='insufficient_at_cabinet'
    assert len(mixed['controlled_cabinets'])==1
    assert mixed['ideal_selective']['status']=='meets_minimum'
    pdf=tmp_path/'comparison.pdf'
    render_comparison(pdf,out)
    pages=PdfReader(pdf).pages
    assert len(pages)==4
    text=' '.join(' '.join(p.extract_text() for p in pages).split())
    for phrase in ['0,868','6,105','512/512','НЕ рабочая точка','не окончательный подбор',
                   'характеристики одиночных насосов','не комплект ИОС2']:
        assert phrase in text

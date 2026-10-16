"""Independent СП30 5.7/table 5.1 regression, including actual Studio handoff."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import math

import pytest

from app.calc.sewage_horizontal import calculate_horizontal_sewage, resolve_horizontal_flow, select_ks
from app.calc.water_demand import ConsumerGroup, calculate_water_demand
from app.intake.studio_intake import answer_field, accepted_values, validate_value
from app.intake.studio_section import section_model
from app.pz.section_main_hydraulics import assess_section_main
from app.pz.wastewater_diagnostics import resolve_k1_main_flows, assess_wastewater_diagnostics
from app.pz.generator import generate_wastewater_calculation_html, generate_wastewater_pz_html
from tests.test_section_main_hydraulics import draft, project, main_input
from tests.test_wastewater_diagnostics import _project

# Independently transcribed integer hundredths from supplied official PDF,
# printed p.17, visually verified. Do not generate this oracle from production.
GOLDEN = """
4 61 51 46 43 40 36 34 31 27 25 23 15 13
8 63 53 48 45 41 37 35 32 28 26 24 16 13
12 64 54 49 46 42 39 36 33 29 26 24 16 14
16 65 55 50 47 43 39 37 33 30 27 25 17 14
20 66 56 51 48 44 40 38 34 30 28 25 17 14
24 67 57 52 48 45 41 38 35 31 28 26 17 15
28 68 58 53 49 46 42 39 36 31 29 27 18 15
32 68 59 53 50 47 43 40 36 32 30 27 18 15
36 69 59 54 51 47 43 40 37 33 30 28 19 16
40 70 60 55 52 48 44 41 37 33 31 28 19 16
100 77 69 64 60 56 52 49 45 40 37 34 23 20
500 95 92 89 88 86 83 81 77 73 70 66 50 44
1000 99 98 97 97 96 95 94 93 91 90 88 77 71
"""
CELLS = [(int(row.split()[0]), length, int(ks)/100)
         for row in GOLDEN.strip().splitlines()
         for length, ks in zip((1,3,5,7,10,15,20,30,40,50,100,500,1000), row.split()[1:], strict=True)]


@pytest.mark.parametrize("n,length,ks", CELLS)
def test_every_published_cell_and_formula(n, length, ks):
    result = calculate_horizontal_sewage(7.2, n, length, 1.6)
    assert result.ks == ks
    assert result.q_sewage_lps == pytest.approx(2 + ks*1.6)
    assert result.ks_selection.method == "table"
    assert len(result.ks_selection.cells) == 1


def test_control_twenty_residents_does_not_change_canonical_water_or_riser_formula():
    water = calculate_water_demand([ConsumerGroup("residential_full_bath", 20)])
    assert water.total.q_hr == 1.268 and water.sewage_flow == 2.293
    result = calculate_horizontal_sewage(water.total.q_hr, 32, 10, 1.6)
    assert result.ks == .47
    assert result.q_sewage_lps == pytest.approx(1.1042222222222222)
    assert result.q_sewage_lps != water.total.q_day/24/3.6 + .47*1.6
    assert result.q_sewage_lps != water.total.q_hr/3.6 + 1.6


@pytest.mark.parametrize("n,length", [(1,10),(3,10),(1001,10),(32,.5),(32,1001),
    (32,math.nextafter(1,0)),(32,math.nextafter(1000,math.inf))])
def test_no_extrapolation_or_rounding_back_into_table(n, length):
    with pytest.raises(ValueError, match="таблицы 5.1"):
        calculate_horizontal_sewage(1.268, n, length, 1.6)


@pytest.mark.parametrize("n,length,ks,method", [
    (5,10,.4025,"linear_n"), (33,7,.5025,"linear_n"),
    (32,9,.48,"linear_l"), (33,8.5,.48625,"bilinear"),
    (572,10,.8744,"linear_n"), (572,12.5,.86084,"bilinear"),
    (4,2,.56,"linear_l"), (1000,2,.985,"linear_l"),
    (6,1,.62,"linear_n"), (6,1000,.13,"linear_n"),
])
def test_approved_interpolation_preserves_input_and_unrounded_flow(n, length, ks, method):
    r = calculate_horizontal_sewage(7.71, n, length, 1.6)
    assert r.ks == pytest.approx(ks, abs=1e-14)
    assert r.ks_selection.method == method
    assert r.fixtures_count == n and r.receiving_length_m == length
    assert r.q_sewage_lps == pytest.approx(7.71/3.6 + ks*1.6, abs=1e-14)
    assert "линейной интерполяцией" in r.note
    assert "не отдельное предписание СП" in r.note
    assert len(r.ks_selection.cells) == (4 if method == "bilinear" else 2)


def test_every_table_rectangle_against_independent_rational_weights():
    golden = {(n, length): Fraction(str(ks)) for n, length, ks in CELLS}
    ns = sorted({n for n, _, _ in CELLS})
    lengths = sorted({length for _, length, _ in CELLS})
    for n0, n1 in zip(ns, ns[1:]):
        for l0, l1 in zip(lengths, lengths[1:]):
            corners = [golden[n, l] for n in (n0,n1) for l in (l0,l1)]
            # Unequal intervals 40..100..500..1000 must use actual coordinates.
            for n in (n0+1, (n0+n1)//2, n1-1):
                for u in (Fraction(1,4), Fraction(1,2), Fraction(3,4)):
                    length = Fraction(l0) + u*(l1-l0)
                    t = Fraction(n-n0, n1-n0)
                    expected = ((1-t)*(1-u)*corners[0] + (1-t)*u*corners[1]
                                + t*(1-u)*corners[2] + t*u*corners[3])
                    r = select_ks(n, float(length))
                    assert r.value == pytest.approx(float(expected), abs=1e-14)
                    assert float(min(corners))-1e-14 <= r.value <= float(max(corners))+1e-14
                    assert r.n_bounds == (n0,n1) and r.length_bounds_m == (l0,l1)
                    assert [(c.fixtures_count,c.receiving_length_m) for c in r.cells] == [
                        (n0,l0),(n0,l1),(n1,l0),(n1,l1)]
                    assert [Fraction(str(c.ks)) for c in r.cells] == corners


def test_interpolation_is_continuous_at_table_lengths_and_monotone_on_both_axes():
    ns = sorted({n for n, _, _ in CELLS})
    lengths = sorted({length for _, length, _ in CELLS})
    for n in (4,33,100,572,1000):
        for length in lengths[1:-1]:
            exact = select_ks(n,length).value
            for near in (math.nextafter(length,0), math.nextafter(length,math.inf)):
                assert select_ks(n,near).value == pytest.approx(exact, abs=1e-14)
        for a,b in zip(lengths,lengths[1:]):
            assert select_ks(n,a).value >= select_ks(n,(a+b)/2).value >= select_ks(n,b).value
    for length in (1,8.5,10,37,1000):
        for a,b in zip(ns,ns[1:]):
            assert select_ks(a,length).value <= select_ks((a+b)//2,length).value <= select_ks(b,length).value
    # Both inputs rounded upwards are NOT necessarily conservative.
    assert select_ks(5,9).value > select_ks(8,10).value


@pytest.mark.parametrize("index,value", [(0,0),(0,-1),(0,math.inf),(0,math.nan),(0,True),
    (1,32.0),(1,True),(1,0),(2,0),(2,True),(2,math.inf),(3,math.nan),(3,-1),(3,True)])
def test_invalid_inputs(index, value):
    args = [1.268,32,10,1.6]
    args[index] = value
    with pytest.raises(ValueError):
        calculate_horizontal_sewage(*args)


def automatic_draft():
    d = draft()
    for key, value in dict(flow_basis="whole_building", design_flow_lps=None,
                           fixtures_count=32, receiving_length_m=10).items():
        answer_field(d, "section_k1_"+key, value)
    return d


def test_studio_yaml_pz_and_calculation_are_consistent_not_saved_sewage_flow():
    d = automatic_draft()
    p = project(d)
    expected = section_model(accepted_values(d)).main_checks[0].flow_result
    p.flows.sewage_l_per_s = 999
    html = generate_wastewater_calculation_html(p)
    assert 'data-horizontal-flow="sp30-5.7"' in html
    assert "1,104" in html and "0,47" in html and "1,268" in html
    assert "1.104" in generate_wastewater_pz_html(p)  # full derivation in check.note
    assert expected.q_sewage_lps == pytest.approx(1.1042222222222222)


def test_interpolated_studio_roundtrip_pz_calculation_scheme_and_invalidation():
    from app.pz.wastewater_graphic_exports import representative_section_model
    d = automatic_draft()
    answer_field(d, "section_k1_fixtures_count", 33)
    answer_field(d, "section_k1_receiving_length_m", 8.5)
    p = project(d)  # Includes the ordinary DTO/YAML round trip, no hidden inputs.
    direct = section_model(accepted_values(d)).main_checks[0]
    graphic = representative_section_model(p).main_checks[0]
    assert direct == graphic
    assert direct.flow_result.ks == pytest.approx(.48625)
    assert direct.flow_result.q_sewage_lps == pytest.approx(1.1302222222222222)
    calc = generate_wastewater_calculation_html(p)
    assert "0,48625" in calc and "1,130" in calc and "8,5" in calc
    for html in (calc, generate_wastewater_pz_html(p)):
        assert "линейной интерполяцией по N и L" in html
        assert "N=32, L=7 м: Ks=0.5" in html
        assert "N=36, L=10 м: Ks=0.47" in html
        assert "не отдельное предписание СП" in html
    answer_field(d, "section_k1_receiving_length_m", 1001)
    invalid = section_model(accepted_values(d)).main_checks[0]
    assert invalid.result is None and invalid.flow_result is None
    assert "экстраполяция" in invalid.note


def test_old_whole_building_cannot_reuse_riser_result_without_n_l():
    data = main_input(flow_basis="whole_building", design_flow_lps=None)
    check = assess_section_main("К1", data, total_flow_lps=999,
                                 q_hour_max_m3h=1.268, fixture_max_lps=1.6)
    assert check.status == "pending" and check.result is None
    assert "число" in check.note and "L" in check.note


def test_section_consumers_not_entire_building_and_other_systems_unchanged():
    data = main_input(flow_basis="section_hourly", design_flow_lps=None,
        q_hour_max_m3h=.72, fixtures_count=8, receiving_length_m=3, fixture_max_lps=.8)
    check = assess_section_main("К1", data, q_hour_max_m3h=999, fixture_max_lps=9)
    assert check.flow_result.q_sewage_lps == pytest.approx(.2 + .53*.8)
    assert assess_section_main("К2", data).result is None


def test_manual_flow_needs_source_and_cannot_shadow_formula_input():
    assert resolve_horizontal_flow(design_flow_lps=2)[0] is None
    assert resolve_horizontal_flow(design_flow_lps=2, flow_source="Расчёт участка")[0] == 2
    assert resolve_horizontal_flow(design_flow_lps=2, flow_source="Расчёт", fixtures_count=32)[0] is None


def test_network_no_summing_risers_no_geometric_length_substitute_and_yaml_roundtrip():
    from app.intake.yaml_io import load_request_file, load_request, dump_request
    from app.intake.project_builder import build_project
    from tests.test_wastewater_diagnostics import DEMO
    req = load_request_file(str(DEMO))
    pipe = next(p for p in req.sewer_pipes if p.section_id == "К1-М1")
    pipe.design_flow_lps = None
    pipe.q_hour_max_m3h = 1.268
    pipe.fixtures_count = 32
    pipe.fixture_max_lps = 1.6
    p = build_project(load_request(dump_request(req)))
    assert "К1-М1" not in resolve_k1_main_flows(p)[0]  # Existing calculation_length=52 is NOT L.
    pipe.receiving_length_m = 10
    p = build_project(load_request(dump_request(req)))
    original = deepcopy(p)
    flows, warnings = resolve_k1_main_flows(p)
    assert flows["К1-М1"] == pytest.approx(1.1042222222222222)
    assert "К1-Вып1" not in flows  # No propagation of maximums downstream.
    assert p == original
    assessment = assess_wastewater_diagnostics(p)
    assert any(h.section_id == "К1-М1" and h.design_flow_lps == round(flows["К1-М1"], 3) for h in assessment.hydraulics)
    assert not assessment.ready and "К1-Вып1" in assessment.pending_horizontal_flows

    pipe.fixtures_count = 33
    pipe.receiving_length_m = 8.5
    p = build_project(load_request(dump_request(req)))
    flows, notes = resolve_k1_main_flows(p)
    assert flows["К1-М1"] == pytest.approx(1.1302222222222222)
    assert "линейной интерполяцией по N и L" in assess_wastewater_diagnostics(p).horizontal_flow_notes["К1-М1"]


def test_bad_n_rejected_at_ui_not_coerced_from_inhabitants():
    with pytest.raises(ValueError):
        validate_value("section_k1_fixtures_count", 32.5)


def test_old_cached_network_hydraulics_cannot_reappear_in_pdf():
    p = _project()
    pipe = next(p for p in p.sewage.pipes if p.section_id == "К1-М1")
    pipe.design_flow_lps = 2.758
    pipe.flow_source = "Синтетический расчёт"
    p.sewage.hydraulic_assessment = assess_wastewater_diagnostics(p)
    assert p.sewage.hydraulic_assessment.hydraulics
    pipe.flow_source = ""
    generate_wastewater_calculation_html(p)
    assert not p.sewage.hydraulic_assessment.hydraulics


def test_declared_filling_does_not_confirm_missing_horizontal_flow():
    from app.pz.wastewater_gost import audit_wastewater_gost
    p = _project()
    for pipe in p.sewage.pipes:
        pipe.fill_ratio = .5
    audit = audit_wastewater_gost(p)
    row = next(row for row in audit.checks if row.code == "K-GOST-08F")
    assert row.status == "missing"


def test_educational_study_uses_separate_explicit_receiving_length():
    from tests.test_small_residential_section import model
    from app.pz.small_residential_calculation import calculate_residential_study
    r = calculate_residential_study(model.__wrapped__(), k1_receiving_length_m=10)
    assert r.k1_flow.fixtures_count == 32 and r.k1_flow.receiving_length_m == 10
    assert r.k1.design_flow_lps == 1.104
    assert r.k1.design_flow_lps != r.water.sewage_flow


def test_declared_pump_discharge_does_not_receive_gravity_formula():
    from tests.test_wastewater_pressure_scheme import _pressure_project
    from app.pz.wastewater_gost import audit_wastewater_gost
    p = _pressure_project()
    flows, warnings = resolve_k1_main_flows(p)
    assert "К1-Н1" not in flows
    assert not any("К1-Н1" in text for text in warnings)
    assessment = assess_wastewater_diagnostics(p)
    assert "К1-Н1" not in assessment.pending_horizontal_flows
    assert not any(row.section_id == "К1-Н1" for row in assessment.hydraulics)
    audit = audit_wastewater_gost(p)
    check = next(row for row in audit.checks if row.code == "K-GOST-08F")
    assert "К1-Н1" not in check.evidence
    # Material strength by itself cannot bypass a gravity-flow check.
    p.sewage.pump_required = False
    p.sewage.pump_system = ""
    assert "К1-Н1" in assess_wastewater_diagnostics(p).pending_horizontal_flows

"""Product evidence flows through outputs; legacy hydraulics remain untouched."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.data.metering_products import get_metering_catalogue
from app.pz.meter_products import (
    bind_meter_products, evaluate_meter_product, primary_meter, product_hydraulic_evidence,
)
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.generator import generate_v1_calculation_html
from app.pz.spec import build_water_specification
from app.pz.commission import build_commission_report
from scripts.preview_metering_detail import review_project


def proposal():
    p = review_project(2)
    d = p.metering_detail
    d.catalogue_revision = get_metering_catalogue().revision
    d.meter_selection_mode = "catalogue_proposal"
    d.meter_mounting = "horizontal_dial_up"
    return p


def test_passport_minimum_is_not_legacy_minimum_and_hydraulics_unchanged():
    p = proposal()
    before = [(r.dn, r.s_resist, r.h_a, r.h_b, r.qexpl, r.q_meter_min, r.need_bypass) for r in p.meters.rows]
    bind_meter_products(p)
    assert before == [(r.dn, r.s_resist, r.h_a, r.h_b, r.qexpl, r.q_meter_min, r.need_bypass) for r in p.meters.rows]
    cold = primary_meter(p)
    assert cold.q_meter_min == .1 and cold.q_min_passport_m3h == .12
    assert cold.ok_v is None and cold.q_min_hourly_m3h is None
    assert cold.product['id'] == 'decast-vskm90-dg-dn32'
    assert cold.product['body_length_mm'] == 260
    assert 'минимальный расчётный часовой расход' in cold.minimum_flow_note
    assert 'паспортный расход' not in cold.minimum_flow_note


@pytest.mark.parametrize('dn,qmax', [(15,3),(20,5),(25,7),(32,12),(40,20),(50,30)])
def test_passport_loss_bound_is_not_a_point_curve_or_resistance(dn,qmax):
    product = get_metering_catalogue().products[f'decast-vskm90-dg-dn{dn}']
    evidence = product_hydraulic_evidence(product)
    assert evidence['status'] == 'upper_bound_only'
    assert evidence['max_pressure_loss_mpa'] == .1 and evidence['at_flow_m3h'] == qmax
    assert evidence['exact_loss_m'] is None and evidence['resistance_s'] is None
    assert evidence['source_id'] in product.source_ids
    assert evidence['revision'] == '2026-10-05.1'
    assert evidence['reference'].endswith('не более')
    assert 'не характеристика h(Q)' in evidence['note']


def test_loss_evidence_cannot_be_inherited_by_other_or_invalid_product():
    c = get_metering_catalogue()
    assert product_hydraulic_evidence(c.products['valtec-vt214-dn32']) is None
    assert product_hydraulic_evidence(c.products['decast-vskm90-dn32']) is None
    assert product_hydraulic_evidence(None) is None
    p = proposal()
    bind_meter_products(p)
    assert primary_meter(p).product['hydraulic_evidence']
    p.metering_detail.meter_products['cold'] = 'decast-vskm90-dg-dn50'
    assert evaluate_meter_product(p,primary_meter(p)).summary()['hydraulic_evidence'] is None


def test_loss_basis_and_passport_bound_remain_separate_in_outputs():
    p = proposal()
    bind_meter_products(p)
    r = primary_meter(p)
    assert r.s_resist == 1.3  # Table 12.1, not fitted from .1 MPa at 12 m3/h.
    assert '12.15' in r.product['hydraulic_basis']
    html = generate_v1_calculation_html(p)
    assert 'Паспорт: Δp ≤ 0,1 МПа при Qmax = 12 м³/ч' in html
    assert 'это не паспортная характеристика' in html
    svg = ''.join(build_metering_detail_pages(p))
    assert 'Расчёт по СП 30, п. 12.15' in svg
    assert 'Паспорт: Δp ≤ 0,1 МПа при Qmax = 12 м³/ч' in svg
    assert any('сопротивление модели' in s for s in r.product['pending'])


def test_product_is_the_same_in_calculation_drawing_spec_and_minimum_check():
    p = proposal()
    p.source.meter_minimum_checks = {'cold': {'dn_mm':32, 'q_min_hourly_m3h':.2,
        'flow_reference':'Synthetic test input, not a project assumption'}}
    bind_meter_products(p)
    row = primary_meter(p)
    assert row.ok_v is True
    state = drawing_state(p)
    selection = resolve_metering_products(p, state.meter, bypass=state.bypass, electric_bypass=state.electric_bypass)
    assert selection.selected('meter').id == row.product['id']
    html = generate_v1_calculation_html(p)
    assert row.product['name'] in html and 'Паспорт изготовителя' in html
    pages = build_metering_detail_pages(p)
    assert row.product['name'] in pages[0]
    assert any('Подбор моделей узлов' in page for page in pages)
    spec = build_water_specification(p)
    selected = [r for s in spec.sections for r in s.rows if r.catalogue_id == row.product['id']]
    assert len(selected) == 1 and selected[0].qty == 2


@pytest.mark.parametrize('change, error', [
    (lambda p: setattr(p.metering_detail,'catalogue_revision','stale'), 'Редакция'),
    (lambda p: p.metering_detail.meter_products.update(cold='no-such-meter'), 'Неизвестная'),
    (lambda p: p.metering_detail.meter_products.update(cold='decast-vskm90-dg-dn50'), 'Тип/DN'),
    (lambda p: p.metering_detail.meter_products.update(cold='decast-vskm90-dn32'), 'дистанционную'),
    (lambda p: setattr(p.flows,'q_sec_c',4), 'Qmax'),
    (lambda p: setattr(p.metering_detail,'design_pressure_bar',17), 'PN'),
    (lambda p: setattr(p.metering_detail,'water_temperature_c',130), 'Температура'),
    (lambda p: p.metering_detail.enhancements.update(technology='ultrasonic'), 'технологии'),
])
def test_stale_incompatible_or_different_technology_never_replaced(change,error):
    p = proposal()
    bind_meter_products(p)
    change(p)
    check = evaluate_meter_product(p, primary_meter(p))
    assert check.product is None and check.minimum_ok is None
    assert any(error in e for e in check.errors)
    # Re-export must not accept the old green-looking row snapshot.
    html = generate_v1_calculation_html(p)
    assert error in html
    gate = next(c for c in build_commission_report(p).checks if c.code == 'CALC-03')
    assert gate.blocking
    spec = build_water_specification(p)
    assert not any(r.catalogue_id == 'decast-vskm90-dg-dn32' for s in spec.sections for r in s.rows)


@pytest.mark.parametrize('mounting', ['unknown','vertical'])
def test_class_b_not_applied_to_unknown_or_vertical_mounting(mounting):
    p = proposal()
    p.metering_detail.meter_mounting = mounting
    p.source.meter_minimum_checks = {'cold':dict(dn_mm=32, q_min_hourly_m3h=.2, flow_reference='test')}
    bind_meter_products(p)
    row = primary_meter(p)
    assert row.q_min_passport_m3h is None and row.ok_v is None
    assert any('ориентации' in s for s in row.product['pending'])


def test_conflicting_manual_evidence_cannot_silently_be_overwritten():
    p = proposal()
    p.source.meter_minimum_checks = {'cold':dict(dn_mm=32, q_min_hourly_m3h=.2,
        q_min_passport_m3h=.01, passport_reference='Other meter', flow_reference='test')}
    original = deepcopy(p.source.meter_minimum_checks)
    bind_meter_products(p)
    assert p.source.meter_minimum_checks == original
    row = primary_meter(p)
    assert row.ok_v is None and row.product['id'] == ''
    assert 'Ручной паспортный минимум' in row.minimum_flow_note


def test_minimum_failure_keeps_existing_combined_meter_recommendation():
    p = proposal()
    p.source.meter_minimum_checks = {'cold':dict(dn_mm=32, q_min_hourly_m3h=.01, flow_reference='test')}
    bind_meter_products(p)
    assert primary_meter(p).ok_v is False and primary_meter(p).need_combo


def test_removing_binding_does_not_reuse_derived_passport_evidence():
    p = proposal()
    p.source.meter_minimum_checks = {'cold':dict(dn_mm=32, q_min_hourly_m3h=.2, flow_reference='test')}
    bind_meter_products(p)
    assert primary_meter(p).ok_v is True
    p.metering_detail.meter_selection_mode = 'manual'
    check = evaluate_meter_product(p,primary_meter(p))
    assert check.minimum_ok is None and check.errors and check.product is None


def test_no_catalogue_model_does_not_shrink_demand_or_select_another_dn():
    p = proposal()
    row = primary_meter(p)
    row.dn = 300  # DN65–250 now have sourced flanged models; never clamp beyond them.
    before = asdict(row)
    check = evaluate_meter_product(p,row)
    assert check.product is None and check.errors
    assert asdict(row) == before


def test_pure_evaluation_and_input_copy():
    from app.intake.studio_intake import build_handoff_request
    from app.intake.yaml_io import dump_request, load_request
    from app.intake.project_builder import build_project
    from tests.test_studio_apartment_meters import draft
    p = proposal()
    before = asdict(p)
    evaluate_meter_product(p,primary_meter(p))
    assert asdict(p) == before
    req = build_handoff_request(draft())
    req.metering_detail.meter_products['cold'] = 'decast-vskm90-dg-dn32'
    restored = load_request(dump_request(req))
    assert restored == req
    build_project(restored).metering_detail.meter_products.clear()
    assert restored.metering_detail.meter_products


@pytest.mark.parametrize("per_inlet, mode, inlet_quantity", [
    (None, "common", 1),
    ("no", "common", 1),
    ("yes", "per_inlet", 2),
], ids=["studio-default-common", "explicit-common", "explicit-per-inlet"])
def test_local_heater_three_nodes_counts_and_control_values(tmp_path, per_inlet, mode, inlet_quantity):
    from scripts.build_samara_section_study import load_basis,make_draft
    from app.intake.studio_intake import answer_field, build_handoff_request
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    draft = make_draft(load_basis())
    # This is a disposable study input, not the signed Samara snapshot.
    # Two supply inlets do not imply two meters: exercise both explicit choices
    # and retain coverage of the agreed current Studio default.
    if per_inlet is not None:
        answer_field(draft, "vu_per_inlet", per_inlet)
    req = build_handoff_request(draft)
    assert req.metering_detail.inlet_metering_mode == mode
    p = design_ios2(build_project(req),output_dir=str(tmp_path),render_documents=False).project
    assert [(r.dn,r.h_a) for r in p.meters.rows] == [(50,1.451),(32,3.479),(32,4.703)]
    assert [r.q_min_passport_m3h for r in p.meters.rows] == [.45,.12,.12]
    spec = build_water_specification(p)
    rows = [r for s in spec.sections for r in s.rows if r.catalogue_id.startswith('decast-vskm90-dg-dn')
            and not any(key.startswith('apartment-') for key in r.component_ids)]
    assert [(r.catalogue_id,r.qty) for r in rows] == [
        ('decast-vskm90-dg-dn50',inlet_quantity), ('decast-vskm90-dg-dn32',1), ('decast-vskm90-dg-dn32',1)]
    apartment = [r for s in spec.sections for r in s.rows if r.catalogue_id.startswith('decast-vskm90-dg-dn')
                 and any(key.startswith('apartment-') for key in r.component_ids)]
    assert [(r.catalogue_id,r.qty) for r in apartment] == [('decast-vskm90-dg-dn15',None)] * 2
    assert not any('ВСГд-' in r.type_mark or 'ВСХНд-' in r.type_mark for s in spec.sections for r in s.rows)

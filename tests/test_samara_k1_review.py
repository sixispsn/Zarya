"""Samara K1 uses ordinary inputs; the signed water/fire case is unchanged."""
from copy import deepcopy
from dataclasses import replace
import json
from xml.etree import ElementTree as ET

import pytest

from app.intake import samara_study
from app.intake.studio_intake import accepted_values, build_handoff_request
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request
from app.pz.generator import generate_wastewater_calculation_html, generate_wastewater_pz_html
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg
from app.pz.section_main_hydraulics import assess_section_main
from app.pz.wastewater_graphic_exports import representative_document_model


@pytest.fixture
def draft():
    d = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(d, None)
    assert d['project_calculation']['can_preview']
    return d


def test_inventory_geometry_and_formula_are_explicit_and_current(draft, tmp_path):
    b, fingerprint = samara_study.build(draft, tmp_path)
    m = representative_document_model(b.project)
    c = m.main_checks[0]
    assert m.k1.fixtures_count == 143 + 143 + 175 + 175 == 636
    assert m.k1.receiving_length_m == 10
    assert (m.k1.outer_diameter_mm, m.k1.wall_thickness_mm, m.k1.dn_mm) == (110, 2.7, 100)
    assert m.k1.inner_diameter_mm == pytest.approx(104.6)
    assert c.flow_result.q_hour_max_m3h == 7.71
    assert c.flow_result.ks == pytest.approx(.86 + (.96-.86)*(636-500)/500)
    assert c.flow_result.q_sewage_lps == pytest.approx(7.71/3.6 + .8872*1.6)
    assert c.status == 'verified'
    assert (c.result.design_flow_lps, c.result.velocity_mps, c.result.fill_ratio) == (3.561, .808, .5102)
    assert c.result.self_cleaning_value == .577 and c.result.self_cleaning_ok
    assert 'Учебные N=636' in c.note and 'не паспортное' in m.k1.roughness_source
    assert fingerprint != samara_study.load_case()['payload_sha256']
    assert fingerprint == draft['study']['snapshot']
    assert not draft['project_calculation']['can_release']
    assert b.project.flows.sewage_l_per_s == 4.785
    assert b.project.flows.q_hr_tot == 7.71
    assert b.project.storm.result.q_total_l_per_s == 11.518
    assert (b.project.pumps.q_design_m3h, b.project.pumps.h_design_m) == pytest.approx((11.466, 50.25), abs=1e-10)
    req, _, station_result, _ = samara_study.inputs(draft)
    original = samara_study.load_case()['payload']
    assert station_result == original['result']
    baseline = load_request(original['request_yaml'])
    assert replace(req, wastewater_presentation=baseline.wastewater_presentation,
                   apartment_water_units=baseline.apartment_water_units,
                   metering_detail=baseline.metering_detail) == baseline
    assert req.wastewater_presentation.k2 == baseline.wastewater_presentation.k2
    assert req.wastewater_presentation.fan == baseline.wastewater_presentation.fan


def test_same_result_through_ordinary_studio_yaml_and_documents(draft, tmp_path):
    from app.intake.project_builder import build_project
    values = accepted_values(draft)
    direct = section_model(values)
    ordinary = deepcopy(draft)
    ordinary.pop('study')
    req = load_request(dump_request(build_handoff_request(ordinary)))
    model = representative_document_model(build_project(req))
    b, _ = samara_study.build(draft, tmp_path)
    bound = representative_document_model(b.project)
    assert direct.k1 == model.k1 == bound.k1
    assert direct.main_checks[0] == model.main_checks[0] == bound.main_checks[0]
    for html in (generate_wastewater_pz_html(b.project), generate_wastewater_calculation_html(b.project)):
        assert all(t in html for t in ('3,561', '104,60', '0,808', '0,51', 'Учебные N=636', 'не паспортное'))
        assert 'опорные ячейки' in html and '0.8872' in html
    svg = build_concept_section_svg(bound)
    assert not audit_concept_section_svg(bound, svg)
    node = next(n for n in ET.fromstring(svg).iter() if n.get('data-main-hydraulics') == 'К1')
    assert node.get('data-q-lps') == '3.561' and node.get('data-status') == 'verified'
    assert 'Q=3,561' in svg and 'h/d=0,510' in svg


def test_previous_dn150_is_not_silently_marked_as_verified(draft):
    model = section_model(accepted_values(draft))
    previous = replace(model.k1, dn_mm=150, outer_diameter_mm=160, wall_thickness_mm=3.9)
    c = assess_section_main('К1', previous, q_hour_max_m3h=7.71, fixture_max_lps=1.6)
    assert c.status == 'review' and c.result.velocity_ok
    assert not c.result.minimum_fill_ok and not c.result.self_cleaning_ok
    assert c.result.fill_ratio == .2956


def test_single_checked_segment_is_not_a_quantity_or_a_whole_network_certificate(draft, tmp_path):
    from app.pz.spec import build_wastewater_specification
    from app.pz.wastewater_gost import audit_wastewater_gost
    b, _ = samara_study.build(draft, tmp_path)
    rows = [r for s in build_wastewater_specification(b.project).sections for r in s.rows]
    main = next(r for r in rows if r.name == 'Магистраль и выпуск системы К1')
    assert main.qty is None and main.unit == 'м'
    assert '110×2,7' in main.type_mark and 'полипропилен' in main.note
    assert not b.project.sewage.pipes
    check = next(c for c in audit_wastewater_gost(b.project).checks if c.code == 'K-GOST-08F')
    assert check.status == 'missing' and '3.561' in check.evidence
    assert 'остальных' in check.evidence


@pytest.mark.parametrize('change', ['answers', 'inventory', 'old_snapshot'])
def test_changed_or_old_snapshot_requires_reopening(draft, change):
    if change == 'answers':
        draft['answers']['section_k1_receiving_length_m']['value'] = 15
    elif change == 'inventory':
        draft['study']['k1_assumptions']['fixture_inventory'][0]['count'] += 1
    else:
        draft['study']['snapshot'] = samara_study.load_case()['payload_sha256']
    assert not samara_study.calculate(draft)['can_preview']


def test_new_template_revision_invalidates_old_draft(draft, monkeypatch, tmp_path):
    review = json.loads(samara_study.K1_REVIEW.read_text())
    review['main']['receiving_length_m'] = 12
    path = tmp_path/'k1.json'
    path.write_text(json.dumps(review))
    monkeypatch.setattr(samara_study, 'K1_REVIEW', path)
    assert not samara_study.calculate(draft)['can_preview']
    updated = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(updated, None)
    assert updated['project_calculation']['can_preview']
    assert updated['study']['snapshot'] != draft['study']['snapshot']


def test_ordinary_object_does_not_inherit_study_inputs():
    from tests.test_section_main_hydraulics import draft as ordinary_draft
    d = ordinary_draft()
    values = accepted_values(d)
    assert values.get('section_k1_fixtures_count') != 636
    assert not any('Самар' in str(v) for v in values.values())

"""Recompute current inputs; a drawn DN is never proof of whole-network sizing."""
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from app.calc.storm import StormInput, calculate_storm
from app.intake.project_builder import build_project
from app.intake.studio_intake import accepted_values, answer_field, build_handoff_request, validate_value
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request
from app.pz.generator import generate_wastewater_pz_html
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg
from app.pz.section_storm import SectionStormInput
from app.pz.spec import build_wastewater_specification
from app.pz.wastewater_graphic_exports import representative_section_model, wastewater_graphic_export
from tests.test_section_fan_integration import fan_draft


def bound_draft():
    d = fan_draft()
    for k, v in dict(storm_city="moscow", storm_roof_area_m2=420, storm_walls_area_m2=0,
            storm_selected_riser_dn_mm=100, storm_risers_count=4, storm_max_riser_flow_lps=3,
            storm_funnels_on_different_levels="no", section_fan_working_diameter_mm=100,
            section_fan_opening_distance_m=5, section_fan_attic_insulated="yes",
            section_fan_plastic_exposed="yes", section_fan_uv_protected="yes").items():
        answer_field(d, k, v)
    return d


def project(d=None):
    return build_project(load_request(dump_request(build_handoff_request(d or bound_draft()))))


def test_one_state_in_studio_yaml_project_pdf_model_pz_and_spec():
    d = bound_draft()
    p = project(d)
    m = representative_section_model(p)
    assert m == section_model(accepted_values(d))
    assert m.storm.result == calculate_storm(StormInput("moscow", 420, 0))
    assert m.storm.riser_status == "verified"
    assert m.fan_plan.diameter_mm == 100
    assert all(c.status == "verified" for c in m.fan_plan.checks)
    svg = build_concept_section_svg(m)
    assert 'data-storm-riser-dn="100"' in svg and 'data-inline-pipe-label="К2 ⌀100"' in svg
    assert 'data-fan-collector-dn="100"' in svg
    assert audit_concept_section_svg(m, svg) == ()
    html = generate_wastewater_pz_html(p)
    assert m.fan_plan.diameter_notice in html and m.storm.notice in html
    rows = [r for s in build_wastewater_specification(p).sections for r in s.rows
            if r.name == "Сборный вентиляционный трубопровод К1"]
    assert len(rows) == 1 and rows[0].type_mark == "DN100" and rows[0].qty is None
    assert not p.sewage.pipes and not p.sewage.risers
    assert not wastewater_graphic_export(p, "k1-k2").ready


@pytest.mark.parametrize("dn,capacity", [(85,10), (100,20), (150,50), (200,80)])
def test_riser_table_is_reused_without_new_interpolation(dn, capacity):
    s = SectionStormInput("moscow", 420, selected_riser_dn_mm=dn, risers_count=4, max_riser_flow_lps=3)
    assert s.assessment.effective_riser_capacity_lps == capacity
    assert s.riser_status == "verified"
    p = project()
    p.storm.selected_riser_dn_mm = dn
    m = representative_section_model(p)
    assert audit_concept_section_svg(m, build_concept_section_svg(m)) == ()
    assert next(x for x in m.storm_lower_node().segments if x.role == "riser").dn_mm == dn


@pytest.mark.parametrize("change,status", [
    ({"max_riser_flow_lps":None}, "pending"), ({"risers_count":0}, "verified"),
    ({"selected_riser_dn_mm":110}, "pending"), ({"city_code":""}, "pending"),
    ({"max_riser_flow_lps":30}, "fail"), ({"roof_area_m2":10}, "fail"),
])
def test_missing_or_conflicting_load_never_becomes_a_confirmed_dn(change, status):
    s = SectionStormInput("moscow", 420, selected_riser_dn_mm=100, risers_count=4, max_riser_flow_lps=3)
    assert replace(s, **change).riser_status == status


def test_old_cached_assessment_does_not_survive_changes_to_current_input():
    p = project()
    p.storm.network_assessment = representative_section_model(p).storm.assessment
    p.storm.max_riser_flow_lps = 30
    m = representative_section_model(p)
    assert p.storm.network_assessment.riser_capacity_ok is True
    assert m.storm.riser_status == "fail"
    assert "НЕ СООТВЕТСТВУЕТ" in generate_wastewater_pz_html(p)
    assert 'data-storm-riser-status="fail"' in build_concept_section_svg(m)
    p.storm.max_riser_flow_lps = None
    assert representative_section_model(p).storm.riser_status == "pending"


def test_different_roof_levels_use_existing_coefficient():
    s = representative_section_model(project()).storm
    assert replace(s, funnels_on_different_levels=True).assessment.effective_riser_capacity_lps == 14


def test_changed_k1_dn_updates_vent_floor_and_lower_fittings_not_fixture_branch():
    d = bound_draft()
    answer_field(d, "section_fan_working_diameter_mm", 150)
    m = representative_section_model(project(d))
    assert m.fan_plan.diameter_mm == 150
    for a in [m.apartment(1, "К1-А")]:
        assert not a.validate()
        assert {s.dn_mm for s in a.segments if s.role == "riser"} == {150}
        assert next(f for f in a.fittings if f.fitting_id == "riser_branch_elbow_45").dn_mm == 100
    for lower in m.lower_nodes():
        assert not lower.validate()
        assert next(s for s in lower.segments if s.role == "riser").dn_mm == 150
    assert 'data-inline-pipe-label="К1 ⌀150"' in build_concept_section_svg(m)
    assert "вытяжка и сборный вентиляционный трубопровод DN150" in m.fan_plan.diameter_notice


@pytest.mark.parametrize("field,value,code", [
    ("section_fan_opening_distance_m", 3, "FAN-OPENINGS"),
    ("section_fan_no_openings_confirmed", "yes", "FAN-OPENINGS"),
    ("section_fan_attic_insulated", "no", "FAN-INSULATION"),
    ("section_fan_uv_protected", "no", "FAN-UV"),
])
def test_explicit_negative_evidence_prevents_a_valid_looking_vent(field, value, code):
    d = bound_draft()
    answer_field(d, field, value)
    m = section_model(accepted_values(d))
    assert m.fan_plan.kind == "pending"
    assert any(c.code == code and c.status == "fail" for c in m.fan_plan.checks)
    assert 'data-common-fan="true"' not in build_concept_section_svg(m)


def test_missing_proof_is_not_false_or_an_invented_confirmation():
    d = fan_draft()
    m = section_model(accepted_values(d))
    assert m.fan_plan.diameter_mm is None
    checks = {c.code:c.status for c in m.fan_plan.checks}
    for code in ("FAN-DN", "FAN-COLLECTOR-DN", "FAN-OPENINGS", "FAN-INSULATION", "FAN-UV"):
        assert checks[code] == "pending"


@pytest.mark.parametrize("field,value", [("section_fan_working_diameter_mm", 99),
    ("section_fan_working_diameter_mm", 100.5), ("section_fan_working_diameter_mm", True),
    ("section_fan_opening_distance_m", -1), ("storm_risers_count", 2.5),
    ("storm_max_riser_flow_lps", 0), ("section_fan_attic_insulated", True)])
def test_invalid_advanced_values_rejected(field, value):
    with pytest.raises(ValueError):
        validate_value(field, value)


def test_tampered_svg_diameter_rejected_and_external_drainage_does_not_leak_k2():
    m = section_model(accepted_values(bound_draft()))
    root = ET.fromstring(build_concept_section_svg(m))
    next(r for r in root.iter() if r.get("data-fan-collector-dn")).set("data-fan-collector-dn", "150")
    assert "fan diameter differs from working risers" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))
    svg = build_concept_section_svg(replace(m, drainage="external"))
    assert "data-storm-riser-dn" not in svg and "К2 DN100" not in svg

"""Assigned drawing parameters never become invented hydraulic/takeoff data."""
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
import pymupdf

from app.intake.studio_intake import answer_field, accepted_values, build_handoff_request, extract_candidates, validate_value
from app.intake.studio_section import section_model, section_readiness
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.pz.wastewater_presentation import SectionMainInput, RepresentativeSectionInput
from app.pz.wastewater_graphic_exports import representative_section_model, wastewater_graphic_export
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg, generate_concept_section_pdf
from tests.test_studio_concept_section import ready_draft


def designed_draft():
    d = ready_draft()
    for system, dn, slope, mark, target in (("k1", 150, .02, -1.8, "КК-1"), ("k2", 200, .008, -1.65, "ДК-2")):
        for key, value in dict(dn_mm=dn, slope=slope, outlet_invert_m=mark, discharge_point=target,
                               source_ref="Контрольный пример; параметры назначены для проверки PDF").items():
            answer_field(d, f"section_{system}_{key}", value)
    return d


def test_persisted_parameters_same_renderer_no_invented_pipes():
    d = designed_draft()
    req = load_request(dump_request(build_handoff_request(d)))
    p = build_project(req)
    assert representative_section_model(p) == section_model(accepted_values(d))
    assert not p.sewage.pipes and not p.sewage.risers and not p.sewage.elements
    assert not wastewater_graphic_export(p, "k1-k2").ready
    assert "уклоны и выпуски заданы" in wastewater_graphic_export(p, "k1-k2").reasons[0]
    assert "Вентиляция" in wastewater_graphic_export(p, "k1-k2").reasons[0]
    original = build_project(build_handoff_request(ready_draft()))
    assert p.flows == original.flows


def test_empty_is_not_zero_or_a_new_gate_and_old_yaml_supported():
    m = section_model(accepted_values(ready_draft()))
    assert section_readiness(accepted_values(ready_draft()))["ready"]
    assert m.k1 == SectionMainInput() and m.k2 == SectionMainInput()
    assert "Уточнить" in m.design_notice
    assert RepresentativeSectionInput.from_mapping({"mode": "representative"}).k1 == SectionMainInput()


@pytest.mark.parametrize("key,value", [
    ("slope", 0), ("slope", -1), ("slope", 1), ("slope", 2), ("slope", True),
    ("dn_mm", 50), ("dn_mm", 150.5), ("dn_mm", 2001), ("dn_mm", True),
    ("outlet_invert_m", "NaN"), ("outlet_invert_m", "inf"),
])
def test_invalid_inputs(key, value):
    with pytest.raises(ValueError):
        validate_value("section_k1_"+key, value)


def test_signed_zero_levels_and_comma_grade():
    assert validate_value("section_k1_outlet_invert_m", "−1,800") == -1.8
    assert validate_value("section_k1_outlet_invert_m", 0) == 0
    assert validate_value("section_k1_outlet_invert_m", "+0,500") == .5
    assert validate_value("section_k2_slope", "0,008") == .008


def test_extraction_only_explicit_system_and_units():
    rows = extract_candidates("DN магистрали К1: 150 мм; уклон магистрали К1: 0,02 м/м; "
                              "отметка лотка выпуска К2: −1,650 м", "doc", 4)
    assert {r["field"]:r["value"] for r in rows} == {
        "section_k1_dn_mm":150, "section_k1_slope":.02, "section_k2_outlet_invert_m":-1.65}
    assert extract_candidates("Труба Ø160; уклон 2%; отметка крышки КК-1: −1,0 м", "doc", 1) == []


def test_lower_nodes_reducing_wyes_no_fake_transition_no_cap_on_through():
    m = section_model(accepted_values(designed_draft()))
    initial, through = m.lower_nodes()
    assert initial.service_path and through.service_path is None
    for node in (initial, through, m.storm_lower_node()):
        assert not node.validate()
        dns = {s.role:s.dn_mm for s in node.segments}
        assert dns["riser"] == dns["diagonal"] == 100
        assert dns["main"] == (200 if node.system == "K2" else 150)
        assert not any("transition" in f.kind for f in node.fittings)
    assert next(s for s in through.segments if s.role == "incoming_main").dn_mm == 150
    svg = build_concept_section_svg(m)
    assert audit_concept_section_svg(m, svg) == ()
    assert 'data-inline-pipe-label="К1 ⌀ 150"' in svg
    assert 'data-inline-pipe-label="К2 ⌀ 200"' in svg
    assert "0,020" in svg and "0,008" in svg and ">-1,80<" in svg
    assert 'data-level-mark="outlet-К1"' in svg and ">Лоток<" in svg
    assert "КК-1" in svg and "ДК-2" in svg
    assert all(p[-1] == ("К2:outlet" if s.startswith("К2:") else "К1:outlet") for s,p in m.flow_paths().items())


def test_pdf_and_sources_and_external_drainage(tmp_path):
    m = section_model(accepted_values(designed_draft()))
    out = tmp_path / "design.pdf"
    generate_concept_section_pdf(out, m)
    doc = pymupdf.open(out)
    text = doc[0].get_text()
    assert "-1,80" in text and "0,020" in text and "ДК-2" in text
    assert "Контрольный пример" in text and "не документ к выпуску" in text
    svg = build_concept_section_svg(replace(m, drainage="external"))
    assert 'data-section-outlet="К2"' not in svg and "ДК-2" not in svg


def test_edit_revokes_previous_artifacts_and_does_not_clear_demand():
    d = designed_draft()
    d.update(preview={"run_id":"old"}, package={"run_id":"old"}, project_calculation={"old":True}, calculation={"demand":True})
    answer_field(d, "section_k1_slope", .015)
    assert not d.get("preview") and not d.get("package") and not d.get("project_calculation")
    assert d["calculation"] == {"demand":True}

from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
import pymupdf

from app.intake.studio_intake import answer_field, accepted_values, build_handoff_request, validate_value
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.pz.section_fan import SectionFanInput, resolve_section_fan
from app.pz.residential_concept_section import build_concept_section_svg, audit_concept_section_svg, generate_concept_section_pdf
from app.pz.wastewater_presentation import RepresentativeSectionInput
from app.pz.wastewater_graphic_exports import representative_section_model, wastewater_graphic_export
from app.pz.generator import generate_wastewater_pz_html
from app.pz.spec import build_wastewater_specification, build_water_specification
from tests.test_section_design_inputs import designed_draft


def common_input(**changes):
    return replace(SectionFanInput(mode="common", member_ids=("К1-1", "К1-2", "К1-3", "К1-4"),
        space="cold_attic", space_floor_m=9.9, collector_low_m=10.6, collector_high_m=10.75,
        roof_level_m=11.8, height_m=3, source_ref="Контрольный вариант, не исходные реального объекта"), **changes)


def fan_draft():
    d = designed_draft()
    for key, value in dict(floors=3, roof_type="flat_accessible").items():
        answer_field(d, key, value)
    for key, value in common_input().to_mapping().items():
        if key == "building_attic_kind":
            continue
        answer_field(d, "section_fan_"+key, ", ".join(value) if key == "member_ids" else value)
    return d


@pytest.mark.parametrize("roof", ["flat_non_accessible", "single_slope", "gable"])
def test_individual_height_uses_canonical_rule_and_explicit_value(roof):
    d = designed_draft()
    answer_field(d, "roof_type", roof)
    m = section_model(accepted_values(d))
    assert m.fan_plan.kind == "individual" and m.fan_plan.dimension == "≥200"
    for value, expected in ((.35, "350"), (.19, None)):
        m = replace(m, fan=SectionFanInput(height_m=value))
        svg = build_concept_section_svg(m)
        assert audit_concept_section_svg(m, svg) == ()
        if expected:
            assert f'data-value="{expected}"' in svg
            assert "0,35" in m.fan_notice
        else:
            assert m.fan_plan.kind == "pending"
            assert 'data-fan-open-terminal=' not in svg


def test_accessible_roof_requires_explicit_group_not_two_paper_axes():
    assert resolve_section_fan("flat_accessible", 3, 3.3, SectionFanInput()).kind == "pending"
    assert resolve_section_fan("flat_accessible", 3, 3.3, SectionFanInput(mode="individual", height_m=3)).kind == "pending"
    assert resolve_section_fan("flat_accessible", 3, 3.3, common_input(member_ids=("К1-1", "К1-2", "К1-3"))).kind == "pending"
    p = resolve_section_fan("flat_accessible", 3, 3.3, common_input())
    assert p.kind == "common"
    assert any(c.code == "FAN-FOUR" and c.status == "verified" for c in p.checks)
    assert any(c.code == "FAN-DN" and c.status == "pending" for c in p.checks)
    assert any(c.code == "FAN-OPENINGS" and c.status == "pending" for c in p.checks)
    assert resolve_section_fan("flat_accessible", 3, 3.3, common_input(height_m=2.99)).kind == "pending"


@pytest.mark.parametrize("changes", [dict(space="unknown"), dict(source_ref=""), dict(roof_level_m=None),
    dict(collector_low_m=None), dict(space_floor_m=6.6), dict(collector_low_m=9.8),
    dict(collector_low_m=10.8), dict(collector_high_m=12)])
def test_no_collector_inside_apartments_or_with_unknown_route(changes):
    assert resolve_section_fan("flat_accessible", 3, 3.3, common_input(**changes)).kind == "pending"


@pytest.mark.parametrize("key,value", [("height_m", True), ("height_m", 0), ("height_m", "nan"),
    ("roof_level_m", "inf"), ("member_ids", "К1-1, К1-1"), ("member_ids", "К1-1, К2-1"),
    ("member_ids", "<script>"), ("space", "apartment")])
def test_bad_fan_inputs_rejected(key, value):
    with pytest.raises(ValueError):
        validate_value("section_fan_"+key, value)


def test_persistence_same_inputs_in_svg_pz_and_spec_no_fake_takeoff():
    d = fan_draft()
    p = build_project(load_request(dump_request(build_handoff_request(d))))
    m = representative_section_model(p)
    assert m == section_model(accepted_values(d)) and m.fan == common_input()
    svg, html = build_concept_section_svg(m), generate_wastewater_pz_html(p)
    assert audit_concept_section_svg(m, svg) == ()
    root = ET.fromstring(svg)
    assert [r.get("data-fan-member") for r in root.iter() if r.get("data-fan-member")] == list(m.fan.member_ids[:2])
    group = next(r for r in root.iter() if r.get("data-common-fan"))
    assert group.get("data-fan-group-size") == "4"
    assert all(rid in svg for rid in m.fan.member_ids)
    assert "Другие стояки вне разреза" not in svg
    assert len([r for r in root.iter() if r.get("data-fan-open-terminal")]) == 1
    assert len([r for r in root.iter() if r.get("data-section-apartment")]) == 6
    assert m.fan_notice in html and m.fan_notice in svg
    assert m.fan.source_ref in html and "10,75" in html and "10,60" in html
    rows = [r for s in build_wastewater_specification(p).sections for r in s.rows if "Сборный вентиляционный" in r.name]
    assert len(rows) == 1 and rows[0].qty is None and not rows[0].type_mark
    assert all("Сборный вентиляционный" not in r.name for s in build_water_specification(p).sections for r in s.rows)
    assert not p.sewage.pipes and not p.sewage.risers and not wastewater_graphic_export(p, "k1-k2").ready
    assert all(path[-1] == ("К2:outlet" if key.startswith("К2:") else "К1:outlet") for key,path in m.flow_paths().items())
    terminal = next(r for r in root.iter() if r.get("data-fan-open-terminal"))
    terminal.attrib.pop("data-fan-open-terminal")
    assert "missing or invented fan terminal" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))
    root = ET.fromstring(svg)
    collector = next(r for r in root.iter() if r.get("data-fan-collector"))
    collector.clear()
    assert "missing common fan collector" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))
    root = ET.fromstring(svg)
    riser = next(r for r in root.iter() if r.get("data-section-riser") == "К1-А")
    riser.set("y1", str(float(riser.get("y1"))+5))
    assert "riser disconnected from common fan collector" in audit_concept_section_svg(m, ET.tostring(root, encoding="unicode"))


def test_old_inputs_and_changes_do_not_keep_stale_scheme():
    assert RepresentativeSectionInput.from_mapping({"mode":"representative"}).fan == SectionFanInput()
    d = fan_draft()
    d["preview"] = {"id":"stale"}
    answer_field(d, "section_fan_roof_level_m", 10)
    assert d["preview"] is None
    m = section_model(accepted_values(d))
    assert m.fan_plan.kind == "pending" and 'data-common-fan' not in build_concept_section_svg(m)


def test_building_attic_answer_cannot_conflict_with_fan_route():
    d = fan_draft()
    answer_field(d, "attic_kind", "none")
    model = section_model(accepted_values(d))
    assert model.fan_plan.kind == "pending" and "противоречит" in model.fan_notice
    restored = build_project(load_request(dump_request(build_handoff_request(d))))
    assert representative_section_model(restored).fan_plan.kind == "pending"


@pytest.mark.parametrize("floors", [1, 2, 3, 4, 16])
def test_common_section_single_a3_keeps_floor_breaks_and_height(tmp_path, floors):
    m = section_model(accepted_values(fan_draft()))
    delta = (floors-3)*m.floor_height_m
    fan = common_input(**{k:getattr(m.fan,k)+delta for k in
        ("space_floor_m", "roof_level_m", "collector_low_m", "collector_high_m")})
    m = replace(m, floors=floors, fan=fan)
    svg = build_concept_section_svg(m)
    assert audit_concept_section_svg(m, svg) == ()
    path = tmp_path / "fan.pdf"
    generate_concept_section_pdf(path, m)
    with pymupdf.open(path) as pdf:
        assert len(pdf) == 1
        assert abs(pdf[0].rect.width*25.4/72-297) < .01
        assert "3000" in pdf[0].get_text() and "Общая вытяжка" in pdf[0].get_text()

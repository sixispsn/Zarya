from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request, dump_request, YamlFormatError
from app.pz.metering_detail import build_metering_detail_pages, drawing_state
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_pipes import MeteringPipeSection, pipe_checks, support_pipe
from app.pz.metering_product_selection import resolve_metering_products
from scripts.preview_metering_detail import review_project, mixed_pipe_sections


def resolve(p):
    state = drawing_state(p)
    return resolve_metering_products(p, state.meter, bypass=state.bypass,
                                    electric_bypass=state.electric_bypass)


def test_mixed_pipes_have_explicit_geometry_without_blanket_material_or_fake_dn():
    sections = mixed_pipe_sections()
    assert sections["inlet"].inner_diameter_mm == 53
    assert sections["before_meter"].inner_diameter_mm == pytest.approx(35.9)
    assert sections["outlet"].inner_diameter_mm == pytest.approx(45.8)
    assert sections["outlet"].nominal_dn is None  # Ø63 is NOT DN63.
    p = review_project()
    p.materials.cold_mains = "нержавеющая сталь"
    # No reuse of the free-text VGP classifier: stainless has no guessed size.
    p.metering_detail.pipe_sections = {"inlet": MeteringPipeSection(material="stainless_steel")}
    assert support_pipe(replace(p.metering_detail, support_pipe_section="inlet"))[:2] == (None,"stainless_steel")
    assert p.metering_detail.pipe_sections["inlet"].inner_diameter_mm is None
    assert any("нужны материал" in item for item in pipe_checks(p.metering_detail,bypass=True,fire_branch=False)[1])


@pytest.mark.parametrize("data", [
    {"outer_diameter_mm": True}, {"outer_diameter_mm": float("nan")},
    {"wall_thickness_mm": float("inf")}, {"wall_thickness_mm": 0},
    {"outer_diameter_mm": 10,"wall_thickness_mm": 5},
    {"outer_diameter_mm": 10,"wall_thickness_mm": 6},
    {"material": "магическая сталь"}, {"material": []}, {"joining": "guess"},
    {"nominal_dn": 32.5}, {"nominal_dn": True}, {"geometry_source": 1},
])
def test_invalid_pipe_geometry_never_accepted(data):
    section = MeteringPipeSection(**data)
    assert section.validate() and section.inner_diameter_mm is None
    assert MeteringDetailData(pipe_sections={"inlet":section}).validate()


@pytest.mark.parametrize("data", [None, [], {"unknown":{}}, {"inlet":True},
                                       {"inlet":{"wall":3.5}}])
def test_invalid_pipe_shape_or_unknown_keys_not_silently_discarded(data):
    assert MeteringDetailData(pipe_sections=data).validate()


def test_bound_support_rechecks_current_material_and_outside_diameter():
    p = review_project()
    d = p.metering_detail
    d.catalogue_revision = get_metering_catalogue().revision
    d.catalogue_items = {"pipe_clamp":"walraven-3117063"}
    d.pipe_sections = {"inlet":MeteringPipeSection(material="stainless_steel", outer_diameter_mm=60.3)}
    d.support_pipe_section = "inlet"
    assert not resolve(p).errors
    d.pipe_sections["inlet"] = MeteringPipeSection(material="steel",outer_diameter_mm=60)
    assert any("материалу" in error for error in resolve(p).errors)
    d.pipe_sections["inlet"] = MeteringPipeSection(material="stainless_steel",outer_diameter_mm=70)
    assert any("диаметр трубы вне" in error for error in resolve(p).errors)


def test_bound_support_missing_section_or_conflicting_manual_data_never_falls_back():
    d = MeteringDetailData(support_pipe_section="inlet", support_pipe_material="stainless_steel",
                          support_pipe_outer_diameter_mm=60.3)
    assert support_pipe(d)[:2] == (None,"unknown")
    assert support_pipe(d)[2]
    d.pipe_sections["inlet"] = MeteringPipeSection(material="ppr",outer_diameter_mm=63)
    assert support_pipe(d)[:2] == (63,"ppr")
    assert len(support_pipe(d)[2]) == 2


def test_no_material_auto_connects_and_inactive_branches_report_error():
    p = review_project(2)
    p.metering_detail.pipe_sections = mixed_pipe_sections()  # No bypass for two inlets.
    assert any("этой ветви" in e for e in resolve(p).errors)
    p = review_project()
    p.metering_detail.pipe_sections = {"fire_branch":mixed_pipe_sections()["inlet"]}
    assert any("этой ветви" in e for e in resolve(p).errors)
    errors,pending = pipe_checks(MeteringDetailData(pipe_sections=mixed_pipe_sections()),
                                bypass=True,fire_branch=False)
    assert not errors and any("Совпадение DN не подтверждает" in item for item in pending)
    assert any("требует проверки переходной детали" in item for item in pending)


def test_pipe_conflicts_reach_release_gate_without_catalogue_choices():
    from app.pz.commission import build_commission_report
    p = review_project(2)
    p.metering_detail.pipe_sections = mixed_pipe_sections()
    assert not p.metering_detail.catalogue_items
    gate = next(c for c in build_commission_report(p).checks if c.code == "VU-COMPOSITION")
    assert gate.blocking and gate.status == "fail" and "VU-CATALOGUE" in gate.result


@pytest.mark.parametrize("role", ["inlet","before_meter","after_meter","bypass"])
def test_known_nominal_dn_conflicts_not_hidden_by_matching_material(role):
    p = review_project()
    p.metering_detail.pipe_sections = {role:MeteringPipeSection(material="steel",nominal_dn=80)}
    assert any("DN трубы расходится" in e for e in resolve(p).errors)


def test_pipe_sections_yaml_roundtrip_and_builder_copy():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  support_pipe_section: inlet
  pipe_sections:
    inlet:
      material: steel
      nominal_dn: 50
      outer_diameter_mm: 60
      wall_thickness_mm: 3.5
      joining: threaded
      geometry_source: ГОСТ 3262-75
    outlet:
      material: ppr
      outer_diameter_mm: 63
      wall_thickness_mm: 8.6
''')
    assert load_request(dump_request(req)) == req
    project = build_project(req)
    assert isinstance(project.metering_detail.pipe_sections["inlet"],MeteringPipeSection)
    project.metering_detail.pipe_sections.pop("inlet")
    assert "inlet" in req.metering_detail.pipe_sections
    with pytest.raises(YamlFormatError):
        load_request(dump_request(req).replace("outer_diameter_mm: 60", "outer_diameter_mm: false"))


def test_svg_marks_match_pipe_schedule_and_no_hydraulic_mutation_or_fake_total():
    p = review_project()
    p.metering_detail.pipe_sections = mixed_pipe_sections()
    before = deepcopy(asdict(p))
    pages = build_metering_detail_pages(p)
    assert asdict(p) == before
    assert "Ø63×8,6" in pages[0] and "DN63" not in "".join(pages)
    signs = [e for svg in pages for e in ET.fromstring(svg).iter() if e.get("data-vector-diameter-sign")]
    assert len(signs) == 8  # Three drawing marks and five pipe schedule rows.
    tags = {el.get("data-pipe-section") for el in ET.fromstring(pages[0]).iter()
            if el.get("data-pipe-section")}
    rows = {el.get("data-pipe-row") for svg in pages for el in ET.fromstring(svg).iter()
            if el.get("data-pipe-row")}
    assert tags == rows == set(mixed_pipe_sections())
    assert any('data-meter-pipes="true"' in svg for svg in pages)
    assert resolve(p).assembly_length_mm is None
    assert drawing_state(p).meter.h_a == pytest.approx(1.573)
    for svg in pages:
        assert 'width="420mm" height="297mm"' in svg
        for element in ET.fromstring(svg).iter():
            if element.tag.endswith("text"):
                assert float(element.get("y")) <= 292
                assert "Ø" not in (element.text or "") and "⌀" not in (element.text or "")


def test_pipe_label_escaping_and_empty_old_project_no_new_sheet():
    p = review_project()
    assert not any('data-meter-pipes' in svg for svg in build_metering_detail_pages(p))
    p.metering_detail.pipe_sections = {"inlet": MeteringPipeSection(series='<x & y>')}
    assert "&lt;x &amp; y&gt;" in "".join(build_metering_detail_pages(p))

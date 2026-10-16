"""Real catalogue connectors: stable graph binding, not preview-only geometry."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.studio_intake import build_handoff_request
from app.intake.yaml_io import dump_request, load_request
from app.pz.equipment_origin import origin
from app.pz.metering_chain import ChainNode, MeteringChain, build_metering_chain
from app.pz.metering_detail import drawing_state
from app.pz.metering_joint_audit import check_inline_joints, audit_direct_joints
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_mounting import resolve_mounting
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from scripts.preview_metering_detail import catalogue_review_project
from tests.test_studio_apartment_meters import draft

JOINT = "joint_valve_before__filter"
PART = "valfex-vf582n114"


def resolve(p):
    s = drawing_state(p)
    result = resolve_metering_products(p, s.meter, bypass=s.bypass, electric_bypass=s.electric_bypass)
    return result, build_metering_chain(p.metering_detail, s, result)


def test_catalogue_uses_agreeing_drawing_and_catalogue_not_conflicting_series():
    c = get_metering_catalogue()
    p = c.thread_connectors[PART]
    assert dict(p.dimensions_mm) == {"L": 40, "SW": 43.5, "D": 46}
    assert p.equipment_thread == p.pipe_connector_thread == "1 1/4"
    assert p.equipment_sex == p.pipe_connector_sex == "male"
    assert p.pn_bar == 40 and p.temperature_c == (-20, 200)
    assert len(p.source_ids) == 2
    assert all(c.sources[s]["sha256"] for s in p.source_ids)
    assert [p.id for p in c.thread_connectors.values() if p.manufacturer == "VALFEX"] == [PART]
    assert origin(PART)["country"] == "unknown"  # Never infer from Russian brand.


@pytest.mark.parametrize("mode", ["explicit", "proposal"])
@pytest.mark.parametrize("scale", [5, 10, 20])
def test_same_part_in_chain_scale_so_and_mounting_without_changing_hydraulics(mode, scale):
    p = catalogue_review_project()
    d = p.metering_detail
    d.mounting.scale = scale
    if mode == "explicit":
        d.inline_joint_items = {JOINT: PART}
    else:
        d.inline_joint_selection_mode = "catalogue_proposal"
    before = deepcopy(asdict(p))
    selection, chain = resolve(p)
    check = next(c for c in selection.inline_joints if c.id == JOINT)
    assert check.part.id == PART and not check.errors
    assert check.proposed == (mode == "proposal")
    assert chain.node(JOINT).catalogue_id == PART
    ports = audit_direct_joints(chain, get_metering_catalogue(), inlet_dn=d.inlet_dn)
    assert all(c.status == "ports_match" for c in ports if JOINT in (c.before, c.after))
    layout = build_metering_layout(p).part(JOINT)
    assert layout.catalogue_id == PART and layout.length_mm == 40
    assert layout.points[-1][0] - layout.points[0][0] == pytest.approx(40 / scale)
    rows = [r for r in build_metering_spec_section(p).rows if JOINT in r.component_ids]
    assert len(rows) == 1 and rows[0].qty == 1 and rows[0].diagram_pos == "С7"
    assert rows[0].catalogue_id == PART and rows[0].type_mark == "VF.582.N.114"
    assert ("Предварительное" in rows[0].note) == (mode == "proposal")
    result = resolve_mounting(p)
    assert not result.dimensions_complete and result.chains[0].length_mm is None
    assert next(s for s in result.chains[0].spans if s.id == JOINT).length_mm == 40
    svg = "".join(layout_contents(p))
    assert "L корпуса 40 мм; посадки уточнить" in svg and "VF.582.N.114" in svg
    assert asdict(p) == before


def test_two_inputs_count_connector_twice_but_never_duplicate_kit():
    p = catalogue_review_project()
    p.source.inputs_count = p.meters.inputs_count = 2
    p.metering_detail.inline_joint_items = {JOINT: PART}
    rows = build_metering_spec_section(p).rows
    assert next(r for r in rows if JOINT in r.component_ids).qty == 2
    assert next(r for r in rows if "kit_in" in r.component_ids).qty == 2


@pytest.mark.parametrize("failure", ["unknown", "wrong_size", "stale_joint", "revision", "russian", "changed_filter"])
def test_manual_failure_does_not_turn_into_successful_automatic_substitution(failure):
    p = catalogue_review_project()
    d = p.metering_detail
    d.inline_joint_selection_mode = "catalogue_proposal"
    d.inline_joint_items = {JOINT: PART}
    if failure == "unknown":
        d.inline_joint_items[JOINT] = "not-a-product"
    elif failure == "wrong_size":
        d.inline_joint_items[JOINT] = "ld-67-501-50"
    elif failure == "stale_joint":
        d.inline_joint_items = {"joint_old__filter": PART}
    elif failure == "revision":
        d.catalogue_revision = "old"
    elif failure == "russian":
        d.russian_equipment_only = True
    elif failure == "changed_filter":
        d.catalogue_items["filter"] = "unknown-filter"
    selection, chain = resolve(p)
    failed = next(c for c in selection.inline_joints if c.id in d.inline_joint_items)
    assert failed.part is None and failed.errors and selection.errors
    assert all(n.catalogue_id is None for n in chain.nodes if n.id in d.inline_joint_items)
    assert not any(r.catalogue_id for r in build_metering_spec_section(p).rows
                   if set(r.component_ids) & d.inline_joint_items.keys())


def required_joint(thread):
    return MeteringChain((ChainNode(JOINT, "Ниппель", role="inline_nipple",
        required_standard="G", required_thread=thread),), (), 1)


@pytest.mark.parametrize("pressure,temperature", [(41, 25), (6, 201), (6, -21)])
def test_explicit_connector_limits_not_just_matching_threads(pressure, temperature):
    d = catalogue_review_project().metering_detail
    d.inline_joint_items = {JOINT: PART}
    d.design_pressure_bar, d.water_temperature_c = pressure, temperature
    c = check_inline_joints(required_joint("1 1/4"), d, get_metering_catalogue(), revision_ok=True)[0]
    assert c.part is None and c.errors
    assert all(p.id != PART for p in c.candidates)  # Other newly sourced models may fit; no silent substitution.


def test_manual_default_ambiguity_missing_conditions_and_origin_filter():
    d = catalogue_review_project().metering_detail
    catalog = get_metering_catalogue()
    check = lambda thread: check_inline_joints(required_joint(thread), d, catalog, revision_ok=True)[0]
    assert check("1 1/4").part is None  # Existing manual projects unchanged.
    d.inline_joint_selection_mode = "catalogue_proposal"
    assert check("1 1/4").part.id == PART
    c = check("2")
    assert len(c.candidates) == 2 and c.part is None  # No arbitrary brand ranking.
    d.russian_equipment_only = True
    assert not check("1 1/4").candidates
    assert check("2").part.id == "ld-67-501-50"
    d.russian_equipment_only = False
    d.design_pressure_bar = None
    assert check("1 1/4").part is None
    d.design_pressure_bar, d.water_temperature_c = 6, None
    assert check("1 1/4").part is None


def test_studio_opt_in_and_manual_assignment_survive_yaml_roundtrip():
    request = build_handoff_request(draft())
    assert request.metering_detail.inline_joint_selection_mode == "catalogue_proposal"
    request.metering_detail.inline_joint_items = {JOINT: PART}
    restored = load_request(dump_request(request))
    assert restored.metering_detail.inline_joint_selection_mode == "catalogue_proposal"
    assert restored.metering_detail.inline_joint_items == {JOINT: PART}


def test_normal_pdf_path_includes_connector_and_its_unfinished_conditions(tmp_path):
    from pypdf import PdfReader
    from app.pz.generator import generate_metering_scheme_pdf
    p = catalogue_review_project()
    p.metering_detail.inline_joint_selection_mode = "catalogue_proposal"
    p.metering_detail.mounting.enabled = True
    path = tmp_path / "with-nipple.pdf"
    generate_metering_scheme_pdf(p, str(path))
    pdf = PdfReader(path)
    text = "\n".join(page.extract_text() for page in pdf.pages)
    compact = "".join(text.split())  # Embedded drafting font can omit word spaces.
    assert "VF.582.N.114" in text
    assert "40мм" in compact and "PN40бар" in compact
    assert "Предварительноекаталожноепредложение" in compact
    assert "посадки" in text


@pytest.mark.parametrize("items", [[], {12: PART}, {"valve_before": PART}, {JOINT: ""}])
def test_invalid_input_is_reported(items):
    d = catalogue_review_project().metering_detail
    d.inline_joint_items = items
    assert any("inline_joint_items" in e for e in d.validate())

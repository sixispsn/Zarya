from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from app.data.metering_products import get_metering_catalogue
from app.data.metering_coverage import metering_coverage
from app.pz.metering_chain import build_metering_chain, ChainNode, ChainPath, MeteringChain
from app.pz.metering_detail import drawing_state
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_joint_audit import audit_direct_joints
from app.pz.metering_layout import build_metering_layout, layout_contents
from app.pz.metering_spec import build_metering_spec_section
from app.pz.metering_extras import resolve_metering_extras, metering_option_rows
from scripts.preview_metering_flanged import flanged_review_project
from scripts.preview_metering_detail import catalogue_review_project


def resolve(p):
    s = drawing_state(p)
    selection = resolve_metering_products(p,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    return selection, build_metering_chain(p.metering_detail,s,selection)


def fitted_project():
    p = flanged_review_project(100)
    d = p.metering_detail
    d.fitting_items = {"bypass_start":"vodopribor-tee-dn100x100",
                       "bypass_end":"vodopribor-tee-dn100x100"}
    d.catalogue_items.pop("filter")
    d.enhancements = {"magnetic_filter":"vodopribor_fmf_replace"}
    d.mounting.scale = 20
    return p


def test_catalogue_geometry_sources_no_interpolation_or_fake_elbow_L():
    c = get_metering_catalogue()
    assert len(c.fittings) == 47 and len(c.reducers) == 15 and len(c.thread_connectors) == 8
    assert c.fittings["valtec-vtr130-dn20"].body_length_mm == 53  # Not old PS428=58.
    assert c.fittings["vodopribor-tee-dn100x80"].branch_length_mm == 175
    assert c.fittings["vodopribor-xf-dn150x100"].body_length_mm == 250
    assert c.fittings["vodopribor-elbow90-dn200"].body_length_mm is None
    assert c.fittings["vodopribor-elbow90-dn200"].dimensions_mm["A"] == 300
    for p in c.fittings.values():
        assert p.source_page and p.source_ids and all(len(c.sources[s]["sha256"]) == 64 for s in p.source_ids)
    assert not c.fitting_candidates("tee", 125)
    assert not c.fitting_candidates("tee",100,branch_dn=65)
    assert not c.fitting_candidates("tee",50,material="ppr")
    assert c.fitting_candidates("tee",50,material="brass",connection="threaded")
    with pytest.raises(TypeError):
        c.fittings["valtec-vtr130-dn20"].dimensions_mm["L"] = 1


def test_exact_fmf_size_geometry_service_envelope_and_no_dn125():
    c = get_metering_catalogue()
    assert c.products["vodopribor-fmf-dn250"].body_length_mm == 800
    assert c.products["vodopribor-fmf-dn250"].dimensions_mm["L_service"] == 1100
    assert "vodopribor-fmf-dn125" not in c.products
    assert not metering_coverage(125)["equipment"]["magnetic_filter"]
    assert not metering_coverage(250)["geometry_complete"]  # Large tees/elbows still need primary-source dimensions.
    assert not any(metering_coverage(999)["equipment"].values())
    assert metering_coverage(250)["service_instruments"] == metering_coverage(15)["service_instruments"]
    assert not metering_coverage(100,russian_only=True)["fittings"]["tee"]


def test_disagreeing_manufacturer_dimensions_are_quarantined():
    c = get_metering_catalogue()
    nipple = c.thread_connectors["valtec-vtr582-0004"]
    assert nipple.dimension_status == "conflict" and nipple.body_length_mm is None
    assert nipple.dimensions_mm == {"passport_L":23, "drawing_L":25}
    assert c.thread_connectors["valtec-vtr582-0005"].body_length_mm == 29
    reducer = c.reducers["valtec-vtr580-0905"]
    assert reducer.dimension_status == "conflict" and reducer.body_length_mm is None
    assert reducer.dimensions_mm == {"passport_L":41, "drawing_L":38.5}
    assert reducer.id not in metering_coverage(50)["fittings"]["thread_reducer"]
    assert c.reducers["valtec-vtr580-0804"].body_length_mm == 38
    assert len([r for r in c.reducers.values() if r.dimension_status == "conflict"]) == 11
    assert len([r for r in c.thread_connectors.values() if r.dimension_status == "conflict"]) == 3
    assert "vtr582-drawing" in nipple.source_ids and "vtr580-drawing" in reducer.source_ids


def test_known_pressure_derating_is_not_replaced_by_pn():
    from app.pz.metering_joint_audit import check_inline_joints
    from app.pz.metering_fitting_selection import check_fittings
    c = get_metering_catalogue()
    p = catalogue_review_project()
    d = p.metering_detail
    d.design_pressure_bar, d.water_temperature_c = 30, 250
    d.bypass_dn = d.inlet_dn = 20
    d.fitting_items = {"bypass_start":"valtec-vtr130-dn20"}
    check = check_fittings(d,c,drawing_state(p).meter,bypass=True,fire_branch=False,revision_ok=True)[0]
    assert check.part is None and any("при заданной температуре" in e for e in check.errors)
    node = ChainNode("joint_test", "inline_nipple", required_standard="G",required_thread="3/4")
    d.inline_joint_items = {"joint_test":"valtec-vtr582-0005"}
    check = check_inline_joints(MeteringChain((node,),(),1),d,c,revision_ok=True)[0]
    assert check.part is None and any("при заданной температуре" in e for e in check.errors)


def test_modern_accessories_are_listed_once_in_layout_composition():
    from scripts.preview_metering_fittings import review
    p = review(100)
    rows = build_metering_spec_section(p).rows
    accessories = [r for r in rows if r.quantity_basis == "explicit_vu_accessory"]
    assert len(accessories) == 2 and all(r.qty == 1 for r in accessories)
    svg = "".join(layout_contents(p))
    assert "SAURES" in svg and "WSP+" in svg


def test_fittings_propagate_to_chain_scale_and_spec_without_changing_calc():
    p = fitted_project()
    before = deepcopy(asdict(p))
    selection, chain = resolve(p)
    assert not selection.errors
    assert selection.selected("filter").id == "vodopribor-fmf-dn100"
    layout = build_metering_layout(p)
    assert not layout.issues
    for ident in ("bypass_start","bypass_end"):
        assert chain.node(ident).catalogue_id == "vodopribor-tee-dn100x100"
        part = layout.part(ident)
        assert part.length_mm == 400 and part.branch_length_mm == 200
        assert part.points[-1][0] - part.points[0][0] == pytest.approx(400/layout.scale)
    branch = next(l for l in layout.links if l.before == "bypass_start" and l.after == "bypass_route_in")
    assert branch.points[0][1] == layout.part("bypass_start").center[1] - 200 / layout.scale
    rows = build_metering_spec_section(p).rows
    filters = [r for r in rows if r.component_ids == ("filter",)]
    assert len(filters) == 1 and filters[0].catalogue_id == "vodopribor-fmf-dn100" and filters[0].qty == 1
    for ident in ("bypass_start","bypass_end"):
        row = [r for r in rows if ident in r.component_ids]
        assert len(row) == 1 and row[0].unit == "шт." and row[0].qty == 1
    assert not resolve_metering_extras(p)["items"]  # Filter already in main SO, no duplicate.
    assert asdict(p) == before


@pytest.mark.parametrize("role,part", [
    ("service_before","valtec-vtr130-dn25"),  # Tee has 3, node has 4 ports.
    ("bypass_start","vodopribor-tee-dn100x80"),
    ("service_after","vodopribor-tee-dn100x100"),
    ("fire_takeoff","vodopribor-tee-dn100x100"),  # No fire branch here.
    ("reducer_in","vodopribor-xf-dn100x80"),  # No DN change here.
])
def test_wrong_topology_does_not_produce_a_confirmed_part(role,part):
    p = fitted_project()
    p.metering_detail.fitting_items = {role:part}
    selection, chain = resolve(p)
    assert selection.errors and not selection.fittings[0].part
    assert not any(n.catalogue_id == part for n in chain.nodes)
    assert not any(r.catalogue_id == part for r in build_metering_spec_section(p).rows)


def test_flanged_reducer_orientation_and_real_tee_branch_port():
    p = fitted_project()
    d = p.metering_detail
    d.inlet_dn = d.bypass_dn = 150
    for role in ("inlet_valve","bypass_valve"):
        d.catalogue_items[role] = "adl-kr20-pn16-dn150"
    d.catalogue_items["check_valve"] = "ridan-nvd402r-dn150"
    d.fitting_items = {"bypass_start":"vodopribor-tee-dn150x150", "bypass_end":"vodopribor-tee-dn150x150",
                       "reducer_in":"vodopribor-xf-dn150x100", "reducer_out":"vodopribor-xf-dn150x100"}
    s, chain = resolve(p)
    assert not s.errors
    checks = audit_direct_joints(chain,get_metering_catalogue(),inlet_dn=150)
    r = next(c for c in checks if c.before == "reducer_in")
    assert r.left.dn == r.right.dn == 100
    r = next(c for c in checks if c.after == "reducer_out")
    assert r.left.dn == r.right.dn == 100
    layout = build_metering_layout(p)
    assert not layout.issues and layout.part("reducer_out").kind == "reducer_expand"


def test_branch_ports_are_not_confused_with_main_ports():
    c = get_metering_catalogue()
    chain = MeteringChain((ChainNode("bypass_start","", "vodopribor-tee-dn100x80"),
        ChainNode("bypass_route_in","", "adl-kr20-pn16-dn80")),
        (ChainPath("bypass","",("bypass_start","bypass_route_in")),),1)
    joint = audit_direct_joints(chain,c,inlet_dn=100)[0]
    assert joint.left.dn == joint.right.dn == 80
    assert joint.status == "unresolved"  # Hole 18 vs19 alone does not prove incompatibility; bolt still unknown.


def test_modern_family_uses_current_dn_not_fixed32_and_preserves_old_choice():
    p = catalogue_review_project()
    p.metering_detail.enhancements = {"technology":"pulsar_m2_us_family"}
    plan = resolve_metering_extras(p)
    assert plan["selections"][0]["products"][0]["id"] == "pulsar-m2-e1-t105-rs485-dn32"
    p.metering_detail.enhancements["power"] = "battery"
    assert resolve_metering_extras(p)["selections"][0]["status"] == "conflict"
    p = flanged_review_project(250)
    p.metering_detail.enhancements = {"technology":"pulsar_m2_us_family"}
    plan = resolve_metering_extras(p)
    assert not plan["selections"][0]["products"] and plan["issues"]
    assert "DN250" in metering_option_rows(p)[0]["requirement"]
    p.metering_detail.enhancements = {"technology":"pulsar_m2_us32"}
    assert resolve_metering_extras(p)["selections"][0]["status"] == "conflict"


def test_conflicting_filter_or_ru_filter_not_silently_replaced():
    p = fitted_project()
    p.metering_detail.catalogue_items["filter"] = "adl-is16-dn100"
    selection, _ = resolve(p)
    assert selection.selected("filter") is None and selection.errors
    p.metering_detail.catalogue_items.pop("filter")
    p.metering_detail.russian_equipment_only = True
    assert resolve(p)[0].selected("filter") is None


def test_yaml_roundtrip_and_read_only_catalogue_api():
    from app.intake.project_builder import build_project
    from app.intake.yaml_io import dump_request, load_request
    from app.intake.studio_intake import build_handoff_request
    from tests.test_studio_apartment_meters import draft
    from app.api.water_meters import assembly_catalogue
    request = build_handoff_request(draft())
    request.metering_detail.fitting_items = {"bypass_start":"valtec-vtr130-dn50"}
    restored = load_request(dump_request(request))
    assert restored.metering_detail.fitting_items == request.metering_detail.fitting_items
    p = build_project(restored)
    p.metering_detail.fitting_items.clear()
    assert restored.metering_detail.fitting_items
    data = assembly_catalogue(100)
    assert data["coverage"]["dn"] == 100 and data["fittings"]
    assert all(row["ports"] and row["sources"] for row in data["fittings"])

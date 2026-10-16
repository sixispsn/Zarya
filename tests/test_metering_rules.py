from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from app.intake.yaml_io import load_request, dump_request
from app.intake.project_builder import build_project
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_rules import control_cock_dn, evaluate_metering_rules, remote_readout_required
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.project import BuildingPurpose
from app.data.metering_products import get_metering_catalogue
from scripts.preview_metering_detail import review_project


def checks(p):
    state = drawing_state(p)
    return {r.code: r for r in evaluate_metering_rules(p, state.meter,
            inputs_count=state.inputs_count, bypass=state.bypass)}


@pytest.mark.parametrize("kind,dn,expected", [
    ("крыльчатый",15,15), ("крыльчатый",50,15), ("турбинный",65,25),
    ("турбинный",100,25), ("ультразвуковой",50,None), ("",32,None),
    ("турбинный",50,None), ("крыльчатый",65,None),
])
def test_control_dn_follows_type_and_dn_not_guess(kind,dn,expected):
    assert control_cock_dn(SimpleNamespace(type_label=kind,dn=dn)) == expected


def test_two_capped_cocks_straddle_downstream_shutoff_and_one_is_within_500():
    root = ET.fromstring(build_metering_detail_pages(review_project())[0])
    cocks = [e for e in root.iter() if e.get("data-control-cock")]
    assert len(cocks) == 2
    assert all(e.get("data-capped") == "true" and e.get("data-dn") == "15" for e in cocks)
    x = [float(e.get("data-connection-x")) for e in cocks]
    assert 150 < x[0] < 219 < x[1] < 247  # Meter -> first tap -> valve -> second tap -> check.
    assert "≤500 мм" in ET.tostring(root,encoding="unicode")


@pytest.mark.parametrize("count,bypass,need,error", [
    (1,False,False,True),(1,True,False,False),
    (2,False,False,False),(2,False,True,True),(2,True,True,False),
])
def test_bypass_check_never_changes_accepted_hydraulic_result(count,bypass,need,error):
    p = review_project(count)
    p.meters.has_bypass = bypass
    drawing_state(p).meter.need_bypass = need
    before = deepcopy(asdict(p))
    assert (checks(p)["VU-BYPASS"].status == "error") == error
    assert asdict(p) == before


@pytest.mark.parametrize("purpose,required", [(BuildingPurpose.RESIDENTIAL,True),
    (BuildingPurpose.PUBLIC,True),(BuildingPurpose.INDUSTRIAL,False)])
def test_readout_requirement_does_not_depend_on_askue_checkbox(purpose,required):
    p = review_project()
    p.building.purpose = purpose
    p.meters.has_askue = False
    assert remote_readout_required(p) == required
    assert ("VU-REMOTE" in checks(p)) == required


def test_non_remote_meter_is_rejected_for_residential_not_auto_upgraded():
    p = review_project()
    p.building.purpose = BuildingPurpose.RESIDENTIAL
    p.metering_detail.catalogue_revision = get_metering_catalogue().revision
    p.metering_detail.catalogue_items = {"meter":"decast-vskm90-dn32"}
    assert checks(p)["VU-REMOTE"].status == "error"
    s = drawing_state(p)
    selected = resolve_metering_products(p,s.meter,bypass=s.bypass,electric_bypass=s.electric_bypass)
    assert selected.selected("meter") is None
    assert p.metering_detail.catalogue_items["meter"] == "decast-vskm90-dn32"


@pytest.mark.parametrize("temp,status", [(None,"needs_data"),(4.9,"error"),(5,"checked")])
def test_room_temperature_threshold(temp,status):
    p = review_project()
    p.metering_detail.room_min_temperature_c = temp
    assert checks(p)["VU-ROOM-TEMP"].status == status


@pytest.mark.parametrize("seismic,active", [(0,False),(6,False),(7,True),(8,True),(9,True)])
def test_seismic_applicability_and_no_fake_flexible_layout(seismic,active):
    p = review_project()
    p.building.seismicity = seismic
    assert ("VU-SEISMIC-FLEX" in checks(p)) == active
    pages = build_metering_detail_pages(p)
    assert ('data-special-layout="unresolved"' in pages[0]) == active
    assert ('data-wall-crossing="true"' in pages[0]) != active
    if active:
        assert "15.2.6" in ''.join(pages)


def test_seismic_outside_rule_scope_and_basis_are_not_auto_approved():
    p = review_project()
    p.building.seismicity = 10
    assert checks(p)["VU-SEISMIC-SCOPE"].status == "error"
    p.building.seismicity = 8
    p.metering_detail.seismic_design_basis = "Решение КР, лист 10"
    assert checks(p)["VU-SEISMIC-FLEX"].status == "review"
    assert 'data-special-layout="unresolved"' in build_metering_detail_pages(p)[0]


@pytest.mark.parametrize("location,status", [("unknown","needs_data"),("basement","error"),
    ("ventilated_crawlspace","error"),("first_floor","checked")])
def test_permafrost_location_is_explicit_not_guessed_from_elevation(location,status):
    p = review_project()
    p.building.permafrost = True
    p.metering_detail.room_location = location
    p.metering_detail.inlet_elevation_m = -2
    assert checks(p)["VU-FROZEN-LOCATION"].status == status
    assert 'data-wall-crossing=' not in build_metering_detail_pages(p)[0]


def test_permafrost_minimum_applies_to_inlet_not_meter_dn_and_does_not_mutate():
    p = review_project()
    p.building.permafrost = True
    assert drawing_state(p).meter.dn == 32
    assert checks(p)["VU-FROZEN-DN"].status == "checked"  # Inlet DN50, meter DN32.
    p.metering_detail.inlet_dn = 40
    assert checks(p)["VU-FROZEN-DN"].status == "error"
    assert p.metering_detail.inlet_dn == 40
    p.building.permafrost = False
    assert "VU-FROZEN-DN" not in checks(p)


def test_conditions_roundtrip_from_yaml_to_project_and_never_inferred():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6, seismicity: 8, permafrost: true}
fire: {height_m: 3.3}
metering_detail:
  room_location: first_floor
  room_min_temperature_c: 5
  service_access_confirmed: true
  seismic_design_basis: КР лист 10
''')
    assert not req.validate()
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    assert p.building.seismicity == 8 and p.building.permafrost
    assert p.metering_detail.room_location == "first_floor"
    assert p.metering_detail.service_access_confirmed is True
    assert "VU-SEISMIC-FLEX" in checks(p) and "VU-FROZEN-DN" in checks(p)


@pytest.mark.parametrize("data", [{"room_location":"invented"}, {"room_min_temperature_c":True},
    {"room_min_temperature_c":float("nan")}, {"service_access_confirmed":"yes"},
    {"seismic_design_basis":False}])
def test_bad_installation_inputs_rejected(data):
    assert MeteringDetailData(**data).validate()


def test_rules_reach_paginated_pdf_input_and_keep_legible_physical_font():
    p = review_project()
    p.building.seismicity = 8
    p.building.permafrost = True
    pages = build_metering_detail_pages(p)
    roots = [ET.fromstring(s) for s in pages if 'data-meter-rules="true"' in s]
    rules = [e for r in roots for e in r.iter() if e.get("data-meter-rule")]
    assert {e.get("data-meter-rule") for e in rules} == set(checks(p))
    for rule in rules:
        for e in rule:
            if e.tag.endswith("text"):
                assert float(e.get("y")) < 228
                assert e.get("data-text-height-mm") == "3.5"


def test_known_invalid_composition_blocks_release_not_calculation():
    from app.pz.commission import build_commission_report
    p = review_project()
    p.metering_detail.room_min_temperature_c = -5
    before = deepcopy(asdict(p))
    result = next(c for c in build_commission_report(p).checks if c.code == "VU-COMPOSITION")
    assert result.blocking and result.status == "fail"
    assert "VU-ROOM-TEMP" in result.result
    assert asdict(p) == before
    p.metering_detail.room_min_temperature_c = None
    p.building.seismicity = 8
    result = next(c for c in build_commission_report(p).checks if c.code == "VU-COMPOSITION")
    assert result.blocking and result.status == "missing"


def test_calculation_only_pipeline_exposes_same_composition_warnings(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    p = review_project()
    p.metering_detail.room_min_temperature_c = -5
    bundle = design_ios2(p,output_dir=str(tmp_path),render_documents=False)
    assert any("VU-ROOM-TEMP" in w for w in bundle.warnings)
    assert not bundle.metering_scheme_pdf

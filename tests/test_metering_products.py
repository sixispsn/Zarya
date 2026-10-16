from copy import deepcopy
from dataclasses import asdict

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request, dump_request
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.project import BuildingPurpose
from scripts.preview_metering_detail import review_project


def selected_project():
    p = review_project()
    # The base non-impulse model is eligible only outside the mandatory
    # residential/public remote-readout profile. Geometry tests aren't a
    # waiver of SP30 §12.13; that rejection is exercised separately.
    p.building.purpose = BuildingPurpose.INDUSTRIAL
    p.metering_detail.catalogue_revision = get_metering_catalogue().revision
    p.metering_detail.catalogue_items = {
        "meter": "decast-vskm90-dn32", "meter_valves": "valtec-vt214-dn32",
        "inlet_valve": "valtec-vt214-dn50", "filter": "valtec-vt192-dn32",
        "bypass_valve": "valtec-vt214-dn50",
    }
    p.metering_detail.design_pressure_bar = 6
    p.metering_detail.water_temperature_c = 25
    return p


def resolve(p):
    state = drawing_state(p)
    return resolve_metering_products(p, state.meter, bypass=state.bypass,
                                    electric_bypass=state.electric_bypass)


def test_catalogue_has_sourced_geometry_and_does_not_treat_handle_as_length():
    c = get_metering_catalogue()
    assert len(c.products) == 94
    assert sum(p.dimension_status == "verified" for p in c.products.values()) == 88
    for p in c.products.values():
        assert p.source_ids and all(s in c.sources for s in p.source_ids)
    v = c.products["valtec-vt214-dn32"]
    assert v.body_length_mm == 77.5
    assert v.dimensions_mm["A_handle"] == 122
    assert v.dimensions_mm["B_above_axis"] == 60
    assert c.products["valtec-vt192-dn32"].body_length_mm == 98


def test_body_and_kit_connection_and_reference_length_remain_distinct():
    p = get_metering_catalogue().products["decast-vskm90-dn32"]
    assert p.body_length_mm == 260
    assert p.dimensions_mm["L1_reference"] == 387
    assert p.thread == "1 1/2" and p.kit_pipe_thread == "1 1/4"
    with pytest.raises(TypeError):
        p.dimensions_mm["L"] = 999


def test_conflicting_passport_and_drawing_never_enter_automatic_candidates():
    c = get_metering_catalogue()
    for dn in (15,20,25,32,40,50):
        p = c.products[f"valtec-vt161-dn{dn}"]
        assert p.dimension_status == "conflict" and p.body_length_mm is None
        assert p not in c.candidates("check", dn)
        expected = [f"itap-europa100-g-dn{dn}"] + (["ridan-nvd402r-dn50"] if dn == 50 else [])
        assert [v.id for v in c.candidates("check", dn)] == expected
    p = selected_project()
    p.metering_detail.catalogue_items["check_valve"] = "valtec-vt161-dn50"
    r = resolve(p)
    assert r.selected("check_valve") is None
    assert any("Конфликт" in e for e in r.errors)
    assert r.selected("meter") is not None


def test_project_binding_is_explicit_and_has_no_fake_assembly_length():
    p = selected_project()
    before = deepcopy(asdict(p))
    r = resolve(p)
    assert not r.errors
    assert r.selected("meter").body_length_mm == 260
    assert r.selected("filter").dn == 32
    assert r.selected("inlet_valve").dn == 50
    assert r.assembly_length_mm is None
    assert asdict(p) == before
    # No implicit brand selection, even if one candidate remains.
    r = resolve(review_project())
    assert [p.id for p in r.positions[0].candidates] == ["decast-vskm90-dg-dn32"]
    assert all(x.product is None for x in r.positions)


@pytest.mark.parametrize("change,expected", [
    (lambda d: setattr(d,"catalogue_revision","old"), "Редакция"),
    (lambda d: d.catalogue_items.update(meter="decast-vskm90-dn50"), "Тип/DN"),
    (lambda d: d.catalogue_items.update(meter="unknown"), "Неизвестный"),
    (lambda d: d.catalogue_items.update(meter="valtec-vt192-dn32"), "Тип/DN"),
    (lambda d: setattr(d,"water_temperature_c",121), "Температура"),
    (lambda d: setattr(d,"design_pressure_bar",17), "Давление"),
    (lambda d: setattr(d,"meter_model","Другая модель"), "наименование"),
])
def test_stale_or_incompatible_meter_is_not_substituted(change, expected):
    p = selected_project()
    change(p.metering_detail)
    r = resolve(p)
    assert r.selected("meter") is None
    assert any(expected in e for e in r.errors)


def test_drive_and_askue_are_not_silently_downgraded():
    p = selected_project()
    drawing_state(p).meter.need_bypass = True
    p.meters.has_askue = True
    r = resolve(p)
    assert r.selected("bypass_valve") is None and r.selected("meter") is None
    assert any("привода" in e for e in r.errors) and any("АСКУЭ" in e for e in r.errors)


def test_real_model_max_flow_checked_without_overwriting_legacy_values():
    p = selected_project()
    row = drawing_state(p).meter
    assert row.qmax == 10 and row.q_meter_min == .1
    assert resolve(p).selected("meter").flows_m3h["qmax"] == 12
    assert resolve(p).selected("meter").flows_m3h["qmin_B"] == .12
    p.flows.q_sec_c = 4
    assert resolve(p).selected("meter") is None
    assert row.qmax == 10 and row.q_meter_min == .1


def test_pressure_temperature_table_used_without_extrapolation():
    p = selected_project()
    p.metering_detail.water_temperature_c = 150
    p.metering_detail.design_pressure_bar = 9
    r = resolve(p)
    assert r.selected("meter_valves") is None  # DN32: 8 bar at 150 C, not PN25.
    assert any("заданной температуре" in e for e in r.errors)
    p.metering_detail.water_temperature_c = 20
    r = resolve(p)
    assert any("интерполяция" in e for pos in r.positions for e in pos.pending)


def test_ids_persist_and_builder_does_not_share_mutable_choices():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  catalogue_revision: '2026-09-30.1'
  catalogue_items: {meter: decast-vskm90-dn32}
  design_pressure_bar: 6
  water_temperature_c: 25
''')
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    p.metering_detail.catalogue_items.clear()
    assert req.metering_detail.catalogue_items


@pytest.mark.parametrize("data", [
    {"catalogue_items": []}, {"catalogue_items": {"unknown":"x"}},
    {"catalogue_items": {"meter":True}}, {"design_pressure_bar":float("nan")},
    {"design_pressure_bar":-1}, {"water_temperature_c":True},
])
def test_invalid_catalogue_input_rejected(data):
    assert MeteringDetailData(**data).validate()


def test_catalogue_sheets_show_actual_dimensions_without_changing_calculation():
    p = selected_project()
    before = deepcopy(asdict(p))
    pages = build_metering_detail_pages(p)
    assert len(pages) > 1
    svg = "".join(pages)
    assert "ДЕКАСТ ВСКМ 90 DN32" in pages[0]
    assert "260,0" in svg and "77,5" in svg and "387,0" in svg
    assert "СПРАВОЧНО" in svg
    assert "Общая монтажная длина узла не определена" in svg
    assert asdict(p) == before

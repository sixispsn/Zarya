from copy import deepcopy
from dataclasses import asdict

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.yaml_io import load_request, dump_request
from app.intake.project_builder import build_project
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_rules import evaluate_metering_rules
from scripts.preview_metering_detail import review_project


def project():
    p = review_project()
    p.metering_detail.catalogue_revision = get_metering_catalogue().revision
    p.metering_detail.catalogue_items = {"meter": "decast-vskm90-dg-dn32",
        "meter_connections": "decast-vskm90-kit-dn32", "pipe_clamp": "walraven-3117043"}
    return p


def resolve(p):
    state = drawing_state(p)
    return resolve_metering_products(p, state.meter, bypass=state.bypass,
                                    electric_bypass=state.electric_bypass)


def test_remote_model_is_separate_sourced_execution_without_hydraulic_mutation():
    c = get_metering_catalogue()
    for dn in (15,20,25,32,40,50):
        base, dg = (c.products[f"decast-vskm90{suffix}-dn{dn}"] for suffix in ("", "-dg"))
        assert dg.remote_readout and not base.remote_readout
        assert dg.source_ids == ("decast-106",)
        assert dg.remote_interface == "Импульсный (геркон)"
        assert dg.body_length_mm == base.body_length_mm
    p = project()
    before = deepcopy(asdict(p))
    result = resolve(p)
    assert not result.errors and result.selected("meter").remote_readout
    assert any("цену импульса" in t for pos in result.positions for t in pos.pending)
    state = drawing_state(p)
    rules = evaluate_metering_rules(p,state.meter,inputs_count=1,bypass=state.bypass)
    assert next(r for r in rules if r.code == "VU-REMOTE").status == "checked"
    assert state.meter.q_meter_min == .1  # Not overwritten by passport 0.12.
    assert asdict(p) == before


def test_kit_is_explicit_and_reference_length_is_not_installed_length():
    p = project()
    r = resolve(p)
    kit = get_metering_catalogue().connection_kits["decast-vskm90-kit-dn32"]
    assert kit.meter_thread == "1 1/2" and kit.pipe_thread == "1 1/4"
    assert kit.length_with_meter_reference_mm == 387 and kit.status == "reference_only"
    assert r.assembly_length_mm is None
    assert not r.accessories[0].errors
    assert any("пределами" in t for t in r.accessories[0].pending)
    p.metering_detail.catalogue_items.pop("meter_connections")
    assert not any(a.role == "meter_connections" for a in resolve(p).accessories)


@pytest.mark.parametrize("role,ident", [("meter_connections","decast-vskm90-kit-dn40"),
    ("meter_connections","unknown"), ("pipe_clamp","unknown")])
def test_wrong_accessory_never_silently_substituted(role,ident):
    p = project()
    p.metering_detail.catalogue_items[role] = ident
    assert resolve(p).errors
    assert p.metering_detail.catalogue_items[role] == ident


@pytest.mark.parametrize("diameter,valid", [(32,False),(39.99,False),(40,True),(42.4,True),(43,True),(43.01,False)])
def test_clamp_matches_outer_diameter_not_dn(diameter,valid):
    p = project()
    p.metering_detail.support_pipe_outer_diameter_mm = diameter
    c = next(a for a in resolve(p).accessories if a.role == "pipe_clamp")
    assert (not c.errors) is valid


def test_support_needs_data_is_not_a_calculated_stand_or_invented_load():
    p = project()
    c = resolve(p).accessories[-1]
    assert not c.errors and any("не задана" in t for t in c.pending)
    assert any("не готовая опора" in t for t in c.pending)
    p.metering_detail.support_pipe_material = "steel"
    assert resolve(p).accessories[-1].errors
    p.metering_detail.support_pipe_material = "stainless_steel"
    p.metering_detail.support_design_load_z_n = 900
    assert not resolve(p).accessories[-1].errors
    p.metering_detail.support_design_load_z_n = 900.01
    assert resolve(p).accessories[-1].errors


def test_stale_revision_invalidates_meter_kit_and_clamp():
    p = project()
    p.metering_detail.catalogue_revision = "2026-09-30.1"
    r = resolve(p)
    assert r.selected("meter") is None
    assert all(a.errors for a in r.accessories)


def test_missing_meter_does_not_allow_kit_and_known_errors_reach_release_gate():
    from app.pz.commission import build_commission_report
    p = project()
    p.metering_detail.catalogue_items.pop("meter")
    assert resolve(p).accessories[0].errors
    gate = next(c for c in build_commission_report(p).checks if c.code == "VU-COMPOSITION")
    assert gate.blocking and gate.status == "fail" and "VU-CATALOGUE" in gate.result


@pytest.mark.parametrize("data", [{"support_pipe_outer_diameter_mm":True},
    {"support_design_load_z_n":float("nan")}, {"support_design_load_z_n":-1},
    {"support_pipe_material":"magic"}])
def test_invalid_support_inputs_rejected(data):
    assert MeteringDetailData(**data).validate()


def test_accessory_inputs_persist_and_pdf_distinguishes_output_from_askue():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  catalogue_revision: '2026-09-30.2'
  catalogue_items: {pipe_clamp: walraven-3117043}
  support_pipe_outer_diameter_mm: 42.4
  support_pipe_material: stainless_steel
  support_design_load_z_n: 100
''')
    assert load_request(dump_request(req)) == req
    built = build_project(req)
    assert built.metering_detail.support_design_load_z_n == 100
    p = project()
    before = deepcopy(asdict(p))
    pages = build_metering_detail_pages(p)
    assert "Импульсный (геркон)" in pages[0]
    # Selecting a product alone cannot imply horizontal mounting/class B.
    assert "Qmin, м³/ч · паспорт для ориентации" in pages[0]
    assert "Qmin, м³/ч · модель, класс B" not in pages[0]
    assert "Проверка малых расходов по паспорту не завершена" in pages[0]
    assert drawing_state(p).meter.q_min_passport_m3h is None
    svg = "".join(pages)
    assert "L1 со счётчиком = 387 мм СПРАВОЧНО" in svg
    assert "не готовая опора" in svg and "3117043" in svg
    assert "готовность АСКУЭ" in svg
    assert asdict(p) == before

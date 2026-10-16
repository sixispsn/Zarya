from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.data.metering_products import get_metering_catalogue
from app.intake.project_builder import build_project
from app.intake.yaml_io import dump_request, load_request
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_detail import drawing_state, build_metering_detail_pages, _label_width
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_reducers import check_reducers
from app.pz.metering_rules import evaluate_metering_rules
from scripts.preview_metering_detail import catalogue_review_project, review_project


ID = "valtec-vtr580-0907"


def resolve(p):
    state = drawing_state(p)
    return resolve_metering_products(p, state.meter, bypass=state.bypass,
                                    electric_bypass=state.electric_bypass)


def check_direct(p=None, *, catalog=None, products=None, bypass=True, meter_dn=32, revision_ok=True):
    p = p or catalogue_review_project()
    catalog = catalog or get_metering_catalogue()
    products = products if products is not None else {
        "inlet_valve": catalog.products["valtec-vt214-dn50"],
        "meter_valves": catalog.products["valtec-vt214-dn32"],
        "check_valve": catalog.products["itap-europa100-g-dn50"],
    }
    return check_reducers(p.metering_detail,catalog,products,meter_dn=meter_dn,
                          bypass=bypass,revision_ok=revision_ok)


def test_manufacturer_geometry_is_not_installed_length_or_full_contour():
    c = get_metering_catalogue()
    r = c.reducers[ID]
    assert c.revision == "2026-09-30.5"
    assert (r.large_dn,r.small_dn,r.large_thread,r.small_thread) == (50,32,"2","1 1/4")
    assert r.large_sex == r.small_sex == "male"
    assert dict(r.dimensions_mm) == {"L":41}  # 61 / 65.5 transverse conflict NOT loaded
    assert r.body_length_mm == 41
    assert {c.sources[s]["sha256"] for s in r.source_ids} == {
        "44e8069b8d2e0660acd4e1ca60a2e4f9b42c047db86bf31bafc22ca1a76be6f6",
        "0e85fe1c895808359d59831e34bf1cb57ba326b77ae2f4282479ef65c0d25df2"}
    with pytest.raises(TypeError):
        r.dimensions_mm["L"] = 42


def test_two_directions_and_no_port_approval_for_an_unspecified_tee():
    p = catalogue_review_project()
    before = deepcopy(asdict(p))
    r = resolve(p)
    assert asdict(p) == before
    assert not r.errors and len(r.reducers) == 2
    entry, exit_ = r.reducers
    assert entry.ports == (("G","2","male"),("G","1 1/4","male"))
    assert exit_.ports == entry.ports[::-1]
    assert entry.joints_confirmed == (False,True)
    assert exit_.joints_confirmed == (True,False)
    assert all(c.part and not c.ports_confirmed and c.installed_length_mm is None for c in r.reducers)
    assert all(any("Тройник обводной" in s for s in c.pending) for c in r.reducers)
    state = drawing_state(p)
    chain = build_metering_chain(p.metering_detail,state,r)
    assert chain.node("reducer_in").catalogue_id == chain.node("reducer_out").catalogue_id == ID
    assert not chain.installation_complete and r.assembly_length_mm is None


def test_no_bypass_checks_actual_inlet_valve_but_does_not_skip_service_tee():
    entry, exit_ = check_direct(bypass=False)
    assert entry.ports_confirmed and entry.joints_confirmed == (True,True)
    assert exit_.joints_confirmed == (True,False) and not exit_.ports_confirmed
    assert exit_.neighbours[1] == "Узел контрольного отбора"


@pytest.mark.parametrize("changes,expected", [
    ({"thread":"1"},"размер резьбы"),
    ({"connection_standard":"NPT"},"стандарт/размер"),
    ({"connection_sex":"male"},"две наружные"),
])
def test_both_meter_valve_joints_revalidated(changes, expected):
    c = get_metering_catalogue()
    valve = replace(c.products["valtec-vt214-dn32"],**changes)
    results = check_direct(products={"meter_valves":valve})
    assert all(r.part is None and any(expected in s for s in r.errors) for r in results)


def test_inlet_joint_is_checked_only_when_physically_adjacent():
    c = get_metering_catalogue()
    products = {"inlet_valve":replace(c.products["valtec-vt214-dn50"],connection_sex="male"),
                "meter_valves":c.products["valtec-vt214-dn32"]}
    assert not check_direct(products=products,bypass=True)[0].errors
    assert check_direct(products=products,bypass=False)[0].errors


@pytest.mark.parametrize("products", [{}, {"meter_valves":None}])
def test_unknown_neighbour_is_not_assumed_a_female_thread(products):
    results = check_direct(products=products)
    assert all(not r.ports_confirmed and not any(r.joints_confirmed) for r in results)


def test_same_dn_keeps_error_without_drawing_or_auto_substitution():
    p = catalogue_review_project()
    p.metering_detail.inlet_dn = 32
    results = check_direct(p)
    assert all(r.part is None and any("DN одинаковы" in s for s in r.errors) for r in results)
    state = drawing_state(p)
    chain = build_metering_chain(p.metering_detail,state,resolve(p))
    assert not any(n.id.startswith("reducer") for n in chain.nodes)
    assert 'data-reducer-role=' not in build_metering_detail_pages(p)[0]


@pytest.mark.parametrize("inlet_dn,meter_dn", [(40,32),(50,25),(32,25)])
def test_stale_selection_rejected_when_current_dn_changes(inlet_dn,meter_dn):
    p = catalogue_review_project()
    p.metering_detail.inlet_dn = inlet_dn
    assert all(r.part is None and r.errors for r in check_direct(p,meter_dn=meter_dn))


def test_unknown_current_dn_is_pending_not_default_50_or_32():
    p = catalogue_review_project()
    p.metering_detail.inlet_dn = None
    assert all(r.part is None and not r.assignment_confirmed for r in check_direct(p))
    assert all(r.part is None for r in check_direct(meter_dn=None))


def test_reducer_orientation_follows_current_dn_not_fixed_left_right_shape():
    from app.pz.metering_detail import _assembly
    p = catalogue_review_project()
    p.metering_detail.inlet_dn = 32
    catalog = get_metering_catalogue()
    products = {"meter_valves":catalog.products["valtec-vt214-dn50"]}
    entry, exit_ = check_direct(p,products=products,meter_dn=50)
    assert entry.ports == (("G","1 1/4","male"),("G","2","male"))
    assert exit_.ports == entry.ports[::-1]
    assert entry.joints_confirmed == (False,True) and exit_.joints_confirmed == (True,False)
    state = drawing_state(p)
    state = replace(state,meter=replace(state.meter,dn=50))
    svg = _assembly(p,state)
    assert 'd="M79,83 L85,81 V85 L79,83 Z"' in svg
    assert 'd="M225,81 L231,83 V83 L225,85 Z"' in svg


def test_bad_reducer_alone_reaches_composition_gate():
    from app.pz.commission import build_commission_report
    p = review_project()
    p.metering_detail.catalogue_revision = get_metering_catalogue().revision
    p.metering_detail.reducer_items = {"reducer_in":"missing"}
    assert not p.metering_detail.catalogue_items and not p.metering_detail.pipe_sections
    state = drawing_state(p)
    rules = evaluate_metering_rules(p,state.meter,inputs_count=state.inputs_count,bypass=state.bypass)
    assert any(r.code == "VU-CATALOGUE" and r.status == "error" for r in rules)
    gate = next(c for c in build_commission_report(p).checks if c.code == "VU-COMPOSITION")
    assert gate.blocking and gate.status == "fail" and "VU-CATALOGUE" in gate.result


def test_no_choice_no_new_error_or_part_in_stage_p():
    p = review_project()
    assert resolve(p).reducers == ()
    assert not any('data-meter-reducers' in s for s in build_metering_detail_pages(p))


@pytest.mark.parametrize("update,expected", [
    ({"catalogue_revision":"old"},"Редакция каталога"),
    ({"reducer_items":{"reducer_in":"missing"}},"Неизвестный переход"),
    ({"design_pressure_bar":26},"выше PN"),
    ({"water_temperature_c":251},"вне паспортного"),
    ({"water_temperature_c":-41},"вне паспортного"),
])
def test_invalid_choices_reach_release_validation(update,expected):
    p = catalogue_review_project()
    for k,v in update.items():
        setattr(p.metering_detail,k,v)
    assert any(expected in e for e in resolve(p).errors)
    state = drawing_state(p)
    report = evaluate_metering_rules(p,state.meter,inputs_count=state.inputs_count,bypass=state.bypass)
    assert any(r.code == "VU-CATALOGUE" and r.status == "error" for r in report)


def test_conflicted_dimension_is_rejected():
    c = get_metering_catalogue()
    altered = replace(c,reducers={ID:replace(c.reducers[ID],dimension_status="conflict")})
    assert all(r.part is None and r.errors for r in check_direct(catalog=altered))


def test_exact_pressure_temperature_and_no_silent_interpolation():
    p = catalogue_review_project()
    p.metering_detail.water_temperature_c = 200
    p.metering_detail.design_pressure_bar = 21
    assert all(any("при заданной температуре" in e for e in r.errors) for r in check_direct(p))
    p.metering_detail.design_pressure_bar = 20
    assert all(not r.errors for r in check_direct(p))
    p.metering_detail.water_temperature_c = 175
    assert all(any("интерполяция не выполнялась" in s for s in r.pending) for r in check_direct(p))


def test_double_assignment_at_c3_is_not_ignored():
    p = catalogue_review_project()
    p.metering_detail.connection_items["meter_valve_out"] = "proaqua-pa22524p"
    r = check_direct(p)[1]
    assert r.part is None and any("одновременно" in e for e in r.errors)


@pytest.mark.parametrize("items", [None,[],{"foo":ID},{"reducer_in":True},{"reducer_out":" "}])
def test_invalid_payload(items):
    assert MeteringDetailData(reducer_items=items).validate()


def test_yaml_roundtrip_and_project_independence():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  catalogue_revision: '2026-09-30.5'
  reducer_items: {reducer_in: valtec-vtr580-0907, reducer_out: valtec-vtr580-0907}
''')
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    p.metering_detail.reducer_items.clear()
    assert len(req.metering_detail.reducer_items) == 2


def test_pdf_marks_sources_readable_sizes_and_no_hydraulic_mutation():
    p = catalogue_review_project()
    before = deepcopy(asdict(p))
    pages = build_metering_detail_pages(p)
    assert asdict(p) == before
    assert 'data-reducer-role="reducer_in"' in pages[0]
    assert 'data-reducer-role="reducer_out"' in pages[0]
    sheets = [s for s in pages if 'data-meter-reducers' in s]
    assert sheets
    text = ''.join(sheets)
    assert "VTr.580.N.0907" in text and "41 мм" in text
    assert "монтажной длине" in text and "Поперечный габарит не подтверждён" in text
    for svg in sheets:
        for e in ET.fromstring(svg).iter():
            if not e.tag.endswith("text") or e.get("data-text-height-mm") is None:
                continue
            x,y = float(e.get("x")),float(e.get("y"))
            if y < 230:
                assert y <= 227
                assert x+_label_width(e.text or "",float(e.get("data-text-height-mm"))) <= 412

from copy import deepcopy
from dataclasses import asdict, replace
from types import MappingProxyType
import xml.etree.ElementTree as ET

import pytest
import cairosvg
import pymupdf

from tests.graphic_text_bounds import assert_graphic_text_bounds

from app.data.metering_products import get_metering_catalogue
from app.pz.metering_connections import check_connections
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_product_selection import resolve_metering_products
from app.intake.yaml_io import load_request, dump_request, YamlFormatError
from app.intake.project_builder import build_project
from scripts.preview_metering_detail import review_project, mixed_pipe_sections, catalogue_review_project


def project():
    p = review_project()
    d = p.metering_detail
    d.pipe_sections = mixed_pipe_sections()
    d.catalogue_revision = get_metering_catalogue().revision
    d.catalogue_items = {"check_valve": "itap-europa100-g-dn50"}
    d.connection_items = {"check_valve_out": "valtec-vtp761-06309"}
    d.design_pressure_bar, d.water_temperature_c = 6, 25
    return p


def resolve(p):
    state = drawing_state(p)
    return resolve_metering_products(p, state.meter, bypass=state.bypass,
                                    electric_bypass=state.electric_bypass)


def test_real_sources_conflicts_and_no_guess_of_installed_length():
    c = get_metering_catalogue()
    assert c.revision == "2026-09-30.5"
    assert len(c.connectors) == 3
    for ident in ("valtec-vtp707-06309", "valtec-vtp761-06309"):
        part = c.connectors[ident]
        assert part.dimension_status == "conflict" and part.body_length_mm is None
        assert part.dimensions_mm["passport_L"] != part.dimensions_mm["drawing_L"]
        assert all(c.sources[s]["sha256"] for s in part.source_ids)
        with pytest.raises(TypeError):
            part.dimensions_mm["L"] = 1
    r = resolve(project())
    assert r.connections[0].connector is None
    assert r.connections[0].installed_length_mm is None
    assert r.assembly_length_mm is None
    assert any("Конфликт габаритов" in e for e in r.errors)


def test_itap_g_articles_dimensions_and_quarantine_is_not_removed():
    c = get_metering_catalogue()
    part = c.products["itap-europa100-g-dn50"]
    assert (part.article, part.body_length_mm, part.thread) == ("1000200", 101, "2")
    assert part.connection_standard == "G" and part.connection_sex == "female"
    assert part.pn_bar == 18 and part.temperature_c == (-20,100)
    assert c.products["valtec-vt161-dn50"].body_length_mm is None
    assert resolve(project()).selected("check_valve") == part


@pytest.mark.parametrize("changes, expected", [
    ({"material":"pe"}, "Материал трубы"),
    ({"material":"steel"}, "Материал трубы"),
    ({"outer_diameter_mm":50}, "Наружный диаметр"),
    ({"joining":"press"}, "Способ соединения"),
])
def test_changing_pipe_invalidates_saved_connector(changes, expected):
    p = project()
    p.metering_detail.pipe_sections["outlet"] = replace(p.metering_detail.pipe_sections["outlet"], **changes)
    assert any(expected in e for e in resolve(p).errors)


@pytest.mark.parametrize("changes, expected", [
    ({"system_id":""}, "Трубная система не указана"),
    ({"system_id":"other_ppr"}, "Другая трубная система"),
    ({"wall_thickness_mm":None}, "Подтвердить серию"),
    ({"material":"unknown"}, "Материал трубы не задан"),
    ({"outer_diameter_mm":None}, "Наружный диаметр трубы не задан"),
])
def test_missing_or_different_system_does_not_get_a_green_fit(changes, expected):
    p = project()
    p.metering_detail.pipe_sections["outlet"] = replace(p.metering_detail.pipe_sections["outlet"], **changes)
    check = resolve(p).connections[0]
    assert check.connector is None
    assert any(expected in s for s in check.pending)


def test_both_ports_are_checked_even_for_unverified_geometry():
    p = project()
    c = get_metering_catalogue()
    # Pure validator fixtures, NOT catalogue approvals or real model mutations.
    valve = c.products["itap-europa100-g-dn50"]
    for changes, expected in [({"thread":"1"}, "Стандарт/размер"),
                              ({"connection_standard":"NPT"}, "Стандарт/размер"),
                              ({"connection_sex":"male"}, "Одинаковое направление")]:
        result = check_connections(p.metering_detail,c,{"check_valve":replace(valve, **changes)},
                                   bypass=True,revision_ok=True)[0]
        assert any(expected in e for e in result.errors)


def test_verified_fixture_checks_ports_without_inventing_installation_depths():
    p = project()
    c = get_metering_catalogue()
    candidate = c.connectors["valtec-vtp761-06309"]
    # Synthetic future-catalogue fixture. Actual VALTEC remains quarantined.
    part = replace(candidate, dimension_status="verified", dimensions_mm={"L":85,"socket_depth":27})
    fixture = replace(c, connectors={part.id:part})
    result = check_connections(p.metering_detail, fixture,
        {"check_valve":c.products["itap-europa100-g-dn50"]}, bypass=True,revision_ok=True)[0]
    assert not result.errors and result.ports_confirmed and result.connector == part
    assert result.pending and result.installed_length_mm is None
    p.metering_detail.pipe_sections.pop("outlet")
    result = check_connections(p.metering_detail,fixture,
        {"check_valve":c.products["itap-europa100-g-dn50"]},bypass=True,revision_ok=True)[0]
    assert result.connector is None and not result.ports_confirmed


@pytest.mark.parametrize("pressure, temperature, expected", [(26,25,"Давление"),(6,96,"Температура")])
def test_known_pressure_temperature_violation_is_not_hidden(pressure,temperature,expected):
    p = project()
    p.metering_detail.design_pressure_bar = pressure
    p.metering_detail.water_temperature_c = temperature
    assert any(expected in e for e in resolve(p).connections[0].errors)


def test_missing_product_revision_and_unknown_connector_do_not_fallback():
    p = project()
    p.metering_detail.catalogue_items = {}
    assert any("арматура не выбрана" in s for s in resolve(p).connections[0].pending)
    p.metering_detail.catalogue_revision = "2026-09-30.2"
    assert any("Редакция" in e for e in resolve(p).errors)
    p.metering_detail.connection_items["check_valve_out"] = "not-in-catalogue"
    assert any("Неизвестный соединитель" in e for e in resolve(p).errors)


def test_connector_only_error_reaches_release_gate_and_inactive_bypass():
    from app.pz.commission import build_commission_report
    p = review_project(2)
    p.metering_detail.connection_items = {"bypass_valve_out":"valtec-vtp761-06309"}
    p.metering_detail.catalogue_revision = get_metering_catalogue().revision
    assert any("Обводной линии" in e for e in resolve(p).errors)
    gate = next(c for c in build_commission_report(p).checks if c.code == "VU-COMPOSITION")
    assert gate.blocking and gate.status == "fail" and "VU-CATALOGUE" in gate.result


@pytest.mark.parametrize("items", [None,[],{"oops":"x"},{"check_valve_out":True},{"check_valve_out":" "}])
def test_malformed_connection_input_fails_cleanly(items):
    assert MeteringDetailData(connection_items=items).validate()


def test_yaml_roundtrip_and_copied_mapping():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  catalogue_revision: '2026-09-30.3'
  connection_items: {check_valve_out: valtec-vtp761-06309}
  pipe_sections:
    outlet: {material: ppr, system_id: valtec_ppr, outer_diameter_mm: 63, wall_thickness_mm: 8.6}
''')
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    p.metering_detail.connection_items.clear()
    assert req.metering_detail.connection_items
    with pytest.raises(YamlFormatError):
        load_request(dump_request(req).replace("system_id: valtec_ppr", "system_id: false"))


def test_pdf_source_card_ports_and_conflict_do_not_mutate_hydraulics():
    p = project()
    before = deepcopy(asdict(p))
    pages = build_metering_detail_pages(p)
    assert asdict(p) == before
    assert drawing_state(p).meter.h_a == pytest.approx(1.573)
    assert 'data-connection-port="check_valve_out"' in pages[0]
    card = next(svg for svg in pages if 'data-meter-connections="true"' in svg)
    assert "ГАБАРИТ НЕ ПРИНЯТ" in card and "94,3" in card and "85,0" in card
    assert "не назначенная глубина посадки" in card
    for svg in pages:
        root = ET.fromstring(svg)
        assert root.get("width") == "420mm" and root.get("height") == "297mm"
        with pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf") as pdf:
            assert_graphic_text_bounds(pdf[0], 420, 297, "А3")
    assert not any('data-meter-connections' in s for s in build_metering_detail_pages(review_project()))


def test_real_composite_connection_both_ports_and_geometry_not_installation():
    p = catalogue_review_project()
    before = deepcopy(asdict(p))
    check = resolve(p).connections[0]
    assert check.ports_confirmed and not check.errors
    assert check.connector.article == "PA22524P"
    assert check.connector.body_length_mm == 77
    assert check.thread_adapter.article == "VTr.582.N.0009"
    assert check.thread_adapter.body_length_mm == 44
    assert p.metering_detail.pipe_sections["outlet"].inner_diameter_mm == 42
    assert any("Предельные P/T" in s for s in check.pending)
    assert check.installed_length_mm is None and resolve(p).assembly_length_mm is None
    assert asdict(p) == before
    assert drawing_state(p).meter.h_a == pytest.approx(1.573)


def test_female_socket_does_not_join_female_valve_without_explicit_nipple():
    p = catalogue_review_project()
    p.metering_detail.connection_thread_items.clear()
    check = resolve(p).connections[0]
    assert not check.ports_confirmed and check.connector is None
    assert any("Одинаковое направление" in e for e in check.errors)


@pytest.mark.parametrize("change, expected", [
    ({"equipment_sex":"female"}, "стык 1"),
    ({"pipe_connector_sex":"female"}, "стык 2"),
    ({"equipment_thread":"1"}, "стык 1"),
    ({"pipe_connector_thread":"1"}, "стык 2"),
    ({"connection_standard":"NPT"}, "Стандарт/размер"),
    ({"dimension_status":"conflict"}, "Габариты промежуточного"),
])
def test_composite_connection_checks_each_side(change, expected):
    p, catalog = catalogue_review_project(), get_metering_catalogue()
    part = catalog.thread_connectors["valtec-vtr582-0009"]
    fixture = replace(catalog, thread_connectors={part.id:replace(part, **change)})
    check = check_connections(p.metering_detail, fixture,
        {"check_valve":catalog.products["itap-europa100-g-dn50"]}, bypass=True, revision_ok=True)[0]
    assert not check.ports_confirmed and check.connector is None
    assert any(expected in e for e in check.errors)


def test_unknown_or_orphan_intermediate_fitting_is_not_ignored():
    p = catalogue_review_project()
    p.metering_detail.connection_thread_items["check_valve_out"] = "unknown"
    assert any("Неизвестный промежуточный" in e for e in resolve(p).errors)
    p.metering_detail.connection_items.clear()
    assert any("без конечного" in e for e in p.metering_detail.validate())
    with pytest.raises(ValueError, match="без конечного"):
        drawing_state(p)


@pytest.mark.parametrize("pressure, temperature", [(26,25),(6,251),(6,-41)])
def test_intermediate_fitting_limits_invalidate_port_confirmation(pressure,temperature):
    p, catalog = catalogue_review_project(), get_metering_catalogue()
    p.metering_detail.design_pressure_bar = pressure
    p.metering_detail.water_temperature_c = temperature
    check = check_connections(p.metering_detail,catalog,
        {"check_valve":catalog.products["itap-europa100-g-dn50"]},bypass=True,revision_ok=True)[0]
    assert check.errors and not check.ports_confirmed and check.connector is None


def test_unknown_gender_does_not_confirm_connection():
    p, catalog = catalogue_review_project(), get_metering_catalogue()
    check = check_connections(p.metering_detail,catalog,
        {"check_valve":replace(catalog.products["itap-europa100-g-dn50"],connection_sex="unknown")},
        bypass=True,revision_ok=True)[0]
    assert not check.ports_confirmed and any("направление резьбы" in s for s in check.pending)


@pytest.mark.parametrize("items", [None, [], {"other":"x"}, {"check_valve_out":True}])
def test_invalid_thread_connector_input(items):
    assert MeteringDetailData(connection_thread_items=items).validate()


def test_composite_roundtrip_keeps_intermediate_choice_and_isolation():
    req = load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  catalogue_revision: '2026-09-30.4'
  connection_items: {check_valve_out: proaqua-pa22524p}
  connection_thread_items: {check_valve_out: valtec-vtr582-0009}
''')
    assert load_request(dump_request(req)) == req
    p = build_project(req)
    p.metering_detail.connection_thread_items.clear()
    assert req.metering_detail.connection_thread_items


def test_composite_card_is_traceable_and_honest_about_unconfirmed_dimensions():
    p = catalogue_review_project()
    cards = [s for s in build_metering_detail_pages(p) if 'data-meter-connections="true"' in s]
    text = ''.join(cards)
    assert "PA22524P" in text and "VTr.582.N.0009" in text
    assert "77,0" in text and "44,0" in text
    assert "Порты" in text and "Предельные P/T" in text
    assert "ГАБАРИТ НЕ ПРИНЯТ" not in text
    assert "монтажная длина" in text.lower()

"""Every active VU component has one SO owner; counts are not CAD lengths."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.pz.generator import generate_spec_html, generate_wastewater_spec_html
from app.pz.metering_chain import build_metering_chain
from app.pz.metering_detail import drawing_state, build_metering_detail_pages
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.metering_spec import build_metering_spec_section
from app.pz.spec import build_water_specification, format_spec_qty
from scripts.preview_metering_detail import catalogue_review_project, review_project


def row_for(section, node):
    return next(r for r in section.rows if node in r.component_ids)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_all_graph_nodes_once_and_quantities_follow_actual_inlets(count):
    project = review_project(count)
    before = deepcopy(asdict(project))
    state = drawing_state(project)
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                         electric_bypass=state.electric_bypass)
    chain = build_metering_chain(project.metering_detail, state, selection)
    section = build_metering_spec_section(project)
    assert Counter(n for r in section.rows for n in r.component_ids) == Counter(n.id for n in chain.nodes)
    assert row_for(section, "meter").qty == count
    assert row_for(section, "inlet_valve").qty == count
    assert row_for(section, "valve_before").qty == 2 * count
    assert row_for(section, "control_cap_1").qty == 2 * count
    assert row_for(section, "control_cock_1").qty == 2 * count
    assert row_for(section, "gauge_cock").qty == row_for(section, "gauge").qty == count
    assert row_for(section, "kit_in").qty == count
    assert asdict(project) == before


def test_network_inlets_are_authoritative_and_count_conflict_stays_visible():
    project = review_project()
    project.v1_network = SimpleNamespace(inlets=[object(), object()])
    assert row_for(build_metering_spec_section(project), "meter").qty == 2
    assert any("Число вводов" in s for s in drawing_state(project).missing)


def test_catalogue_models_kit_and_two_reducers_without_double_counting():
    section = build_metering_spec_section(catalogue_review_project())
    meter = row_for(section, "meter")
    assert meter.catalogue_id == "decast-vskm90-dg-dn32" and meter.qty == 1
    assert "ВСХН" not in meter.type_mark
    kit = row_for(section, "kit_in")
    assert kit is row_for(section, "kit_out") and kit.unit == "компл." and kit.qty == 1
    assert "без счётчика" in kit.name and kit.catalogue_id == "decast-vskm90-kit-dn32"
    reducers = [r for r in section.rows if r.catalogue_id == "valtec-vtr580-0907"]
    assert [r.diagram_pos for r in reducers] == ["П1", "П2"]
    assert sum(r.qty for r in reducers) == 2
    assert all(r.code == "" for r in section.rows)  # article is not a classifier code


def test_bypass_uses_own_dn_not_meter_dn_and_disappears_only_with_branch():
    project = catalogue_review_project()
    section = build_metering_spec_section(project)
    assert row_for(section, "bypass_valve").name.endswith("DN50")
    assert row_for(section, "bypass_start").qty == 2
    project.meters.has_bypass = False
    section = build_metering_spec_section(project)
    assert not any("bypass" in n for r in section.rows for n in r.component_ids)
    assert not any(r.diagram_pos == "6" for r in section.rows)


def test_fire_branch_is_counted_only_when_current_scheme_contains_it():
    project = review_project(2)
    section = build_metering_spec_section(project)
    assert row_for(section, "fire_valve").qty == 2
    assert "С электроприводом" in row_for(section, "fire_valve").note
    project.fire.required = False
    assert not any("fire" in n for r in build_metering_spec_section(project).rows for n in r.component_ids)


@pytest.mark.parametrize("mutation", ["old_revision", "wrong_dn", "unknown_model", "wrong_material"])
def test_stale_or_invalid_product_is_not_reported_as_accepted(mutation):
    project = catalogue_review_project()
    d = project.metering_detail
    if mutation == "old_revision":
        d.catalogue_revision = "old"
        node = "meter"
    elif mutation == "wrong_dn":
        d.inlet_dn = 40
        node = "inlet_valve"
    elif mutation == "unknown_model":
        d.catalogue_items["meter"] = "missing"
        node = "meter"
    else:
        d.pipe_sections["outlet"] = replace(d.pipe_sections["outlet"], material="pe")
        node = "outlet_connector"
    row = row_for(build_metering_spec_section(project), node)
    assert row.qty == 1 and row.catalogue_id == "" and row.type_mark == ""
    assert "не подтвержден" in row.note.lower()


def test_same_dn_has_no_reducers_even_if_stale_ids_exist():
    project = catalogue_review_project()
    project.metering_detail.inlet_dn = 32
    assert not any(r.diagram_pos in ("П1", "П2") for r in build_metering_spec_section(project).rows)


def test_compound_c4_parts_each_counted_once():
    section = build_metering_spec_section(catalogue_review_project())
    a, b = row_for(section, "outlet_thread"), row_for(section, "outlet_connector")
    assert (a.catalogue_id, b.catalogue_id) == ("valtec-vtr582-0009", "proaqua-pa22524p")
    assert a.qty == b.qty == 1 and a.diagram_pos == b.diagram_pos == "С4"


def test_all_named_connections_in_active_paths_and_no_inactive_bypass_parts():
    project = catalogue_review_project()
    for role in ("inlet_valve_in", "filter_in", "meter_valve_out", "bypass_valve_in", "bypass_valve_out"):
        project.metering_detail.connection_items[role] = "missing"
        project.metering_detail.connection_thread_items[role] = "missing"
    rows = build_metering_spec_section(project).rows
    for mark in ("С1", "С2", "С3", "С4", "С5", "С6"):
        assert sum(r.qty for r in rows if r.diagram_pos == mark) == 2
    project.meters.has_bypass = False
    assert not any(r.diagram_pos in ("С5", "С6") for r in build_metering_spec_section(project).rows)


def test_unknown_geometry_never_yields_fake_dn_lengths_or_one_stand():
    project = review_project()
    project.metering_detail.inlet_dn = None
    project.meters.rows = [replace(project.meters.rows[0], label="Квартирный ХВС")]
    section = build_metering_spec_section(project)
    assert "DN уточнить" in row_for(section, "meter").name
    assert "DN уточнить" in row_for(section, "inlet_valve").name
    assert all(r.qty is None for r in section.rows if r.unit in ("м", "кг"))
    assert next(r for r in section.rows if "Опоры и крепления" in r.name).qty is None
    assert all("Подставка" not in r.name for r in section.rows)


def test_vu_pipe_materials_are_local_not_global_or_body_lengths():
    project = catalogue_review_project()
    section = build_metering_spec_section(project)
    assert "Сталь" in row_for(section, "inlet").type_mark
    assert "Ø60×3,5" in row_for(section, "inlet").type_mark
    assert "PP-R" in row_for(section, "outlet").type_mark
    assert "Ø63×10,5" in row_for(section, "outlet").type_mark
    assert all(r.qty is None for r in section.rows if r.unit == "м")


def test_so_subsection_has_single_owner_for_common_meter_and_instruments():
    project = catalogue_review_project()
    specification = build_water_specification(project)
    vu = next(s for s in specification.sections if "Водомерный узел" in s.title)
    general = next(s for s in specification.sections if s.title.startswith("В1"))
    assert general is not vu
    assert not any("водомерного узла" in r.name or "Счётчик" in r.name or "Манометр" in r.name for r in general.rows)
    for r in vu.rows:
        if r.qty is not None:
            assert "," not in format_spec_qty(r.qty, r.unit)
    html = generate_spec_html(project)
    assert "В1 — Водомерный узел" in html and 'class="c">1.1</td>' in html
    assert "PA22524P" in html and "VTr.580.N.0907" in html


def test_drawing_and_specification_share_graphic_references():
    project = catalogue_review_project()
    svg = build_metering_detail_pages(project)[0]
    section = build_metering_spec_section(project)
    for row in section.rows:
        if row.diagram_pos != "—":
            assert row.diagram_pos in svg


def test_wastewater_export_does_not_build_vu(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("VU composition must not enter IOS3")
    monkeypatch.setattr("app.pz.metering_spec.build_metering_spec_section", unexpected)
    assert "Водомерный узел" not in generate_wastewater_spec_html(review_project())

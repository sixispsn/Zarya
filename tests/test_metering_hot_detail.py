"""The hot branch owns its graph/SO; cold geometry and fire do not leak in."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict

import pytest

from app.intake.studio_metering import layout_summary
from app.pz.metering_detail import build_metering_detail_pages, drawing_state
from app.pz.metering_hot_node import hot_meter_view, hot_spec_section, hot_detail_contents
from app.pz.metering_layout import build_metering_layout
from app.pz.metering_product_selection import resolve_metering_products
from app.pz.spec import build_water_specification
from tests.test_studio_metering_nodes import project
from tests.test_studio_apartment_meters import draft


@pytest.mark.parametrize('axis', ['horizontal_dial_up', 'vertical_up', 'vertical_down'])
@pytest.mark.parametrize('heater', ['yes', 'no'])
def test_separate_node_keeps_real_calculation_and_orientation(axis, heater, tmp_path):
    p = project(draft(vu_hot_orientation=axis, hws_heater_in_scope=heater), tmp_path)
    before = deepcopy(asdict(p))
    v = hot_meter_view(p); state = drawing_state(v); layout = build_metering_layout(v)
    assert state.node_key == 'hot' and state.inputs_count == 1
    assert state.meter is v.node_meter
    assert not state.bypass and not state.electric_bypass and not state.fire_branch
    assert v.node_system == ('В1' if heater == 'yes' else 'Т3')
    assert layout.parts and not layout.issues and layout.orientation == axis
    assert layout.part('meter').mark == 'Г.7'
    assert not any(part.id in ('inlet_valve', 'fire_takeoff', 'bypass_valve') for part in layout.parts)
    assert v.flows is p.flows  # never fake cold demand to reuse the renderer
    assert layout_summary(p)['hot_drawing']['available']
    assert hot_detail_contents(p) and any('data-meter-hot-node=' in s for s in build_metering_detail_pages(p))
    assert asdict(p) == before


def test_primary_inlet_inputs_do_not_become_hot_branch_geometry(tmp_path):
    p = project(draft(inputs_count=2, vu_orientation='vertical_up',
                      vu_hot_orientation='horizontal_dial_up',
                      vu_filter_layout='valtec_vt192_vtr090'), tmp_path)
    d = p.metering_detail
    d.inlet_dn = 100; d.room_number = '101'; d.water_temperature_c = 5
    d.design_pressure_bar = 16; d.mounting.support_count = 4; d.mounting.support_basis = 'КР ввода'
    d.catalogue_items['filter'] = 'valtec-vt192-dn100'
    v = hot_meter_view(p); branch = v.metering_detail
    assert branch.inlet_dn is None and branch.room_number == ''
    assert branch.water_temperature_c is None and branch.design_pressure_bar is None
    assert not branch.catalogue_items and not branch.filter_offset_family
    assert not branch.flexible_connections and not branch.mounting.pipe_cuts
    assert branch.mounting.support_count is None
    layout = build_metering_layout(v)
    rows = hot_spec_section(p).rows
    assert Counter(n for r in rows for n in r.component_ids) == Counter('hot:'+x.id for x in layout.parts)
    assert next(r for r in rows if 'hot:meter' in r.component_ids).qty == 1
    assert next(r for r in rows if 'hot:kit_in' in r.component_ids).qty == 1
    assert next(r for r in rows if 'hot:valve_before' in r.component_ids).qty == 2


def test_full_spec_has_one_owner_and_no_old_hot_filter_or_meter_duplicate(tmp_path):
    p = project(draft(), tmp_path)
    spec = build_water_specification(p)
    rows = [r for s in spec.sections for r in s.rows]
    ids = [ident for r in rows for ident in r.component_ids]
    assert ids.count('hot:meter') == ids.count('hot:kit_in') == ids.count('hot:filter') == 1
    assert 'meter_hot' not in ids and 'meter_hot_kit' not in ids
    assert not any(r.name == 'Фильтр узла учёта ГВС' for r in rows)
    assert next(r for r in rows if 'hot:meter' in r.component_ids).diagram_pos == 'Г.7'
    kit = next(r for r in rows if 'hot:kit_in' in r.component_ids)
    assert 'К поз. Г.7;' in kit.note and 'К поз. 7;' not in kit.note
    service = next(r for r in rows if 'hot:service_before' in r.component_ids)
    assert 'К поз. Г.3.1, Г.3.2 и Г.4.1;' in service.note
    service_after = next(r for r in rows if 'hot:service_after' in r.component_ids)
    assert 'К поз. Г.4.1;' in service_after.note
    cold = next(r for r in rows if 'kit_in' in r.component_ids)
    assert 'К поз. 7;' in cold.note and 'Г.7' not in cold.note


def test_hot_flow_not_cold_flow_is_checked_against_catalogue(tmp_path):
    p = project(draft(), tmp_path)
    p.flows.q_sec_c = 100  # must not reject the hot model
    v = hot_meter_view(p); state = drawing_state(v)
    assert resolve_metering_products(v,state.meter,bypass=False,electric_bypass=False).selected('meter')
    p.flows.q_sec_h = 100
    assert not resolve_metering_products(v,state.meter,bypass=False,electric_bypass=False).selected('meter')


def test_hot_orientation_change_does_not_touch_primary_layout(tmp_path):
    p = project(draft(), tmp_path)
    before = build_metering_layout(p)
    p.metering_detail.meter_orientations['hot'] = 'vertical_up'
    assert build_metering_layout(p) == before
    assert build_metering_layout(hot_meter_view(p)).orientation == 'vertical_up'


def test_hot_release_gate_rejects_contradiction_not_missing_mounting_mm(tmp_path):
    from app.pz.commission import build_commission_report
    p = project(draft(), tmp_path)
    def check():
        return next(c for c in build_commission_report(p).checks if c.code == 'VU-HOT-COMPOSITION')
    assert not check().blocking  # unknown hot pipe DN/room is not a false contradiction
    p.metering_detail.meter_products['hot'] = 'missing'
    assert check().blocking and check().status == 'fail'


def test_absent_hot_meter_generates_no_hot_equipment(tmp_path):
    p = project(draft(hws_type='none'), tmp_path)
    assert hot_meter_view(p) is None and hot_spec_section(p) is None
    assert hot_detail_contents(p) == []
    assert not any('data-meter-hot-node=' in s for s in build_metering_detail_pages(p))


@pytest.mark.parametrize('axis', ['horizontal_dial_up','vertical_down'])
def test_bad_hot_model_does_not_fall_back_to_cold_meter(axis, tmp_path):
    p = project(draft(vu_hot_orientation=axis), tmp_path)
    p.metering_detail.meter_products['hot'] = 'missing'
    layout = build_metering_layout(hot_meter_view(p))
    assert not layout.parts and layout.issues
    assert not next(r for r in hot_spec_section(p).rows if 'hot:meter' in r.component_ids).catalogue_id


def test_no_saved_hot_dn_is_not_rendered_as_a_successful_node(tmp_path):
    p = project(draft(), tmp_path)
    hot_meter_view(p).node_meter.dn = 0
    assert not build_metering_layout(hot_meter_view(p)).parts


@pytest.mark.parametrize('axis', ['vertical_up','vertical_down'])
def test_prefixed_horizontal_labels_do_not_overlap(axis, tmp_path):
    from xml.etree import ElementTree as ET
    from app.pz.metering_vertical_drawing import vertical_contents
    v = hot_meter_view(project(draft(vu_hot_orientation=axis), tmp_path))
    svg = vertical_contents(v,drawing_state(v),build_metering_layout(v))
    groups = ET.fromstring('<svg>'+svg+'</svg>').findall('.//*[@data-horizontal-mark]')
    rows = {}
    for g in groups:
        rows.setdefault(g.attrib['data-label-row'],[]).append((float(g.attrib['data-label-left']),float(g.attrib['data-label-right'])))
    for intervals in rows.values():
        ordered = sorted(intervals)
        assert all(a[1]+2.9 <= b[0] for a,b in zip(ordered,ordered[1:]))


def test_actual_meter_body_length_is_preserved_at_paper_scale(tmp_path):
    p = project(draft(residents=200, apartments=80, vu_drawing_scale='10'), tmp_path)
    part = build_metering_layout(hot_meter_view(p)).part('meter')
    assert part.length_mm == 260
    from math import dist
    assert dist(part.points[0], part.points[-1]) == pytest.approx(26)


def test_pdf_has_separate_hot_pages_bookmarks_and_a3_frame(tmp_path):
    from app.pz.generator import generate_metering_scheme_pdf
    from pypdf import PdfReader
    p = project(draft(), tmp_path)
    path = tmp_path/'meters.pdf'
    generate_metering_scheme_pdf(p, str(path))
    reader = PdfReader(path)
    assert len(reader.pages) == len(build_metering_detail_pages(p))
    assert any('ВУ-Г.' in str(item) for item in reader.outline)
    assert all(float(page.mediabox.width)*25.4/72 == pytest.approx(420,abs=.01) for page in reader.pages)

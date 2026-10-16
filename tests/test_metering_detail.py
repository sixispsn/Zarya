from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from pypdf import PdfReader

from app.intake.yaml_io import load_request, dump_request, YamlFormatError
from app.intake.project_builder import build_project
from app.pz.aux_schemes import build_metering_scheme_svg
from app.pz.generator import generate_metering_scheme_pdf
from app.pz.metering_detail import build_metering_detail_pages, drawing_state
from app.pz.metering_detail_data import MeteringDetailData
from app.pz.project import Project
from scripts.preview_metering_detail import review_project


def test_calculated_dn_losses_and_catalog_data_are_displayed_without_mutation():
    p = review_project()
    before = deepcopy(asdict(p))
    svg = build_metering_scheme_svg(p)
    assert "DN32" in svg
    assert "1,573" in svg
    assert "10,000" in svg
    assert "0,100" in svg
    assert "Паспортный Qmin не подтверждён" in svg
    assert asdict(p) == before


def test_one_inlet_manual_bypass_is_not_an_automatic_electric_valve():
    p = review_project()
    state = drawing_state(p)
    assert state.bypass and not state.electric_bypass
    svg = build_metering_scheme_svg(p)
    assert 'data-bypass="true"' in svg
    assert "Ручная арматура" in svg
    assert "Электропривод" not in svg


def test_two_inlets_and_fire_branches_before_the_meters_without_bypass():
    p = review_project(2)
    svg = build_metering_scheme_svg(p)
    assert 'data-bypass="true"' not in svg
    assert svg.count('data-pre-meter-fire="true"') == 2
    root = ET.fromstring(svg)
    crossings = [e for e in root.iter() if e.get('data-wall-crossing')]
    assert len(crossings) == 2
    assert all(float(e.get('x1')) < 65 < 71 < float(e.get('x2')) for e in crossings)
    assert "задвижка с электроприводом" in svg


@pytest.mark.parametrize("topology", ["separate", "combined"])
def test_separate_and_combined_are_not_pre_meter_branches(topology):
    p = review_project(2)
    p.fire.network_topology = topology
    p.materials.cold_is_plastic_uncertified = False
    svg = build_metering_scheme_svg(p)
    assert 'data-pre-meter-fire="true"' not in svg
    assert ("К сети В1+В2" in svg) == (topology == "combined")


def test_fire_bypass_electric_drive_only_when_selected_row_requires_it():
    p = review_project()
    drawing_state(p).meter.need_bypass = True
    assert drawing_state(p).electric_bypass
    assert "Электропривод" in build_metering_scheme_svg(p)


def test_missing_data_never_becomes_dn100_or_a_room_or_a_meter():
    p = Project()
    svg = build_metering_scheme_svg(p)
    assert "DN100" not in svg and "DN50" not in svg
    assert "Подбор отсутствует" in svg
    assert "DN трубопровода ввода не задан" in svg
    assert "номер помещения" in svg
    assert 'data-meter-transition="true"' not in svg


def test_total_inlet_meter_takes_precedence_over_hot_and_cold_rows():
    p = review_project()
    inlet = deepcopy(p.meters.rows[0])
    inlet.label = "Счётчик на вводе (общий)"
    p.meters.rows.append(inlet)
    assert drawing_state(p).meter is inlet
    p.meters.rows = [p.meters.rows[1]]  # Hot meter is not the inlet.
    assert drawing_state(p).meter is None


def test_ambiguous_and_failed_selection_are_not_rendered_as_selected():
    p = review_project()
    p.meters.rows.append(deepcopy(p.meters.rows[0]))
    assert drawing_state(p).meter is None
    p = review_project()
    p.meters.selection_error = "Расход вне каталога"
    assert drawing_state(p).meter is None
    p.meters.selection_error = ""
    p.flows.q_day_c = 50000
    assert drawing_state(p).meter is None


def test_minimum_flow_failure_is_not_shown_as_success():
    p = review_project()
    drawing_state(p).meter.ok_v = False
    assert "Проверка малых расходов не пройдена" in build_metering_scheme_svg(p)


def test_inlet_elevation_comes_only_from_explicit_drawing_data():
    p = review_project()
    p.metering_detail.inlet_elevation_m = None
    p.source.elev_header_m = -9.99
    assert "Ось:" not in build_metering_scheme_svg(p)
    p.metering_detail.inlet_elevation_m = -.5
    assert "Ось: -0,50" in build_metering_scheme_svg(p)


def test_multiple_inlets_paginate_and_use_network_count():
    p = review_project(2)
    p.v1_network = SimpleNamespace(inlets=[object()] * 5)
    pages = build_metering_detail_pages(p)
    schematic = [s for s in pages if 'data-meter-detail=' in s]
    assert len(schematic) == 3
    assert any('data-meter-rules=' in s for s in pages)
    assert 'data-inlet="5"' in pages[2]
    assert 'data-inlet="6"' not in pages[2]
    assert "Число вводов расходится с расчётом водомеров" in pages[0]


def test_leaders_have_physical_font_height_arrow_and_thin_horizontal_shelf():
    root = ET.fromstring(build_metering_scheme_svg(review_project()))
    leaders = [e for e in root.iter() if e.get("data-leader-id")]
    assert len(leaders) == 3
    for element in leaders:
        assert element.get("data-text-height-mm") == "3.5"
        assert element.get("data-line-width-mm") == "0.25"
        assert element.get("data-title-above-shelf") == "true"
        assert element.get("data-detail-below-shelf") == "true"
        assert element.get("data-knee-y") == element.get("data-shelf-outer-y")
        assert any(e.get("data-leader-arrow") for e in element)


def test_drawing_metadata_yaml_roundtrip_and_builder():
    req = load_request('''
document: {object_name: Жилой дом}
building: {type: residential, floors: 2, height_m: 6.6}
fire: {height_m: 3.3}
metering_detail:
  room_number: '001'
  room_name: Водомерная
  inlet_dn: 50
  bypass_dn: 50
  inlet_elevation_m: -1.5
''')
    assert load_request(dump_request(req)) == req
    project = build_project(req)
    assert project.metering_detail == req.metering_detail
    assert project.metering_detail is not req.metering_detail


@pytest.mark.parametrize("bad", [0, -15, True, 50.5, "50"])
def test_invalid_dn_is_not_silently_coerced(bad):
    assert MeteringDetailData(inlet_dn=bad).validate()


def test_unknown_yaml_drawing_fields_rejected():
    with pytest.raises(YamlFormatError,match="metering_detail"):
        load_request('''
document: {}
building: {type: residential, floors: 2, height_m: 6.6}
metering_detail: {unknown: 50}
''')


def test_xml_escaping_and_dispatching_symbol():
    p = review_project()
    p.metering_detail.room_name = '<ВУ & АСКУЭ>'
    p.meters.has_askue = True
    svg = build_metering_scheme_svg(p)
    ET.fromstring(svg)
    assert '&lt;ВУ &amp; АСКУЭ&gt;' in svg
    assert 'data-askue="true"' in svg


def test_pdf_is_a3_vector_with_embedded_gost_font_and_cyrillic(tmp_path):
    p = review_project(2)
    p.source.inputs_count = p.meters.inputs_count = 3
    output = tmp_path / "water-meter.pdf"
    generate_metering_scheme_pdf(p,str(output))
    pdf = PdfReader(output)
    assert len(pdf.pages) > 2  # Two schematic sheets plus rule-trace appendix.
    for page in pdf.pages:
        assert float(page.mediabox.width) == pytest.approx(420*72/25.4,abs=.02)
        assert float(page.mediabox.height) == pytest.approx(297*72/25.4,abs=.02)
        fonts = [v.get_object() for v in page['/Resources']['/Font'].values()]
        assert any('OpenGOST' in str(font['/BaseFont']) for font in fonts)
    assert "Водосчётчик" in pdf.pages[0].extract_text()
    assert "Ввод3" in pdf.pages[1].extract_text().replace(" ", "")

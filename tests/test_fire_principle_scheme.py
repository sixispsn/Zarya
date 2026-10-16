"""V2 graphics must preserve the accepted model, references and paper layout."""
from copy import deepcopy
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from app.pz.fire_principle_scheme import (
    _floor_layout, build_principle_sheets, build_riser_sheet,
    build_station_sheet, station_requirement_rows,
)
from app.pz.fire_review_binding import spec_rows
from app.pz.fire_review_scheme import generate_review_scheme
from app.intake.project_builder import build_project
from app.intake.studio_intake import build_handoff_request
from app.pz.ios2_orchestrator import design_ios2
from tests.test_fire_review_binding import passing_model, station_draft


@pytest.fixture(scope='module')
def accepted(tmp_path_factory):
    p = build_project(build_handoff_request(station_draft(passing_model())))
    # Explicit architecture input for this graphics test, not a generator default.
    p.building.floors_above = 16
    p.building.floor_elevations_m = {f: (f-1)*3. for f in range(1, 17)} | {-1: -3.25}
    return design_ios2(p, output_dir=str(tmp_path_factory.mktemp('v2-sheets')),
                       render_documents=False).project


def elements(svg, attribute):
    return [e for e in ET.fromstring(svg).iter() if attribute in e.attrib]


def test_installed_reserve_not_parallel_duty_and_minimum_equipment_matches_spec(accepted):
    svg = build_station_sheet(accepted)
    ids = [e.attrib['data-component'] for e in elements(svg, 'data-component')]
    expected = {'Н1', 'Н2', 'ЗС1', 'ЗС2', 'ЗН1', 'ЗН2', 'КО1', 'КО2', 'PG1', 'PG2', 'PG3', 'PG4'}
    assert len(ids) == len(expected) and set(ids) == expected
    assert 'Н1 рабочий, Н2 резервный. Один насос питает оба выхода.' in svg
    assert f'Q={accepted.fire_pumps.wp_q:.3f}' in svg
    assert 'Коллекторы и насосные ветви: DN не задан' in svg
    required = station_requirement_rows()
    assert all(row in spec_rows(accepted) for row in required)
    assert all(type(row['qty']) is int for row in required)
    for row in required:
        assert set(row['id'].split('/')).issubset(expected)


def test_external_datum_is_not_wall_or_station_room_datum(accepted):
    svg = build_station_sheet(accepted)
    assert 'Точка подключения -2,19' in svg
    assert 'Пол и помещение насосной уточнить по АР' in svg
    assert 'data-level-mark="pump-axis" data-elevation-m="-2.45"' in svg
    assert 'data-level-mark="basement-reference" data-elevation-m="-3.25"' in svg
    assert 'N1 · В2-НУ-Выход1' in svg


def test_explicit_floors_and_only_named_cabinets_no_guessed_floor_quantities(accepted):
    rows = accepted.fire_station_model_input['network']['risers']
    bands, terminals, breaks = _floor_layout(accepted, rows)
    assert set(bands) == {1, 2, 14, 16}
    assert terminals == {'СТ-В2-1':14, 'СТ-В2-2':16}
    assert [(a,b) for _,_,a,b in breaks] == [(15,15), (3,13)]
    svg = build_riser_sheet(accepted, rows, page=2, total=4, graph_page=3)
    cabinets = elements(svg, 'data-cabinet-elevation')
    assert len(cabinets) == len(rows)
    assert [float(e.attrib['data-cabinet-elevation']) for e in cabinets] == [40.35, 46.35]
    assert 'От N3 (В2-У1) · лист 3' in svg
    assert 'От N5 (В2-У3) · лист 3' in svg
    assert 'количество изделий по этажам не восстановлены' in svg


def test_risers_and_architecture_are_cut_at_full_width_breaks(accepted):
    rows = accepted.fire_station_model_input['network']['risers']
    _, _, breaks = _floor_layout(accepted, rows)
    svg = build_riser_sheet(accepted, rows, page=2, total=4, graph_page=3)
    for segment in elements(svg, 'data-riser-segment') + elements(svg, 'data-section-limit'):
        start, end = segment.attrib['d'].split(' L')
        y0, y1 = float(start.split(',')[1]), float(end.split(',')[1])
        assert all(y1 <= lo or y0 >= hi for lo, hi, _, _ in breaks)
    cuts = elements(svg, 'data-building-break')
    assert len(cuts) == 2*len(breaks)
    assert all(e.attrib['d'].startswith('M60,') and e.attrib['d'].endswith('H408') for e in cuts)
    # A floor line through the Z would erase the break symbol.
    for e in elements(svg, 'data-floor-boundary'):
        y = float(e.attrib['d'].split(' L')[0].split(',')[1])
        assert y not in {v for lo, hi, _, _ in breaks for v in (lo, hi)}


@pytest.mark.parametrize('levels', [{1:0.}, {1:0., 16:45.}, {f:0. for f in range(1,17)}])
def test_partial_or_invalid_architecture_does_not_assign_all_pks_to_first_floor(accepted, levels, tmp_path):
    p = deepcopy(accepted)
    p.building.floor_elevations_m = levels
    p = design_ios2(p, output_dir=str(tmp_path), render_documents=False).project
    rows = p.fire_station_model_input['network']['risers']
    assert _floor_layout(p, rows) == ({}, {}, [])
    svg = build_riser_sheet(p, rows, page=2, total=4, graph_page=3)
    assert 'Привязка ПК к этажам не определена' in svg
    assert not elements(svg, 'data-floor-boundary')
    assert len(elements(svg, 'data-cabinet-elevation')) == 2


def test_many_risers_paginate_without_dropping_any(accepted):
    # A pure layout stress fixture; bypass binding validation only here, not in
    # the public renderer, to avoid pretending that copied risers were solved.
    p = deepcopy(accepted)
    prototype = p.fire_station_model_input['network']['risers'][0]
    schedule = p.fire_pumps.pressure_review['schedule'][0]
    rows = [dict(prototype, name=f'СТ-{i}') for i in range(1,9)]
    p.fire_station_model_input['network']['risers'] = rows
    p.fire_pumps.pressure_review['schedule'] = [dict(schedule, riser=r['name']) for r in rows]
    with patch('app.pz.fire_principle_scheme.validate_binding', return_value=p.fire_pumps.pressure_review):
        sheets, graph_page, total = build_principle_sheets(p)
    assert len(sheets) == 5 and graph_page == 6 and total == 7
    drawn = [e.attrib['data-riser'] for svg, _ in sheets for e in elements(svg, 'data-riser')]
    assert drawn == [r['name'] for r in rows]


def test_pdf_has_bookmarks_stamps_and_does_not_mutate_inputs(accepted, tmp_path):
    from pypdf import PdfReader
    before = deepcopy(accepted)
    path = generate_review_scheme(tmp_path/'v2.pdf', accepted)
    pdf = PdfReader(path)
    assert len(pdf.pages) == len(pdf.outline) == 4
    assert [pdf.get_destination_page_number(b) for b in pdf.outline] == list(range(4))
    for page, title in zip(pdf.pages, ('Насосная В2', 'Характерные стояки', 'Схема соединений', 'Узлы установки')):
        text = page.extract_text()
        assert title in text
        assert 'Листов' in text and '\ufffd' not in text and '■' not in text
    # Text boxes in the paper-space scheme may not overlap one another.
    import pymupdf
    from itertools import combinations
    with pymupdf.open(path) as rendered:
        for page in rendered:
            spans = [span for block in page.get_text('dict')['blocks'] if 'lines' in block
                     for line in block['lines'] for span in line['spans']]
            for a, b in combinations(spans, 2):
                overlap = pymupdf.Rect(a['bbox']) & pymupdf.Rect(b['bbox'])
                assert overlap.width <= 1 or overlap.height <= 1, (a['text'], b['text'])
    assert accepted == before


def test_stale_results_cannot_be_rendered_as_current(accepted):
    p = deepcopy(accepted)
    p.fire_station_model_input['supplies'][0]['guaranteed_head_m'] = 36
    with pytest.raises(ValueError):
        build_principle_sheets(p)

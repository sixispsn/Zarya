"""Every ruled VU schedule has connected vertical borders on every sheet."""
from copy import deepcopy
from dataclasses import asdict, replace
import xml.etree.ElementTree as ET

import pytest

from app.pz.metering_detail import drawing_state
from app.pz.metering_catalogue_sheet import catalogue_contents
from app.pz.metering_rules_sheet import rule_contents
from app.pz.meter_product_sheet import product_contents
from app.pz.metering_pipe_sheet import pipe_contents
from scripts.preview_metering_detail import catalogue_review_project
from scripts.preview_metering_detail import review_project


def check_grid(svg, kind, columns, top):
    root = ET.fromstring('<svg>' + svg + '</svg>')
    grids = [e for e in root.iter('g') if e.get('data-vu-table-grid') == kind]
    assert len(grids) == 1
    lines = list(grids[0].iter('line'))
    vertical = [e for e in lines if e.get('x1') == e.get('x2')]
    assert [float(e.get('x1')) for e in vertical] == list(columns)
    assert all(float(e.get('y1')) == top for e in vertical)
    bottoms = {float(e.get('y2')) for e in vertical}
    assert len(bottoms) == 1
    bottom = bottoms.pop()
    assert top < bottom <= 228
    # The upper and lower horizontal rules meet both side borders.
    for y in (top, bottom):
        assert any(float(e.get('x1')) == columns[0]
                   and float(e.get('x2')) == columns[-1]
                   and float(e.get('y1')) == y == float(e.get('y2'))
                   for e in root.iter('line'))
    assert all(e.get('stroke') == 'black' and e.get('stroke-width') == '0.25'
               for e in lines)


@pytest.mark.parametrize('kind,top', [('catalogue',41), ('rules',42), ('meter-products',35)])
def test_vertical_borders_and_bottom_exist_on_every_continuation(kind, top, monkeypatch):
    p = catalogue_review_project()
    if kind == 'meter-products':
        p.meters.rows *= 4  # Force continuation pages, not project quantities.
    elif kind == 'rules':
        from app.pz import metering_rules_sheet
        original = metering_rules_sheet.evaluate_metering_rules
        monkeypatch.setattr(metering_rules_sheet, 'evaluate_metering_rules',
                            lambda *a, **kw: original(*a, **kw) * 4)
    before = deepcopy(asdict(p))
    state = drawing_state(p)
    pages = (catalogue_contents(p,state) if kind == 'catalogue' else
             rule_contents(p,state) if kind == 'rules' else product_contents(p))
    assert len(pages) > 1
    for page in pages:
        check_grid(page, kind, (27,407), top)
    assert asdict(p) == before


def test_pipe_column_borders_include_header_and_all_continuation_rows():
    p = catalogue_review_project()
    p.metering_detail.pipe_sections = {
        role: replace(pipe, geometry_source='Размеры по исходному каталогу. ' * 30)
        for role, pipe in p.metering_detail.pipe_sections.items()}
    before = deepcopy(asdict(p))
    pages = pipe_contents(p, drawing_state(p))
    tables = [page for page in pages if 'data-pipe-row' in page]
    assert len(tables) > 1
    for page in tables:
        check_grid(page, 'pipes', (27,102,195,255,407), 31)
    assert asdict(p) == before


@pytest.mark.parametrize('case', ['ordinary', 'catalogue', 'missing', 'long'])
def test_overview_parameters_are_two_closed_columns_and_legend_is_plain_text(case):
    from app.pz.metering_detail import _panel, _panel_rows, _label_width
    from app.pz.project import Project
    p = (catalogue_review_project() if case == 'catalogue' else
         Project() if case == 'missing' else review_project())
    if case == 'long':
        p.metering_detail.meter_model = 'Счётчик <Узел & Контроль> с дистанционным считыванием DN32'
    before = deepcopy(asdict(p))
    state = drawing_state(p)
    svg = _panel(p, state)
    check_grid(svg, 'parameters', (291,354,410), 42)
    root = ET.fromstring('<svg>' + svg + '</svg>')
    cells = {e.get('data-vu-parameter-cell'): e for e in root.iter('g')
             if e.get('data-vu-parameter-cell')}
    for index, row in enumerate([('Параметр','Значение'), *_panel_rows(p,state)]):
        for column, value in enumerate(row):
            cell = cells[f'{index}-{column}']
            text_nodes = list(cell.iter('text'))
            assert ''.join(''.join(e.itertext()) for e in text_nodes).replace(' ','') == value.replace(' ','')
            for text in text_nodes:
                x, y = float(text.get('x')), float(text.get('y'))
                assert text.get('data-text-height-mm') == '3.5'
                assert x >= float(cell.get('data-left'))+2
                assert x + _label_width(text.text,3.5) <= float(cell.get('data-right'))-2+.01
                assert y-3.5 >= float(cell.get('data-top'))+2-.01
                assert y < float(cell.get('data-bottom'))-1
    legend = next(e for e in root.iter('g') if e.get('data-vu-panel-legend'))
    assert all(e.tag == 'text' for e in legend)
    assert asdict(p) == before


def test_parameter_columns_survive_vector_pdf_render(tmp_path):
    import pymupdf
    from app.pz.generator import generate_metering_scheme_pdf
    output = tmp_path/'meter.pdf'
    generate_metering_scheme_pdf(review_project(), str(output))
    with pymupdf.open(output) as document:
        lines = [item for path in document[0].get_drawings()
                 for item in path['items'] if item[0] == 'l']
        for x in (291,354,410):
            assert any(abs(item[1].x-x*72/25.4) < .02
                       and abs(item[2].x-item[1].x) < .02
                       and abs(item[1].y-42*72/25.4) < .02
                       and item[2].y > item[1].y+40
                       for item in lines)


def test_connection_chain_has_closed_columns_on_continuations(monkeypatch):
    from app.pz import metering_chain
    original = metering_chain.build_metering_chain
    def longer_chain(*args, **kwargs):
        chain = original(*args, **kwargs)
        return replace(chain, paths=chain.paths[:1]+chain.paths[1:]*4)
    monkeypatch.setattr(metering_chain, 'build_metering_chain', longer_chain)
    p = catalogue_review_project()
    before = deepcopy(asdict(p))
    pages = metering_chain.chain_contents(p, drawing_state(p))
    assert len(pages) > 1
    for index, page in enumerate(pages):
        check_grid(page, 'chain', (27,122,407), 38 if index == 0 else 29)
    assert asdict(p) == before


def test_reducer_cards_are_plain_text_without_rules():
    from app.pz.metering_reducers import reducer_contents
    p = catalogue_review_project()
    before = deepcopy(asdict(p))
    pages = reducer_contents(p, drawing_state(p))
    assert pages
    for page in pages:
        root = ET.fromstring('<svg>' + page + '</svg>')
        assert list(root) and all(e.tag == 'text' for e in root)
    assert asdict(p) == before


def test_connection_cards_have_no_decorative_heading_rule():
    from app.pz.metering_connection_sheet import connection_contents
    p = catalogue_review_project()
    pages = connection_contents(p, drawing_state(p))
    assert pages
    for page in pages:
        root = ET.fromstring('<svg>' + page + '</svg>')
        assert not any(e.get('x1') == '27' and e.get('x2') == '407'
                       and e.get('y1') == e.get('y2') == '32'
                       for e in root.iter('line'))

"""Delivered annex/specification frames: actual dimensions, titles and pages."""
from copy import deepcopy
from dataclasses import asdict, replace

import fitz
import pytest
from reportlab.lib.units import mm

from app.pz import generator
from app.pz.project import DocumentInfo, Project
from app.pz.spec import Specification, SpecSection, SpecRow
from app.pz.text_document_frame import frame_pdf
from tests.test_pz_balance_frame import lines, region


@pytest.mark.parametrize('number,total', [(1, 1), (1, 3), (2, 3), (3, 3)])
def test_a3_text_forms_3_6(number, total):
    pdf = fitz.open(stream=frame_pdf(DocumentInfo(cipher='QA.СО'), number, total,
                                   layout='a3_text'), filetype='pdf')
    page = pdf[0]
    top = 237 if number == 1 else 277
    assert page.rect.width / mm == pytest.approx(420, abs=.001)
    for line in ((230, top, 415, top), (230, top, 230, 292), (295, top, 295, 292),
                 (20, 5, 415, 5), (8, 207, 8, 292), (13, 207, 13, 292)):
        assert line in lines(page)
    if number == 1:
        assert region(page, 380, 267, 395, 277) == ('1' if total > 1 else '')
        assert region(page, 395, 267, 415, 277) == str(total)
    else:
        assert (405, 284, 415, 284) in lines(page)
        assert region(page, 405, 284, 415, 292) == str(number)


@pytest.mark.parametrize('kind,suffix,needs_report', [
    ('rainwater_reuse', '.ДВ', False), ('v1_calculation', '.РВ1', False),
    ('wastewater_calculation', '.РР', False), ('commission_control', '.НК', False),
    ('hydraulic_report', '.ГР', True), ('resilience', '.ЖВ', True),
])
def test_annex_three_pages_keep_cipher_count_and_project(tmp_path, monkeypatch, kind, suffix, needs_report):
    project = Project(document=DocumentInfo(cipher='QA-ИОС2', sheet_total='99', stage='Р'))
    # Exercise both fire-station and ordinary hydraulic branches without
    # calculating new flows; presentation must not mutate the project.
    if kind == 'hydraulic_report':
        project.fire_station_input = object()
    original_doc = deepcopy(asdict(project.document))
    def html(*args, **kwargs):
        return ('<div class="stamp3">OBSOLETE STAMP</div>'
                '<h1>Body first</h1><p style="break-before:page">Body second</p>'
                '<p style="break-before:page">Body third</p>')
    monkeypatch.setattr(generator, 'generate_' + kind + '_html', html)
    target = tmp_path / (kind + '.pdf')
    args = (project, None, str(target)) if needs_report else (project, str(target))
    getattr(generator, 'generate_' + kind + '_pdf')(*args)
    pdf = fitz.open(target)
    assert len(pdf) == 3
    cipher = ('QA-ИОС3' if kind == 'wastewater_calculation' else 'QA-ИОС2') + suffix
    for i, page in enumerate(pdf, 1):
        assert page.get_text().count(cipher) == 1
        assert 'OBSOLETE' not in page.get_text() and '99' not in page.get_text()
        assert page.get_text().count('Изм.') == 1
        top = 237 if i == 1 else 277
        assert (20, top, 205, top) in lines(page)
        assert not region(page, 190, 0, 205, 10)
        for w in page.get_text('words'):
            if w[4] == 'Body':
                assert w[0] / mm >= 25 - .01 and w[3] / mm <= top - 5
    assert region(pdf[0], 185, 267, 205, 277) == '3'
    assert region(pdf[0], 155, 267, 170, 277) == 'Р'
    assert region(pdf[2], 195, 284, 205, 292) == '3'
    assert asdict(project.document) == original_doc


@pytest.mark.parametrize('wastewater', [False, True])
def test_spec_rows_and_grid_unchanged_actual_frames(tmp_path, monkeypatch, wastewater):
    spec = Specification(sections=[SpecSection('В1', 'Водоснабжение', [
        SpecRow(i, f'Item{i:03}', qty=i, note='Полное примечание. ' * 12 if i % 3 == 0 else '')
        for i in range(1, 46)])])
    project = Project(document=DocumentInfo(cipher='QA-ИОС2', sheet_total='99'))
    before = deepcopy(asdict(spec)), deepcopy(asdict(project))
    monkeypatch.setattr(generator, 'build_wastewater_specification' if wastewater
                        else 'build_water_specification', lambda _: spec)
    target = tmp_path / 'spec.pdf'
    fn = generator.generate_wastewater_spec_pdf if wastewater else generator.generate_spec_pdf
    fn(project, str(target))
    pdf = fitz.open(target)
    assert len(pdf) > 1
    text = '\n'.join(p.get_text() for p in pdf)
    for i in range(1, 46):
        assert text.count(f'Item{i:03}') == 1
    cipher = 'QA-ИОС3.СО' if wastewater else 'QA-ИОС2.СО'
    for i, page in enumerate(pdf, 1):
        top = 237 if i == 1 else 277
        assert (230, top, 415, top) in lines(page)
        assert page.get_text().count(cipher) == 1
        assert '99' not in page.get_text()
        if i == 1:
            assert region(page, 395, 267, 415, 277) == str(len(pdf))
        else:
            assert region(page, 405, 284, 415, 292) == str(i)
        for w in page.get_text('words'):
            if w[4].startswith('Item'):
                assert w[3] / mm < top
    assert (asdict(spec), asdict(project)) == before


@pytest.mark.parametrize('kind,suffix', [('tz', '.ТЗ'), ('tu', '.ИД')])
def test_source_documents_keep_actual_stage(tmp_path, kind, suffix):
    project = Project(document=DocumentInfo(cipher='QA', stage='Р', sheet_total='99'))
    target = tmp_path / (kind + '.pdf')
    getattr(generator, 'generate_' + kind + '_pdf')(project, str(target))
    pdf = fitz.open(target)
    assert region(pdf[0], 155, 267, 170, 277) == 'Р'
    assert region(pdf[0], 185, 267, 205, 277) == str(len(pdf))
    assert 'QA' + suffix in pdf[0].get_text()


def test_long_hydraulic_table_keeps_rows_and_continuation_frame(tmp_path):
    from tests.test_hydraulic_report_render import _report_and_project
    report, project = _report_and_project()
    # Repetition is a layout stress fixture, not a recalculated network.
    report.segments = [replace(report.segments[0], segment_id=f'ROW{i:03}') for i in range(80)]
    target = tmp_path / 'hydraulic-long.pdf'
    generator.generate_hydraulic_report_pdf(project, report, str(target))
    pdf = fitz.open(target)
    assert len(pdf) > 1
    for i, page in enumerate(pdf, 1):
        top = 237 if i == 1 else 277
        assert (20, top, 205, top) in lines(page)
        if i > 1:
            assert region(page, 195, 284, 205, 292) == str(i)
        for w in page.get_text('words'):
            if w[4].startswith('ROW'):
                assert w[3] / mm < top - 5
    text = '\n'.join(p.get_text() for p in pdf)
    for i in range(80):
        # Once in the hydraulic table and once in the diameter verdict list.
        assert text.count(f'ROW{i:03}') == 2

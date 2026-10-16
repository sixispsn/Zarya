"""Measure delivered PDF geometry, numbering, and body clearance for IOS2/3."""
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO

import fitz
import pytest
from pypdf import PdfReader
from reportlab.lib.units import mm
from weasyprint import HTML

from app.pz import generator
from app.pz.project import BalanceData, ConsumerRow, DocumentInfo, Project
from app.pz.text_document_frame import apply_frame, frame_pdf


def lines(page):
    return [tuple(round(v / mm, 3) for p in item[1:3] for v in p)
            for drawing in page.get_drawings() for item in drawing['items'] if item[0] == 'l']


def region(page, x, y, right, bottom):
    return page.get_text(clip=fitz.Rect(x * mm, y * mm, right * mm, bottom * mm)).strip()


@pytest.mark.parametrize('number,total', [(1, 1), (1, 3), (2, 3), (3, 3)])
def test_a3_graphic_form3_on_every_page(number, total):
    pdf = fitz.open(stream=frame_pdf(DocumentInfo(cipher='QA.БВ'), number, total,
                                   layout='a3_graphic'), filetype='pdf')
    page = pdf[0]
    assert page.rect.width / mm == pytest.approx(420, abs=.001)
    assert page.rect.height / mm == pytest.approx(297, abs=.001)
    segments = lines(page)
    for segment in ((20, 5, 415, 5), (415, 5, 415, 292), (415, 292, 20, 292),
                    (20, 292, 20, 5), (230, 237, 415, 237), (230, 237, 230, 292),
                    (295, 237, 295, 292), (295, 247, 415, 247),
                    (8, 207, 8, 292), (13, 207, 13, 292)):
        assert segment in segments
    for x in (240, 250, 260, 270, 285):
        assert (x, 237, x, 262 if x in (240, 260) else 292) in segments
    assert region(page, 380, 267, 395, 277) == (str(number) if total > 1 else '')
    assert region(page, 395, 267, 415, 277) == (str(total) if number == 1 else '')
    assert region(page, 295, 237, 415, 247) == 'QA.БВ'
    assert 'Формат А3' in page.get_text()


@pytest.mark.parametrize('kind', ['pz', 'wastewater_pz', 'balance', 'wastewater_balance'])
def test_generators_actual_numbering_no_duplicate_stamp_or_mutation(tmp_path, monkeypatch, kind):
    project = Project(document=DocumentInfo(cipher='QA-ИОС2', sheet_no='99', sheet_total='99'))
    before = deepcopy(asdict(project))
    template = 'balance_document.html' if 'balance' in kind else 'document.html'
    # Use the real shared template, including its legacy running blocks. They
    # must be hidden in these PDFs, not printed underneath the vector frame.
    def html(p):
        body = '<h2>Body one</h2><p style="break-before:page">Body two</p>'
        if 'balance' in kind:
            body = None
        result = generator._build_env().get_template(template).render(
            doc=p.document, body_html=body, balance=p.balance)
        if 'balance' in kind:
            result = result.replace('</main>', '<p style="break-before:page">Body two</p></main>')
        return result
    monkeypatch.setattr(generator, 'generate_' + kind + '_html', html)
    target = tmp_path / (kind + '.pdf')
    getattr(generator, 'generate_' + kind + '_pdf')(project, str(target))
    pdf = fitz.open(target)
    assert len(pdf) == 2
    graphic = 'balance' in kind
    dx = 210 if graphic else 0
    cipher = ('QA-ИОС3' if 'wastewater' in kind else 'QA-ИОС2') + ('.БВ' if graphic else '')
    for i, page in enumerate(pdf, 1):
        top = 237 if graphic or i == 1 else 277
        assert (20 + dx, top, 205 + dx, top) in lines(page)
        assert page.get_text().count(cipher) == 1
        assert '99' not in page.get_text()
        assert not region(page, 190 + dx, 0, 205 + dx, 10)
        assert page.get_text().count('Изм.') == 1
        if graphic or i == 1:
            assert region(page, 170 + dx, 267, 185 + dx, 277) == str(i)
            assert region(page, 185 + dx, 267, 205 + dx, 277) == ('2' if i == 1 else '')
        else:
            assert region(page, 195, 284, 205, 292) == str(i)
        for word in page.get_text('words'):
            if word[4] == 'Body':
                assert word[0] / mm >= 25 - .01
                assert word[3] / mm <= top - 5
    assert asdict(project) == before


def test_overlay_preserves_metadata_and_navigation():
    body = HTML(string='<title>Original title</title><h1>Original heading</h1>').write_pdf()
    framed = PdfReader(BytesIO(apply_frame(body, DocumentInfo())))
    assert framed.metadata.title == 'Original title'
    assert framed.outline[0].title == 'Original heading'


def test_frame_rejects_incompatible_paper():
    body = HTML(string='<style>@page { size: A3 landscape; }</style><p>Body</p>').write_pdf()
    with pytest.raises(ValueError, match='требует лист'):
        apply_frame(body, DocumentInfo())


@pytest.mark.parametrize('kind', ['balance', 'wastewater_balance'])
def test_long_balance_repeats_header_and_keeps_all_rows_outside_stamp(tmp_path, kind):
    project = Project(document=DocumentInfo(cipher='QA-ИОС2', object_name='Контрольный пример'),
                      balance=BalanceData(rows=[ConsumerRow(name=f'Consumer{i:03}') for i in range(60)]))
    target = tmp_path / (kind + '.pdf')
    getattr(generator, 'generate_' + kind + '_pdf')(project, str(target))
    pdf = fitz.open(target)
    assert len(pdf) > 1
    all_text = '\n'.join(page.get_text() for page in pdf)
    for i in range(60):
        assert all_text.count(f'Consumer{i:03}') == 1
    for i, page in enumerate(pdf, 1):
        assert 'Наименование' in page.get_text()
        assert region(page, 380, 267, 395, 277) == str(i)
        assert region(page, 395, 267, 415, 277) == (str(len(pdf)) if i == 1 else '')
        body = [w for w in page.get_text('words') if w[0] / mm >= 24 and w[1] / mm < 237]
        assert max(w[3] / mm for w in body) <= 232.1

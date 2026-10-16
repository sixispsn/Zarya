"""Physical PDF coordinates, not a claim of compliance based on CSS names."""
from copy import deepcopy
from dataclasses import asdict

import fitz
import pytest
from reportlab.lib.units import mm

from app.pz.project import DocumentInfo, Project
from app.pz.text_document_frame import frame_pdf
from app.pz import generator


def segments(page):
    return [tuple(round(v / mm, 3) for p in item[1:3] for v in p)
            for drawing in page.get_drawings() for item in drawing['items'] if item[0] == 'l']


@pytest.mark.parametrize('number,total,top', [(1, 4, 237), (2, 4, 277), (4, 4, 277), (1, 1, 237)])
def test_exact_a4_frame_forms_and_number_cells(number, total, top):
    doc = DocumentInfo(cipher='QA-ИОС2.РН', object_name='Проверка', sheet_total='99')
    pdf = fitz.open(stream=frame_pdf(doc, number, total), filetype='pdf')
    page = pdf[0]
    assert page.rect.width / mm == pytest.approx(210, abs=.001)
    assert page.rect.height / mm == pytest.approx(297, abs=.001)
    lines = segments(page)
    for line in ((20, 5, 205, 5), (205, 5, 205, 292), (205, 292, 20, 292),
                 (20, 292, 20, 5), (20, top, 205, top), (85, top, 85, 292),
                 (8, 207, 8, 292), (13, 207, 13, 292)):
        assert line in lines
    for x in (30, 40, 50, 60, 75):
        expected_bottom = top + 25 if number == 1 and x in (30, 50) else 292
        assert (x, top, x, expected_bottom) in lines
    def region(x1, y1, x2, y2):
        return page.get_text(clip=fitz.Rect(x1 * mm, y1 * mm, x2 * mm, y2 * mm)).strip()
    if number == 1:
        assert region(170, 267, 185, 277) == ('1' if total > 1 else '')
        assert region(185, 267, 205, 277) == str(total)
        assert (85, 247, 205, 247) in lines
        assert (85, 262, 205, 262) in lines
        assert (85, 277, 205, 277) in lines
    else:
        assert (195, 277, 195, 292) in lines
        assert (195, 284, 205, 284) in lines
        assert region(195, 284, 205, 292) == str(number)
    assert '99' not in page.get_text()


def test_long_stamp_text_fails_instead_of_clipping():
    with pytest.raises(ValueError, match='не помещается'):
        frame_pdf(DocumentInfo(object_name='Очень длинное имя ' * 100), 1, 2)


def test_generated_pump_pdf_uses_actual_count_and_does_not_mutate(tmp_path, monkeypatch):
    project = Project(document=DocumentInfo(cipher='TEST', sheet_total='99'))
    before = deepcopy(asdict(project))
    monkeypatch.setattr(generator, 'generate_pump_selection_html', lambda _: (
        '<p>Body one</p><p style="break-before:page">Body two</p>'
        '<p style="break-before:page">Body three</p>'))
    target = tmp_path / 'pump.pdf'
    generator.generate_pump_selection_pdf(project, str(target))
    pdf = fitz.open(target)
    assert len(pdf) == 3
    for i, page in enumerate(pdf):
        assert 'TEST.РН' in page.get_text()
        assert (20, 237 if i == 0 else 277, 205, 237 if i == 0 else 277) in segments(page)
        assert '99' not in page.get_text()
        for word in page.get_text('words'):
            if word[4] == 'Body':
                assert word[0] / mm >= 25 - .01
                assert word[3] / mm < (237 if i == 0 else 277) - 5
    assert asdict(project) == before

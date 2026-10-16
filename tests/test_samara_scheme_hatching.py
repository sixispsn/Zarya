"""Check printed floor/base hatches, not just the presence of SVG tags.

References: supplied GOST R 21.619-2023 Appendix Б and 21.620-2023
Appendix В. These bands are schematic; no structural thickness is inferred.
"""
from copy import deepcopy
from dataclasses import asdict
from xml.etree import ElementTree as ET

import pymupdf
import pytest

from app.intake import samara_study
from app.pz.generator import generate_scheme_result, generate_scheme_pdf
from app.pz.residential_concept_section import build_concept_section_svg
from app.pz.wastewater_graphic_exports import (
    representative_document_model, generate_wastewater_graphic_export,
)


@pytest.fixture(scope='module')
def samara(tmp_path_factory):
    draft = dict(revision=0, answers={}, documents=[])
    samara_study.initialize(draft, None)
    return samara_study.build(draft, tmp_path_factory.mktemp('hatch-model'), render=False)[0].project


def _assert_printed_hatch(page, rectangle):
    x, y, width, height = [float(rectangle.get(k)) for k in ('x', 'y', 'width', 'height')]
    mm = 72 / 25.4
    # Stay inside the band: its outline or a vertical wall cannot pass this test.
    # Two separated strips also catch a white overlay hiding part of the hatch.
    for offset in (15, width * .72):
        clip = pymupdf.Rect((x+offset)*mm, (y+.45)*mm,
                           (x+offset+12)*mm, (y+height-.45)*mm)
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=clip,
                                 colorspace=pymupdf.csGRAY).samples
        dark_fraction = sum(v < 180 for v in pixels) / len(pixels)
        assert .015 < dark_fraction < .4, (rectangle.attrib, offset, dark_fraction)


@pytest.mark.parametrize('system', ['water', 'sewer'])
def test_current_samara_pdf_keeps_every_shown_floor_and_basement_hatched(samara, tmp_path, system):
    before = deepcopy(asdict(samara))
    path = tmp_path / (system + '.pdf')
    if system == 'water':
        # Same scope split as the IOS2 orchestrator: В2 has its separate sheet.
        drawing = deepcopy(samara)
        drawing.fire.required = drawing.fire_pumps.required = False
        result = generate_scheme_result(drawing)
        root = ET.fromstring(result.svg)
        assert root.get('data-residential-water-section') == 'approval'
        slabs = {e.get('data-section-slab'): list(e)[0]
                 for e in root.iter() if e.get('data-section-slab')}
        assert set(slabs) == {'water-floor-1', 'water-floor-2', 'water-floor-16', 'water-base'}
        generate_scheme_pdf(drawing, str(path), scheme_result=result)
        expected_width = 594
    else:
        model = representative_document_model(samara)
        root = ET.fromstring(build_concept_section_svg(model))
        slabs = {e.get('data-floor-boundary'): e
                 for e in root.iter() if e.get('data-floor-boundary')}
        assert set(slabs) == {'1', '2', '16'}
        basement = [e for e in root.iter() if e.get('data-basement-floor')]
        assert len(basement) == 1
        slabs['base'] = basement[0]
        result = generate_wastewater_graphic_export(samara, 'k1-k2', str(path))
        assert result.backend == 'representative-section' and not result.ready
        expected_width = 297
    with pymupdf.open(path) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width * 25.4 / 72 == pytest.approx(expected_width, abs=.01)
        assert page.rect.height * 25.4 / 72 == pytest.approx(420, abs=.01)
        assert 'Подвал' in page.get_text() and '-3,25' in page.get_text()
        for slab in slabs.values():
            _assert_printed_hatch(page, slab)
    # Architectural styling cannot alter calculation/specification inputs.
    assert asdict(samara) == before

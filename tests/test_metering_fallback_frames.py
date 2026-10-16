"""Remaining graphic frames: physical PDF checks, not hydraulic approval."""

from copy import deepcopy
from dataclasses import asdict

import cairosvg
import fitz
import pytest
from reportlab.lib.units import mm

from app.pz.generator import (
    _svg_to_a1_mm,
    generate_metering_scheme_pdf,
    generate_scheme_pdf,
)
from app.pz.metering_detail import build_metering_detail_pages
from app.pz.scheme import build_scheme
from app.pz.wastewater_scheme import build_wastewater_scheme
from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
from scripts.preview_metering_detail import review_project
from tests.test_metering_g1_switching import project as g1_project
from tests.test_pump_document_frame import segments
from tests.test_station_graphic_frames import qa_document
from tests.test_wastewater_scheme_service import _project as sewer_project


def check_graphic_page(page, width, height, number, total):
    assert page.rect.width / mm == pytest.approx(width, abs=0.01)
    assert page.rect.height / mm == pytest.approx(height, abs=0.01)
    x, y = width - 190, height - 60
    lines = segments(page)
    for dx in (10, 20, 30, 40, 55, 65):
        expected = (x + dx, y, x + dx, y + (25 if dx in (10, 30) else 55))
        assert any(
            all(abs(a - b) < 0.02 for a, b in zip(row, expected)) for row in lines
        )
    rectangles = [
        item[1] for d in page.get_drawings() for item in d["items"] if item[0] == "re"
    ]
    for expected in ((20, 5, width - 5, height - 5), (x, y, width - 5, height - 5)):
        assert any(
            all(abs(a / mm - b) < 0.02 for a, b in zip(r, expected)) for r in rectangles
        )

    def cell(x1, y1, x2, y2):
        return page.get_text(
            clip=fitz.Rect(*(v * mm for v in (x1, y1, x2, y2)))
        ).strip()

    assert cell(x + 150, y + 30, x + 165, y + 40) == (str(number) if total > 1 else "")
    assert cell(x + 165, y + 30, x + 185, y + 40) == (str(total) if number == 1 else "")
    assert cell(x + 135, y + 30, x + 150, y + 40) == "Р"
    assert "Взам." in cell(8, height - 90, 13, height - 65)
    assert "Формат А" in page.get_text()
    assert page.get_text().count("Изм.") == 1
    assert "…" not in page.get_text(
        clip=fitz.Rect(x * mm, y * mm, (width - 5) * mm, (height - 5) * mm)
    )
    assert any("OpenGOST" in str(font) for font in page.get_fonts())


@pytest.mark.parametrize("kind", ["one", "three", "g1"])
def test_metering_all_pages_have_actual_numbers_and_physical_a3_frame(tmp_path, kind):
    p = g1_project() if kind == "g1" else review_project()
    if kind == "three":
        p.source.inputs_count = p.meters.inputs_count = 3
    p.document = qa_document()
    p.document.sheet_no = "78"
    before = deepcopy(asdict(p))
    svg_pages = build_metering_detail_pages(p)
    path = tmp_path / "meter.pdf"
    generate_metering_scheme_pdf(p, str(path))
    pdf = fitz.open(path)
    assert len(pdf) == len(svg_pages) > 1
    for i, page in enumerate(pdf, 1):
        check_graphic_page(page, 420, 297, i, len(pdf))
        assert 'data-title-block="form-3"' in svg_pages[i - 1]
    assert asdict(p) == before


@pytest.mark.parametrize("kind", ["water", "sewer", "sewer-continuation"])
def test_fallback_export_exact_a1_not_rounded_pixel_proportions(tmp_path, kind):
    p = sewer_project() if kind.startswith("sewer") else review_project()
    p.document = qa_document()
    p.document.sheet_no = "78"
    if kind.startswith("sewer"):
        # The existing diagnostic renderer populates its transient cache.
        # Establish that cache before checking presentation-only immutability.
        assess_wastewater_diagnostics(p)
    before = deepcopy(asdict(p))
    number, total = (2, 3) if kind.endswith("continuation") else (1, 1)
    if kind == "water":
        path = tmp_path / "water.pdf"
        generate_scheme_pdf(p, str(path), scheme_result=build_scheme(p))
        pdf = fitz.open(path)
    else:
        svg = build_wastewater_scheme(p, sheet_no=number, sheet_total=total).svg
        pdf = fitz.open(
            stream=cairosvg.svg2pdf(bytestring=_svg_to_a1_mm(svg).encode()),
            filetype="pdf",
        )
    check_graphic_page(pdf[0], 841, 594, number, total)
    assert asdict(p) == before


@pytest.mark.parametrize(
    "builder", [build_metering_detail_pages, build_scheme, build_wastewater_scheme]
)
def test_long_requisites_are_not_silently_cut(builder):
    p = review_project()
    p.document.object_name = "Очень длинное название " * 100
    with pytest.raises(ValueError, match="не помещается"):
        builder(p)


def test_structural_review_passes_actual_number_to_fallback():
    from app.pz.wastewater_layout_builder import build_wastewater_floor_stack
    from app.pz.wastewater_structure_renderer import (
        build_wastewater_structure_svg,
        WastewaterStructureScope,
    )

    p = sewer_project()
    p.document = qa_document()
    svg = build_wastewater_structure_svg(
        p,
        build_wastewater_floor_stack(p).layout,
        WastewaterStructureScope.BASEMENT_K1_MAIN,
        sheet_no=2,
        sheet_total=4,
    )
    pdf = fitz.open(
        stream=cairosvg.svg2pdf(bytestring=_svg_to_a1_mm(svg).encode()), filetype="pdf"
    )
    check_graphic_page(pdf[0], 841, 594, 2, 4)

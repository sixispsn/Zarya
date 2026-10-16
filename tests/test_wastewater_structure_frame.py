"""Physical frames of the intermediate sheets, not approval of their contents."""

from copy import deepcopy
from dataclasses import asdict, replace
from xml.etree import ElementTree as ET

import fitz
import pytest

from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
from app.pz.wastewater_layout_builder import build_wastewater_floor_stack
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope as Scope,
    build_wastewater_structure_svg,
    generate_wastewater_structure_pdf,
)
from tests.test_metering_fallback_frames import check_graphic_page
from tests.test_station_graphic_frames import qa_document
from tests.test_wastewater_floor_stack import _project


def review_case():
    p = _project()
    p.document = qa_document()
    p.document.sheet_no = "77"
    assess_wastewater_diagnostics(p)  # Existing fallback cache, not frame work.
    return p, build_wastewater_floor_stack(p).layout


@pytest.mark.parametrize("scope", list(Scope))
@pytest.mark.parametrize("number,total", [(1, 1), (1, 3), (2, 3)])
def test_each_scope_exports_one_exact_frame_without_mutating_inputs(
    tmp_path, scope, number, total
):
    p, layout = review_case()
    before = deepcopy((asdict(p), asdict(layout)))
    svg = build_wastewater_structure_svg(
        p, layout, scope, sheet_no=number, sheet_total=total
    )
    root = ET.fromstring(svg)
    assert sum(e.get("data-title-block") == "form-3" for e in root.iter()) == 1
    assert sum(e.get("data-sheet-border") == "true" for e in root.iter()) == 1
    path = tmp_path / "structure.pdf"
    generate_wastewater_structure_pdf(
        p, layout, str(path), scope, sheet_no=number, sheet_total=total
    )
    pdf = fitz.open(path)
    assert len(pdf) == 1
    check_graphic_page(pdf[0], 841, 594, number, total)
    assert (asdict(p), asdict(layout)) == before


@pytest.mark.parametrize("scope", [Scope.FOUNDATION, Scope.FULL_FLOOR_STACK])
def test_frame_uses_actual_paper_dimensions_not_fixed_a1(tmp_path, scope):
    p, layout = review_case()
    layout = replace(layout, sheet_width_mm=1189, sheet_height_mm=841)
    before = deepcopy(asdict(layout))
    path = tmp_path / "a0.pdf"
    generate_wastewater_structure_pdf(p, layout, str(path), scope)
    pdf = fitz.open(path)
    check_graphic_page(pdf[0], 1189, 841, 1, 1)
    assert "Формат А0" in pdf[0].get_text()
    assert asdict(layout) == before


@pytest.mark.parametrize("scope", [Scope.FOUNDATION, Scope.FULL_FLOOR_STACK])
def test_oversized_metadata_is_rejected_not_truncated(scope):
    p, layout = review_case()
    p.document.object_name = "Длинное название " * 100
    with pytest.raises(ValueError, match="не помещается"):
        build_wastewater_structure_svg(p, layout, scope)


@pytest.mark.parametrize("number,total", [(0, 1), (2, 1), (1, 0)])
def test_invalid_numbering_is_not_printed(number, total):
    p, layout = review_case()
    with pytest.raises(ValueError, match="нумерация"):
        build_wastewater_structure_svg(p, layout, sheet_no=number, sheet_total=total)

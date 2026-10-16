"""Paper layout only: a hatch band is not a structural slab dimension."""

from copy import deepcopy
from dataclasses import asdict
from xml.etree import ElementTree as ET

import fitz
import pytest
from reportlab.lib.units import mm

from app.pz.wastewater_scheme import (
    H,
    W,
    WastewaterSchemeScope,
    build_wastewater_scheme,
)
from app.pz.wastewater_structure_renderer import (
    WastewaterStructureScope,
    generate_wastewater_structure_pdf,
)
from app.pz.wastewater_layout_builder import build_wastewater_floor_stack
from tests.test_metering_fallback_frames import check_graphic_page
from tests.test_wastewater_structure_frame import review_case


def slab(svg):
    root = ET.fromstring(svg)
    return next(e for e in root.iter() if e.get("data-basement-slab") == "true")


def check_clearance(page, svg):
    band = list(slab(svg))[0]
    x, y, w, h = [float(band.get(k)) for k in ("x", "y", "width", "height")]
    # True printed stroke envelopes, not centerlines or a white stamp cover.
    bottom = (y + h + 0.75) * 594 / H
    stamp_top = 594 - 60 - 0.25
    assert stamp_top - bottom >= 5 - 1e-7
    # A crop at the former collision must show the complete lower edge and
    # the hatch on the right end, not an opaque title-block mask.
    for left in (x + 100, x + w - 60):
        clip = fitz.Rect(
            (left * 841 / W) * mm,
            ((y + 2) * 594 / H) * mm,
            ((left + 40) * 841 / W) * mm,
            ((y + h - 2) * 594 / H) * mm,
        )
        pixels = page.get_pixmap(
            matrix=fitz.Matrix(3, 3), clip=clip, colorspace=fitz.csGRAY
        ).samples
        assert sum(v < 180 for v in pixels) / len(pixels) > 0.01
    clip = fitz.Rect(652 * mm, (bottom + 0.3) * mm, 675 * mm, (stamp_top - 0.3) * mm)
    pixels = page.get_pixmap(
        matrix=fitz.Matrix(2, 2), clip=clip, colorspace=fitz.csGRAY
    ).samples
    assert min(pixels) > 245  # Entire physical clearance is blank.


@pytest.mark.parametrize("floors", [1, 2, 3, 16, 25])
def test_basement_slab_is_visible_with_five_mm_clearance(tmp_path, floors):
    p, layout = review_case()
    p.building.floors_above = floors
    layout = build_wastewater_floor_stack(p).layout
    before = deepcopy(asdict(p))
    result = build_wastewater_scheme(p, WastewaterSchemeScope.BASEMENT_K1_MAIN)
    band = list(slab(result.svg))[0]
    assert float(band.get("y")) == 1730
    assert float(band.get("width")) == 2060
    assert 30 < float(band.get("height")) < 32
    path = tmp_path / "basement.pdf"
    generate_wastewater_structure_pdf(
        p,
        layout,
        str(path),
        WastewaterStructureScope.BASEMENT_K1_MAIN,
        sheet_no=2,
        sheet_total=3,
    )
    pdf = fitz.open(path)
    check_graphic_page(pdf[0], 841, 594, 2, 3)
    check_clearance(pdf[0], result.svg)
    assert asdict(p) == before


def test_full_scheme_hatch_geometry_is_not_changed():
    p, _ = review_case()
    band = list(slab(build_wastewater_scheme(p).svg))[0]
    assert tuple(float(band.get(k)) for k in ("x", "y", "width", "height")) == (
        200,
        1696,
        2060,
        34,
    )


def test_no_room_fails_instead_of_covering_stamp(monkeypatch):
    from dataclasses import replace
    from app.pz import wastewater_scheme as module

    original = module.build_section_scaffold
    monkeypatch.setattr(
        module,
        "build_section_scaffold",
        lambda p: replace(original(p), basement_y=1800),
    )
    p, _ = review_case()
    with pytest.raises(ValueError, match="Нет места"):
        build_wastewater_scheme(p, WastewaterSchemeScope.BASEMENT_K1_MAIN)

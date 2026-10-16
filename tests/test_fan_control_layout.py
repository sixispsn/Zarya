"""Nonproject fan controls retain their own identification, not a project stamp."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest
from reportlab.lib.units import mm

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.wastewater_fan_drafting import build_fan_detail_svgs, _roof_svg, _sheet_end
from scripts.build_fan_details import control_fan_details
from tests.section_fan_fixture import section_fan_fixture


def control_views():
    data = control_fan_details()
    model, binding = section_fan_fixture()
    return (
        *build_fan_detail_svgs(data),
        _roof_svg(binding.data, binding.data.roofs[0], 2, 2,
                  {r.riser_id: 1 for r in binding.data.risers}, off_plane_risers=frozenset({"К1-2", "К1-3"})),
        _roof_svg(data, data.roofs[0], 4, 4, {r.riser_id: 1 for r in data.roofs[0].risers}),
    )


def engineering_svg(svg):
    root = ET.fromstring(svg)
    kept = []
    for element in root:
        if element.get("data-fan-control-notes") or (element.tag.endswith("line") and element.get("y1") == "226"):
            break
        if element.tag.endswith("rect") and element.get("x") == "20" and element.get("y") == "5":
            continue
        kept.append(ET.canonicalize(ET.tostring(element, encoding="unicode"), rewrite_prefixes=True).encode())
    return b"".join(kept)


BASELINE = (
    "dbd1e3d8991e2d45bb9103e357ab7f0cb6a15d3e5db2ceab9e0ed226bf625259",
    "2e79a9874f86636f03307fe9f57bea0b70e6cdc376059e702a64d117e5c7ed1c",
    "f8cc90643b23a86e0c7ee4be01d28ad85ccceb471fcc03de2d66ffa5b609cedd",
    "7866c42e6eeb5df04acd2f9ec8560f9b9c9287c1752a2a72d83a657aeec847ac",
)


def check_control_page(page):
    assert tuple(v / mm for v in page.rect) == pytest.approx((0, 0, 420, 297), abs=.003)
    assert any(tuple(v / mm for v in d["rect"]) == pytest.approx((20, 5, 415, 292), abs=.003)
               for d in page.get_drawings())
    assert "Не является готовым листом ПД или монтажным чертежом" in page.get_text()
    assert "Стадия" not in page.get_text()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                x1, y1, x2, y2 = (v / mm for v in span["bbox"])
                assert 20 < x1 < x2 < 415 and 5 < y1 < y2 < 292, span["text"]


@pytest.mark.parametrize("index", range(4))
def test_geometry_and_visible_control_status_remain(index):
    svg = control_views()[index]
    assert sha256(engineering_svg(svg)).hexdigest() == BASELINE[index]
    root = ET.fromstring(svg)
    assert root.get("data-production-release") == "false"
    assert not any(e.get("data-drawing-frame") for e in root.iter())
    assert not any(e.tag.endswith("line") and e.get("y1") == e.get("y2") == "226" for e in root.iter())
    notes = next(e for e in root if e.get("data-fan-control-notes"))
    assert len(notes) == 5
    assert [float(e.get("y")) for e in notes] == [234, 241, 248, 255, 262]
    ensure_drafting_font_registered()
    with fitz.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf") as pdf:
        check_control_page(pdf[0])
        # The gap below all notes is clear, not hidden by a white footer.
        pixels = pdf[0].get_pixmap(clip=fitz.Rect(21*mm, 271*mm, 414*mm, 275*mm),
                                  colorspace=fitz.csGRAY, alpha=False)
        assert min(pixels.samples) == 255


@pytest.mark.parametrize("damage", ["border", "footer", "duplicate", "disclaimer", "page", "release", "format"])
def test_invalid_control_identity_cannot_overwrite_pdf(damage, tmp_path, monkeypatch):
    import app.pz.wastewater_fan_drafting as module

    data = control_fan_details()
    pages = list(build_fan_detail_svgs(data))
    root = ET.fromstring(pages[-1])
    footer = next(e for e in root if e.get("data-fan-control-footer"))
    if damage == "border":
        root.remove(next(e for e in root if e.get("data-fan-control-border")))
    elif damage == "footer":
        root.remove(footer)
    elif damage == "duplicate":
        root.append(deepcopy(footer))
    elif damage == "disclaimer":
        next(e for e in footer if e.text and e.text.startswith("Не является")).text = "Готово к выпуску"
    elif damage == "page":
        next(e for e in footer if e.text == "2 / 2").text = "1 / 1"
    elif damage == "release":
        root.set("data-production-release", "true")
    else:
        root.set("width", "594mm")
    pages[-1] = ET.tostring(root, encoding="unicode")
    monkeypatch.setattr(module, "build_fan_detail_svgs", lambda *a: tuple(pages))
    path = tmp_path / "preserved.pdf"
    path.write_bytes(b"existing control")
    with pytest.raises(ValueError):
        module.generate_fan_details_pdf(data, str(path))
    assert path.read_bytes() == b"existing control"


def test_notes_refuse_overflow_without_shrinking():
    with pytest.raises(ValueError, match="Примечания"):
        _sheet_end(1, 1, "Контроль", 50, ["Длинная строка " * 100])
    with pytest.raises(ValueError, match="Примечания"):
        _sheet_end(1, 1, "Контроль", 50, ["Примечание"] * 20)


def test_one_control_sheet_and_models_are_unchanged(tmp_path):
    from app.pz.wastewater_fan_drafting import generate_fan_details_pdf

    full = control_fan_details()
    data = replace(full, valves=(), risers=full.risers[:-1],
                   evidence=replace(full.evidence, terminals=full.evidence.terminals[:1]))
    before = deepcopy(data)
    path = generate_fan_details_pdf(data, str(tmp_path / "single.pdf"))
    assert data == before
    with fitz.open(path) as pdf:
        assert len(pdf) == 1
        check_control_page(pdf[0])
        assert "1 / 1" in pdf[0].get_text()

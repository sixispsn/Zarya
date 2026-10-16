"""Presentation-only control basement checks, including stack reuse."""
from copy import deepcopy
from hashlib import sha256
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest


from app.pz import wastewater_basement_drafting as drafting
from app.pz.generator import generate_wastewater_basement_node_pdf
from tests.test_basement_slope_sign import restore_pre_correction_slope_for_snapshot


@pytest.fixture(autouse=True)
def stable_svg_namespace_for_hashes(monkeypatch):
    # Other renderers register a process-wide default SVG namespace.  Pin only
    # serialization for these byte hashes, keeping their pre-edit values intact.
    monkeypatch.delitem(ET._namespace_map, "http://www.w3.org/2000/svg", raising=False)


@pytest.mark.parametrize("kwargs,expected", [
    ({}, "c62ba77963abe69ab8e0d7dcc8840916d5b229579c2f9a3ec3f51c9b1c1576ce"),
    (dict(basement_floor_elevation_m=-3.2, outlet_invert_elevation_m=-1.75,
          collector_slope_per_mille=20, outlet_dn_mm=150),
     "b29108fe222e7fb41d40fca5ab912985114e4a54fc0f98db3cbc9a9e9303693e"),
])
def test_engineering_fragment_unchanged_and_a3_pdf(tmp_path, kwargs, expected):
    basement = drafting.build_wastewater_basement_assembly(**kwargs)
    before = deepcopy(basement)
    svg = drafting.build_wastewater_basement_control_svg(basement)
    assert basement == before
    root = ET.fromstring(svg)
    assert root.get("data-release-ready") == "false"
    assert not any(e.tag.endswith("rect") and e.get("fill") == "none" for e in root)
    assert not any(e.get("y1") == "935.0" for e in root)
    # Keep the historical body hash; reverse only the independently checked
    # acute-angle/baseline delta in this diagnostic XML copy.
    restore_pre_correction_slope_for_snapshot(root)
    for e in root.iter():
        if e.text in {"отм. пола не задана", "отм. лотка не задана"}:
            e.text = e.text.replace("не задана", "________")
    children = list(root)
    start = next(i for i, e in enumerate(children) if e.get("data-level") == "first-floor")
    end = next(i for i, e in enumerate(children) if "".join(e.itertext()) == "Что проверяет модуль")
    fragment = "".join(ET.tostring(e, encoding="unicode") for e in children[start:end])
    assert sha256(fragment.encode()).hexdigest() == expected
    target = tmp_path / "basement.pdf"
    generate_wastewater_basement_node_pdf(str(target), **kwargs)
    with fitz.open(target) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(420, abs=.01)
        assert page.rect.height / 72 * 25.4 == pytest.approx(297, abs=.01)
        text = page.get_text()
        assert drafting._BASEMENT_CONTROL_NOTICE in text
        assert "Лист 1 из 1" in text
        assert "________" not in text and "Стадия" not in text
        assert not page.get_images()
        for note in drafting._BASEMENT_CONTROL_NOTES:
            assert "".join(note.split()) in "".join(text.split())
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert x0 > 25 and x1 < page.rect.width - 25
            assert y0 > 25 and y1 < page.rect.height - 25


def test_notes_preserve_complete_words_identifiers_and_font():
    for value in ("Длинное пояснение " * 20, "ИДЕНТИФИКАТОР" * 30):
        svg = drafting._basement_control_notes_svg([value], y=20, width=500, bottom=1200)
        root = ET.fromstring(f"<g>{svg}</g>")
        assert "".join("".join(root.itertext()).split()) == "".join(value.split())
        assert all(e.get("font-size") == "18" for e in root)
    with pytest.raises(ValueError, match="не помещаются"):
        drafting._basement_control_notes_svg(["Текст " * 10000])


@pytest.mark.parametrize("field", ["sheet_title", "sheet_subtitle"])
def test_long_header_is_rejected_not_cut(field):
    basement = drafting.build_wastewater_basement_assembly()
    with pytest.raises(ValueError, match="выходит за поле"):
        drafting.build_wastewater_basement_control_svg(basement, **{field: "ДЛИННЫЙ" * 200})


def test_sheet_number_and_stack_integration():
    from app.pz.wastewater_stack_drafting import (
        build_wastewater_stack_assembly, build_wastewater_stack_basement_page_svg,
    )

    basement = drafting.build_wastewater_basement_assembly()
    with pytest.raises(ValueError, match="numbering"):
        drafting.build_wastewater_basement_control_svg(basement, sheet_no=2, sheet_count=1)
    stack = build_wastewater_stack_assembly(floors_above=6, collapse_typical_floors=False)
    svg = build_wastewater_stack_basement_page_svg(stack)
    assert svg.count(drafting._BASEMENT_CONTROL_NOTICE) == 1
    assert svg.count("Лист 3 из 3") == 1
    assert 'data-stack-basement-continuation="from-sheet-2"' in svg
    assert 'width="841mm"' in svg


@pytest.mark.parametrize("failure", ["riser", "outlet", "notes", "convert", "replace"])
def test_failure_preserves_previous_file(tmp_path, monkeypatch, failure):
    target = tmp_path / "basement.pdf"
    target.write_bytes(b"previous pdf")

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    kwargs = {}
    if failure == "riser":
        kwargs["riser_id"] = "СТОЯК" * 500
    elif failure == "outlet":
        kwargs["outlet_id"] = "ВЫПУСК" * 500
    elif failure == "notes":
        monkeypatch.setattr(drafting, "_BASEMENT_CONTROL_NOTES", ("Пояснение " * 10000,))
    elif failure == "convert":
        monkeypatch.setattr(cairosvg, "svg2pdf", fail)
    else:
        monkeypatch.setattr(drafting.os, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        generate_wastewater_basement_node_pdf(str(target), **kwargs)
    assert target.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [target]

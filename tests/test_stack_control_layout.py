"""Non-release stack wrapper; engineering geometry and standalone basement are pinned."""
from copy import deepcopy
from hashlib import sha256
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest


from app.pz import wastewater_stack_drafting as drafting
from app.pz.generator import generate_wastewater_stack_node_pdf
from app.pz.wastewater_basement_drafting import (
    build_wastewater_basement_assembly, build_wastewater_basement_control_svg,
)
from tests.test_basement_slope_sign import restore_pre_correction_slope_for_snapshot


@pytest.fixture(autouse=True)
def stable_svg_namespace_for_hashes(monkeypatch):
    # Other renderers register a process-wide default SVG namespace.  Pin only
    # serialization for these byte hashes, keeping their pre-edit values intact.
    monkeypatch.delitem(ET._namespace_map, "http://www.w3.org/2000/svg", raising=False)


CASES = [
    (dict(floors_above=9), (
        "238e80f6077a7b0f231e1d90592b48d4e4b55fbc0aa73595b911b2aa77c8163a",
        "c0f9279a804225e5d2c2c7570f565e70c6586ce47022a85fddc0ec933fb4cd7c",
    )),
    (dict(floors_above=6, collapse_typical_floors=False), (
        "67bea2dacb6c6a351457ebcaf714cb3f6c6e424780aec6af33ee834341d88a44",
        "7844edbd149aa83b5dee078cc78c3aacbc10bc038fa14bc287fd3c7527de570b",
        "531c21944f9821d17f53a727def07dc464390580adc0ce32de61b12505b343d7",
    )),
]

# Old values above remain evidence of the wrapper-only stage. These three
# exact annotation deltas were compared against the historical renderer;
# all nodes outside slope groups were identical. See floor_annotations_2026-10-16.md.
REVIEWED_SLOPE_DELTAS = {
    "238e80f6077a7b0f231e1d90592b48d4e4b55fbc0aa73595b911b2aa77c8163a":
        "e8019f4bd623f694a805a68015431e7b2e2e8597d97d2ebf7933db05cf142a65",
    "67bea2dacb6c6a351457ebcaf714cb3f6c6e424780aec6af33ee834341d88a44":
        "a912643a8078bebaf5ae0d910434f889cf53171a149ac237dd12c69fcee1a9bb",
    "7844edbd149aa83b5dee078cc78c3aacbc10bc038fa14bc287fd3c7527de570b":
        "65d754e3850ae930bb800047d26a8d5c75bea3f4032f36ffb8028b3fb6444f60",
}


@pytest.mark.parametrize("kwargs,hashes", CASES)
def test_geometry_model_and_paginated_pdf(tmp_path, kwargs, hashes):
    stack = drafting.build_wastewater_stack_assembly(**kwargs)
    before = deepcopy(stack)
    svgs = drafting.build_wastewater_stack_control_svgs(stack)
    assert stack == before
    assert len(svgs) == len(hashes)
    for index, (svg, expected) in enumerate(zip(svgs, hashes)):
        root = ET.fromstring(svg)
        assert root.get("data-release-ready") == "false"
        assert f"Лист {index+1} из {len(hashes)}" in svg
        assert drafting._STACK_CONTROL_NOTICE in svg
        assert not any(e.tag.endswith("rect") and e.get("fill") == "none" for e in root)
        assert not any(e.tag.endswith("line") and e.get("stroke") == "#777" for e in root)
        children = list(root)
        if index < len(stack.pages):
            start = next(i for i, e in enumerate(children) if e.get("data-floor-assembly") is not None)
            end = next(i for i, e in enumerate(children) if "".join(e.itertext()) == "Параметры стояка")
        else:
            restore_pre_correction_slope_for_snapshot(root)
            start = next(i for i, e in enumerate(children) if e.get("data-level") == "first-floor")
            end = next(i for i, e in enumerate(children) if "".join(e.itertext()) == "Что проверяет модуль")
            assert not any(e.get("y1") == "935.0" for e in children)
            # Only the displayed placeholder changed; no elevation was assigned.
            for e in root.iter():
                if e.text in {"отм. пола не задана", "отм. лотка не задана"}:
                    e.text = e.text.replace("не задана", "________")
        fragment = "".join(ET.tostring(e, encoding="unicode") for e in children[start:end])
        assert sha256(fragment.encode()).hexdigest() == REVIEWED_SLOPE_DELTAS.get(expected, expected)
    output = tmp_path / "stack.pdf"
    generate_wastewater_stack_node_pdf(str(output), **kwargs)
    with fitz.open(output) as pdf:
        assert len(pdf) == len(hashes)
        for index, page in enumerate(pdf):
            assert page.rect.width / 72 * 25.4 == pytest.approx(841, abs=.01)
            assert page.rect.height / 72 * 25.4 == pytest.approx(594, abs=.01)
            text = page.get_text()
            assert drafting._STACK_CONTROL_NOTICE in text
            assert f"Лист {index+1} из {len(pdf)}" in text
            assert "________" not in text and "Стадия" not in text
            assert not page.get_images()
            for x0, y0, x1, y1, *_ in page.get_text("words"):
                assert x0 > 35 and x1 < page.rect.width - 35
                assert y0 > 35 and y1 < page.rect.height - 35


def test_standalone_basement_engineering_fragment_is_unchanged():
    svg = build_wastewater_basement_control_svg(build_wastewater_basement_assembly())
    root = ET.fromstring(svg)
    restore_pre_correction_slope_for_snapshot(root)
    for e in root.iter():
        if e.text in {"отм. пола не задана", "отм. лотка не задана"}:
            e.text = e.text.replace("не задана", "________")
    children = list(root)
    start = next(i for i, e in enumerate(children) if e.get("data-level") == "first-floor")
    end = next(i for i, e in enumerate(children) if "".join(e.itertext()) == "Что проверяет модуль")
    fragment = "".join(ET.tostring(e, encoding="unicode") for e in children[start:end])
    # Presentation changed in the basement stage; this pins its pre-edit scene.
    assert sha256(fragment.encode()).hexdigest() == "c62ba77963abe69ab8e0d7dcc8840916d5b229579c2f9a3ec3f51c9b1c1576ce"


def test_wrapping_keeps_complete_text_and_font_size():
    for value in ("Этажи: " + ", ".join(map(str, range(200))), "ИДЕНТИФИКАТОР" * 50):
        svg, _ = drafting._stack_control_text(value, x=0, y=20, width=500, bottom=2000)
        root = ET.fromstring(f"<g>{svg}</g>")
        assert "".join("".join(root.itertext()).split()) == "".join(value.split())
        assert all(e.get("font-size") == "18" for e in root)
    with pytest.raises(ValueError, match="не помещаются"):
        drafting._stack_control_text("Текст " * 1000, x=0, y=20, width=500, bottom=60)


def test_long_floor_lists_are_not_truncated():
    stack = drafting.build_wastewater_stack_assembly(floors_above=150, collapse_typical_floors=False)
    svg = drafting.build_wastewater_stack_page_svg(stack, stack.pages[0])
    text = "".join("".join(ET.fromstring(svg).itertext()).split())
    assert "".join(("Показаны этажи: " + ", ".join(map(str, stack.displayed_floor_numbers))).split()) in text
    assert "".join(("Этажи: " + ", ".join(map(str, stack.revision_floors))).split()) in text


@pytest.mark.parametrize("failure", ["identifier", "outlet", "notes", "convert", "merge", "replace"])
def test_failed_export_keeps_previous_pdf(tmp_path, monkeypatch, failure):
    from pypdf import PdfWriter

    target = tmp_path / "stack.pdf"
    target.write_bytes(b"previous pdf")

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    kwargs = {}
    if failure == "identifier":
        kwargs["riser_id"] = "СТОЯК" * 300
    elif failure == "outlet":
        kwargs["outlet_id"] = "ВЫПУСК" * 300
    elif failure == "notes":
        monkeypatch.setitem(drafting._ROOF_LABELS, "flat_non_accessible", "Кровля " * 10000)
    elif failure == "convert":
        original = cairosvg.svg2pdf
        calls = []

        def second_page_fails(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                fail()
            return original(*args, **kwargs)
        monkeypatch.setattr(cairosvg, "svg2pdf", second_page_fails)
    elif failure == "merge":
        monkeypatch.setattr(PdfWriter, "write", fail)
    else:
        monkeypatch.setattr(drafting.os, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        generate_wastewater_stack_node_pdf(str(target), **kwargs)
    assert target.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [target]

"""Control-sheet guardrails; engineering geometry excludes reviewed slope captions."""
from copy import deepcopy
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest

from app.pz import wastewater_floor_drafting as drafting
from app.pz.generator import generate_wastewater_typical_floor_node_pdf
from tests.test_floor_slope_layout import geometry_digest


# Reviewed schematic room edges/room-caption X only; old hashes retained.
# Evidence: docs/floor_schematic_rooms_2026-10-16.md and the before/after SVG audit.
REVIEWED_ROOM_DELTAS = {
    "f3bbe9a61bccf8d45f2c991a8cb73f631f270bc91bb25f3cfc43d7fc42014f05":
        "f12159c341ae57f52bc07f5e148442e5ebd4b9f2f7a5b30c1a2ea660e39c2646",
    "64dd78889cdf2b867ee7a1cfa6921c0374cdff18a286b70294d4b9897cd24a4b":
        "9018bcf650e1f7d54bca1281b6c6c09d09391a1cec45b375ddb6870c06ff24fa",
}


@pytest.mark.parametrize("floor,elevation,expected", [
    (2, 3., "f3bbe9a61bccf8d45f2c991a8cb73f631f270bc91bb25f3cfc43d7fc42014f05"),
    (10, 27., "64dd78889cdf2b867ee7a1cfa6921c0374cdff18a286b70294d4b9897cd24a4b"),
])
def test_geometry_unchanged_and_nonproject_pdf(tmp_path, floor, elevation, expected):
    assembly = drafting.build_typical_floor_assembly(floor_no=floor, floor_elevation_m=elevation)
    before = deepcopy(assembly)
    svg = drafting.build_typical_floor_control_sheet_svg(assembly)
    assert assembly == before
    fragment = drafting.render_typical_floor_assembly_svg(
        assembly, diagnostics=False, x=112., y=106., scale=2.15)
    assert geometry_digest(fragment) == REVIEWED_ROOM_DELTAS[expected]
    assert fragment in svg
    root = ET.fromstring(svg)
    assert root.get("data-release-ready") == "false"
    assert not any(e.tag.endswith("line") for e in root)
    assert len([e for e in root if e.tag.endswith("rect")]) == 1
    output = tmp_path / "control.pdf"
    generate_wastewater_typical_floor_node_pdf(
        str(output), floor_no=floor, floor_elevation_m=elevation)
    with fitz.open(output) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(297, abs=.01)
        assert page.rect.height / 72 * 25.4 == pytest.approx(210, abs=.01)
        text = page.get_text()
        assert drafting._FLOOR_CONTROL_NOTICE in text
        assert "Лист 1 из 1" in text
        assert "Стадия" not in text and not page.get_images()
        for check in drafting._FLOOR_CONTROL_CHECKS:
            assert "".join(check.split()) in "".join(text.split())
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert x0 >= 25 and x1 <= page.rect.width - 25
            assert y0 >= 25 and y1 <= page.rect.height - 20


def test_wrapping_preserves_words_and_unbroken_identifiers():
    for value in ("Длинное пояснение " * 15, "ОБЪЕКТ" * 40):
        fragment, _ = drafting._floor_control_text(value, x=10, y=20, width=185, bottom=700)
        root = ET.fromstring(f"<g>{fragment}</g>")
        assert "".join("".join(root.itertext()).split()) == "".join(value.split())
        assert all(e.get("font-size") == "12" for e in root)
    with pytest.raises(ValueError, match="не помещаются"):
        drafting._floor_control_text("Текст " * 2000, x=10, y=20, width=185, bottom=100)


@pytest.mark.parametrize("failure", ["notes", "room", "identifier", "geometry", "convert", "replace"])
def test_failure_preserves_previous_pdf(tmp_path, monkeypatch, failure):
    target = tmp_path / "control.pdf"
    target.write_bytes(b"previous pdf")

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    kwargs = {}
    if failure == "notes":
        monkeypatch.setattr(drafting, "_FLOOR_CONTROL_CHECKS", ("Замечание " * 3000,))
    elif failure in {"room", "identifier", "geometry"}:
        fixtures = [
            drafting.FloorFixtureInput("К1-Мой1", "sink", "Кухня"),
            drafting.FloorFixtureInput("К1-Ум1", "washbasin", "Санузел"),
            drafting.FloorFixtureInput("К1-Ун1", "toilet", "Санузел"),
        ]
        if failure == "room":
            fixtures[0] = drafting.FloorFixtureInput("К1-Мой1", "sink", "Очень длинная кухня " * 20)
        elif failure == "identifier":
            fixtures[0] = drafting.FloorFixtureInput("К1-Мой" * 100, "sink", "Кухня")
        else:
            fixtures[1:1] = [drafting.FloorFixtureInput(f"К1-Ван{i}", "bath", "Санузел") for i in range(10)]
        kwargs["fixtures"] = fixtures
    elif failure == "convert":
        monkeypatch.setattr(cairosvg, "svg2pdf", fail)
    else:
        monkeypatch.setattr(drafting.os, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        generate_wastewater_typical_floor_node_pdf(str(target), **kwargs)
    assert target.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [target]


def test_three_fixture_variant_is_supported(tmp_path):
    fixtures = [drafting.FloorFixtureInput("М1", "sink", "Кухня"),
                drafting.FloorFixtureInput("У1", "washbasin", "Санузел"),
                drafting.FloorFixtureInput("Т1", "toilet", "Санузел")]
    target = tmp_path / "three.pdf"
    generate_wastewater_typical_floor_node_pdf(str(target), fixtures=fixtures)
    with fitz.open(target) as pdf:
        assert len(pdf) == 1
        assert "М1" in pdf[0].get_text()

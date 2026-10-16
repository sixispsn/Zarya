"""Schematic partitions must clear appliance ink/captions, never move the graph."""
from copy import deepcopy
from functools import lru_cache
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest

from app.pz import wastewater_floor_drafting as d
from app.pz.leader_layout import _text_width
from app.pz.wastewater_ugo import get_ugo_connection_anchor, render_ugo
from tests.test_floor_slope_layout import three


@lru_cache
def ink_span(kind):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
           + render_ugo(kind, 100, 100) + '</svg>')
    with fitz.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf") as pdf:
        drawings = pdf[0].get_drawings()
        # Include half stroke width, not only the path centreline.
        return (min((r["rect"].x0 - (r.get("width") or 0)/2) / .75 - 100 for r in drawings),
                max((r["rect"].x1 + (r.get("width") or 0)/2) / .75 - 100 for r in drawings))


@pytest.mark.parametrize("kind", list(d._FIXTURE_DEFAULT_DN))
def test_layout_envelope_contains_actual_catalog_ink(kind):
    left, right = ink_span(kind)
    assert -30 <= left < right <= 30


@pytest.mark.parametrize("fixtures", [None, three()])
@pytest.mark.parametrize("scale", [1.25, 2.15])
@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("compact", [False, True])
def test_room_edges_clear_actual_appliances_and_captions(fixtures, scale, mirror, compact):
    model = d.build_typical_floor_assembly(fixtures=fixtures)
    before = deepcopy(model)
    root = ET.fromstring(d.render_typical_floor_assembly_svg(
        model, x=900, y=100, scale=scale, mirror_x=mirror, compact_fixture_annotations=compact))
    direction = -1 if mirror else 1
    rooms = [n for n in root if n.get("data-architecture") == "room"]
    assert [n.get("data-room-name") for n in rooms] == ["Кухня", "Санузел"]
    for fixture in model.fixtures:
        room = next(n for n in rooms if n.get("data-room-name") == fixture.room_label)
        left, right = float(room.get("x")), float(room.get("x")) + float(room.get("width"))
        outlet_x = 900 + direction * model.port(fixture.fixture_outlet_port_id).point.x_mm * scale
        anchor, _ = get_ugo_connection_anchor(fixture.kind)
        ink = [outlet_x + direction * (v-anchor) * d._FIXTURE_SYMBOL_RATIO * scale
               for v in ink_span(fixture.kind)]
        assert left + 1 < min(ink) <= max(ink) < right - 1
        if not compact:
            # Read actual rendered text by outlet coordinate, independently of
            # the layout helper's string construction.
            captions = [n for n in root if n.tag == "text" and n.get("x") == f"{outlet_x:.1f}"
                        and n.get("font-size") == f"{d._FONT_H_2_5:.3f}"]
            assert len(captions) >= 2
            for caption in captions:
                half = _text_width(caption.text, float(caption.get("font-size"))) / 2
                assert left + 1 < outlet_x - half and outlet_x + half < right - 1
    assert model == before

    # A shifted partition must also avoid the fixed cleanout callout text.
    callout = next(e for e in root if e.tag == "text" and e.text == "Прочистка")
    cx = float(callout.get("x"))
    width = _text_width(callout.text, float(callout.get("font-size")))
    for room in rooms:
        for edge in (float(room.get("x")), float(room.get("x")) + float(room.get("width"))):
            assert not cx - 1 < edge < cx + width + 1


def test_no_partition_space_keeps_previous_pdf(tmp_path):
    fixtures = three()
    fixtures[1] = d.FloorFixtureInput("У" * 200, "washbasin", "Санузел")
    target = tmp_path / "previous.pdf"
    target.write_bytes(b"previous verified artifact")
    with pytest.raises(ValueError, match="Нет места для условной границы"):
        d.generate_typical_floor_control_pdf(str(target), fixtures=fixtures)
    assert target.read_bytes() == b"previous verified artifact"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("damage", ["pipe", "caption", "slope_value", "slope_y"])
def test_room_comparison_does_not_hide_other_changes(damage):
    from scripts.verify_floor_annotations import compare_schematic_rooms

    svg = d.render_typical_floor_assembly_svg(d.build_typical_floor_assembly())
    root = ET.fromstring(svg)
    if damage == "pipe":
        next(e for e in root if e.get("data-floor-segment")).set("x1", "999")
    elif damage == "caption":
        next(e for e in root if e.tag == "text" and e.text == "Прочистка").text = "Иное"
    else:
        sign = next(e for e in root if e.get("data-slope-marker"))
        if damage == "slope_value":
            sign.find("text").text = "0,999"
        else:
            sign.find("text").set("y", "999")
    with pytest.raises(AssertionError):
        compare_schematic_rooms(svg, ET.tostring(root).decode())

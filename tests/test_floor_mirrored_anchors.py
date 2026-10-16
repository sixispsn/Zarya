"""Mirror symbols about their own semantic anchors, not about the sheet origin."""
from copy import deepcopy
import re
from xml.etree import ElementTree as ET

import pytest

from app.pz.wastewater_floor_drafting import FloorFixtureInput, build_typical_floor_assembly, render_typical_floor_assembly_svg
from app.pz.wastewater_ugo import get_ugo_connection_anchor


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("scale", [1., 1.25, 2.15])
def test_every_fixture_and_trap_endpoint_coincides_with_graph_port(mirror, scale):
    fixtures = [FloorFixtureInput(str(i), kind, "Санузел") for i, kind in enumerate(
        ("sink", "shower", "bath", "washbasin", "floor_drain", "toilet"))]
    assembly = build_typical_floor_assembly(fixtures=fixtures)
    before = deepcopy(assembly)
    root = ET.fromstring(render_typical_floor_assembly_svg(
        assembly, x=1400, y=100, scale=scale, mirror_x=mirror, render_architecture=False,
    ))
    direction = -1 if mirror else 1

    def expected(port_id):
        point = assembly.port(port_id).point
        return 1400 + direction * point.x_mm * scale, 100 + point.y_mm * scale

    def transformed(symbol, local):
        tx, ty, angle, sx, sy = map(float, re.findall(r"-?\d+(?:\.\d+)?", symbol.get("transform")))
        assert angle == 0 and sy > 0 and (sx < 0) is mirror
        return tx + sx * local[0], ty + sy * local[1]

    for fixture in assembly.fixtures:
        group = next(e for e in root.iter() if e.get("data-floor-fixture") == fixture.fixture_id)
        symbol = next(e for e in group.iter() if e.get("data-ugo") == fixture.kind)
        assert transformed(symbol, get_ugo_connection_anchor(fixture.kind)) == pytest.approx(
            expected(fixture.fixture_outlet_port_id), abs=.02)
        if fixture.trap_mode == "external":
            trap = next(e for e in group.iter() if e.get("data-ugo") == "trap")
            assert trap.find("path").get("d").startswith("M-14,-20")
            assert trap.find("path").get("d").endswith("V20")
            assert transformed(trap, (-14, -20)) == pytest.approx(expected(fixture.trap_inlet_port_id), abs=.02)
            assert transformed(trap, (23, 20)) == pytest.approx(expected(fixture.trap_outlet_port_id), abs=.02)
    arrow = next(e for e in root.iter() if e.get("data-flow-direction") == "collector")
    tail_x, _, tip_x, *_ = map(float, re.findall(r"-?\d+(?:\.\d+)?", arrow.get("d")))
    assert (tip_x < tail_x) is mirror
    label = next(e for e in root.iter() if e.get("data-fitting-label") == "riser_branch_wye_45")
    assert (float(label.get("x")) < expected("riser_join")[0]) is mirror
    assert label.get("text-anchor", "start") == ("end" if mirror else "start")
    assert assembly == before


@pytest.mark.parametrize("scale", [0.28, 0.36, 1.25])
def test_paper_stroke_width_is_identical_after_reflection(scale):
    from app.pz.drawing_sheet_style import apply_residential_paper_style

    widths = []
    for sign in (1, -1):
        svg = (f'<g data-ugo="trap" transform="translate(30 40) scale({sign * scale} {scale})">'
               '<path d="M0,0 L10,10" fill="none" stroke="#000" stroke-width="1.3"/></g>')
        root = ET.fromstring(apply_residential_paper_style(svg))
        path = next(e for e in root.iter() if e.tag.endswith("path"))
        widths.append(float(path.get("stroke-width")) * scale * .5 / (10 / 3))
    assert widths[0] == widths[1]
    assert widths[0] == pytest.approx(.25, abs=.0002)

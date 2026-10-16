"""Only annotation placement/shape changes; flow geometry stays immutable."""
from copy import deepcopy
from hashlib import sha256
import re
from xml.etree import ElementTree as ET

import pytest

from app.pz import wastewater_floor_drafting as d


def geometry_digest(svg):
    root = ET.fromstring(svg)
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    floor = next(e for e in root.iter() if e.get("data-floor-assembly"))
    for parent in floor.iter():
        for child in list(parent):
            if child.get("data-slope-marker"):
                parent.remove(child)
    return sha256(ET.tostring(floor)).hexdigest()


def three():
    return [d.FloorFixtureInput("М1", "sink", "Кухня"),
            d.FloorFixtureInput("У1", "washbasin", "Санузел"),
            d.FloorFixtureInput("Т1", "toilet", "Санузел")]


@pytest.mark.parametrize("fixtures", [three(), None])
@pytest.mark.parametrize("scale", [1., 1.25, 2.15])
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("architecture", [False, True])
def test_slopes_clear_connections_and_preserve_topology(fixtures, scale, mirrored, architecture):
    assembly = d.build_typical_floor_assembly(fixtures=fixtures)
    before = deepcopy(assembly)
    if fixtures is not None and scale == 1 and architecture:
        # At this scale the fixed-height appliance captions leave no safe
        # partition interval, in either direction. Do not shrink or conceal.
        with pytest.raises(ValueError, match="Нет места для условной границы"):
            d.render_typical_floor_assembly_svg(assembly, scale=scale, mirror_x=mirrored,
                                                render_architecture=architecture, x=900, y=100)
        assert assembly == before
        return
    svg = d.render_typical_floor_assembly_svg(assembly, scale=scale, mirror_x=mirrored,
                                             render_architecture=architecture, x=900, y=100)
    assert assembly == before and assembly.validate() == []
    root = ET.fromstring(svg)
    for sign in (e for e in root.iter() if e.get("data-slope-marker")):
        values = list(map(float, re.findall(r"-?\d+(?:\.\d+)?", sign.find("path").get("d"))))
        hx, hy, ax, ay, lx, ly = values
        assert hx == lx and hy < ay and ay == ly
        assert (ax < hx) is mirrored
        assert sign.find("text").text in {"0,030", "0,020"}
        box = d._floor_slope_bounds(sign)
        assert box
        # Independent rectangle/segment check on actual connection strokes.
        for line in root.iter("line"):
            if not (line.get("data-floor-segment") or line.get("data-direct-fitting-joint")
                    or line.get("data-fitting-boundary")):
                continue
            x1, y1, x2, y2 = (float(line.get(k)) for k in ("x1", "y1", "x2", "y2"))
            half = float(line.get("stroke-width")) / 2
            assert (box[2] + 1.8 <= min(x1, x2) - half
                    or max(x1, x2) + half + 1.8 <= box[0]
                    or box[3] + 1.8 <= min(y1, y2) - half
                    or max(y1, y2) + half + 1.8 <= box[1])
    assert d.audit_floor_rendering_conventions(assembly, svg) == ()


@pytest.mark.parametrize("damage", ["chevron", "reverse", "text-touch"])
def test_audit_checks_coordinates_even_when_metadata_claims_success(damage):
    assembly = d.build_typical_floor_assembly(fixtures=three())
    root = ET.fromstring(d.render_typical_floor_assembly_svg(assembly))
    sign = next(e for e in root.iter() if e.get("data-slope-marker"))
    angle = sign.find("path")
    hx, hy, ax, ay, lx, ly = map(float, re.findall(r"-?\d+(?:\.\d+)?", angle.get("d")))
    if damage == "chevron":
        angle.set("d", f"M{hx},{hy} L{ax},{ay} L{lx},{ay + 6}")
    elif damage == "reverse":
        angle.set("d", f"M{hx},{hy} L{hx - 10},{ay} L{lx},{ly}")
    else:
        text = sign.find("text")
        x, y = float(text.get("x")) - 3, float(text.get("y"))
        ET.SubElement(root, "line", {"x1": str(x), "x2": str(x), "y1": str(y - 10),
                                    "y2": str(y), "stroke-width": "3"})
    codes = {row.code for row in d.audit_floor_rendering_conventions(assembly, ET.tostring(root).decode())}
    assert ("slope_annotation_collision" if damage == "text-touch"
            else "invalid_slope_sign_geometry") in codes


def test_no_room_does_not_overwrite_previous_pdf(tmp_path, monkeypatch):
    target = tmp_path / "old.pdf"
    target.write_bytes(b"previous verified artifact")
    monkeypatch.setattr(d, "_floor_annotation_obstacles", lambda svg: ((-10000, -10000, 10000, 10000),))
    with pytest.raises(ValueError, match="Нет свободного места"):
        d.generate_typical_floor_control_pdf(str(target), fixtures=three())
    assert target.read_bytes() == b"previous verified artifact"
    assert list(tmp_path.iterdir()) == [target]

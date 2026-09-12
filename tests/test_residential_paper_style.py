"""Regression checks on physical output, not just style metadata."""

from math import hypot, sqrt
import re
from xml.etree import ElementTree as ET

import pytest
from app.pz.leader_layout import _text_width

from app.pz.wastewater_building_drafting import (
    build_residential_wastewater_reference_svg,
)
from tests.test_wastewater_building_drafting import _demo_assembly


def _numbers(value):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", value)]


def _physical_elements(row, scale=1):
    transform = row.get("transform", "")
    for values in re.findall(r"scale\(([^)]+)\)", transform):
        scale *= abs(float(values.split()[0]))
    for values in re.findall(r"matrix\(([^)]+)\)", transform):
        a, b, c, d, _, _ = map(float, re.split(r"[ ,]+", values.strip()))
        scale *= sqrt(abs(a * d - b * c))
    yield row, scale
    for child in row:
        yield from _physical_elements(child, scale)


@pytest.fixture(scope="module")
def sheet():
    return ET.fromstring(build_residential_wastewater_reference_svg(_demo_assembly()))


def test_cut_mask_uses_exact_same_boundary_and_has_ten_mm_tails(sheet):
    cut = next(x for x in sheet.iter() if x.get("data-building-section-break"))
    upper = next(x for x in cut if x.get("data-section-break-line") == "upper")
    lower = next(x for x in cut if x.get("data-section-break-line") == "lower")
    mask = next(x for x in cut if x.get("data-section-break-mask"))
    u, low, m = (_numbers(x.get("d")) for x in (upper, lower, mask))
    assert m[: len(u)] == u
    assert list(zip(m[len(u) :: 2], m[len(u) + 1 :: 2])) == list(
        reversed(list(zip(low[::2], low[1::2])))
    )
    assert (230 - u[0]) * 0.5 / (10 / 3) == pytest.approx(10, abs=0.001)
    assert (u[-2] - 2440) * 0.5 / (10 / 3) == pytest.approx(10, abs=0.001)
    extensions = [r for r in cut if r.get("data-section-partition-extension")]
    assert len(extensions) >= 16
    for r in extensions:
        assert r.get("x1") == r.get("x2")
        if r.get("data-section-partition-extension") == "upper":
            assert float(r.get("y2")) >= max(u[1::2])
        else:
            assert float(r.get("y1")) <= min(low[1::2])


def test_actual_text_heights_survive_half_scale_embedding(sheet):
    checked = []
    for layer in (r for r in sheet if r.get("data-residential-layer")):
        for row, scale in _physical_elements(layer):
            if row.tag.rsplit("}", 1)[-1] != "text":
                continue
            height = float(row.get("font-size")) * 0.823 * scale / (10 / 3)
            assert height >= 2.5 - 0.001, row.text
            if row.get("data-paper-text-height-mm") == "3.5":
                assert height == pytest.approx(3.5, abs=0.001)
            checked.append(height)
    assert len(checked) > 80


def test_slopes_have_horizontal_lower_arm_and_match_dimension_height(sheet):
    slopes = [r for r in sheet.iter() if r.get("data-slope-marker")]
    assert len(slopes) == 16
    for slope in slopes:
        path = next(r for r in slope if r.tag.rsplit("}", 1)[-1] == "path")
        text = next(r for r in slope if r.tag.rsplit("}", 1)[-1] == "text")
        coordinates = _numbers(path.get("d"))
        assert coordinates[3] == coordinates[5]
        assert coordinates[1] < coordinates[3]
        assert float(text.get("font-size")) * 0.823 * 0.5 / (10 / 3) == pytest.approx(
            3.5, abs=0.001
        )


def test_reducer_flat_side_meets_inlet_socket_of_larger_wye(sheet):
    systems = [r for r in sheet.iter() if r.get("data-basement-system")]
    for system in systems:
        transition = next(r for r in system if r.get("data-building-transition"))
        triangle = next(r for r in transition if r.get("data-diameter-transition"))
        points = _numbers(triangle.get("d"))
        flat = ((points[0] + points[4]) / 2, (points[1] + points[5]) / 2)
        wye = next(
            r for r in system.iter() if r.get("data-fitting") == "through_wye_45"
        )
        tick = _numbers(wye.get("d"))
        socket = ((tick[0] + tick[2]) / 2, (tick[1] + tick[3]) / 2)
        assert hypot(flat[0] - socket[0], flat[1] - socket[1]) < 0.1
        assert points[2] < flat[0]  # smaller-DN apex is upstream
        assert wye.get("data-fitting-size-dn") == "150"


def test_leaders_and_imported_vector_symbols_keep_thin_line_weight(sheet):
    leaders = [r for r in sheet.iter() if r.get("data-leader-line")]
    assert len(leaders) == 6
    for leader in leaders:
        assert float(leader.get("stroke-width")) / (10 / 3) == pytest.approx(
            0.25, abs=0.001
        )
    vectors = []
    for row, scale in _physical_elements(sheet):
        if row.get("data-paper-line-width-mm") != "0.25":
            continue
        width = float(row.get("stroke-width")) * scale / (10 / 3)
        assert width == pytest.approx(0.25, abs=0.001)
        vectors.append(width)
    assert len(vectors) > 100


def test_large_slope_labels_do_not_overlap_fixture_quantities(sheet):
    def text_box(text):
        size = float(text.get("font-size"))
        x, y = float(text.get("x")), float(text.get("y"))
        width = _text_width(text.text or "", size)
        anchor = text.get("text-anchor", "start")
        left = (
            x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
        )
        return left, y - size, left + width, y + size * 0.22

    for floor in (r for r in sheet.iter() if r.get("data-floor-assembly")):
        quantities = [
            text_box(r)
            for r in floor
            if r.get("data-floor-fixture-quantity") or r.text == "Прочистка"
        ]
        for slope in (r for r in floor if r.get("data-slope-marker")):
            text = next(r for r in slope if r.tag.rsplit("}", 1)[-1] == "text")
            path = next(r for r in slope if r.tag.rsplit("}", 1)[-1] == "path")
            coords = _numbers(path.get("d"))
            a, b, c, d = text_box(text)
            bounds = (
                min(a, min(coords[::2])),
                min(b, min(coords[1::2])),
                max(c, max(coords[::2])),
                max(d, max(coords[1::2])),
            )
            for q in quantities:
                assert (
                    bounds[2] <= q[0]
                    or bounds[0] >= q[2]
                    or bounds[3] <= q[1]
                    or bounds[1] >= q[3]
                )

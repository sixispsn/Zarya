"""Full lower-node annotations stay readable without changing the pipe drawing."""
from copy import deepcopy
import re
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest

from app.pz.basement_callout_layout import (
    callout_geometry, clear, distinct_departure, hits_box,
    layout_basement_callouts, obstacles, text_box,
)
from app.pz.wastewater_building_drafting import (
    build_wastewater_building_assembly, build_wastewater_building_svgs,
    generate_wastewater_building_pdf_from_project,
)
from app.pz.wastewater_project_inputs import resolve_wastewater_building_project_inputs
from tests.test_wastewater_building_drafting import _project_with_linear_riser_count
from tests.test_wastewater_visual_golden import _production_svgs


def groups(root):
    return [n for n in root.iter() if n.get("data-lower-node-callout")]


def assert_clear(svg):
    root = ET.fromstring(svg)
    lines, boxes = obstacles(root)
    for group in groups(root):
        segments, candidates = callout_geometry(group)
        assert clear(segments, candidates, lines, boxes), group.attrib
        assert not any(hits_box(*segments[0], box) for box in candidates)
        assert distinct_departure(segments[0], lines)
        lines.extend(segments)
        boxes.extend(candidates)


@pytest.mark.parametrize("count", [1, 2, 5])
def test_paginated_callouts_clear_and_all_nonplacement_content_unchanged(count):
    project = _project_with_linear_riser_count(count)
    assembly = build_wastewater_building_assembly(
        resolve_wastewater_building_project_inputs(project),
        floor_height_m=3, roof_kind="flat_non_accessible",
    )
    before = deepcopy(assembly)
    with patch("app.pz.basement_callout_layout.layout_basement_callouts", side_effect=lambda s: s):
        originals = build_wastewater_building_svgs(assembly)
    current = build_wastewater_building_svgs(assembly)
    assert assembly == before
    pattern = r'<g data-lower-node-callout="[^>]+>.*?</g>'
    for old, new in zip(originals, current, strict=True):
        # All geometry and annotations outside these groups are BYTE identical.
        assert re.sub(pattern, "", old) == re.sub(pattern, "", new)
        for a, b in zip(groups(ET.fromstring(old)), groups(ET.fromstring(new)), strict=True):
            assert a.attrib == b.attrib  # including target coordinates and IDs
            assert len(a) == len(b) == 4
            for x, y in zip(a, b, strict=True):
                assert x.tag == y.tag and x.text == y.text
                allowed = {"d"} if x.tag.endswith("path") else {"x", "y"}
                assert {k: v for k, v in x.attrib.items() if k not in allowed} == {
                    k: v for k, v in y.attrib.items() if k not in allowed
                }
        assert_clear(new)


def test_old_k2_collision_is_detected_and_repaired():
    from scripts.audit_wastewater_visual_golden import restore_basement_callout_positions
    svg = _production_svgs()["k1-k2"][1]
    root = ET.fromstring(svg)
    restore_basement_callout_positions(root)
    lines, boxes = obstacles(root)
    old = next(g for g in groups(root) if g.get("data-lower-node-callout") == "К2-ПрНП1")
    segments, candidates = callout_geometry(old)
    assert not clear(segments, candidates, lines, boxes)
    assert_clear(svg)


def test_crowded_layout_fails_without_overwriting_previous_pdf(tmp_path):
    output = tmp_path / "previous.pdf"
    output.write_bytes(b"previous output")
    with patch("app.pz.basement_callout_layout.clear", return_value=False):
        with pytest.raises(ValueError, match="cannot place complete basement callout"):
            generate_wastewater_building_pdf_from_project(
                str(output), _project_with_linear_riser_count(5),
                floor_height_m=3, roof_kind="flat_non_accessible",
            )
    assert output.read_bytes() == b"previous output"


def test_unsupported_sheet_is_not_silently_relaid_out():
    with pytest.raises(ValueError, match="ordinary basement"):
        layout_basement_callouts(_production_svgs()["k1-k2"][0])


def test_pressure_caption_outside_plot_and_note_box_removed():
    scheme, curve = map(ET.fromstring, _production_svgs()["pressure"])
    assert not any(n.get("x") == "170" and n.get("y") == "1160"
                   and n.tag.endswith("rect") for n in scheme.iter())
    wp = next(n for n in curve if n.get("data-working-point"))
    caption = wp[-1]
    box = text_box(caption)
    assert box[0] > 1670 and box[1] > 420 and box[3] < 480
    assert caption.text == "РТ: Q=4,00; H=6,00"
    assert wp[-2].get("cx") == "1126.5"  # reviewed marker did not move


@pytest.mark.parametrize("line", [((0, 0), (100, 1)), ((0, 0), (100, 0))])
def test_nearly_coincident_departure_is_rejected(line):
    assert not distinct_departure(((0, 0), (100, 0)), [line])
    assert distinct_departure(((0, 0), (0, 100)), [line])

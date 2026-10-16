"""Additional body-only evidence, NOT approval/replacement of full-page goldens.

These hashes were independently reproduced from the unchanged historical full
goldens by audit_wastewater_visual_golden.py. No Git history needed in CI.
"""
from copy import deepcopy
import hashlib
import json
from xml.etree import ElementTree as ET

import pytest

from scripts.audit_wastewater_visual_golden import (
    GOLDEN_SHA256, HISTORICAL_GOLDEN, REVIEWED_BODY_DELTAS, body_without_known_presentation,
)
from tests.test_wastewater_visual_golden import _production_svgs


HISTORICAL_BODIES = {
    ("k1-k2", 1): "2e044fe67b63b0e7178e389b8a2e7997d2a75598f484185b37180b549c6e6ef7",
    ("k1-k2", 2): "4dff82593a6abec92eda5d251b5d05ef589b578509403a49394247719f52ac42",
    ("residential", 1): "6447a2a20a3843e7e0828d34f1ecf8c43c99ecc536b29c2583130d9c455a42a7",
    ("k3", 1): "87ebde5012d80543abf65bc657b776a6a6732d19d625a3a6e8673912bd6a2b95",
    ("k3", 2): "02d1b9c20a5c28743a7243ca5e7adc4c5e9e1b67ad512cd5f373a3f641426288",
    ("pressure", 1): "8c2deee2fdf19bfec03cd6aa6e7ee02c7d202dac5b3cf55d79a0a6ebee3b86f0",
    ("pressure", 2): "e395c4afb857fec8e3a8ff02021f1b7438f4f6d2a4f0701dbf3bcfcf8ee3f69e",
}


def test_historical_full_golden_archive_is_immutable():
    assert hashlib.sha256(HISTORICAL_GOLDEN.read_bytes()).hexdigest() == GOLDEN_SHA256


def test_floor_annotation_review_changes_exactly_two_full_snapshots():
    archive = HISTORICAL_GOLDEN.with_name("wastewater_graphics.pre-2026-10-16-floor-annotations.json")
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == (
        "a64c3cd14fcdfdffc3e9950a81491a6e25f5221f08da3f5f28062b0d34a99daa"
    )
    before = json.loads(archive.read_text())
    after = json.loads((archive.parent.parent / "wastewater_graphics.json").read_text())
    assert before.keys() == after.keys()
    changed = set()
    for kind in before:
        for page, (old, new) in enumerate(zip(before[kind], after[kind], strict=True), 1):
            if old != new:
                changed.add((kind, page))
    assert changed == set(REVIEWED_BODY_DELTAS)


@pytest.fixture(scope="module")
def pages():
    return _production_svgs()


@pytest.mark.parametrize("kind,page", HISTORICAL_BODIES)
def test_engineering_body_matches_historical_or_exact_reviewed_delta(pages, kind, page):
    digest, _ = body_without_known_presentation(
        pages[kind][page - 1], kind=kind, page=page, historical=False,
    )
    reviewed = REVIEWED_BODY_DELTAS.get((kind, page))
    if reviewed:
        assert reviewed[0] == HISTORICAL_BODIES[kind, page]
    assert digest == (reviewed[1] if reviewed else HISTORICAL_BODIES[kind, page])


@pytest.mark.parametrize("mutation", ["table_value", "table_line", "pipe", "note", "extra_line", "callout_text", "callout_target"])
def test_audit_does_not_hide_changes_outside_named_decorations(pages, mutation):
    kind, page = ("pressure", 2) if mutation.startswith("table") else ("k1-k2", 1)
    if mutation.startswith("callout"):
        page = 2
    root = ET.fromstring(pages[kind][page - 1])
    if mutation.startswith("table"):
        table = next(n for n in root if n.get("data-pressure-calculation-table"))
        node = table[7] if mutation == "table_value" else table[5]
        if mutation == "table_value":
            node.text = "999 м³/ч"
        else:
            node.set("y1", "999")
    elif mutation.startswith("callout"):
        group = next(n for n in root.iter() if n.get("data-lower-node-callout"))
        if mutation == "callout_text":
            group[-1].text += " CHANGED"
        else:
            group.set("data-callout-target-x", "999")
    elif mutation == "pipe":
        group = next(n for n in root.iter() if n.get("data-building-pipe-line"))
        group[0].set("x1", "999")
    elif mutation == "note":
        node = next(n for n in root if (n.text or "").startswith("Все показанные приборы"))
        node.text += " CHANGED"
    else:
        ET.SubElement(root, "{http://www.w3.org/2000/svg}line", {"x1": "80", "y1": "1694"})
    digest, _ = body_without_known_presentation(
        ET.tostring(root, encoding="unicode"), kind=kind, page=page, historical=False,
    )
    reviewed = REVIEWED_BODY_DELTAS.get((kind, page))
    assert digest != (reviewed[1] if reviewed else HISTORICAL_BODIES[kind, page])


def test_duplicate_frame_is_not_ignored(pages):
    root = ET.fromstring(pages["k1-k2"][0])
    root.append(deepcopy(next(n for n in root if n.get("data-title-block"))))
    with pytest.raises(AssertionError, match="exactly one title block"):
        body_without_known_presentation(
            ET.tostring(root, encoding="unicode"), kind="k1-k2", page=1, historical=False,
        )

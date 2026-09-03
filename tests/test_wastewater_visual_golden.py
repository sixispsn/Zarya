"""Approved vector-layout snapshots for every production IOS3 scheme.

The snapshot is based on normalized SVG geometry and text rather than PDF
bytes, so it is stable across Cairo/Pango versions.  Every page is also
rasterized in the test to catch invalid SVG that merely has a stable digest.
Updating the golden file is an explicit drawing-review action.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from xml.etree import ElementTree

import cairosvg

from app.pz.wastewater_building_drafting import build_wastewater_building_svgs
from app.pz.wastewater_k3_drafting import build_wastewater_k3_svgs
from app.pz.wastewater_k3_project_inputs import (
    resolve_wastewater_k3_project_inputs,
)
from app.pz.wastewater_pressure_drafting import build_wastewater_pressure_svgs
from app.pz.wastewater_pressure_project_inputs import (
    resolve_wastewater_pressure_project_inputs,
)
from tests.test_wastewater_building_drafting import _demo_assembly
from tests.test_wastewater_k3_scheme import _k3_project
from tests.test_wastewater_pressure_scheme import _pressure_project


GOLDEN = Path(__file__).parent / "golden" / "wastewater_graphics.json"


def _visual_digest(svg: str) -> str:
    rows = []
    for element in ElementTree.fromstring(svg).iter():
        tag = element.tag.rsplit("}", 1)[-1]
        attributes = tuple(sorted(
            (
                key.rsplit("}", 1)[-1],
                " ".join(value.split()),
            )
            for key, value in element.attrib.items()
        ))
        text = " ".join((element.text or "").split())
        rows.append((tag, attributes, text))
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _production_svgs() -> dict[str, tuple[str, ...]]:
    k3_project = _k3_project()
    pressure_project = _pressure_project()
    return {
        "k1-k2": build_wastewater_building_svgs(_demo_assembly()),
        "k3": build_wastewater_k3_svgs(
            k3_project,
            resolve_wastewater_k3_project_inputs(k3_project),
        ),
        "pressure": build_wastewater_pressure_svgs(
            pressure_project,
            resolve_wastewater_pressure_project_inputs(pressure_project),
        ),
    }


def test_production_wastewater_schemes_match_approved_visual_golden():
    approved = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = {
        key: [_visual_digest(page) for page in pages]
        for key, pages in _production_svgs().items()
    }

    assert actual == approved


def test_every_approved_page_rasterizes_without_artifacts_from_invalid_svg():
    for pages in _production_svgs().values():
        for svg in pages:
            png = cairosvg.svg2png(
                bytestring=svg.encode("utf-8"),
                output_width=420,
                output_height=297,
            )
            assert png.startswith(b"\x89PNG\r\n\x1a\n")
            assert struct.unpack(">II", png[16:24]) == (420, 297)

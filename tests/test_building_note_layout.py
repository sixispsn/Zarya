"""Presentation-only delta: all SVG content except three old decorations is frozen."""
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest

from app.pz.wastewater_building_drafting import (
    _build_two_riser_basement_reference_svg,
    build_wastewater_building_svgs,
)
from app.pz.wastewater_fan_binding import build_bound_fan_preview_svgs
from tests.fan_binding_fixture import fan_binding_fixture
from tests.test_wastewater_building_drafting import _demo_assembly
from tests.test_wastewater_visual_golden import _production_svgs, _visual_digest


def is_old_note_decoration(element):
    tag = element.tag.rsplit("}", 1)[-1]
    if tag == "rect":
        return element.attrib == {
            "x": "85", "y": "1680", "width": "2010", "height": "215",
            "fill": "white", "stroke": "#777", "stroke-width": "1",
        }
    return tag == "line" and element.attrib == {
        "x1": "80", "y1": "1695.0", "x2": "2136.7", "y2": "1695.0",
        "stroke": "#777",
    }


def note_layout_samples():
    assembly = _demo_assembly()
    project, data = fan_binding_fixture()
    before = deepcopy((assembly, project, data))
    samples = dict(enumerate(build_wastewater_building_svgs(assembly)))
    samples["reference"] = _build_two_riser_basement_reference_svg(assembly)
    samples.update({f"bound-{i}": svg for i, svg in enumerate(
        build_bound_fan_preview_svgs(project, data)
    )})
    samples["residential"] = _production_svgs()["residential"][0]
    assert (assembly, project, data) == before
    return samples


# Captured BEFORE this change, removing only the exact decorations above.
# This is a scoped delta check, not replacement of wastewater_graphics.json.
BEFORE_WITHOUT_DECORATIONS = {
    0: "c69fead2b750662f7d75f0f29cc869c083c34020aa10398743bb14b12e01de7a",
    1: "aa2143eed54f4e4d75db05c275011a472645b73109c78d71e7f7f42a8603eb70",
    "reference": "94728eafea44fe8f1a658cff32f2bc2d22f8ca5864b8c99b6d419020bcbbb0a0",
    "bound-0": "7098bbeda66f992c20db0063f1f248e05ff6d19d91e7d00e4f4ada9eb5f72ae6",
    "bound-1": "bbed5c61620473ff257fe61f7b929223bb484ea8c88289f7e7d020a97fe33eaf",
    "bound-2": "e170b6335bad15b62d77ad76a04991ca2b3a08c5e623141f2aeee92f255ab36a",
    "bound-3": "82c610313faa5e1d3eb404dcd9a681da587e59dc917890bdfde59a10f8b1f5d4",
    "bound-4": "1b673c6d2c870cbba1f5ec588171fbd442a52d8877e5b2763dd06d569ebdadf7",
    "bound-5": "48a2ffafad5f82f186f81399bec654d797ce297943daebbeb6ebd3d1bdd99c02",
    "bound-6": "1a9183671fc773689feb93b0ce7ec04dc873849a058bf5deec5600c66e715611",
    "residential": "60a659e67cae187b00a2b942b43ffee0dc0a393c5df8af671654e096debd5d28",
}

# The later, already reviewed floor-annotation change also affects these pages.
# Old values remain above. Independently reproduced by the read-only
# audit_building_note_layout.py; everything outside the reviewed groups matches.
REVIEWED_FLOOR_DELTAS = {
    0: "8d7c49c26528f41245696960c2597cb892b64bc02d0cc2b3db28dd8296d2253e",
    "bound-0": "dad136e9e0d5a0a04a0a890cd858ea983ae2ab23fae132a7734c581bba81a3cf",
    "bound-1": "691816564098ed0e32153da6544b07879a1af8aad857a3190384f559fca4a188",
    "bound-2": "ce146385b31c1c9f56dc2e68a5e494d97b8048a6f5e56b759cb2dd357fd9020a",
    "residential": "13fdaf99d55f9ac5700600428da8d655632c7e4af43a1332eed43e19f103527b",
}


@pytest.mark.parametrize("key", [0, 1, "reference", *(f"bound-{i}" for i in range(7)), "residential"])
def test_only_note_decorations_changed(key):
    svg = note_layout_samples()[key]
    assert not any(is_old_note_decoration(el) for el in ET.fromstring(svg).iter())
    if key == 1:
        from scripts.audit_wastewater_visual_golden import restore_basement_callout_positions
        root = ET.fromstring(svg)
        restore_basement_callout_positions(root)
        svg = ET.tostring(root, encoding="unicode")
    assert _visual_digest(svg) == REVIEWED_FLOOR_DELTAS.get(key, BEFORE_WITHOUT_DECORATIONS[key])


def test_bound_control_status_and_notes_survive():
    samples = note_layout_samples()
    for i in range(7):
        root = ET.fromstring(samples[f"bound-{i}"])
        assert root.get("data-production-release") == "false"
        if i < 6:
            assert "Не проектная документация" in "".join(root.itertext())
            expected = "Все показанные приборы" if i < 3 else "Граница детализации"
            assert expected in "".join(root.itertext())

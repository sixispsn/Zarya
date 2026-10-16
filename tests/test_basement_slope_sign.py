"""Actual coordinates, not metadata alone, guard the basement slope sign."""
from copy import deepcopy
import re
from xml.etree import ElementTree as ET

import pytest

from app.pz.wastewater_basement_drafting import (
    build_wastewater_basement_assembly, build_wastewater_basement_control_svg,
)
from app.pz.wastewater_stack_drafting import (
    build_wastewater_stack_assembly, build_wastewater_stack_basement_page_svg,
)


def checked_slope(root):
    signs = [e for e in root.iter() if e.get("data-basement-slope")]
    assert len(signs) == 1
    sign = signs[0]
    path, text = list(sign)
    assert path.tag.rsplit("}", 1)[-1] == "path"
    assert text.tag.rsplit("}", 1)[-1] == "text"
    assert sign.get("data-sign-shape") == "acute-angle"
    assert sign.get("data-lower-leg-horizontal") == "true"
    assert sign.get("data-label-underline") == "false"
    values = re.fullmatch(r"M(-?[\d.]+),(-?[\d.]+) L(-?[\d.]+),(-?[\d.]+) L(-?[\d.]+),(-?[\d.]+)", path.get("d"))
    assert values
    hx, hy, ax, ay, lx, ly = map(float, values.groups())
    assert hx == lx and hy == pytest.approx(ay - 6) and ly == ay
    assert ax == pytest.approx(hx + 10)  # this control module always flows right
    assert path.get("fill") == "none" and path.get("stroke-width") == "1.3"
    assert float(text.get("x")) == pytest.approx(hx - 5)
    assert float(text.get("y")) == pytest.approx(ay - 2)
    assert text.get("text-anchor") == "end" and text.get("font-size") == "12"
    return sign, path, text, hx, ay, ax


def restore_pre_correction_slope_for_snapshot(root):
    """Diagnostic copy only: reverse precisely the checked presentation delta.

    Retains position, text, font and every other SVG node. Existing full-body
    hashes still reject unrelated changes; checked_slope rejects shape changes.
    Never called by a production renderer.
    """
    sign, path, text, hx, ay, ax = checked_slope(root)
    del sign.attrib["data-sign-shape"]
    del sign.attrib["data-lower-leg-horizontal"]
    path.set("d", f"M{hx:.1f},{ay-6:.1f} L{ax:.1f},{ay:.1f} L{hx:.1f},{ay+6:.1f}")
    text.set("y", f"{ay+3.5:.1f}")


@pytest.mark.parametrize("slope,label,status", [(None, "уклон не задан", "required"),
                                             (20, "0,020", "confirmed"),
                                             (12.5, "0,013", "confirmed")])
@pytest.mark.parametrize("dn", [100, 150])
def test_basement_sign_geometry_value_and_model(slope, label, status, dn):
    model = build_wastewater_basement_assembly(collector_slope_per_mille=slope, outlet_dn_mm=dn)
    before = deepcopy(model)
    root = ET.fromstring(build_wastewater_basement_control_svg(model))
    assert model == before
    sign, _, text, hx, ay, ax = checked_slope(root)
    assert text.text == label and sign.get("data-slope-status") == status
    assert root.get("data-release-ready") == "false"
    lines = [e for e in root.iter() if e.get("data-basement-segment") in
             {"collector_main", "collector_to_sleeve"}]
    assert len(lines) == 2
    left = min(float(e.get("x1")) for e in lines)
    right = max(float(e.get("x2")) for e in lines)
    assert left < hx < ax < right
    assert ay + 1 < min(float(e.get("y1")) for e in lines)


@pytest.mark.parametrize("floors", [6, 9])
def test_stack_reuses_corrected_sign_without_model_changes(floors):
    model = build_wastewater_stack_assembly(floors_above=floors, collapse_typical_floors=floors == 9)
    before = deepcopy(model)
    checked_slope(ET.fromstring(build_wastewater_stack_basement_page_svg(model)))
    assert model == before


@pytest.mark.parametrize("damage", ["chevron", "reverse", "baseline"])
def test_snapshot_normalization_does_not_conceal_bad_shape(damage):
    root = ET.fromstring(build_wastewater_basement_control_svg(build_wastewater_basement_assembly()))
    _, path, text, hx, ay, ax = checked_slope(root)
    if damage == "chevron":
        path.set("d", f"M{hx},{ay-6} L{ax},{ay} L{hx},{ay+6}")
    elif damage == "reverse":
        path.set("d", f"M{hx},{ay-6} L{hx-10},{ay} L{hx},{ay}")
    else:
        text.set("y", str(ay+3.5))
    with pytest.raises(AssertionError):
        restore_pre_correction_slope_for_snapshot(root)

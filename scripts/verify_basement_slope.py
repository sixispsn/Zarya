"""Render bounded basement slope QA; never accept or overwrite production goldens."""
# ruff: noqa: E402 -- repository script bootstrap
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.wastewater_basement_drafting import (
    build_wastewater_basement_assembly, build_wastewater_basement_control_svg,
)
from app.pz.wastewater_stack_drafting import (
    build_wastewater_stack_assembly, build_wastewater_stack_basement_page_svg,
)


def outside_slope(svg):
    root = ET.fromstring(svg)
    signs = [e for e in root.iter() if e.get("data-basement-slope")]
    assert len(signs) == 1
    for parent in root.iter():
        if signs[0] in list(parent):
            parent.remove(signs[0])
            break
    return ET.tostring(root)


def main(output, baseline=None):
    output.mkdir(parents=True, exist_ok=False)
    ensure_drafting_font_registered()
    models, svgs = {}, {}
    for name, kwargs in (
        ("unknown", {}),
        ("confirmed20", dict(collector_slope_per_mille=20, outlet_dn_mm=150,
                             basement_floor_elevation_m=-3.2, outlet_invert_elevation_m=-1.75)),
        ("confirmed12_5", dict(collector_slope_per_mille=12.5)),
    ):
        model = build_wastewater_basement_assembly(**kwargs)
        models[name] = asdict(model)
        svgs[name] = build_wastewater_basement_control_svg(model)
    for floors in (6, 9):
        name = f"stack{floors}"
        model = build_wastewater_stack_assembly(floors_above=floors, collapse_typical_floors=floors == 9)
        models[name] = asdict(model)
        svgs[name] = build_wastewater_stack_basement_page_svg(model)
    serialized = json.dumps(models, ensure_ascii=False, indent=2) + "\n"
    (output / "models.json").write_text(serialized)
    for name, svg in svgs.items():
        (output / f"{name}.svg").write_text(svg)
        cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(output / f"{name}.pdf"))
    if baseline:
        assert (baseline / "models.json").read_text() == serialized
        for name, svg in svgs.items():
            assert outside_slope((baseline / f"{name}.svg").read_text()) == outside_slope(svg), name
        report = dict(models_unchanged=True, outside_slope_unchanged=list(svgs),
                      baseline=str(baseline), current=str(output))
        (output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    main(args.output, args.baseline)

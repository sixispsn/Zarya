"""Reproduce floor annotation cases without changing a project or accepting goldens."""
# ruff: noqa: E402 -- repository bootstrap
import argparse
from dataclasses import asdict
from io import BytesIO
import json
import re
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairosvg
from pypdf import PdfReader, PdfWriter
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.wastewater_floor_drafting import (
    FloorFixtureInput, build_typical_floor_assembly, build_typical_floor_control_sheet_svg,
    render_typical_floor_assembly_svg,
)
from tests.test_wastewater_visual_golden import _production_svgs, _visual_digest


def _unreviewed_geometry(svg):
    root = ET.fromstring(svg)
    for parent in root.iter():
        for child in list(parent):
            if ((child.get("data-slope-marker") and child.get("data-first-segment"))
                    or child.get("data-floor-fixture")
                    or child.get("data-flow-direction") == "collector"
                    or child.get("data-fitting-label") == "riser_branch_wye_45"):
                parent.remove(child)
    return ET.tostring(root)


def _outside_schematic_rooms(svg):
    root = ET.fromstring(svg)
    for parent in root.iter():
        children = list(parent)
        for i, child in enumerate(children):
            if child.get("data-architecture") == "room":
                assert child.get("data-geometry-source") == "schematic-fixture-groups"
                label = children[i + 1]
                assert label.tag.rsplit("}", 1)[-1] == "text"
                assert label.text == child.get("data-room-name")
                parent.remove(child)
                parent.remove(label)
    return ET.tostring(root)


def compare_schematic_rooms(before, after):
    """Compare all other content; allow at most one SVG rounding step in slope X.

    A room edge reconstructed as rounded x+width can vary by 0.1 after a
    partition move. Check the complete rigid translation before normalizing
    it in this diagnostic copy; never ignore a whole slope group.
    """
    old, new = (ET.fromstring(_outside_schematic_rooms(svg)) for svg in (before, after))
    old_signs = [e for e in old.iter() if e.get("data-slope-marker")]
    new_signs = [e for e in new.iter() if e.get("data-slope-marker")]
    translated = []
    for a, b in zip(old_signs, new_signs, strict=True):
        assert a.attrib == b.attrib
        if ET.tostring(a) == ET.tostring(b):
            continue
        pa, ta = list(a)
        pb, tb = list(b)
        av, bv = (list(map(float, re.findall(r"-?\d+(?:\.\d+)?", p.get("d")))) for p in (pa, pb))
        assert len(av) == len(bv) == 6
        dx = bv[0] - av[0]
        assert abs(dx) <= .10001
        assert all(abs((v-u) - (dx if i % 2 == 0 else 0)) < .00001
                   for i, (u, v) in enumerate(zip(av, bv, strict=True)))
        assert abs(float(tb.get("x")) - float(ta.get("x")) - dx) < .00001
        pb.set("d", pa.get("d"))
        tb.set("x", ta.get("x"))
        assert ET.tostring(a) == ET.tostring(b)
        translated.append(dict(sign=a.get("data-slope-marker"), dx=round(dx, 3)))
    assert ET.tostring(old) == ET.tostring(new)
    return translated


def main(output, baseline=None, review="floor-annotations"):
    output.mkdir(parents=True, exist_ok=True)
    ensure_drafting_font_registered()
    three = [FloorFixtureInput("М1", "sink", "Кухня"),
             FloorFixtureInput("У1", "washbasin", "Санузел"),
             FloorFixtureInput("Т1", "toilet", "Санузел")]
    six = [*three[:1], FloorFixtureInput("Д1", "shower", "Санузел"),
           FloorFixtureInput("В1", "bath", "Санузел"), *three[1:2],
           FloorFixtureInput("ТП1", "floor_drain", "Санузел"), three[-1]]
    cases = [
        ("three-control", dict(fixtures=three), None),
        ("four-control", {}, None),
        ("three-mirrored", dict(fixtures=three), dict(mirror_x=True, x=1400)),
        ("three-spacing45", dict(fixtures=three, junction_spacing_mm=45), {}),
        ("six-fixtures", dict(fixtures=six), {}),
        ("compact-mirrored", dict(fixtures=three), dict(mirror_x=True, x=1400,
                                                     compact_fixture_annotations=True,
                                                     render_architecture=False)),
    ]
    writer = PdfWriter()
    models = {}
    for name, inputs, render in cases:
        assembly = build_typical_floor_assembly(**inputs)
        models[name] = asdict(assembly)
        if render is None:
            svg = build_typical_floor_control_sheet_svg(assembly)
        else:
            options = dict(x=150, y=140, scale=2.15)
            options.update(render)
            fragment = render_typical_floor_assembly_svg(assembly, **options)
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1587" height="1123" '
                   'viewBox="0 0 1587 1123"><rect width="1587" height="1123" fill="white"/>'
                   f'<text x="60" y="60" font-size="20">{name} / Synthetic QA - not for release</text>'
                   + fragment + '</svg>')
        (output / f"{name}.svg").write_text(svg)
        pdf = cairosvg.svg2pdf(bytestring=svg.encode())
        (output / f"{name}.pdf").write_bytes(pdf)
        writer.append(PdfReader(BytesIO(pdf)), outline_item=name)
    writer.write(output / "floor-annotations.pdf")
    (output / "models.json").write_text(json.dumps(models, ensure_ascii=False, indent=2) + "\n")
    golden = {}
    for key, pages in _production_svgs().items():
        golden[key] = [_visual_digest(svg) for svg in pages]
        for i, svg in enumerate(pages, 1):
            (output / f"production-{key}-{i}.svg").write_text(svg)
    (output / "production-digests.json").write_text(json.dumps(golden, indent=2) + "\n")
    if baseline:
        assert (baseline / "models.json").read_bytes() == (output / "models.json").read_bytes()
        reviewed = []
        rounded_translations = {}
        for source in sorted(baseline.glob("*.svg")):
            current = output / source.name
            assert current.is_file(), source.name
            if review == "schematic-rooms":
                translations = compare_schematic_rooms(source.read_text(), current.read_text())
                if translations:
                    rounded_translations[source.name] = translations
            else:
                assert _unreviewed_geometry(source.read_text()) == _unreviewed_geometry(current.read_text()), source.name
            reviewed.append(source.name)
        report = dict(review=review, models_unchanged=True, geometry_outside_reviewed_groups_unchanged=reviewed,
                      slope_rounding_translations=rounded_translations,
                      baseline=str(baseline), current=str(output))
        (output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print("Models and geometry outside reviewed groups unchanged:", len(reviewed), "SVGs")
    print(output / "floor-annotations.pdf")
    print(json.dumps(golden, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--review", choices=("floor-annotations", "schematic-rooms"), default="floor-annotations")
    args = parser.parse_args()
    main(args.output, args.baseline, args.review)

"""Read-only provenance audit. Never updates goldens or production modules.

Historical renderers run only in temporary Python modules against today's
fixtures/dependencies. Their FULL hashes must first reproduce the untouched
approved file. Only then do we compare bodies outside named presentation deltas.
This diagnostic does not replace the strict production snapshot test.
"""
# ruff: noqa: E402 -- repository script bootstrap
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import tests.test_wastewater_visual_golden as snapshots
from tests.test_building_note_layout import is_old_note_decoration

BASE_REVISION = "17b71ebf0ada745fe08340f5fc23695f984b3e18"
GOLDEN_SHA256 = "7ddbfdf777668e72c5c63e88f02235ced1d605e070e031cdb8a03d0ee0c6cd26"
HISTORICAL_GOLDEN = ROOT / "tests/golden/archive/wastewater_graphics.pre-2026-10-15.json"
# Reviewed 16.10: exact old/new body pairs, never a wildcard exemption.
# Evidence: docs/floor_annotations_2026-10-16.md; models/other SVG groups unchanged.
REVIEWED_BODY_DELTAS = {
    ("k1-k2", 1): (
        "2e044fe67b63b0e7178e389b8a2e7997d2a75598f484185b37180b549c6e6ef7",
        "cf15b36e1fb4e83ee7abf254b76ec7354e77e831ade10dc56a53f98309b17b4c",
        "floor_slope_acute_angle_and_collision_free_placement",
    ),
    ("residential", 1): (
        "6447a2a20a3843e7e0828d34f1ecf8c43c99ecc536b29c2583130d9c455a42a7",
        "e2d66ef2cb298f29ccaabadf48763083c619954dfc570a5ad1fb8513c345706a",
        "mirrored_ugo_anchors_and_flow_arrow; physical_stroke_width_preserved",
    ),
}
K3_OLD_NOTES = (
    '<line xmlns="http://www.w3.org/2000/svg" x1="80" y1="1692" '
    'x2="2136.7" y2="1692" stroke="#777"/>',
    '<rect xmlns="http://www.w3.org/2000/svg" x="88" y="1665" width="1910" '
    'height="210" fill="white" stroke="#777" stroke-width="1"/>',
)


def restore_basement_callout_positions(root):
    """Diagnostic copy only: restore old coordinates, retaining text/IDs/styles.

    Full-page goldens and collision tests independently check new coordinates.
    """
    groups = [n for n in root.iter() if n.get("data-lower-node-callout")]
    assert len(groups) == 4
    for group in groups:
        tx, ty = (float(group.get(f"data-callout-target-{a}")) for a in ("x", "y"))
        texts = [n for n in group if n.tag.rsplit("}", 1)[-1] == "text"]
        paths = [n for n in group if n.tag.rsplit("}", 1)[-1] == "path"]
        assert len(texts) == 3 and len(paths) == 1 and len(group) == 4
        if group.get("data-callout-target-kind") == "cleanout-cap":
            x, knee_y, knee_dx, outer_dx = tx - 24, ty - 96, 82, 345
            text_dx, offsets = 336, (-105, -72, -49)
        else:
            assert group.get("data-callout-target-kind") == "through-wye"
            x, knee_y, knee_dx, outer_dx = tx - 76, ty + 48, 74, -155
            text_dx, offsets = 65, (39, 72, 95)
        paths[0].set("d", f"M{tx:.1f},{ty:.1f} L{x+knee_dx:.1f},{knee_y:.1f} H{x+outer_dx:.1f}")
        for node, dy in zip(texts, offsets, strict=True):
            node.set("x", f"{x+text_dx:.1f}")
            node.set("y", f"{ty+dy:.1f}")


def restore_k3_fixture_caption(root):
    """Undo exactly one reviewed label move in a diagnostic XML copy only."""
    groups = [n for n in root.iter() if n.get("data-k3-treatment-element") == "К3-ЖУ1"]
    assert len(groups) == 1
    caption = groups[0][-1]
    assert caption.tag.rsplit("}", 1)[-1] == "text"
    assert caption.get("x") == "1002.1" and caption.get("y") == "860.9"
    caption.set("y", "920.9")


@contextmanager
def historical_renderers():
    """No checkout/reset, no substitution of calculations or project inputs."""
    loaded = []
    try:
        for basename in ("wastewater_floor_drafting", "drawing_sheet_style",
                         "wastewater_building_drafting", "wastewater_pressure_drafting",
                         "wastewater_k3_drafting"):
            path = f"app/pz/{basename}.py"
            source = subprocess.check_output(
                ["git", "show", f"{BASE_REVISION}:{path}"], cwd=ROOT, text=True,
            )
            name = f"app.pz._golden_audit_{basename}"
            if name in sys.modules:
                raise RuntimeError(f"audit module already loaded: {name}")
            module = types.ModuleType(name)
            module.__file__ = str(ROOT / path)
            sys.modules[name] = module
            loaded.append(module)
            exec(compile(source, f"{BASE_REVISION}:{path}", "exec"), module.__dict__)
        floor, style, building, pressure, k3 = loaded
        with (
            patch.object(building, "render_typical_floor_assembly_svg", floor.render_typical_floor_assembly_svg),
            patch.object(building, "apply_residential_paper_style", style.apply_residential_paper_style),
            patch.object(k3, "_title_block_svg", building._title_block_svg),
            patch.object(pressure, "_title_block_svg", building._title_block_svg),
            patch.object(snapshots, "build_wastewater_building_release_svgs",
                         building.build_wastewater_building_release_svgs),
            patch.object(snapshots, "build_wastewater_pressure_svgs",
                         pressure.build_wastewater_pressure_svgs),
            patch.object(snapshots, "build_wastewater_k3_svgs", k3.build_wastewater_k3_svgs),
        ):
            yield floor
    finally:
        for module in loaded:
            sys.modules.pop(module.__name__, None)


def body_without_known_presentation(svg, *, kind, page, historical):
    """Retain ALL content, normalizing only identified presentation deltas."""
    root = ET.fromstring(svg)
    frames = [node for node in root.iter() if node.get("data-title-block") == "form-3"]
    assert len(frames) == 1, "expected exactly one title block"
    frame = frames[0]
    parent = next(node for node in root.iter() if frame in list(node))
    frame_digest = snapshots._visual_digest(ET.tostring(frame, encoding="unicode"))
    parent.remove(frame)
    if parent is not root:
        assert historical and kind == "residential"
        assert not len(parent) and parent.attrib == {"transform": "translate(-1403.333 0)"}
        root.remove(parent)

    notes = [node for node in root if is_old_note_decoration(node)]
    assert len(notes) == int(historical and kind == "k1-k2")
    for node in notes:
        root.remove(node)

    if kind == "k1-k2" and page == 2 and not historical:
        restore_basement_callout_positions(root)

    if kind == "pressure" and page == 1:
        decoration = ET.fromstring(
            '<rect xmlns="http://www.w3.org/2000/svg" x="170" y="1160" '
            'width="2460" height="330" fill="none" stroke="#000" stroke-width="2"/>'
        )
        matches = [n for n in root if n.tag == decoration.tag and n.attrib == decoration.attrib]
        assert len(matches) == int(historical)
        if not historical:
            title = next(n for n in root if n.text == "ДАННЫЕ И УКАЗАНИЯ")
            root.insert(list(root).index(title), decoration)

    if kind == "k3":
        # Keep the independently reproduced historical BODY hashes unchanged.
        # Reinsert only the exact removed decoration into a diagnostic XML copy;
        # nothing is restored to the renderer or an exported PDF.
        decoration = ET.fromstring(K3_OLD_NOTES[page - 1])
        matches = [node for node in root if node.tag == decoration.tag
                   and node.attrib == decoration.attrib]
        assert len(matches) == int(historical), "unexpected K3 note decoration count"
        if not historical:
            anchor = next(node for node in root if
                          (page == 1 and (node.text or "").startswith("К3 показана самостоятельной"))
                          or (page == 2 and node.text == "Данные К3"))
            root.insert(list(root).index(anchor), decoration)
            if page == 1:
                restore_k3_fixture_caption(root)

    if kind == "pressure" and page == 2:
        if historical:
            border = next(node for node in root if node.attrib == {
                "x": "1745", "y": "480", "width": "885", "height": "700",
                "fill": "none", "stroke": "#000", "stroke-width": "2",
            })
            title = next(node for node in root if node.text == "РАСЧЁТНАЯ ТАБЛИЦА")
            root.remove(border)
            root.remove(title)
        else:
            working_point = next(n for n in root.iter() if n.get("data-working-point"))
            caption = working_point[-1]
            marker = working_point[-2]
            assert caption.get("x") == "1760.0" and caption.get("y") == "450.0"
            assert marker.tag.rsplit("}", 1)[-1] == "circle"
            caption.set("x", f"{float(marker.get('cx')) + 18:.1f}")
            caption.set("y", f"{float(marker.get('cy')) - 18:.1f}")
            table = next(node for node in root
                         if node.get("data-pressure-calculation-table") == "closed-grid")
            children = list(table)
            assert len(children) == 32  # 5 layout nodes + 9 unchanged three-node rows
            assert [n.tag.rsplit("}", 1)[-1] for n in children[:5]] == [
                "rect", "line", "line", "text", "text",
            ]
            assert [n.text for n in children[3:5]] == ["Параметр", "Значение"]
            index = list(root).index(table)
            root.remove(table)
            for offset, node in enumerate(children[5:]):
                root.insert(index + offset, node)
    return snapshots._visual_digest(ET.tostring(root, encoding="unicode")), frame_digest


def audit():
    approved_bytes = HISTORICAL_GOLDEN.read_bytes()
    assert hashlib.sha256(approved_bytes).hexdigest() == GOLDEN_SHA256
    approved = json.loads(approved_bytes)
    current = snapshots._production_svgs()
    with historical_renderers():
        historical = snapshots._production_svgs()
    assert snapshots._production_svgs() == current, "historical imports leaked into production"
    rows = []
    for kind, expected in approved.items():
        assert len(current[kind]) == len(historical[kind]) == len(expected)
        for page, (old, new, expected_hash) in enumerate(
            zip(historical[kind], current[kind], expected, strict=True), 1,
        ):
            assert snapshots._visual_digest(old) == expected_hash, f"unreproduced golden: {kind}/{page}"
            old_body, old_frame = body_without_known_presentation(
                old, kind=kind, page=page, historical=True,
            )
            new_body, new_frame = body_without_known_presentation(
                new, kind=kind, page=page, historical=False,
            )
            reviewed = REVIEWED_BODY_DELTAS.get((kind, page))
            if reviewed:
                assert (old_body, new_body) == reviewed[:2], f"unexplained body difference: {kind}/{page}"
            else:
                assert old_body == new_body, f"unexplained body difference: {kind}/{page}"
            changes = ["shared_title_block"]
            if reviewed:
                changes.append(reviewed[2])
            if kind == "residential":
                changes.append("actual_A2_frame_instead_of_translated_A1")
            if kind in ("k1-k2", "k3"):
                changes.append("removed_note_line" if page == 1 else "removed_note_box")
            if kind == "k3" and page == 1:
                changes.append("grease_trap_caption_y_920.9_to_860.9; text_and_symbol_unchanged")
            if kind == "k1-k2" and page == 2:
                changes.append("four_complete_callouts_repositioned; targets_text_styles_pipes_unchanged")
            if kind == "pressure" and page == 1:
                changes.append("removed_note_box; all_text_and_coordinates_unchanged")
            if kind == "pressure" and page == 2:
                changes.append("closed_table_grid_and_two_column_header; all_9_rows_unchanged")
                changes.append("working_point_caption_under_legend; marker_curves_Q_H_unchanged")
            rows.append({
                "kind": kind, "page": page, "historical_full_hash": expected_hash,
                "current_full_hash": snapshots._visual_digest(new),
                "unchanged_body_hash": old_body if old_body == new_body else None,
                "historical_body_hash": old_body, "current_body_hash": new_body,
                "old_frame_hash": old_frame,
                "new_frame_hash": new_frame, "changes": changes,
            })
    assert HISTORICAL_GOLDEN.read_bytes() == approved_bytes
    return {"revision": BASE_REVISION, "golden_sha256": GOLDEN_SHA256,
            "pages_explained": len(rows), "golden_updated": False, "pages": rows}


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))

"""Read-only provenance check against an explicit pre-annotation source snapshot.

Never accepts or writes goldens. The old renderer must reproduce ALL old hashes
before its comparison can justify the already reviewed floor-annotation delta.
Run with python -m scripts.audit_building_note_layout --baseline-root <snapshot>.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch
from xml.etree import ElementTree as ET

from app.pz import wastewater_building_drafting as building
from app.pz import wastewater_stack_drafting as stack
from scripts.audit_wastewater_visual_golden import restore_basement_callout_positions
from scripts.verify_floor_annotations import _unreviewed_geometry
from tests.test_building_note_layout import (
    BEFORE_WITHOUT_DECORATIONS, REVIEWED_FLOOR_DELTAS, note_layout_samples,
)
from tests.test_wastewater_visual_golden import _visual_digest


def audit(baseline: Path) -> dict:
    current = note_layout_samples()
    loaded, sources = [], {}
    try:
        for basename in ("wastewater_floor_drafting", "drawing_sheet_style"):
            path = baseline / "app" / "pz" / (basename + ".py")
            source = path.read_bytes()
            sources[basename] = sha256(source).hexdigest()
            name = "app.pz._note_audit_" + basename
            if name in sys.modules:
                raise RuntimeError("audit module already loaded")
            module = types.ModuleType(name)
            module.__file__ = str(path)
            sys.modules[name] = module
            loaded.append(module)
            exec(compile(source, str(path), "exec"), module.__dict__)
        floor, style = loaded
        with (
            patch.object(building, "render_typical_floor_assembly_svg", floor.render_typical_floor_assembly_svg),
            patch.object(stack, "render_typical_floor_assembly_svg", floor.render_typical_floor_assembly_svg),
            patch.object(building, "apply_residential_paper_style", style.apply_residential_paper_style),
        ):
            old = note_layout_samples()
    finally:
        for module in loaded:
            sys.modules.pop(module.__name__, None)
    assert note_layout_samples() == current, "historical renderer leaked"
    rows = []
    for key, previous in old.items():
        new = current[key]
        assert _unreviewed_geometry(previous) == _unreviewed_geometry(new), key
        if key == 1:
            # Keep the previously approved callout delta separate.
            values = []
            for svg in (previous, new):
                root = ET.fromstring(svg)
                restore_basement_callout_positions(root)
                values.append(ET.tostring(root, encoding="unicode"))
            previous, new = values
        before, after = _visual_digest(previous), _visual_digest(new)
        assert before == BEFORE_WITHOUT_DECORATIONS[key], key
        assert after == REVIEWED_FLOOR_DELTAS.get(key, before), key
        rows.append(dict(key=key, before=before, after=after, outside_review_unchanged=True))
    return dict(source_sha256=sources, pages=rows, verified=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().baseline_root), indent=2))

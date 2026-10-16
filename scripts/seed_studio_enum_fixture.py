"""Seed obsolete enum values ONLY in the browser harness's private temp draft.

Invalid saved data cannot be created through today's API. No calculation or
validator is mocked; after this explicit fixture seed all edits use real UI.
"""
import sys
import tempfile
from pathlib import Path

from app.intake.studio_store import StudioStore


def main():
    root = Path(sys.argv[1]).resolve()
    if (root.parent != Path(tempfile.gettempdir()).resolve()
            or not root.name.startswith("zarya-finding-inputs-")
            or not (root / "fixture.json").is_file()):
        raise ValueError("Expected the private browser harness temp directory")
    storage = StudioStore(root / "studio")
    draft_id = sys.argv[2]
    current = storage.load(draft_id)
    with storage.edit(draft_id, current["revision"]) as draft:
        row = draft["answers"]["sewer_elements"]["value"][1]
        row.update(system="K3", kind="legacy-kind", service_direction="legacy-direction",
                   service_fitting='legacy"><img src=x onerror="boom">', unit="", include_in_spec=True)
        for key in ("project_calculation", "preview", "package"):
            draft[key] = None


if __name__ == "__main__":
    main()

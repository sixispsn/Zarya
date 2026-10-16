"""Obsolete values in an isolated browser fixture; never accepted through API."""
import sys
import tempfile
from pathlib import Path

from app.intake.studio_store import StudioStore


def main():
    root = Path(sys.argv[1]).resolve()
    if (root.parent != Path(tempfile.gettempdir()).resolve()
            or not root.name.startswith("zarya-finding-inputs-")
            or not (root / "fixture.json").is_file()):
        raise ValueError("Expected private browser harness temp directory")
    storage = StudioStore(root / "studio")
    draft_id = sys.argv[2]
    current = storage.load(draft_id)
    with storage.edit(draft_id, current["revision"]) as draft:
        data = draft["answers"]["wastewater_fan_ventilation"]["value"]
        data["terminals"][1]["kind"] = 'legacy"><img src=x onerror="boom">'
        data.update(external_ventilation_verified="false", external_ventilation_ref=0)
        for key in ("project_calculation", "preview", "package"):
            draft[key] = None


if __name__ == "__main__":
    main()

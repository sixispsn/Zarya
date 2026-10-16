#!/usr/bin/env python3
"""Read-only engineering review of the existing control source (no PDF/release)."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.intake.preflight import preflight_request  # noqa: E402
from app.intake.project_builder import build_project  # noqa: E402
from app.intake.yaml_io import load_request_file  # noqa: E402
from app.pz.ios2_orchestrator import design_ios2  # noqa: E402
from app.quality_gates import build_release_quality_report  # noqa: E402
from scripts.verify_control_release import blocker_snapshot  # noqa: E402


def review():
    request = load_request_file(str(ROOT / 'demo/demo_project.yaml'))
    preflight = preflight_request(request)
    with tempfile.TemporaryDirectory(prefix='zarya-review-') as temporary:
        bundle = design_ios2(build_project(request), output_dir=temporary, render_documents=False)
        quality = build_release_quality_report(preflight, bundle.commission_report)
        return {'source': 'demo/demo_project.yaml', 'render_documents': False,
                'quality': quality.to_dict(),
                'blockers': blocker_snapshot(quality, bundle.commission_report)}


if __name__ == '__main__':
    print(json.dumps(review(), ensure_ascii=False, indent=2))

"""UI-only motion contracts: no changes to engineering or input validation."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_motion_controller():
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    if not node:
        pytest.fail("Set NODE_BINARY for Studio motion regression tests")
    result = subprocess.run(
        [node, "--test", "tests/studio_motion.test.cjs"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_motion_is_progressive_and_does_not_animate_typing():
    template = Path("app/web/templates/studio.html").read_text()
    js = Path("app/web/static/studio.js").read_text()
    css = Path("app/web/static/studio.css").read_text()
    assert template.index("studio_motion.js") < template.index("studio.js")
    input_handler = js.split("root.addEventListener('input', event => {")[1].split("root.addEventListener('toggle'")[0]
    assert "motion.change" not in input_handler
    assert "$('.calculation-output').hidden=true" in input_handler
    assert "$('#calculation').hidden=true" in input_handler
    assert "if (message) motion.stop();" in js
    assert "render(false)" in js
    assert "::view-transition { pointer-events:none; }" in css
    assert "prefers-reduced-motion: reduce" in css

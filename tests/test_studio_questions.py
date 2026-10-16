"""The clarification widget changes presentation, not engineering readiness."""
import os
from pathlib import Path
import shutil
import subprocess


def test_question_queue():
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    assert node, "Set NODE_BINARY for the Studio widget tests"
    result = subprocess.run([node, "--test", "tests/studio_questions.test.cjs", "tests/studio_transport.test.cjs"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_widget_has_native_dialog_keyboard_exit_and_motion_fallback():
    html = Path("app/web/templates/studio.html").read_text()
    js = Path("app/web/static/studio.js").read_text()
    css = Path("app/web/static/studio.css").read_text()
    assert html.count('id="next-step"') == 1 and 'id="next-step"' not in js
    assert 'aria-labelledby="next-title" aria-describedby="next-description"' in html
    assert html.index("studio_questions.js") < html.index("studio.js")
    assert "$('#clarification-dialog').showModal()" in js
    assert "addEventListener('cancel'" in js and "addEventListener('close'" in js
    assert 'data-action="close-questions">Позже' in js
    # The existing checkbox-aware branch has braces; both unsaved values
    # and checkbox state must survive opening the clarification dialog.
    assert "if(original) {input.value=original.value;" in js
    assert "if(input.type==='checkbox')input.checked=original.checked;" in js
    assert "!prompted.has(row.key)) return" in js  # no unseen PDF confirmations
    assert "#ff123b" in css and "signal 2.4s" in css
    assert "prefers-reduced-motion: reduce" in css and "animation: none !important" in css

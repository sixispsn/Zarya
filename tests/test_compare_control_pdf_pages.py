"""The review report must expose missing/changed pages, never approve them."""
from copy import deepcopy
import json

import pytest

from scripts import compare_control_pdf_pages as comparison


def row(document, page, digest, *, text=10, outside=None):
    return dict(document=document, page=page, pixel_hash=digest,
                png=f"{document}-{page}.png", text_chars=text, outside_page=outside or [])


def test_report_distinguishes_all_page_states(tmp_path, monkeypatch):
    before = [row("a.pdf", 1, "same"), row("a.pdf", 2, "old"), row("b.pdf", 1, "gone")]
    after = [row("a.pdf", 1, "same"), row("a.pdf", 2, "new"),
             row("c.pdf", 1, "added", text=0, outside=[[1, 2, 3, 4, "outside"]])]
    baseline, current, output = (tmp_path / name for name in ("before", "after", "review"))
    monkeypatch.setattr(comparison, "render_build", lambda source, target:
                        deepcopy(before if source == baseline else after))
    comparison.main(baseline, current, output)
    report = json.loads((output / "comparison.json").read_text())
    assert [p["status"] for p in report["pages"]] == ["unchanged", "changed", "added"]
    assert report["removed"] == [before[-1]]
    assert report["summary"] == dict(documents=2, pages=3, unchanged_pages=1,
                                     changed_pages=1, added_pages=1, removed_pages=1,
                                     pages_without_text=1, outside_page_words=1)
    assert report["pages"][1]["baseline_png"] == before[1]["png"]
    assert report["pages"][2]["baseline_png"] is None
    assert "release_ready" not in report


def test_existing_evidence_is_never_overwritten(tmp_path):
    report = tmp_path / "comparison.json"
    report.write_bytes(b"previous review")
    with pytest.raises(FileExistsError):
        comparison.main(tmp_path / "before", tmp_path / "after", tmp_path)
    assert report.read_bytes() == b"previous review"


def test_empty_input_is_not_successful_review(tmp_path):
    with pytest.raises(ValueError, match="No PDFs"):
        comparison.render_build(tmp_path, tmp_path / "review")

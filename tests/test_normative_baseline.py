from dataclasses import replace

from app.normative.baseline import (
    NormativeBaseline,
    NormativeDocumentState,
    get_active_baseline,
)


EXPECTED_BASELINE_SHA256 = (
    "6c3ceb9cdd99f7d86d72820f95aa05a48cd39347204bc9122e34a104fd9d9669"
)


def test_active_baseline_has_stable_fingerprint_and_source_hashes():
    baseline = get_active_baseline()

    assert baseline.fingerprint == EXPECTED_BASELINE_SHA256
    assert len({row.document_id for row in baseline.documents}) == len(
        baseline.documents
    )
    assert all(len(row.local_sha256) == 64 for row in baseline.documents)
    assert all(row.verified_on for row in baseline.documents)


def test_sp10_change_is_visible_and_not_silently_adopted():
    document = get_active_baseline().document("sp_10_13130_2020")

    assert document.state == NormativeDocumentState.REVIEW_REQUIRED
    assert document.amendments == ()
    assert "Изменение № 1" in document.current_edition_note
    assert "01.09.2026" in document.current_edition_note


def test_any_normative_record_change_changes_baseline_fingerprint():
    baseline = get_active_baseline()
    modified_first = replace(
        baseline.documents[0],
        verified_on="2026-09-04",
    )
    changed = NormativeBaseline(
        baseline_id=baseline.baseline_id,
        accepted_on=baseline.accepted_on,
        documents=(modified_first, *baseline.documents[1:]),
    )

    assert changed.fingerprint != baseline.fingerprint

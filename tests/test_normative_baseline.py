from dataclasses import replace

from app.normative.baseline import (
    NormativeBaseline,
    NormativeDocumentState,
    get_active_baseline,
)


EXPECTED_BASELINE_SHA256 = (
    "8279f3d7806e8175897fe537ca6f5acb540367f25c08bc1f2524f23dc584d0cc"
)


def test_active_baseline_has_stable_fingerprint_and_source_hashes():
    baseline = get_active_baseline()

    assert baseline.fingerprint == EXPECTED_BASELINE_SHA256
    assert len({row.document_id for row in baseline.documents}) == len(
        baseline.documents
    )
    assert all(len(row.local_sha256) == 64 for row in baseline.documents)
    assert all(row.verified_on for row in baseline.documents)
    assert all(
        row.source_url.startswith("https://protect.gost.ru/")
        for row in baseline.documents
        if row.document_id != "pp87"
    )


def test_sp10_change_is_explicitly_adopted_with_source_hash():
    document = get_active_baseline().document("sp_10_13130_2020")

    assert document.state == NormativeDocumentState.ACCEPTED
    assert document.amendments == ("1",)
    assert "Изменение № 1" in document.current_edition_note
    assert "01.09.2026" in document.current_edition_note
    assert document.local_source_name == "sp-10.13130-izm.1.pdf"
    assert document.local_sha256 == (
        "930d6d249938dba8a9175791ed0576648db367a461e89a246296d596725c2225"
    )


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

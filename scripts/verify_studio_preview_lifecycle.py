"""Read-only semantic/physical checks of --lifecycle's genuine private PDFs.

Run as: venv/bin/python -m scripts.verify_studio_preview_lifecycle <browser-qa.json>
Does not generate or modify documents; visual inspection remains a separate step.
"""
from hashlib import sha256
import json
from pathlib import Path
import sys

from pypdf import PdfReader

from tests.test_studio_user_preview import assert_frame


def verify(report_path: Path) -> None:
    report = json.loads(report_path.read_text())
    expected_stages = ["initial", "renamed", "incomplete"]
    atomicity = report.get("previewAtomicity") or report.get("previewPersistence")
    if atomicity:
        assert atomicity["failedStatus"] == (503 if report.get("previewPersistence") else 422)
        assert atomicity["staleStatus"] == 409
        assert atomicity["successfulBuilds"] == 2 and atomicity["noRetry"] and atomicity["readOnlyRecovery"]
        expected_stages = ["initial", "after_failure"]
    if report.get("previewRecovery"):
        assert [r["kind"] for r in report["previewRecovery"]] == ["connection", "server500", "malformed200"]
        assert all(r["serverStatus"] == 200 and r["noRetry"] and r["reloadReadOnly"] for r in report["previewRecovery"])
        expected_stages += ["restored", "connection", "server500", "malformed200"]
    assert report["passed"] and report["previewPosts"] == (4 if atomicity else len(expected_stages))
    assert not report["errors"] and not report["consoleErrors"]
    stages = report["lifecycle"]
    assert [s["stage"] for s in stages] == expected_stages
    assert len({s["id"] for s in stages}) == len(expected_stages)
    texts_by_stage = []
    count = 0
    for stage in stages:
        texts = {}
        documents = {d["kind"]: d for d in stage["documents"]}
        for kind, document in documents.items():
            content = Path(document["path"]).read_bytes()
            assert sha256(content).hexdigest() == document["sha256"]
            reader = PdfReader(document["path"])
            assert reader.pages
            texts[kind] = [page.extract_text() or "" for page in reader.pages]
            assert all(text.strip() for text in texts[kind]), (stage["stage"], kind)
            if kind in {"balance_pdf", "wastewater_balance_pdf"}:
                assert len(reader.pages) == 1
                assert_frame(content, 420, 297)
            if kind == "wastewater_scheme_pdf":
                assert len(reader.pages) == 1
                assert_frame(content, 841 if stage["stage"] == "incomplete" else 420, 594)
            count += 1
        pz = texts["wastewater_pz_pdf"]
        calc = texts["wastewater_calculation_pdf"]
        balance = texts["wastewater_balance_pdf"]
        assert pz[-len(calc) - len(balance):] == calc + balance
        assert texts["wastewater_package_pdf"] == (
            pz + texts["wastewater_scheme_pdf"] + texts["wastewater_ugo_pdf"]
            + texts["wastewater_spec_pdf"]
        )
        assert "Предварительный просмотр" in pz[0]
        scheme = texts["wastewater_scheme_pdf"][0]
        if stage["stage"] == "incomplete":
            assert documents["wastewater_scheme_pdf"]["state"] == "incomplete"
            assert documents["wastewater_package_pdf"]["state"] == "incomplete"
            assert "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА" in scheme
            assert "не разрешает выпуск" in scheme
            assert "К1-Новый-ID" in scheme
            assert "Режим стояка" in scheme
        else:
            assert documents["wastewater_scheme_pdf"]["state"] == "ready"
            assert "ПРИНЦИПИАЛЬНАЯ СХЕМА НЕ СФОРМИРОВАНА" not in scheme
            original_ids = stage["stage"] == "initial" or atomicity
            assert ("К1-Ст2" if original_ids else "К1-Новый-ID") in scheme
            assert ("К1-Новый-ID" if original_ids else "К1-Ст2") not in scheme
        texts_by_stage.append(texts)
    # Registry identity / removal does not silently change building demand.
    for texts in texts_by_stage[1:]:
        for kind in ("balance_pdf", "wastewater_balance_pdf"):
            assert texts[kind] == texts_by_stage[0][kind]
    for texts in texts_by_stage[3:]:
        assert texts["wastewater_scheme_pdf"] == texts_by_stage[1]["wastewater_scheme_pdf"]
    print(f"PASS: {count} genuine PDFs; hashes, text, {len(stages)} compositions, "
          "stage-specific states/labels, unchanged balances, physical frames/stamps.")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))

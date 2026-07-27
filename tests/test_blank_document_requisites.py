from dataclasses import replace
from pathlib import Path

from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.request_dto import DocumentRequest
from app.pz.generator import _document_cipher
from app.pz.ios2_orchestrator import design_ios2
from tests.test_pump_bridge import _request


def _pdf_text(path: str) -> str:
    return " ".join(page.extract_text() or "" for page in PdfReader(path).pages)


def test_document_suffix_is_not_invented_for_blank_cipher():
    assert _document_cipher("", ".РВ1") == ""
    assert _document_cipher("ABC", ".РВ1") == "ABC.РВ1"
    assert _document_cipher("ABC.РВ1", ".РВ1") == "ABC.РВ1"


def test_full_bundle_builds_with_blank_document_requisites(tmp_path):
    req = replace(
        _request(),
        document=DocumentRequest(cipher="", object_name="", organization=""),
    )
    bundle = design_ios2(build_project(req), output_dir=str(tmp_path))

    paths = (
        bundle.pz_pdf,
        bundle.v1_calculation_pdf,
        bundle.balance_pdf,
        bundle.pump_selection_pdf,
        bundle.spec_pdf,
        bundle.scheme_pdf,
    )
    assert all(path and Path(path).exists() for path in paths)
    assert bundle.project.document.cipher == ""
    assert bundle.project.document.object_name == ""
    assert bundle.project.document.organization == ""

    text = " ".join(_pdf_text(path) for path in paths)
    for token in (
        "⟦ШИФР⟧",
        "⟦ОБЪЕКТ⟧",
        "⟦ЧАСТЬ⟧",
        "⟦ОРГАНИЗАЦИЯ⟧",
    ):
        assert token not in text

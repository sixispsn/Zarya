"""Presentation-only regression: evidence survives pagination or export fails safely."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import re
from types import SimpleNamespace

import fitz
import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz import defense
from app.pz.digital_passport import build_passport_info
from app.pz.proof import ProofFact, ProofStep
from tests.test_defense import _graph, _head_decision


def response_case(long=False):
    project = build_project(load_request_file("demo/demo_project.yaml"))
    project.document.object_name = "Синтетическая проверка ответа эксперту. Не для выпуска"
    project.document.cipher = "QA-DEFENSE"
    project.digital_passport = build_passport_info("qa-defense", "https://example.invalid")
    decision = _head_decision()
    question = "Какими исходными данными подтверждено решение?"
    documents = [{"label": "Контрольный документ", "page": 2, "page_count": 19}]
    if long:
        question = "Длинный вопрос: " + "проверьте полноту доказательств и привязку к документам; " * 16
        decision = replace(decision, steps=[*decision.steps, ProofStep(
            "source", "Многостраничное доказательство", "Начало доказательства",
            " ".join(f"МАРКЕР{i:03d} контроль исходных данных." for i in range(160)),
        )], facts=[ProofFact(
            id=f"ФАКТ{i:03d}", label="Контроль исходных данных", value=f"ЗНАЧЕНИЕ{i:03d}",
            unit="", status="user_declared", status_label="введено",
            source_kind="yaml", source_label="Контрольный источник",
            source_ref="https://example.invalid/" + "abcdef0123456789" * 8 if i == 0 else f"ИСТОЧНИК{i:03d}",
        ) for i in range(24)])
        documents = [{"label": f"ДОКУМЕНТ{i:03d}", "page": None, "page_count": None} for i in range(24)]
    return project, _graph(decision), decision, question, documents


def pdf_text(path):
    return " ".join(re.sub(r"Лист \d+ из \d+", "", page.extract_text()) for page in PdfReader(path).pages)


@pytest.mark.parametrize("long", [False, True])
def test_pagination_preserves_evidence_and_inputs(tmp_path, long):
    case = response_case(long)
    before = deepcopy(case)
    output = tmp_path / "answer.pdf"
    defense.generate_expert_response_pdf(*case, str(output))
    assert case == before
    text = pdf_text(output)
    compact = "".join(text.split())
    assert "".join(case[3].split()) in compact
    assert case[0].digital_passport.url in compact
    for step in case[2].steps:
        for value in (step.label, step.value, step.detail):
            assert "".join(value.split()) in compact
    for fact in case[2].facts:
        assert fact.id in compact and fact.value in compact
        assert "".join(fact.source_ref.split()) in compact
    for document in case[4]:
        assert "".join(document["label"].split()) in compact
    with fitz.open(output) as pdf:
        if long:
            assert len(pdf) > 3
        else:
            assert len(pdf) == 1
        for i, page in enumerate(pdf, 1):
            assert round(page.rect.width) == 595 and round(page.rect.height) == 842
            assert f"Лист {i} из {len(pdf)}" in page.get_text()
            assert all("Zarya-Defense" in font[3] for font in page.get_fonts())
            for x0, y0, x1, y1, *_ in page.get_text("words"):
                assert x0 >= 41 and x1 <= 554
                assert y0 >= 41 and y1 <= 829
            # Header repetition on every page with continued fact/document rows.
            content = page.get_text()
            if "ФАКТ" in content:
                assert "Происхождение" in content
            if "ДОКУМЕНТ" in content:
                assert "Статус привязки" in content


def test_template_and_qr_payload_are_unchanged():
    template = defense.TEMPLATES_DIR / "defense_answer.html"
    assert sha256(template.read_bytes()).hexdigest() == "fe20c8b744d10ebce97936aa4094e522d83d357949330b7572d771e450430c37"
    project, graph, decision, question, documents = response_case()
    html = defense._environment().get_template(template.name).render(
        project=project, proof=graph, decision=decision, question=question, documents=documents,
    )
    assert f'src="{project.digital_passport.qr_data_uri}"' in html
    css = (defense.TEMPLATES_DIR / "defense_answer.css").read_text()
    assert "border-top:" not in css and "border-bottom:" not in css
    assert "border-left:" not in css and "border-right:" not in css
    assert "th, td {" in css and "border: .6pt solid" in css


def test_empty_documents_and_long_unbroken_metadata(tmp_path):
    case = list(response_case())
    case[0].digital_passport = None
    case[0].document.object_name = "ОБЪЕКТ" * 100
    case[0].document.cipher = "ШИФР" * 100
    case[3], case[4] = "", []
    output = tmp_path / "answer.pdf"
    defense.generate_expert_response_pdf(*case, str(output))
    text = "".join(pdf_text(output).split())
    assert case[0].document.object_name in text
    assert case[0].document.cipher in text
    assert "".join(defense.DEFAULT_QUESTIONS[case[2].id].split()) in text
    assert "Связанныйдокументвтекущемкомплектенесформирован." in text
    assert "Постоянныйцифровойпаспорт" not in text


def test_oversize_table_cell_is_rejected_without_overwriting(tmp_path):
    case = list(response_case())
    case[4] = [{"label": "Очень длинное поле " * 300, "page": None}]
    output = tmp_path / "answer.pdf"
    output.write_bytes(b"previous pdf")
    with pytest.raises(ValueError, match="строка таблицы не помещается"):
        defense.generate_expert_response_pdf(*case, str(output))
    assert output.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [output]


def test_layout_overflow_keeps_previous_file(tmp_path, monkeypatch):
    css = defense.CSS(string="@page { size: A4; margin: 15mm; } body { width: 400mm; }")
    monkeypatch.setattr(defense, "CSS", lambda **kwargs: css)
    output = tmp_path / "answer.pdf"
    output.write_bytes(b"previous pdf")
    with pytest.raises(ValueError, match="не помещается"):
        defense.generate_expert_response_pdf(*response_case(), str(output))
    assert output.read_bytes() == b"previous pdf"


def test_route_reports_layout_error_without_returning_old_pdf(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from app.web import wizard

    project, graph, decision, question, documents = response_case()
    documents = [{"label": "Очень длинное поле " * 300, "page": None}]
    run = {"proof_graph": graph, "bundle": SimpleNamespace(project=project),
           "defense_payload": {"decisions": [{"id": decision.id, "documents": documents}]}}
    output = tmp_path / "previous.pdf"
    output.write_bytes(b"previous pdf")
    monkeypatch.setattr(wizard, "_get_run", lambda _: run)
    monkeypatch.setattr(wizard, "_run_documents", lambda _: (documents, []))
    monkeypatch.setattr(wizard, "_RELEASE_STORE", SimpleNamespace(answer_path=lambda *_: output))
    with pytest.raises(HTTPException) as failure:
        wizard.wizard_defense_answer("test-run", decision.id, question)
    assert failure.value.status_code == 422
    assert "строка таблицы не помещается" in failure.value.detail
    assert output.read_bytes() == b"previous pdf"


@pytest.mark.parametrize("failure", ["render", "write_pdf", "replace"])
def test_failure_keeps_previous_file(tmp_path, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise OSError("synthetic failure")
    if failure == "render":
        monkeypatch.setattr(defense.HTML, "render", fail)
    elif failure == "write_pdf":
        from weasyprint.document import Document
        monkeypatch.setattr(Document, "write_pdf", fail)
    else:
        monkeypatch.setattr(defense.os, "replace", fail)
    output = tmp_path / "answer.pdf"
    output.write_bytes(b"previous pdf")
    with pytest.raises(OSError, match="synthetic failure"):
        defense.generate_expert_response_pdf(*response_case(), str(output))
    assert output.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [output]

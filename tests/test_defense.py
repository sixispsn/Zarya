from pathlib import Path

from pypdf import PdfReader
from weasyprint import HTML

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.defense import (
    build_defense_payload,
    generate_expert_response_pdf,
)
from app.pz.proof import ProofDecision, ProofGraph, ProofStep


def _graph(decision: ProofDecision) -> ProofGraph:
    return ProofGraph(
        project_fingerprint="0123456789ABCDEF",
        legacy_fingerprint="FEDCBA9876543210",
        build_commit="abc123",
        generated_at="30.07.2026 12:00 MSK",
        decisions=[decision],
    )


def _head_decision() -> ProofDecision:
    return ProofDecision(
        id="v1-head",
        system="В1",
        title="Требуемый напор",
        value="47,20",
        unit="м вод. ст.",
        status="verified",
        summary="Все составляющие напора сопоставлены.",
        steps=[
            ProofStep(
                "source", "Составляющие напора",
                "Hгеом + Hтр + Hпр",
            ),
            ProofStep(
                "norm", "Формула требуемого напора",
                "СП 30.13330.2020, п. 8.27, формула (14)",
            ),
            ProofStep(
                "decision", "Сопоставление с ТУ",
                "Hтр=47,20 м; Hгар=20,00 м",
            ),
        ],
        artifacts=["Пояснительная записка"],
        impact=["рабочая точка насоса"],
    )


def test_defense_routes_and_launch_button_are_exposed():
    from app.web.wizard import router

    paths = {route.path for route in router.routes}
    assert "/wizard/defense/{run_id}" in paths
    assert "/wizard/defense/{run_id}/answer" in paths
    assert "/wizard/view/{run_id}/{name}" in paths
    result = Path("app/web/templates/wizard_result.html").read_text(
        encoding="utf-8",
    )
    assert 'href="/wizard/defense/{{ run_id }}"' in result
    assert "Защитить проект" in result


def test_defense_payload_opens_actual_pdf_page(tmp_path):
    pdf = tmp_path / "Пояснительная_записка.pdf"
    HTML(string="""
      <style>@page { size: A4 } .next { break-before: page }</style>
      <h1>Общие сведения</h1>
      <section class="next">
        <h1>Требуемый напор</h1>
        <p>Свободный напор диктующего прибора принят по исходным данным.</p>
      </section>
    """).write_pdf(pdf)
    payload = build_defense_payload(
        _graph(_head_decision()),
        [{
            "group": "common",
            "label": "Пояснительная записка",
            "name": pdf.name,
        }],
        str(tmp_path),
        run_id="test-run",
    )
    document = payload["decisions"][0]["documents"][0]
    assert document["page"] == 2
    assert document["page_count"] == 2
    assert document["view_url"].startswith("/wizard/view/test-run/")
    assert payload["summary"]["proven"] == 1


def test_expert_response_is_a4_and_contains_proof(tmp_path):
    request = load_request_file("demo/demo_project.yaml")
    project = build_project(request)
    decision = _head_decision()
    graph = _graph(decision)
    output = tmp_path / "Ответ_эксперту.pdf"
    generate_expert_response_pdf(
        project,
        graph,
        decision,
        "Почему принят такой требуемый напор?",
        [{
            "label": "Пояснительная записка",
            "page": 2,
            "page_count": 19,
        }],
        str(output),
    )
    reader = PdfReader(str(output))
    text = " ".join(page.extract_text() or "" for page in reader.pages)
    flat_text = " ".join(text.split())
    assert "Ответ на вопрос по проектному решению" in flat_text
    assert "Почему принят такой требуемый напор?" in text
    assert "СП 30.13330.2020" in text
    assert graph.project_fingerprint in text
    width = float(reader.pages[0].mediabox.width)
    height = float(reader.pages[0].mediabox.height)
    assert round(width) == 595
    assert round(height) == 842


def test_defense_interface_contains_live_proof_and_safe_what_if():
    template = Path(
        "app/web/templates/wizard_defense.html",
    ).read_text(encoding="utf-8")
    javascript = Path(
        "app/web/static/defense.js",
    ).read_text(encoding="utf-8")
    stylesheet = Path(
        "app/web/static/defense.css",
    ).read_text(encoding="utf-8")
    for token in (
        "Карта решений",
        "Доказательная цепочка",
        "Вопрос комиссии",
        "Оспорить исходные данные",
        "Фактический документ",
        "Сформировать ответ PDF",
    ):
        assert token in template
    assert 'fetch(impactForm.dataset.endpoint' in javascript
    assert "history.replaceState" in javascript
    assert ".defense-workspace" in stylesheet
    assert "@media (max-width: 620px)" in stylesheet

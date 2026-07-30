"""Материалы для живой защиты проекта перед комиссией.

Модуль не выполняет инженерных расчётов. Он связывает уже собранный
ProofGraph с фактически выпущенными PDF и формирует воспроизводимый протокол
ответа на вопрос по выбранному проектному решению.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfReader
from weasyprint import CSS, HTML

from app.pz.proof import ProofDecision, ProofGraph
from app.pz.project import Project


TEMPLATES_DIR = Path(__file__).parent / "templates"

DEFAULT_QUESTIONS = {
    "v1-q-day": "Чем подтверждён суточный расход воды?",
    "v1-q-sec": "Как получен секундный расход холодной воды?",
    "v1-meter": "Почему принят именно этот водомерный узел?",
    "v1-diameter": "Чем подтверждено принятое сечение ввода?",
    "v1-head": "Из каких составляющих получен требуемый напор?",
    "v1-pump": "Почему принята эта повысительная насосная установка?",
    "v2-requirement": "Почему внутренний противопожарный водопровод требуется или не требуется?",
    "v2-hydraulics": "Чем подтверждены напор и рабочая точка насоса В2?",
    "t3-t4-stage": "Почему точная гидравлика Т3/Т4 отнесена к стадии Р?",
    "high-rise-systems": "Какие требования для высотного здания учтены?",
    "apartment-hose-tap": "Учтены ли квартирные краны DN15?",
    "k1-flow": "Как определён расчётный расход хозяйственно-бытовых стоков?",
    "k2-flow": "Как определён расход внутреннего водостока?",
    "k2-network": "Чем подтверждено количество воронок и стояков К2?",
    "k1-grease": "Почему предусматриваются жироуловители?",
}

QUESTION_KEYWORDS = {
    "v1-q-day": ["суточ", "водопотреб", "м3/сут", "м³/сут", "жител"],
    "v1-q-sec": ["секунд", "расход хвс", "вероятност", "альфа", "alpha"],
    "v1-meter": ["водомер", "счетчик", "счётчик", "учет воды", "учёт воды"],
    "v1-diameter": ["диаметр", "сечение", "скорост", "труб"],
    "v1-head": ["требуемый напор", "свободный напор", "hтр", "20 м"],
    "v1-pump": ["насос в1", "повыситель", "рабочая точка", "q-h", "насос"],
    "v2-requirement": ["в2", "впв", "пожаротуш", "пожарный водопровод"],
    "v2-hydraulics": ["напор в2", "насос в2", "диктующ", "пожарная насос"],
    "t3-t4-stage": ["т3", "т4", "циркуляц", "балансиров", "стадия р"],
    "high-rise-systems": ["высот", "сп 253", "раздельные в1", "частот"],
    "apartment-hose-tap": ["квартирный кран", "dn15", "шланг"],
    "k1-flow": ["к1", "сток", "канализац", "водоотвед"],
    "k2-flow": ["к2", "дождев", "водосток", "ливнев"],
    "k2-network": ["ворон", "стояк к2", "кровл"],
    "k1-grease": ["жироулов", "предприятие питания", "кухн"],
}

PAGE_SEARCH_TERMS = {
    "v1-q-day": ["суточный расход", "суточные расходы", "qсут"],
    "v1-q-sec": ["секундный расход", "расчетный секундный", "qsec"],
    "v1-meter": ["водомер", "счетчик воды", "счётчик воды"],
    "v1-diameter": ["сечение ввода", "внутренний диаметр", "скорость воды"],
    "v1-head": ["требуемый напор", "hтр", "свободный напор"],
    "v1-pump": ["рабочая точка", "подбор насос", "повысительная установ"],
    "v2-requirement": [
        "внутренний противопожарный водопровод",
        "необходимость впв",
        "противопожарного водопровода",
    ],
    "v2-hydraulics": [
        "диктующий сценарий",
        "гидравлический расчет",
        "гидравлический расчёт",
    ],
    "t3-t4-stage": ["циркуляцион", "балансировоч", "т3/т4"],
    "high-rise-systems": ["сп 253", "высотн", "раздельные системы"],
    "apartment-hose-tap": ["квартирн", "dn15"],
    "k1-flow": ["расчетный расход стоков", "расчётный расход стоков", "qₛ"],
    "k2-flow": ["дождевой расход", "внутренний водосток", "водостоков"],
    "k2-network": ["водосточная воронка", "воронок", "стояков к2"],
    "k1-grease": ["жироулов"],
}

ARTIFACT_DOCUMENTS = {
    "Пояснительная записка": ["Пояснительная записка"],
    "Расчёты В1": ["Расчётные обоснования В1 и Т3"],
    "Баланс ВиВ": ["Баланс водопотребления и водоотведения"],
    "Подбор насосов": ["Расчёт и подбор насосов"],
    "Спецификация": ["Сводная спецификация"],
    "Схема": ["Сводная принципиальная схема"],
    "Паспорт проекта": ["Паспорт проекта и нормативный контроль"],
    "Гидравлический расчёт": ["Гидравлический расчёт В2"],
    "Гидравлический расчёт В2": ["Гидравлический расчёт В2"],
    "Пояснительная записка К1/К2": ["Пояснительная записка К1 и К2"],
    "Расчёты К1/К2": ["Расчётные обоснования К1 и К2"],
    "Схема К1/К2": ["Принципиальная схема К1 и К2"],
    "Спецификация К1/К2": ["Спецификация К1 и К2"],
}


def _normalise(text: str) -> str:
    value = (text or "").casefold().replace("ё", "е")
    value = re.sub(r"\s+", " ", value)
    return value


@lru_cache(maxsize=256)
def _pdf_pages(path: str) -> tuple[str, ...]:
    reader = PdfReader(path)
    return tuple(_normalise(page.extract_text() or "") for page in reader.pages)


def locate_decision_page(path: str, decision: ProofDecision) -> int | None:
    """Найти фактическую страницу, содержащую сильный маркер решения."""
    terms = list(PAGE_SEARCH_TERMS.get(decision.id, ()))
    if decision.value and decision.value not in {
        "—", "не требуется", "стадия Р", "зафиксирована",
    }:
        terms.append(decision.value)
    normalised_terms = [_normalise(term) for term in terms if len(term) >= 3]
    if not normalised_terms:
        return None
    best_page = None
    best_score = 0
    for page_number, text in enumerate(_pdf_pages(path), start=1):
        score = sum(term in text for term in normalised_terms)
        if score > best_score:
            best_page = page_number
            best_score = score
    return best_page if best_score else None


def _document_labels_for(decision: ProofDecision) -> set[str]:
    labels: set[str] = set()
    for artifact in decision.artifacts:
        labels.update(ARTIFACT_DOCUMENTS.get(artifact, ()))
    return labels


def build_defense_payload(
    graph: ProofGraph,
    documents: Iterable[dict],
    outdir: str,
    *,
    run_id: str,
) -> dict:
    """Связать доказательства с реально существующими файлами и страницами."""
    existing_documents = [
        document for document in documents
        if Path(outdir, document["name"]).is_file()
    ]
    decisions = []
    for decision in graph.decisions:
        encoded = {
            "id": decision.id,
            "system": decision.system,
            "title": decision.title,
            "value": decision.value,
            "unit": decision.unit,
            "status": decision.status,
            "status_label": decision.status_label,
            "summary": decision.summary,
            "steps": [
                {
                    "kind": step.kind,
                    "kind_label": step.kind_label,
                    "label": step.label,
                    "value": step.value,
                    "detail": step.detail,
                }
                for step in decision.steps
            ],
            "impact": list(decision.impact),
            "default_question": DEFAULT_QUESTIONS.get(
                decision.id, f"Чем подтверждено решение «{decision.title}»?",
            ),
            "keywords": QUESTION_KEYWORDS.get(decision.id, []),
            "documents": [],
        }
        linked_labels = _document_labels_for(decision)
        for document in existing_documents:
            if document["label"] not in linked_labels:
                continue
            path = str(Path(outdir, document["name"]))
            try:
                page = locate_decision_page(path, decision)
                page_count = len(_pdf_pages(path))
            except Exception:
                page = None
                page_count = None
            encoded["documents"].append({
                "label": document["label"],
                "name": document["name"],
                "group": document["group"],
                "page": page,
                "page_count": page_count,
                "view_url": f"/wizard/view/{run_id}/{document['name']}",
                "download_url": f"/wizard/file/{run_id}/{document['name']}",
            })
        decisions.append(encoded)

    return {
        "version": "1.0",
        "project_fingerprint": graph.project_fingerprint,
        "legacy_fingerprint": graph.legacy_fingerprint,
        "build_commit": graph.build_commit,
        "generated_at": graph.generated_at,
        "summary": {
            "total": len(graph.decisions),
            "proven": graph.proven_count,
            "missing": graph.missing_count,
            "stage_r": graph.stage_r_count,
        },
        "decisions": decisions,
    }


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def generate_expert_response_pdf(
    project: Project,
    graph: ProofGraph,
    decision: ProofDecision,
    question: str,
    documents: list[dict],
    output_path: str,
) -> str:
    """Сформировать протокол ответа без пересчёта и новых допущений."""
    clean_question = " ".join((question or "").split())
    if not clean_question:
        clean_question = DEFAULT_QUESTIONS.get(
            decision.id, f"Чем подтверждено решение «{decision.title}»?",
        )
    html = _environment().get_template("defense_answer.html").render(
        project=project,
        proof=graph,
        decision=decision,
        question=clean_question,
        documents=documents,
    )
    HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path,
        stylesheets=[CSS(
            filename=str(TEMPLATES_DIR / "defense_answer.css"),
            base_url=str(TEMPLATES_DIR),
        )],
    )
    return output_path

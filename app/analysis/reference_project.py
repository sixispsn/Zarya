# -*- coding: utf-8 -*-
"""Детерминированный разбор проектов-аналогов из PDF и ZIP.

Модуль не заменяет нормативные расчёты Zarya и не считает прошедший
экспертизу проект эталоном. Он извлекает проверяемые факты с указанием
документа и страницы, отмечает расхождения и сохраняет компактный отчёт.
Полный распознанный текст в отчёт не записывается.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Sequence

from pypdf import PdfReader


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_DOCUMENTS = 30
MAX_PAGES_PER_DOCUMENT = 600
MAX_PAGE_TEXT_CHARS = 250_000
_ID_RE = re.compile(r"^[a-f0-9]{10}$")
_SYSTEM_RE = re.compile(
    r"(?<![A-ZА-ЯЁ0-9])(В1|В2|Т3|Т4|К1|К2)(?![A-ZА-ЯЁ0-9])",
    re.IGNORECASE,
)


class ReferenceAnalysisError(ValueError):
    """Загруженный комплект невозможно безопасно разобрать."""


@dataclass(frozen=True)
class UploadedPackage:
    name: str
    content: bytes


@dataclass(frozen=True)
class SourcePdf:
    original_name: str
    content: bytes


_CATEGORY_LABELS = {
    "pz": "Пояснительная записка",
    "calculation": "Расчёты",
    "specification": "Спецификация",
    "scheme": "Схема",
    "conclusion": "Заключение экспертизы",
    "other": "Прочий документ",
}

_CATEGORY_KEYWORDS = {
    "conclusion": (
        "заключение экспертизы", "положительное заключение",
        "экспертное заключение", "замечания экспертизы",
    ),
    "specification": (
        "спецификация оборудования", "изделий и материалов",
        "ведомость оборудования",
    ),
    "scheme": (
        "принципиальная схема", "аксонометрическая схема",
        "схема системы",
    ),
    "calculation": (
        "гидравлический расчет", "гидравлический расчёт",
        "расчетные обоснования", "расчётные обоснования",
        "расчет и подбор", "расчёт и подбор",
        "баланс водопотребления", "подбор насосов",
    ),
    "pz": (
        "пояснительная записка", "текстовая часть",
        "сведения об инженерном оборудовании",
    ),
}

_METRIC_PATTERNS = (
    {
        "metric": "daily_flow",
        "label": "Суточный расход",
        "unit": "м³/сут",
        "system": "В1",
        "systems": ("В1", "Т3", "К1"),
        "pattern": re.compile(
            r"(?:суточн\w*\s+расход\w*|[Qq]\s*сут(?:\.|ки)?)"
            r"[^0-9]{0,42}(?P<value>\d{1,6}(?:[.,]\d{1,4})?)"
            r"\s*м[³3]\s*/\s*сут",
            re.IGNORECASE,
        ),
    },
    {
        "metric": "second_flow",
        "label": "Секундный расход",
        "unit": "л/с",
        "system": "В1",
        "systems": ("В1", "Т3", "К1"),
        "pattern": re.compile(
            r"(?:секундн\w*\s+расход\w*|[Qq]\s*(?:сек|tot))"
            r"[^0-9]{0,42}(?P<value>\d{1,5}(?:[.,]\d{1,4})?)"
            r"\s*л\s*/\s*с",
            re.IGNORECASE,
        ),
    },
    {
        "metric": "required_head",
        "label": "Требуемый напор",
        "unit": "м",
        "system": "В1",
        "systems": ("В1", "В2", "Т3", "Т4"),
        "pattern": re.compile(
            r"(?:требуем\w*\s+напор\w*|[HН]\s*тр(?:еб)?)"
            r"[^0-9]{0,42}(?P<value>\d{1,5}(?:[.,]\d{1,3})?)"
            r"\s*м(?:\s*вод)?",
            re.IGNORECASE,
        ),
    },
    {
        "metric": "guaranteed_head",
        "label": "Гарантированный напор",
        "unit": "м",
        "system": "В1",
        "systems": ("В1", "В2"),
        "pattern": re.compile(
            r"(?:гарантированн\w*\s+напор\w*|[HН]\s*гар)"
            r"[^0-9]{0,42}(?P<value>\d{1,5}(?:[.,]\d{1,3})?)"
            r"\s*м(?:\s*вод)?",
            re.IGNORECASE,
        ),
    },
    {
        "metric": "fire_flow",
        "label": "Расход В2",
        "unit": "л/с",
        "system": "В2",
        "systems": ("В2",),
        "pattern": re.compile(
            r"(?:пожарн\w*\s+расход\w*|расход\w*\s+(?:В2|на\s+ВПВ))"
            r"[^0-9]{0,42}(?P<value>\d{1,5}(?:[.,]\d{1,3})?)"
            r"\s*л\s*/\s*с",
            re.IGNORECASE,
        ),
    },
    {
        "metric": "sewage_flow",
        "label": "Расход К1",
        "unit": "л/с",
        "system": "К1",
        "systems": ("К1",),
        "pattern": re.compile(
            r"(?:расход\w*\s+(?:сточн\w*\s+вод|К1)|[Qq]\s*[sс]\b)"
            r"[^0-9]{0,42}(?P<value>\d{1,5}(?:[.,]\d{1,3})?)"
            r"\s*л\s*/\s*с",
            re.IGNORECASE,
        ),
    },
    {
        "metric": "storm_flow",
        "label": "Расход К2",
        "unit": "л/с",
        "system": "К2",
        "systems": ("К2",),
        "pattern": re.compile(
            r"(?:дождев\w*\s+расход\w*|расход\w*\s+К2)"
            r"[^0-9]{0,42}(?P<value>\d{1,6}(?:[.,]\d{1,3})?)"
            r"\s*л\s*/\s*с",
            re.IGNORECASE,
        ),
    },
)

_PUMP_POINT_RE = re.compile(
    r"(?:рабоч\w*\s+точк\w*|насос\w*)[^QНH]{0,100}"
    r"[Qq]\s*[=:]\s*(?P<q>\d{1,5}(?:[.,]\d{1,3})?)\s*м[³3]\s*/\s*ч"
    r"[^НH]{0,100}[НHh]\s*[=:]\s*(?P<h>\d{1,5}(?:[.,]\d{1,3})?)\s*м",
    re.IGNORECASE,
)

_NORM_RE = re.compile(
    r"\b(?:СП|ГОСТ(?:\s+Р)?|СанПиН)\s*"
    r"\d+(?:\.\d+){0,3}(?:[-–]\d{4})?\b",
    re.IGNORECASE,
)

_PREVIOUS_EDITIONS = {
    "СП 30.13330.2016": "СП 30.13330.2020",
    "СП 10.13130.2009": "СП 10.13130.2020",
    "СП 54.13330.2016": "СП 54.13330.2022",
    "СП 118.13330.2012": "СП 118.13330.2022",
}


def _normalise_text(value: str) -> str:
    value = value.replace("\xa0", " ").replace("−", "-").replace("–", "-")
    return re.sub(r"\s+", " ", value).strip()


def _safe_archive_member(name: str) -> bool:
    posix = PurePosixPath(name.replace("\\", "/"))
    return (
        len(name) <= 500
        and not posix.is_absolute()
        and ".." not in posix.parts
        and not name.startswith(("/", "\\"))
    )


def expand_packages(
    packages: Sequence[UploadedPackage],
) -> tuple[List[SourcePdf], List[str]]:
    """Развернуть PDF/ZIP в память без записи архивных путей на диск."""
    pdfs: List[SourcePdf] = []
    ignored: List[str] = []
    unpacked_total = 0
    for package in packages:
        name = package.name.strip() or "document"
        if len(package.content) > MAX_UPLOAD_BYTES:
            raise ReferenceAnalysisError(
                f"Файл «{name}» превышает лимит 100 МБ."
            )
        suffix = Path(name).suffix.lower()
        if suffix == ".pdf":
            if len(package.content) > MAX_PDF_BYTES:
                raise ReferenceAnalysisError(
                    f"PDF «{name}» превышает лимит 40 МБ."
                )
            if not package.content.startswith(b"%PDF"):
                raise ReferenceAnalysisError(f"«{name}» не является PDF.")
            pdfs.append(SourcePdf(Path(name).name, package.content))
            unpacked_total += len(package.content)
            continue
        if suffix != ".zip":
            raise ReferenceAnalysisError(
                f"Формат «{name}» не поддерживается. Загрузите PDF или ZIP."
            )
        try:
            archive = zipfile.ZipFile(io.BytesIO(package.content))
        except zipfile.BadZipFile as exc:
            raise ReferenceAnalysisError(f"Архив «{name}» повреждён.") from exc
        with archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > 100:
                raise ReferenceAnalysisError(
                    f"В архиве «{name}» слишком много файлов."
                )
            for item in members:
                if not _safe_archive_member(item.filename):
                    raise ReferenceAnalysisError(
                        f"Архив «{name}» содержит небезопасный путь."
                    )
                if item.flag_bits & 0x1:
                    raise ReferenceAnalysisError(
                        f"Файл «{item.filename}» защищён паролем."
                    )
                unpacked_total += item.file_size
                if unpacked_total > MAX_UNPACKED_BYTES:
                    raise ReferenceAnalysisError(
                        "Распакованный комплект превышает лимит 200 МБ."
                    )
                if item.file_size > MAX_PDF_BYTES:
                    raise ReferenceAnalysisError(
                        f"Файл «{item.filename}» превышает лимит 40 МБ."
                    )
                if (
                    item.compress_size > 0
                    and item.file_size > 5 * 1024 * 1024
                    and item.file_size / item.compress_size > 150
                ):
                    raise ReferenceAnalysisError(
                        f"Архив «{name}» имеет подозрительную степень сжатия."
                    )
                if Path(item.filename).suffix.lower() != ".pdf":
                    ignored.append(f"{name} / {item.filename}")
                    continue
                content = archive.read(item)
                if not content.startswith(b"%PDF"):
                    raise ReferenceAnalysisError(
                        f"«{item.filename}» имеет расширение PDF, но не является PDF."
                    )
                pdfs.append(SourcePdf(f"{name} / {item.filename}", content))
    if not pdfs:
        raise ReferenceAnalysisError("В комплекте не найдено ни одного PDF.")
    if len(pdfs) > MAX_DOCUMENTS:
        raise ReferenceAnalysisError(
            f"Найдено {len(pdfs)} PDF; максимум за один раз — {MAX_DOCUMENTS}."
        )
    return pdfs, ignored


def _classify_document(name: str, sample: str) -> str:
    filename = Path(name).name.lower().replace("_", " ").replace("-", " ")
    if re.search(r"(?:^|\W)пз(?:\W|$)", filename):
        return "pz"
    if "заключен" in filename or "экспертиз" in filename:
        return "conclusion"
    if "спецификац" in filename:
        return "specification"
    if "схем" in filename:
        return "scheme"
    if any(token in filename for token in (
        "расчет", "расчёт", "баланс", "подбор насос",
    )):
        return "calculation"
    haystack = sample[:25_000].lower()
    scores = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        scores[category] = sum(
            (4 if keyword in filename else 0) + (1 if keyword in haystack else 0)
            for keyword in keywords
        )
    category, score = max(scores.items(), key=lambda item: item[1])
    return category if score else "other"


def _infer_system(text: str, start: int, default: str) -> str:
    before = text[max(0, start - 180):start]
    after = text[start:start + 90]
    matches = list(_SYSTEM_RE.finditer(before))
    if matches:
        return matches[-1].group(1).upper()
    match = _SYSTEM_RE.search(after)
    return match.group(1).upper() if match else default


def _snippet(text: str, start: int, end: int) -> str:
    return _normalise_text(text[max(0, start - 95):min(len(text), end + 125)])[:320]


def _number(value: str) -> float:
    return float(value.replace(",", "."))


def _display_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def _extract_page_evidence(
    text: str,
    document_id: str,
    document_name: str,
    page: int,
    evidence_start: int,
) -> tuple[List[dict], List[dict], set[str]]:
    evidence: List[dict] = []
    norms: List[dict] = []
    systems = {match.group(1).upper() for match in _SYSTEM_RE.finditer(text)}
    seen = set()
    for definition in _METRIC_PATTERNS:
        for match in definition["pattern"].finditer(text):
            prefix = match.group(0)[:match.start("value") - match.start()]
            if (
                definition["metric"] == "guaranteed_head"
                and re.search(r"[HН]\s*тр", prefix, re.IGNORECASE)
            ):
                continue
            if (
                definition["metric"] == "required_head"
                and re.search(r"[HН]\s*гар", prefix, re.IGNORECASE)
            ):
                continue
            value = _number(match.group("value"))
            system = _infer_system(text, match.start(), definition["system"])
            if system not in definition["systems"]:
                system = definition["system"]
            signature = (
                definition["metric"], system, round(value, 4), page
            )
            if signature in seen:
                continue
            seen.add(signature)
            evidence.append({
                "id": f"E{evidence_start + len(evidence):04d}",
                "metric": definition["metric"],
                "label": definition["label"],
                "system": system or "—",
                "value": value,
                "display_value": _display_number(value),
                "unit": definition["unit"],
                "document_id": document_id,
                "document_name": document_name,
                "page": page,
                "quote": _snippet(text, match.start(), match.end()),
                "confidence": "high",
            })
    for match in _PUMP_POINT_RE.finditer(text):
        q_value = _number(match.group("q"))
        h_value = _number(match.group("h"))
        system = _infer_system(text, match.start(), "В1")
        if system not in ("В1", "В2", "Т3", "Т4"):
            system = "В1"
        signature = ("pump_point", system, round(q_value, 4), round(h_value, 4), page)
        if signature in seen:
            continue
        seen.add(signature)
        evidence.append({
            "id": f"E{evidence_start + len(evidence):04d}",
            "metric": "pump_point",
            "label": "Рабочая точка насоса",
            "system": system,
            "value": q_value,
            "display_value": (
                f"Q {_display_number(q_value)} · H {_display_number(h_value)}"
            ),
            "secondary_value": h_value,
            "unit": "м³/ч · м",
            "document_id": document_id,
            "document_name": document_name,
            "page": page,
            "quote": _snippet(text, match.start(), match.end()),
            "confidence": "high",
        })
    norm_seen = set()
    for match in _NORM_RE.finditer(text):
        reference = _normalise_text(match.group(0)).upper()
        reference = re.sub(r"\s+", " ", reference)
        if reference in norm_seen:
            continue
        norm_seen.add(reference)
        norms.append({
            "reference": reference,
            "document_id": document_id,
            "document_name": document_name,
            "page": page,
            "quote": _snippet(text, match.start(), match.end()),
            "replacement": _PREVIOUS_EDITIONS.get(reference, ""),
        })
    return evidence, norms, systems


def _read_pdf(path: Path, document_id: str, original_name: str) -> dict:
    record = {
        "id": document_id,
        "original_name": original_name,
        "stored_name": path.name,
        "category": "other",
        "category_label": _CATEGORY_LABELS["other"],
        "pages": 0,
        "text_pages": 0,
        "characters": 0,
        "status": "error",
        "status_label": "не прочитан",
        "message": "",
        "positive_conclusion": False,
        "evidence": [],
        "norms": [],
        "systems": [],
    }
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except Exception:
                decrypted = 0
            if not decrypted:
                record["message"] = "PDF защищён паролем."
                return record
        record["pages"] = len(reader.pages)
        if record["pages"] > MAX_PAGES_PER_DOCUMENT:
            record["message"] = (
                f"В документе {record['pages']} страниц; лимит анализа — "
                f"{MAX_PAGES_PER_DOCUMENT}."
            )
            return record
        sample_parts = []
        evidence: List[dict] = []
        norms: List[dict] = []
        systems = set()
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            text = _normalise_text(text[:MAX_PAGE_TEXT_CHARS])
            if len(text) >= 40:
                record["text_pages"] += 1
            record["characters"] += len(text)
            if page_number <= 5:
                sample_parts.append(text)
            page_evidence, page_norms, page_systems = _extract_page_evidence(
                text,
                document_id,
                original_name,
                page_number,
                len(evidence) + 1,
            )
            evidence.extend(page_evidence)
            norms.extend(page_norms)
            systems.update(page_systems)
        sample = " ".join(sample_parts)
        record["category"] = _classify_document(original_name, sample)
        record["category_label"] = _CATEGORY_LABELS[record["category"]]
        record["positive_conclusion"] = bool(
            re.search(r"\bположительн\w*\s+заключени\w*", sample, re.IGNORECASE)
        )
        record["evidence"] = evidence
        record["norms"] = norms
        record["systems"] = sorted(systems)
        if record["characters"] < max(80, record["pages"] * 25):
            record["status"] = "scanned"
            record["status_label"] = "нужен OCR"
            record["message"] = "Текстовый слой отсутствует или почти пуст."
        elif record["text_pages"] < record["pages"]:
            record["status"] = "partial"
            record["status_label"] = "частично"
            record["message"] = "Часть страниц не содержит текстового слоя."
        else:
            record["status"] = "text"
            record["status_label"] = "прочитан"
    except Exception as exc:
        record["message"] = f"PDF не разобран: {type(exc).__name__}."
    return record


def _reindex_evidence(documents: Iterable[dict]) -> List[dict]:
    out = []
    for document in documents:
        for item in document.pop("evidence", []):
            item["id"] = f"E{len(out) + 1:04d}"
            out.append(item)
    return out


def _deduplicate_norms(documents: Iterable[dict]) -> List[dict]:
    out = []
    seen = set()
    for document in documents:
        for item in document.pop("norms", []):
            key = (
                item["reference"], item["document_id"], item["page"]
            )
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def _metric_conflicts(evidence: Sequence[dict]) -> List[dict]:
    groups = {}
    for item in evidence:
        if item["metric"] == "pump_point":
            continue
        key = (item["metric"], item["system"], item["unit"])
        groups.setdefault(key, []).append(item)
    findings = []
    for (metric, system, unit), items in groups.items():
        values = sorted({round(float(item["value"]), 4) for item in items})
        if len(values) < 2:
            continue
        span = values[-1] - values[0]
        tolerance = max(0.05, abs(values[-1]) * 0.01)
        if span <= tolerance:
            continue
        sources = [
            {
                "evidence_id": item["id"],
                "value": item["display_value"],
                "unit": item["unit"],
                "document_name": item["document_name"],
                "document_id": item["document_id"],
                "page": item["page"],
            }
            for item in items
        ]
        findings.append({
            "status": "conflict",
            "status_label": "расхождение",
            "title": f"{items[0]['label']} · {system}",
            "message": (
                f"В документах найдены разные значения: "
                f"{', '.join(_display_number(value) for value in values)} {unit}. "
                "Это не объявляется ошибкой автоматически: проверьте режимы и "
                "назначение каждого значения."
            ),
            "sources": sources,
            "metric": metric,
        })
    return findings


def _build_findings(
    documents: Sequence[dict],
    evidence: Sequence[dict],
    norms: Sequence[dict],
) -> List[dict]:
    findings = _metric_conflicts(evidence)
    scanned = [doc for doc in documents if doc["status"] in ("scanned", "error")]
    if scanned:
        findings.append({
            "status": "review",
            "status_label": "нужны данные",
            "title": "Часть документов требует OCR или пароля",
            "message": (
                "Не прочитаны: " + ", ".join(doc["original_name"] for doc in scanned)
            ),
            "sources": [],
        })
    conclusion_docs = [
        doc for doc in documents if doc["category"] == "conclusion"
    ]
    positive = [doc for doc in conclusion_docs if doc["positive_conclusion"]]
    if positive:
        findings.append({
            "status": "confirmed",
            "status_label": "подтверждено",
            "title": "Положительное заключение найдено",
            "message": (
                "Статус определён по тексту загруженного заключения; содержание "
                "инженерных решений всё равно проверяется отдельно."
            ),
            "sources": [{
                "document_name": doc["original_name"],
                "document_id": doc["id"],
                "page": 1,
            } for doc in positive],
        })
    elif conclusion_docs:
        findings.append({
            "status": "review",
            "status_label": "проверить",
            "title": "Заключение загружено, но положительный статус не распознан",
            "message": "Откройте документ и подтвердите вид заключения вручную.",
            "sources": [{
                "document_name": doc["original_name"],
                "document_id": doc["id"],
                "page": 1,
            } for doc in conclusion_docs],
        })
    else:
        findings.append({
            "status": "missing",
            "status_label": "не загружено",
            "title": "Заключение экспертизы отсутствует",
            "message": (
                "Проект можно разобрать как аналог, но факт прохождения экспертизы "
                "системой не подтверждён."
            ),
            "sources": [],
        })
    if not any(doc["category"] == "pz" for doc in documents):
        findings.append({
            "status": "missing",
            "status_label": "не найдено",
            "title": "Пояснительная записка не распознана",
            "message": "Добавьте текстовую часть, чтобы восстановить принятые решения.",
            "sources": [],
        })
    previous = [item for item in norms if item["replacement"]]
    if previous:
        pairs = sorted({
            f"{item['reference']} → {item['replacement']}" for item in previous
        })
        findings.append({
            "status": "review",
            "status_label": "проверить редакцию",
            "title": "Найдены прежние редакции нормативов",
            "message": "; ".join(pairs),
            "sources": [{
                "document_name": item["document_name"],
                "document_id": item["document_id"],
                "page": item["page"],
            } for item in previous[:12]],
        })
    if not evidence:
        findings.append({
            "status": "review",
            "status_label": "мало данных",
            "title": "Расчётные показатели автоматически не найдены",
            "message": (
                "Проверьте наличие текстового слоя и загрузите отдельные расчёты "
                "или баланс."
            ),
            "sources": [],
        })
    order = {"conflict": 0, "review": 1, "missing": 2, "confirmed": 3}
    return sorted(findings, key=lambda item: order.get(item["status"], 9))


class ReferenceAnalysisStore:
    """Персистентное файловое хранилище разборов проектов-аналогов."""

    def __init__(self, root: str | Path | None = None):
        projects_root = os.environ.get(
            "ZARYA_PROJECTS_DIR",
            os.path.expanduser("~/.zarya/projects"),
        )
        self.root = Path(root or Path(projects_root) / "reference_analyses")
        self.root.mkdir(parents=True, exist_ok=True)

    def _directory(self, analysis_id: str) -> Path:
        if not _ID_RE.fullmatch(analysis_id):
            raise ValueError(f"некорректный analysis_id: {analysis_id!r}")
        return self.root / analysis_id

    def create(
        self,
        title: str,
        packages: Sequence[UploadedPackage],
    ) -> str:
        pdfs, ignored = expand_packages(packages)
        analysis_id = uuid.uuid4().hex[:10]
        staging = self.root / f".{analysis_id}.tmp"
        destination = self._directory(analysis_id)
        files_dir = staging / "files"
        files_dir.mkdir(parents=True)
        digest = hashlib.sha256()
        documents = []
        try:
            for index, source in enumerate(pdfs, start=1):
                digest.update(source.content)
                stored_name = f"{index:02d}-{uuid.uuid4().hex[:8]}.pdf"
                path = files_dir / stored_name
                path.write_bytes(source.content)
                documents.append(
                    _read_pdf(path, f"D{index:03d}", source.original_name)
                )
            evidence = _reindex_evidence(documents)
            norms = _deduplicate_norms(documents)
            systems = sorted({
                system for document in documents for system in document["systems"]
            })
            findings = _build_findings(documents, evidence, norms)
            clean_title = _normalise_text(title)[:160]
            if not clean_title:
                clean_title = Path(pdfs[0].original_name).stem[:160]
            created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            manifest = {
                "analysis_id": analysis_id,
                "title": clean_title or "Проект-аналог",
                "created_at": created_at,
                "fingerprint": digest.hexdigest()[:16].upper(),
                "documents": documents,
                "evidence": evidence,
                "norms": norms,
                "systems": systems,
                "findings": findings,
                "ignored_files": ignored,
                "summary": {
                    "documents": len(documents),
                    "pages": sum(doc["pages"] for doc in documents),
                    "text_pages": sum(doc["text_pages"] for doc in documents),
                    "evidence": len(evidence),
                    "norms": len({item["reference"] for item in norms}),
                    "conflicts": sum(
                        item["status"] == "conflict" for item in findings
                    ),
                    "review": sum(
                        item["status"] in ("review", "missing")
                        for item in findings
                    ),
                    "scanned": sum(
                        doc["status"] in ("scanned", "error")
                        for doc in documents
                    ),
                    "positive_conclusion": any(
                        doc["positive_conclusion"] for doc in documents
                    ),
                },
                "method": {
                    "version": "1.0",
                    "mode": "deterministic_pdf_text",
                    "notice": (
                        "Извлечённые значения являются кандидатами для проверки "
                        "проектировщиком и не заменяют расчётные алгоритмы Zarya."
                    ),
                },
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return analysis_id

    def load(self, analysis_id: str) -> dict:
        path = self._directory(analysis_id) / "manifest.json"
        if not path.is_file():
            raise FileNotFoundError(f"разбор {analysis_id} не найден")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> List[dict]:
        analyses = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not _ID_RE.fullmatch(directory.name):
                continue
            try:
                manifest = self.load(directory.name)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            analyses.append({
                "analysis_id": manifest["analysis_id"],
                "title": manifest["title"],
                "created_at": manifest["created_at"],
                "summary": manifest["summary"],
            })
        analyses.sort(key=lambda item: item["created_at"], reverse=True)
        return analyses

    def delete(self, analysis_id: str) -> None:
        directory = self._directory(analysis_id)
        if directory.is_dir():
            shutil.rmtree(directory)

    def file_path(self, analysis_id: str, stored_name: str) -> Path:
        if not re.fullmatch(r"\d{2}-[a-f0-9]{8}\.pdf", stored_name):
            raise ValueError("некорректное имя документа")
        path = self._directory(analysis_id) / "files" / stored_name
        if not path.is_file():
            raise FileNotFoundError(stored_name)
        return path

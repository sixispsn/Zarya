"""Неизменяемый снимок нормативных документов, принятых расчётным ядром.

Baseline описывает именно то, что фактически применялось в выпуске. Сведения
о более новой редакции не заменяют принятую редакцию автоматически: документ
переходит в ``review_required`` до анализа влияния, решения проектировщика и
обновления тестов.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Any


class NormativeDocumentState(str, Enum):
    ACCEPTED = "accepted"
    REVIEW_REQUIRED = "review_required"
    REFERENCE_ONLY = "reference_only"


@dataclass(frozen=True)
class NormativeDocument:
    document_id: str
    designation: str
    title: str
    edition: str
    amendments: tuple[str, ...]
    effective_date: str
    verified_on: str
    source_url: str
    local_source_name: str
    local_sha256: str
    local_scope: str
    state: NormativeDocumentState = NormativeDocumentState.ACCEPTED
    current_edition_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "designation": self.designation,
            "title": self.title,
            "edition": self.edition,
            "amendments": list(self.amendments),
            "effective_date": self.effective_date,
            "verified_on": self.verified_on,
            "source_url": self.source_url,
            "local_source_name": self.local_source_name,
            "local_sha256": self.local_sha256,
            "local_scope": self.local_scope,
            "state": self.state.value,
            "current_edition_note": self.current_edition_note,
        }


@dataclass(frozen=True)
class NormativeBaseline:
    baseline_id: str
    accepted_on: str
    documents: tuple[NormativeDocument, ...]

    def document(self, document_id: str) -> NormativeDocument:
        for row in self.documents:
            if row.document_id == document_id:
                return row
        raise KeyError(f"документ отсутствует в baseline: {document_id}")

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self._unsigned_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    @property
    def status(self) -> str:
        if any(
            row.state == NormativeDocumentState.REVIEW_REQUIRED
            for row in self.documents
        ):
            return "review_required"
        return "accepted"

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "baseline_id": self.baseline_id,
            "accepted_on": self.accepted_on,
            "documents": [row.to_dict() for row in self.documents],
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["status"] = self.status
        payload["fingerprint_sha256"] = self.fingerprint
        return payload

    def commission_summary(self) -> str:
        rows = []
        for document in self.documents:
            edition = document.edition
            if document.amendments:
                edition += ", изм. " + ", ".join(document.amendments)
            rows.append(f"{document.designation} ({edition})")
        return (
            f"{self.baseline_id}; SHA-256 {self.fingerprint[:16]}; "
            + "; ".join(rows)
        )


# Локальные SHA-256 зафиксированы по предоставленным пользователем файлам.
# Путь пользователя намеренно не попадает в публичный паспорт выпуска.
_ACTIVE_BASELINE = NormativeBaseline(
    baseline_id="ru-ios-2026-09-03-v1",
    accepted_on="2026-09-03",
    documents=(
        NormativeDocument(
            document_id="pp87",
            designation="ПП РФ № 87",
            title="О составе разделов проектной документации",
            edition="локальная выдержка по разделам 17–18",
            amendments=("ред. до 2022",),
            effective_date="2008-02-16",
            verified_on="2026-09-03",
            source_url="",
            local_source_name="87 ВК.pdf",
            local_sha256="d5fd7bfbd2227da614603efd5e55c03d6506e7018588b5fc20493783f82cec0d",
            local_scope="Только предоставленная выдержка; не полный текст постановления.",
            state=NormativeDocumentState.REFERENCE_ONLY,
        ),
        NormativeDocument(
            document_id="gost_r_21_619_2023",
            designation="ГОСТ Р 21.619-2023",
            title="СПДС. Правила оформления проектной документации внутренних систем водоснабжения",
            edition="2023",
            amendments=(),
            effective_date="2023-09-01",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/gost/details/82026c11-27c4-48a3-a507-f6a3717dfcae",
            local_source_name="ГОСТ Р 21.619.pdf",
            local_sha256="0360bd760d3d2d86cda14ebaea9cbac74cd79feb06668a166240dbaf331d5d19",
            local_scope="Полный локальный PDF, 24 страницы.",
        ),
        NormativeDocument(
            document_id="gost_r_21_620_2023",
            designation="ГОСТ Р 21.620-2023",
            title="СПДС. Правила оформления проектной документации внутренних систем канализации",
            edition="2023",
            amendments=(),
            effective_date="2023-09-01",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/gost/details/d138a3ab-d266-4e16-891e-432ec1de0973",
            local_source_name="ГОСТ К.pdf",
            local_sha256="2fecd0faca18af350e13dad6ff58c459cec90f3710f3624b038f52dd31a9b523",
            local_scope="Полный локальный PDF, 20 страниц.",
        ),
        NormativeDocument(
            document_id="sp_30_13330_2020",
            designation="СП 30.13330.2020",
            title="Внутренний водопровод и канализация зданий",
            edition="2020",
            amendments=("1", "2", "3", "4", "5"),
            effective_date="2021-04-08",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/sp/details/8cd57a35-8503-4bb8-802a-324b64f3e0e7",
            local_source_name="СП 30.docx",
            local_sha256="1a511c028e439a85d4b2585a41eb5d50ee3790ea108c0a021754e1d705314743",
            local_scope="Предоставленная пользователем сводная локальная копия с изменениями 1–5.",
        ),
        NormativeDocument(
            document_id="sp_10_13130_2020",
            designation="СП 10.13130.2020",
            title="Внутренний противопожарный водопровод",
            edition="2020, базовая редакция",
            amendments=(),
            effective_date="2021-01-27",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/sp/details/d048b9cd-eff7-49de-bab0-4aa54eb6b173",
            local_source_name="SP10.13130.2020.pdf",
            local_sha256="58126f661c57fe2e53d86c0bc0e202bfba395e8563eaf5c5875db437185ad86a",
            local_scope="Базовая редакция 2020 года без Изменения № 1.",
            state=NormativeDocumentState.REVIEW_REQUIRED,
            current_edition_note=(
                "Изменение № 1 действует с 01.09.2026; влияние на таблицы, "
                "область применения и алгоритмы Zarya ещё не принято."
            ),
        ),
        NormativeDocument(
            document_id="sp_54_13330_2022",
            designation="СП 54.13330.2022",
            title="Здания жилые многоквартирные",
            edition="2022",
            amendments=("1", "2"),
            effective_date="2022-06-14",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/sp/details/c8b00dd7-7c13-4f17-ac0c-d9cf70311263",
            local_source_name="sp_54.13330.2022.pdf",
            local_sha256="c7d3352de10d66740144e98c4b4bfbba71701cd8f2f520ec0ce679a0857492ff",
            local_scope="Предоставленная локальная копия с изменениями 1–2.",
        ),
        NormativeDocument(
            document_id="sp_118_13330_2022",
            designation="СП 118.13330.2022",
            title="Общественные здания и сооружения",
            edition="2022",
            amendments=("1", "2", "3", "4", "5"),
            effective_date="2022-06-20",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/sp/details/ced01945-2f53-47c9-bdb8-4875c2b9800e",
            local_source_name="sp-118-13330-2022.pdf",
            local_sha256="5af1679726b2e09fef901ef73d36b2bc785bcdae21c6e3463349d1b42be29b05",
            local_scope="Предоставленная локальная копия с изменениями 1–5.",
        ),
        NormativeDocument(
            document_id="sp_253_1325800_2016",
            designation="СП 253.1325800.2016",
            title="Инженерные системы высотных зданий",
            edition="2016",
            amendments=("1", "2", "3"),
            effective_date="2017-02-04",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/sp/details/98d7f3bd-14a2-4bfe-8d63-8e5d792bc93c",
            local_source_name="SP-253.1325800.2016-Inzhenernye-sistemy-vysotnykh-zdaniy.pdf",
            local_sha256="36afe95ef5b542a55863a5261b6db096287092ca934cd0e356d82631f723f6df",
            local_scope="Предоставленная локальная копия с изменениями 1–3.",
        ),
        NormativeDocument(
            document_id="gost_21_110_2013",
            designation="ГОСТ 21.110-2013",
            title="СПДС. Спецификация оборудования, изделий и материалов",
            edition="2013",
            amendments=("Поправка ИУС 7-2015",),
            effective_date="2015-01-01",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/gost/details/e135d52a-eccd-4b7d-b96f-e758c3fce18c",
            local_source_name="ГОСТ 21.110–2013.pdf",
            local_sha256="055d02e3a1df345b78150297c0364aa4d70a316d128c90057f9f53b1dccef7fc",
            local_scope="Предоставленная локальная копия с поправкой ИУС 7-2015.",
        ),
        NormativeDocument(
            document_id="gost_21_601_2011",
            designation="ГОСТ 21.601-2011",
            title="СПДС. Правила выполнения рабочей документации внутренних систем водоснабжения и канализации",
            edition="2011",
            amendments=(),
            effective_date="2013-05-01",
            verified_on="2026-09-03",
            source_url="https://protect.gost.ru/gost/details/48bcdb43-3e52-4026-86f4-0d2c8e691b82",
            local_source_name="ГОСТ 21.601–2011,.pdf",
            local_sha256="a3b446317fffc787bbc032b65dbeda22b16e6ea530ee1fb3fbd4bcfdba7f443c",
            local_scope="Предоставленная локальная копия; применяется для границы стадии Р.",
            state=NormativeDocumentState.REFERENCE_ONLY,
        ),
    ),
)


def get_active_baseline() -> NormativeBaseline:
    """Вернуть принятый baseline; объект неизменяем и безопасен для снимка."""
    return _ACTIVE_BASELINE

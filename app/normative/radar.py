"""Нормативный радар: безопасное обнаружение изменений официальных карточек.

Радар не меняет расчётные таблицы и правила. Он только сопоставляет принятый
``NormativeBaseline`` с метаданными официального источника, сохраняет снимок
и создаёт неизменяемое событие для последующего инженерного анализа.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Iterator
from urllib.request import Request, urlopen

from app.normative.baseline import (
    NormativeBaseline,
    NormativeDocument,
    NormativeDocumentState,
    get_active_baseline,
)

try:  # Unix в production и локальной разработке; fallback нужен для импорта.
    import fcntl
except ImportError:  # pragma: no cover - Windows не является production-средой.
    fcntl = None


_PROJECTS_ROOT = os.environ.get(
    "ZARYA_PROJECTS_DIR",
    os.path.expanduser("~/.zarya/projects"),
)
DEFAULT_ROOT = os.environ.get(
    "ZARYA_NORMATIVE_RADAR_DIR",
    os.path.join(_PROJECTS_ROOT, "_normatives"),
)
MAX_SOURCE_BYTES = 5 * 1024 * 1024
FetchSource = Callable[[str, float], bytes]


class RadarIndicator(str, Enum):
    GREEN = "green"
    ORANGE = "orange"
    RED = "red"
    GRAY = "gray"


class SourceHealth(str, Enum):
    OK = "ok"
    ERROR = "error"
    NOT_CHECKED = "not_checked"
    UNCONFIGURED = "unconfigured"


@dataclass(frozen=True)
class OfficialProbe:
    designation: str
    official_status: str
    amendments: tuple[str, ...]
    correction_count: int
    semantic_sha256: str


@dataclass(frozen=True)
class RadarEntry:
    document_id: str
    designation: str
    title: str
    edition: str
    accepted_amendments: tuple[str, ...]
    baseline_state: str
    source_url: str
    indicator: RadarIndicator
    reason: str
    source_health: SourceHealth
    official_status: str = ""
    official_amendments: tuple[str, ...] = ()
    official_correction_count: int = 0
    last_checked_at: str = ""
    last_semantic_sha256: str = ""
    accepted_semantic_sha256: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "designation": self.designation,
            "title": self.title,
            "edition": self.edition,
            "accepted_amendments": list(self.accepted_amendments),
            "baseline_state": self.baseline_state,
            "source_url": self.source_url,
            "indicator": self.indicator.value,
            "reason": self.reason,
            "source_health": self.source_health.value,
            "official_status": self.official_status,
            "official_amendments": list(self.official_amendments),
            "official_correction_count": self.official_correction_count,
            "last_checked_at": self.last_checked_at,
            "last_semantic_sha256": self.last_semantic_sha256,
            "accepted_semantic_sha256": self.accepted_semantic_sha256,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RadarEntry":
        return cls(
            document_id=str(value["document_id"]),
            designation=str(value.get("designation", "")),
            title=str(value.get("title", "")),
            edition=str(value.get("edition", "")),
            accepted_amendments=tuple(
                str(row) for row in value.get("accepted_amendments", [])
            ),
            baseline_state=str(value.get("baseline_state", "")),
            source_url=str(value.get("source_url", "")),
            indicator=RadarIndicator(value.get("indicator", "gray")),
            reason=str(value.get("reason", "")),
            source_health=SourceHealth(
                value.get("source_health", "not_checked")
            ),
            official_status=str(value.get("official_status", "")),
            official_amendments=tuple(
                str(row) for row in value.get("official_amendments", [])
            ),
            official_correction_count=int(
                value.get("official_correction_count", 0)
            ),
            last_checked_at=str(value.get("last_checked_at", "")),
            last_semantic_sha256=str(
                value.get("last_semantic_sha256", "")
            ),
            accepted_semantic_sha256=str(
                value.get("accepted_semantic_sha256", "")
            ),
            error=str(value.get("error", "")),
        )


@dataclass(frozen=True)
class RadarEvent:
    event_id: str
    detected_at: str
    document_id: str
    designation: str
    kind: str
    indicator: str
    message: str
    source_url: str
    semantic_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "detected_at": self.detected_at,
            "document_id": self.document_id,
            "designation": self.designation,
            "kind": self.kind,
            "indicator": self.indicator,
            "message": self.message,
            "source_url": self.source_url,
            "semantic_sha256": self.semantic_sha256,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RadarEvent":
        return cls(**{
            field: str(value.get(field, ""))
            for field in (
                "event_id", "detected_at", "document_id", "designation",
                "kind", "indicator", "message", "source_url",
                "semantic_sha256",
            )
        })


@dataclass(frozen=True)
class RadarSnapshot:
    baseline_id: str
    baseline_fingerprint: str
    generated_at: str
    entries: tuple[RadarEntry, ...]

    @property
    def summary(self) -> dict[str, int]:
        counts = {
            indicator.value: sum(
                row.indicator == indicator for row in self.entries
            )
            for indicator in RadarIndicator
        }
        counts["total"] = len(self.entries)
        return counts

    @property
    def overall_indicator(self) -> RadarIndicator:
        for indicator in (
            RadarIndicator.RED,
            RadarIndicator.ORANGE,
            RadarIndicator.GRAY,
            RadarIndicator.GREEN,
        ):
            if self.summary[indicator.value]:
                return indicator
        return RadarIndicator.GRAY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "baseline_id": self.baseline_id,
            "baseline_fingerprint": self.baseline_fingerprint,
            "generated_at": self.generated_at,
            "overall_indicator": self.overall_indicator.value,
            "summary": self.summary,
            "entries": [row.to_dict() for row in self.entries],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RadarSnapshot":
        return cls(
            baseline_id=str(value.get("baseline_id", "")),
            baseline_fingerprint=str(
                value.get("baseline_fingerprint", "")
            ),
            generated_at=str(value.get("generated_at", "")),
            entries=tuple(
                RadarEntry.from_dict(row)
                for row in value.get("entries", [])
            ),
        )


class RadarStoreError(ValueError):
    pass


class NormativeRadarStore:
    """Атомарный снимок плюс append-only журнал событий."""

    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root)
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"
        self.lock_path = self.root / ".lock"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def _lock(self) -> Iterator[None]:
        with self.lock_path.open("a+", encoding="utf-8") as stream:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def load(self, baseline: NormativeBaseline | None = None) -> RadarSnapshot:
        baseline = baseline or get_active_baseline()
        with self._lock():
            return self._load_unlocked(baseline)

    def _load_unlocked(self, baseline: NormativeBaseline) -> RadarSnapshot:
        if not self.state_path.is_file():
            return build_initial_snapshot(baseline)
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            snapshot = RadarSnapshot.from_dict(raw)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RadarStoreError("снимок нормативного радара повреждён") from exc
        return reconcile_snapshot(snapshot, baseline)

    def events(self, limit: int = 50) -> list[RadarEvent]:
        if limit <= 0 or not self.events_path.is_file():
            return []
        with self._lock():
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        rows: list[RadarEvent] = []
        for line in lines[-limit:]:
            try:
                rows.append(RadarEvent.from_dict(json.loads(line)))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return list(reversed(rows))

    def commit(
        self,
        snapshot: RadarSnapshot,
        events: tuple[RadarEvent, ...] = (),
    ) -> None:
        with self._lock():
            existing_ids: set[str] = set()
            if self.events_path.is_file():
                for line in self.events_path.read_text(
                    encoding="utf-8"
                ).splitlines():
                    try:
                        existing_ids.add(str(json.loads(line)["event_id"]))
                    except (KeyError, TypeError, json.JSONDecodeError):
                        continue
            new_events = [
                row for row in events if row.event_id not in existing_ids
            ]
            if new_events:
                with self.events_path.open("a", encoding="utf-8") as stream:
                    for row in new_events:
                        stream.write(json.dumps(
                            row.to_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                        ) + "\n")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".state-",
                suffix=".json",
                dir=self.root,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(
                        snapshot.to_dict(),
                        stream,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, self.state_path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _initial_indicator(document: NormativeDocument) -> tuple[RadarIndicator, str]:
    if document.state == NormativeDocumentState.REVIEW_REQUIRED:
        return RadarIndicator.RED, document.current_edition_note
    if not document.source_url:
        return (
            RadarIndicator.GRAY,
            "Автоматический официальный источник ещё не подключён.",
        )
    return (
        RadarIndicator.GREEN,
        f"Редакция вручную сверена {document.verified_on}; ожидается онлайн-проверка.",
    )


def _entry_from_document(document: NormativeDocument) -> RadarEntry:
    indicator, reason = _initial_indicator(document)
    return RadarEntry(
        document_id=document.document_id,
        designation=document.designation,
        title=document.title,
        edition=document.edition,
        accepted_amendments=document.amendments,
        baseline_state=document.state.value,
        source_url=document.source_url,
        indicator=indicator,
        reason=reason,
        source_health=(
            SourceHealth.NOT_CHECKED
            if document.source_url else SourceHealth.UNCONFIGURED
        ),
    )


def build_initial_snapshot(baseline: NormativeBaseline) -> RadarSnapshot:
    return RadarSnapshot(
        baseline_id=baseline.baseline_id,
        baseline_fingerprint=baseline.fingerprint,
        generated_at="",
        entries=tuple(_entry_from_document(row) for row in baseline.documents),
    )


def reconcile_snapshot(
    snapshot: RadarSnapshot,
    baseline: NormativeBaseline,
) -> RadarSnapshot:
    """Подтянуть состав нового baseline, не теряя результаты прошлой проверки."""
    previous = {row.document_id: row for row in snapshot.entries}
    entries: list[RadarEntry] = []
    for document in baseline.documents:
        old = previous.get(document.document_id)
        if old is None:
            entries.append(_entry_from_document(document))
            continue
        indicator, reason = _initial_indicator(document)
        entries.append(RadarEntry(
            document_id=document.document_id,
            designation=document.designation,
            title=document.title,
            edition=document.edition,
            accepted_amendments=document.amendments,
            baseline_state=document.state.value,
            source_url=document.source_url,
            indicator=(
                indicator
                if snapshot.baseline_fingerprint != baseline.fingerprint
                else old.indicator
            ),
            reason=(
                reason
                if snapshot.baseline_fingerprint != baseline.fingerprint
                else old.reason
            ),
            source_health=old.source_health,
            official_status=old.official_status,
            official_amendments=old.official_amendments,
            official_correction_count=old.official_correction_count,
            last_checked_at=old.last_checked_at,
            last_semantic_sha256=old.last_semantic_sha256,
            accepted_semantic_sha256=(
                ""
                if snapshot.baseline_fingerprint != baseline.fingerprint
                else old.accepted_semantic_sha256
            ),
            error=old.error,
        ))
    return RadarSnapshot(
        baseline_id=baseline.baseline_id,
        baseline_fingerprint=baseline.fingerprint,
        generated_at=snapshot.generated_at,
        entries=tuple(entries),
    )


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self._suppressed = 0
        self._anchor_parts: list[str] | None = None
        self._anchor_href = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._suppressed += 1
        elif tag == "a" and not self._suppressed:
            self._anchor_parts = []
            self._anchor_href = str(dict(attrs).get("href", ""))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._suppressed:
            self._suppressed -= 1
        elif tag == "a" and self._anchor_parts is not None:
            anchor = re.sub(r"\s+", " ", " ".join(self._anchor_parts)).strip()
            if anchor:
                self.anchors.append((self._anchor_href, anchor))
            self._anchor_parts = None
            self._anchor_href = ""

    def handle_data(self, data: str) -> None:
        if not self._suppressed:
            self.parts.append(data)
            if self._anchor_parts is not None:
                self._anchor_parts.append(data)


def parse_official_page(content: bytes, designation: str) -> OfficialProbe:
    parser = _VisibleTextParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    if designation.casefold() not in text.casefold():
        raise ValueError("официальная карточка не содержит обозначение документа")

    position = text.casefold().find(designation.casefold())
    status_window = text[position:position + 2500]
    status_candidates = (
        "Утратил силу в РФ",
        "Срок действия истек",
        "Отменен",
        "Заменен",
        "Принят",
        "Действует только в РФ",
        "Действует",
    )
    found = [
        (status_window.find(label), label)
        for label in status_candidates
        if status_window.find(label) >= 0
    ]
    official_status = min(found)[1] if found else "не определён"

    change_pattern = re.compile(
        r"Изменение\s*№\s*(\d+)\s+к\s+" + re.escape(designation),
        re.IGNORECASE,
    )
    amendments = tuple(sorted(
        {
            value for value in change_pattern.findall(text)
            if value != "0"
        },
        key=lambda value: int(value),
    ))
    correction_pattern = re.compile(
        r"Поправка\s+к\s+" + re.escape(designation),
        re.IGNORECASE,
    )
    correction_count = len({
        (href, anchor.casefold())
        for href, anchor in parser.anchors
        if correction_pattern.search(anchor)
    })
    semantic = {
        "designation": designation,
        "official_status": official_status,
        "amendments": amendments,
        "correction_count": correction_count,
    }
    semantic_sha = sha256(json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return OfficialProbe(
        designation=designation,
        official_status=official_status,
        amendments=amendments,
        correction_count=correction_count,
        semantic_sha256=semantic_sha,
    )


def fetch_official_source(url: str, timeout: float = 12.0) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "Zarya-Normative-Radar/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        content = response.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("официальная карточка превышает допустимый размер")
    return content


def _numeric_amendments(document: NormativeDocument) -> set[str]:
    return {row for row in document.amendments if row.isdigit()}


def _accepted_correction_count(document: NormativeDocument) -> int:
    return sum(
        row.casefold().startswith("поправка")
        for row in document.amendments
    )


_INVALID_OFFICIAL_STATUSES = {
    "Утратил силу в РФ",
    "Срок действия истек",
    "Отменен",
    "Заменен",
}


def _checked_entry(
    document: NormativeDocument,
    previous: RadarEntry,
    probe: OfficialProbe | None,
    error: str,
    checked_at: str,
) -> RadarEntry:
    if probe is None:
        indicator = (
            RadarIndicator.RED
            if document.state == NormativeDocumentState.REVIEW_REQUIRED
            else RadarIndicator.GRAY
        )
        reason = (
            document.current_edition_note
            if indicator == RadarIndicator.RED else
            "Официальный источник временно недоступен; статус не подменён догадкой."
        )
        return RadarEntry(
            document_id=document.document_id,
            designation=document.designation,
            title=document.title,
            edition=document.edition,
            accepted_amendments=document.amendments,
            baseline_state=document.state.value,
            source_url=document.source_url,
            indicator=indicator,
            reason=reason,
            source_health=SourceHealth.ERROR,
            official_status=previous.official_status,
            official_amendments=previous.official_amendments,
            official_correction_count=previous.official_correction_count,
            last_checked_at=checked_at,
            last_semantic_sha256=previous.last_semantic_sha256,
            accepted_semantic_sha256=previous.accepted_semantic_sha256,
            error=error,
        )

    expected = _numeric_amendments(document)
    official = set(probe.amendments)
    missing = expected - official
    extra = official - expected
    expected_corrections = _accepted_correction_count(document)
    missing_corrections = expected_corrections > probe.correction_count
    extra_corrections = probe.correction_count > expected_corrections
    accepted_semantic = previous.accepted_semantic_sha256

    if probe.official_status in _INVALID_OFFICIAL_STATUSES:
        indicator = RadarIndicator.RED
        reason = f"Официальный статус: {probe.official_status}. Новый выпуск требует блокировки."
    elif probe.official_status not in {"Действует", "Действует только в РФ"}:
        indicator = RadarIndicator.GRAY
        reason = "Официальный статус карточки не удалось однозначно определить."
    elif document.state == NormativeDocumentState.REVIEW_REQUIRED:
        indicator = RadarIndicator.RED
        reason = document.current_edition_note
    elif missing:
        indicator = RadarIndicator.GRAY
        reason = (
            "Карточка не подтвердила принятые изменения: "
            + ", ".join(sorted(missing, key=int))
        )
    elif missing_corrections:
        indicator = RadarIndicator.GRAY
        reason = "Карточка не подтвердила принятую поправку к документу."
    elif extra:
        indicator = RadarIndicator.ORANGE
        reason = (
            "Обнаружены непринятые изменения: № "
            + ", ".join(sorted(extra, key=int))
            + ". Требуется анализ влияния."
        )
    elif extra_corrections:
        indicator = RadarIndicator.ORANGE
        reason = (
            "Обнаружена непринятая поправка к документу. "
            "Требуется анализ влияния."
        )
    elif accepted_semantic and accepted_semantic != probe.semantic_sha256:
        indicator = RadarIndicator.ORANGE
        reason = "Семантические данные официальной карточки изменились; требуется проверка."
    else:
        indicator = RadarIndicator.GREEN
        reason = "Принятая редакция совпадает с официальной карточкой Росстандарта."
        accepted_semantic = probe.semantic_sha256

    return RadarEntry(
        document_id=document.document_id,
        designation=document.designation,
        title=document.title,
        edition=document.edition,
        accepted_amendments=document.amendments,
        baseline_state=document.state.value,
        source_url=document.source_url,
        indicator=indicator,
        reason=reason,
        source_health=SourceHealth.OK,
        official_status=probe.official_status,
        official_amendments=probe.amendments,
        official_correction_count=probe.correction_count,
        last_checked_at=checked_at,
        last_semantic_sha256=probe.semantic_sha256,
        accepted_semantic_sha256=accepted_semantic,
        error="",
    )


def _event_for(
    document: NormativeDocument,
    previous: RadarEntry,
    current: RadarEntry,
    detected_at: str,
    baseline_fingerprint: str,
) -> RadarEvent | None:
    expected = _numeric_amendments(document)
    extra = set(current.official_amendments) - expected
    extra_correction = (
        current.official_correction_count
        > _accepted_correction_count(document)
    )
    changed = current.indicator != previous.indicator
    important = current.indicator in {
        RadarIndicator.ORANGE,
        RadarIndicator.RED,
    }
    if not extra and not extra_correction and not (changed and important):
        return None
    if extra:
        kind = "amendment_detected"
    elif extra_correction:
        kind = "correction_detected"
    else:
        kind = "status_changed"
    identity = "|".join((
        baseline_fingerprint,
        document.document_id,
        kind,
        current.indicator.value,
        current.last_semantic_sha256,
        current.reason,
    ))
    return RadarEvent(
        event_id=sha256(identity.encode("utf-8")).hexdigest()[:20],
        detected_at=detected_at,
        document_id=document.document_id,
        designation=document.designation,
        kind=kind,
        indicator=current.indicator.value,
        message=current.reason,
        source_url=document.source_url,
        semantic_sha256=current.last_semantic_sha256,
    )


def run_radar_check(
    *,
    store: NormativeRadarStore | None = None,
    baseline: NormativeBaseline | None = None,
    fetcher: FetchSource = fetch_official_source,
    timeout: float = 12.0,
) -> RadarSnapshot:
    baseline = baseline or get_active_baseline()
    store = store or NormativeRadarStore()
    previous_snapshot = store.load(baseline)
    previous_by_id = {
        row.document_id: row for row in previous_snapshot.entries
    }
    checked_at = _now()

    probes: dict[str, OfficialProbe] = {}
    errors: dict[str, str] = {}
    monitored = [row for row in baseline.documents if row.source_url]
    with ThreadPoolExecutor(max_workers=min(4, len(monitored) or 1)) as pool:
        futures = {
            pool.submit(fetcher, row.source_url, timeout): row
            for row in monitored
        }
        for future in as_completed(futures):
            document = futures[future]
            try:
                probes[document.document_id] = parse_official_page(
                    future.result(),
                    document.designation,
                )
            except Exception as exc:  # сбой одного источника не рушит весь радар.
                errors[document.document_id] = str(exc)[:500]

    entries: list[RadarEntry] = []
    events: list[RadarEvent] = []
    for document in baseline.documents:
        previous = previous_by_id.get(
            document.document_id,
            _entry_from_document(document),
        )
        if not document.source_url:
            current = _entry_from_document(document)
        else:
            current = _checked_entry(
                document,
                previous,
                probes.get(document.document_id),
                errors.get(document.document_id, ""),
                checked_at,
            )
        entries.append(current)
        event = _event_for(
            document,
            previous,
            current,
            checked_at,
            baseline.fingerprint,
        )
        if event is not None:
            events.append(event)

    snapshot = RadarSnapshot(
        baseline_id=baseline.baseline_id,
        baseline_fingerprint=baseline.fingerprint,
        generated_at=checked_at,
        entries=tuple(entries),
    )
    store.commit(snapshot, tuple(events))
    return snapshot

"""Private, versioned drafts for the optional studio (separate from projects)."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from app.intake.studio_intake import (
    IntakeError, MAX_DOCUMENTS, MAX_TOTAL_BYTES, candidate_hash, candidates_for,
)

ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class StaleDraft(IntakeError):
    pass


class StudioStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def folder(self, draft_id: str) -> Path:
        if not ID_PATTERN.fullmatch(draft_id):
            raise FileNotFoundError("Черновик не найден.")
        return self.root / draft_id

    def create(self) -> tuple[str, dict]:
        draft_id = uuid.uuid4().hex
        folder = self.folder(draft_id)
        folder.mkdir(parents=True, mode=0o700)
        draft = {"revision": 0, "documents": [], "answers": {}, "calculation": None, "project_id": draft_id}
        draft["metering_default"] = "common"
        draft["common_vu_topology"] = "gost_g1"
        self._write(folder, draft)
        return draft_id, draft

    @staticmethod
    def _write(folder: Path, draft: dict):
        fd, name = tempfile.mkstemp(dir=folder, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(draft, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, folder / "draft.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def load(self, draft_id: str) -> dict:
        data = json.loads(
            (self.folder(draft_id) / "draft.json").read_text(encoding="utf-8")
        )
        # Old persisted drafts keep their previous topology until the user
        # changes the visible checkbox. New drafts carry an explicit marker.
        data.setdefault("metering_default", "per_inlet")
        data.setdefault("common_vu_topology", "merge_before")
        return {**data, "project_id": draft_id}

    @contextmanager
    def read_revision(self, draft_id: str, revision: int):
        """Consistent opt-in snapshot without modifying the working draft."""
        folder = self.folder(draft_id)
        with (folder / ".lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            draft = self.load(draft_id)
            if draft["revision"] != revision:
                raise StaleDraft("Исходные изменились. Откройте окно сохранения версии заново.")
            yield draft

    @contextmanager
    def edit(self, draft_id: str, revision: int, *, cleanup_preview_on_error: bool = False):
        folder = self.folder(draft_id)
        # Cross-process lock: optimistic revision checks also cover multiple tabs/workers.
        with (folder / ".lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            draft = self.load(draft_id)
            if draft["revision"] != revision:
                raise StaleDraft(
                    "Черновик изменён в другой вкладке. Обновите данные и повторите действие."
                )
            self._finish_deletions(folder, draft)
            previous_preview_id = (draft.get("preview") or {}).get("id")
            yield draft
            draft["revision"] += 1
            try:
                self._write(folder, draft)
            except OSError:
                if cleanup_preview_on_error:
                    # Still under LOCK_EX: no waiting edit can race this decision.
                    # Read back the commit, never infer rollback from an exception.
                    candidate = (draft.get("preview") or {}).get("id")
                    try:
                        persisted = self.load(draft_id)
                    except (OSError, ValueError):
                        persisted = None  # Unknown outcome: preserve files.
                    if (isinstance(candidate, str) and ID_PATTERN.fullmatch(candidate)
                            and candidate != previous_preview_id and persisted is not None
                            and persisted["revision"] == revision
                            and (persisted.get("preview") or {}).get("id") == previous_preview_id):
                        shutil.rmtree(folder / "previews" / candidate, ignore_errors=True)
                raise
            # Metadata/access are revoked durably before unlinking. If unlink
            # fails or the worker stops, the next edit retries the private queue.
            self._finish_deletions(folder, draft)

    def _finish_deletions(self, folder: Path, draft: dict):
        pending = draft.get("pending_document_deletions", [])
        if not pending:
            return
        for document_id in pending:
            if not re.fullmatch(r"[a-f0-9]{24}", document_id):
                raise IntakeError("Некорректный идентификатор удаления.")
            (folder / f"{document_id}.pdf").unlink(missing_ok=True)
        draft.pop("pending_document_deletions", None)
        self._write(folder, draft)

    def delete_document(self, draft_id: str, revision: int, document_id: str) -> dict:
        with self.edit(draft_id, revision) as draft:
            if draft.get("study"):
                raise IntakeError("Документы учебного примера не удаляются.")
            if not any(doc["id"] == document_id for doc in draft["documents"]):
                raise FileNotFoundError("Документ не найден.")
            old_candidates = {key: candidates_for(draft, key) for key in draft["answers"]}
            draft["documents"] = [doc for doc in draft["documents"] if doc["id"] != document_id]
            for key, answer in list(draft["answers"].items()):
                source = answer.get("source") or {}
                if source.get("kind") != "document_confirmed":
                    continue  # Explicit manual inputs remain the user's inputs.
                evidence = [item for item in source.get("evidence", []) if item["document_id"] != document_id]
                if not evidence:
                    del draft["answers"][key]
                    continue
                source["evidence"] = evidence
                if answer.get("candidates_hash") == candidate_hash(old_candidates[key]):
                    answer["candidates_hash"] = candidate_hash(candidates_for(draft, key))
            for key in ("calculation", "project_calculation", "preview", "package"):
                draft[key] = None
            draft.pop("handoff", None)
            draft["pending_document_deletions"] = [document_id]
        return draft

    def add_documents(
        self, draft_id: str, revision: int, documents: list[tuple[dict, bytes]]
    ) -> dict:
        with self.edit(draft_id, revision) as draft:
            known = {doc["id"] for doc in draft["documents"]}
            fresh = []
            for doc, content in documents:
                if doc["id"] not in known:
                    fresh.append((doc, content))
                    known.add(doc["id"])
            if len(known) > MAX_DOCUMENTS:
                raise IntakeError("В одном черновике допускается не больше 10 PDF.")
            if (
                sum(doc["bytes"] for doc in draft["documents"])
                + sum(len(content) for _, content in fresh)
                > MAX_TOTAL_BYTES
            ):
                raise IntakeError("Общий размер документов черновика превышает 40 МБ.")
            for doc, content in fresh:
                path = self.folder(draft_id) / (doc["id"] + ".pdf")
                with path.open("wb") as stream:
                    stream.write(content)
                path.chmod(0o600)
                draft["documents"].append(doc)
            if fresh:
                draft["calculation"] = None
                draft["project_calculation"] = None
                draft["package"] = None
                draft["preview"] = None
        return draft

    def document(self, draft_id: str, document_id: str) -> tuple[Path, dict]:
        draft = self.load(draft_id)
        doc = next(
            (doc for doc in draft["documents"] if doc["id"] == document_id), None
        )
        if doc is None:
            raise FileNotFoundError("Документ не найден.")
        return self.folder(draft_id) / (doc["id"] + ".pdf"), doc

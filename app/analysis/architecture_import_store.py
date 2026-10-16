"""Локальное хранилище сессий подтверждения архитектурных PDF."""
from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import re
import shutil
import threading
import uuid

from app.analysis.architecture_pdf import ArchitecturePdfSurvey, survey_architecture_pdf


_ID_RE = re.compile(r"^[a-f0-9]{10}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_ROUTE_LOCK = threading.RLock()


class ArchitectureImportStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(
            root
            or os.environ.get("ZARYA_ARCHITECTURE_IMPORT_ROOT")
            or "/tmp/zarya_architecture_imports"
        )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _directory(self, import_id: str) -> Path:
        if not _ID_RE.fullmatch(import_id):
            raise ValueError("invalid architecture import id")
        return self.root / import_id

    def create(self, original_name: str, content: bytes) -> str:
        survey = survey_architecture_pdf(content, original_name=original_name)
        import_id = uuid.uuid4().hex[:10]
        directory = self._directory(import_id)
        directory.mkdir(mode=0o700)
        source = directory / "source.pdf"
        source.write_bytes(content)
        source.chmod(0o600)
        metadata = {
            "import_id": import_id,
            "original_name": survey.original_name,
            "sha256": survey.sha256,
        }
        meta_path = directory / "metadata.json"
        meta_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        meta_path.chmod(0o600)
        return import_id

    def metadata(self, import_id: str) -> dict[str, str]:
        path = self._directory(import_id) / "metadata.json"
        if not path.is_file():
            raise FileNotFoundError(import_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid architecture import metadata")
        return {str(key): str(item) for key, item in value.items()}

    def survey(self, import_id: str) -> ArchitecturePdfSurvey:
        directory = self._directory(import_id)
        metadata = self.metadata(import_id)
        source = directory / "source.pdf"
        if not source.is_file():
            raise FileNotFoundError(import_id)
        survey = survey_architecture_pdf(
            source.read_bytes(),
            original_name=metadata["original_name"],
        )
        if survey.sha256 != metadata["sha256"]:
            raise ValueError("architecture import checksum mismatch")
        return survey

    def save_confirmations(self, import_id: str, value: dict) -> None:
        directory = self._directory(import_id)
        self.metadata(import_id)
        target = directory / "confirmations.json"
        target.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        target.chmod(0o600)

    def load_confirmations(self, import_id: str) -> dict:
        target = self._directory(import_id) / "confirmations.json"
        if not target.is_file():
            return {"floors": []}
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid architecture confirmations")
        return value

    def save_wastewater_binding(self, import_id: str, value: dict) -> None:
        directory = self._directory(import_id)
        self.metadata(import_id)
        target = directory / "wastewater_binding.json"
        target.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        target.chmod(0o600)

    def load_wastewater_binding(self, import_id: str) -> dict:
        target = self._directory(import_id) / "wastewater_binding.json"
        if not target.is_file():
            return {}
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid architecture wastewater binding")
        return value

    def save_project_link(
        self,
        import_id: str,
        *,
        project_id: str,
        project_source_sha256: str,
    ) -> None:
        """Зафиксировать проект и точную версию его YAML для этой сессии."""
        if not _ID_RE.fullmatch(project_id):
            raise ValueError("invalid linked project id")
        if not _SHA256_RE.fullmatch(project_source_sha256):
            raise ValueError("invalid linked project checksum")
        directory = self._directory(import_id)
        self.metadata(import_id)
        target = directory / "project_link.json"
        target.write_text(
            json.dumps(
                {
                    "project_id": project_id,
                    "project_source_sha256": project_source_sha256,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        target.chmod(0o600)

    def load_project_link(self, import_id: str) -> dict[str, str]:
        target = self._directory(import_id) / "project_link.json"
        if not target.is_file():
            return {}
        value = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid architecture project link")
        project_id = str(value.get("project_id", ""))
        checksum = str(value.get("project_source_sha256", ""))
        if not _ID_RE.fullmatch(project_id) or not _SHA256_RE.fullmatch(checksum):
            raise ValueError("invalid architecture project link")
        return {
            "project_id": project_id,
            "project_source_sha256": checksum,
        }

    def delete_project_link(self, import_id: str) -> None:
        directory = self._directory(import_id)
        self.metadata(import_id)
        target = directory / "project_link.json"
        if target.is_file():
            target.unlink()

    def load_route_traces(self, import_id: str) -> dict:
        self.metadata(import_id)
        path = self._directory(import_id) / "route_traces.json"
        if not path.is_file():
            return {"version": 1, "revision": 0, "traces": []}
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("version") != 1
                or type(value.get("revision")) is not int or not isinstance(value.get("traces"), list)):
            raise ValueError("invalid route measurement state")
        return value

    def save_route_traces(self, import_id: str, traces: list[dict], *, expected_revision: int) -> None:
        # One lock across processes sharing the local store, plus optimistic
        # revision control: a second tab must not overwrite an unseen edit.
        self.metadata(import_id)
        lock_path = self._directory(import_id) / "route_traces.lock"
        with _ROUTE_LOCK, lock_path.open("a") as lock:
            lock_path.chmod(0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = self.load_route_traces(import_id)
            if type(expected_revision) is not int or current["revision"] != expected_revision:
                raise ValueError("Список трасс изменился в другой вкладке. Обновите страницу.")
            if len(traces) > 100:
                raise ValueError("В одной сессии измерения допускается до 100 трасс.")
            value = {"version": 1, "revision": expected_revision+1, "traces": traces}
            content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
            directory = self._directory(import_id)
            temporary = directory / f"routes-{uuid.uuid4().hex}.tmp"
            try:
                temporary.write_text(content, encoding="utf-8")
                temporary.chmod(0o600)
                temporary.replace(directory / "route_traces.json")
            finally:
                temporary.unlink(missing_ok=True)

    def delete(self, import_id: str) -> None:
        directory = self._directory(import_id)
        if directory.exists():
            shutil.rmtree(directory)

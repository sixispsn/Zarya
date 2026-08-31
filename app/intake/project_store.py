# -*- coding: utf-8 -*-
"""
app/intake/project_store.py — персистентность проектов (поверх YAML).

Хранилище = папка с файлами проектов:

    <root>/
      <project_id>.yaml     # намерение (IOS2Request) в YAML — источник истины
      <project_id>.meta     # название | обновлён ISO8601 | SHA-256
      _revisions/
        <project_id>/<sha256>.yaml

Осознанно файлы, а не БД: git-friendly, читаемо человеком, ноль зависимостей.
Рабочие выпуски и PDF хранятся отдельно в ReleaseStore и PassportStore.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.intake.request_dto import IOS2Request
from app.intake.yaml_io import load_request, dump_request


DEFAULT_ROOT = os.environ.get("ZARYA_PROJECTS_DIR",
                              os.path.expanduser("~/.zarya/projects"))

_ID_RE = re.compile(r"^[a-f0-9]{10}$")


@dataclass
class ProjectSummary:
    project_id: str
    title: str
    updated_at: str          # ISO 8601


@dataclass(frozen=True)
class ProjectRevision:
    project_id: str
    source_sha256: str
    saved_at: str


class ProjectStore:
    """Файловое хранилище намерений проектов."""

    def __init__(self, root: str = DEFAULT_ROOT):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.revisions_root = os.path.join(root, "_revisions")
        os.makedirs(self.revisions_root, exist_ok=True)

    def _atomic_write(self, path: str, content: str) -> None:
        """Записать UTF-8 файл без состояния частичной записи."""
        fd, temporary = tempfile.mkstemp(
            prefix=f".{Path(path).name}.",
            suffix=".tmp",
            dir=self.root,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _revision_directory(self, project_id: str) -> str:
        self._paths(project_id)
        return os.path.join(self.revisions_root, project_id)

    # ── пути (с защитой от traversal) ──
    def _paths(self, project_id: str) -> tuple:
        if not _ID_RE.match(project_id):
            raise ValueError(f"некорректный project_id: {project_id!r}")
        return (os.path.join(self.root, project_id + ".yaml"),
                os.path.join(self.root, project_id + ".meta"))

    # ── операции ──
    def save(self, req: IOS2Request, project_id: Optional[str] = None) -> str:
        """Сохраняет намерение; возвращает project_id (новый или обновлённый)."""
        pid = project_id or uuid.uuid4().hex[:10]
        ypath, mpath = self._paths(pid)
        content = dump_request(req)
        source_hash = sha256(content.encode("utf-8")).hexdigest()
        revision_directory = self._revision_directory(pid)
        os.makedirs(revision_directory, exist_ok=True)
        revision_path = os.path.join(revision_directory, source_hash + ".yaml")
        if not os.path.exists(revision_path):
            self._atomic_write(revision_path, content)
        self._atomic_write(ypath, content)
        title = req.document.object_name or req.document.cipher or pid
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._atomic_write(mpath, f"{title}|{stamp}|{source_hash}")
        return pid

    def load(self, project_id: str) -> IOS2Request:
        ypath, _ = self._paths(project_id)
        if not os.path.isfile(ypath):
            raise FileNotFoundError(f"проект {project_id} не найден")
        with open(ypath, encoding="utf-8") as f:
            return load_request(f.read())

    def source_sha256(self, project_id: str) -> str:
        """Контрольная сумма сохранённого YAML — версия намерения проекта."""
        ypath, _ = self._paths(project_id)
        if not os.path.isfile(ypath):
            raise FileNotFoundError(f"проект {project_id} не найден")
        with open(ypath, "rb") as source:
            return sha256(source.read()).hexdigest()

    def delete(self, project_id: str) -> None:
        ypath, mpath = self._paths(project_id)
        for p in (ypath, mpath):
            if os.path.isfile(p):
                os.remove(p)
        shutil.rmtree(self._revision_directory(project_id), ignore_errors=True)

    def list(self) -> List[ProjectSummary]:
        """Список проектов, свежие сверху."""
        out: List[ProjectSummary] = []
        for fn in os.listdir(self.root):
            if not fn.endswith(".meta"):
                continue
            pid = fn[:-5]
            if not _ID_RE.match(pid):
                continue
            try:
                raw = open(os.path.join(self.root, fn), encoding="utf-8").read()
                parts = raw.rsplit("|", 2)
                if len(parts) < 2:
                    raise ValueError("некорректный meta-файл проекта")
                title, stamp = parts[0], parts[1]
            except (OSError, ValueError):
                continue
            out.append(ProjectSummary(pid, title, stamp))
        out.sort(key=lambda s: s.updated_at, reverse=True)
        return out

    def exists(self, project_id: str) -> bool:
        try:
            ypath, _ = self._paths(project_id)
        except ValueError:
            return False
        return os.path.isfile(ypath)

    def list_revisions(self, project_id: str) -> List[ProjectRevision]:
        """Версии исходного YAML, отсортированные по времени файла."""
        directory = self._revision_directory(project_id)
        if not os.path.isdir(directory):
            return []
        revisions: List[ProjectRevision] = []
        for name in os.listdir(directory):
            if not re.fullmatch(r"[a-f0-9]{64}\.yaml", name):
                continue
            path = os.path.join(directory, name)
            stamp = datetime.fromtimestamp(
                os.path.getmtime(path), timezone.utc
            ).isoformat(timespec="seconds")
            revisions.append(ProjectRevision(project_id, name[:-5], stamp))
        revisions.sort(key=lambda row: row.saved_at, reverse=True)
        return revisions

    def load_revision(self, project_id: str, source_sha256: str) -> IOS2Request:
        if not re.fullmatch(r"[a-f0-9]{64}", source_sha256 or ""):
            raise ValueError("некорректный SHA-256 ревизии")
        path = os.path.join(
            self._revision_directory(project_id), source_sha256 + ".yaml"
        )
        if not os.path.isfile(path):
            raise FileNotFoundError("ревизия проекта не найдена")
        with open(path, encoding="utf-8") as stream:
            return load_request(stream.read())

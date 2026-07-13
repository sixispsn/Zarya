# -*- coding: utf-8 -*-
"""
app/intake/project_store.py — персистентность проектов (поверх YAML).

Хранилище = папка с файлами проектов:

    <root>/
      <project_id>.yaml     # намерение (IOS2Request) в YAML — источник истины
      <project_id>.meta     # строка "название | обновлён ISO8601" для списка

Осознанно файлы, а не БД: git-friendly, читаемо человеком, ноль зависимостей.
Результаты расчёта НЕ храним — они дешёво пересчитываются из намерения
(источник истины — вход, не выход). PDF генерятся заново при открытии.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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


class ProjectStore:
    """Файловое хранилище намерений проектов."""

    def __init__(self, root: str = DEFAULT_ROOT):
        self.root = root
        os.makedirs(root, exist_ok=True)

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
        with open(ypath, "w", encoding="utf-8") as f:
            f.write(dump_request(req))
        title = req.document.object_name or req.document.cipher or pid
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(mpath, "w", encoding="utf-8") as f:
            f.write(f"{title}|{stamp}")
        return pid

    def load(self, project_id: str) -> IOS2Request:
        ypath, _ = self._paths(project_id)
        if not os.path.isfile(ypath):
            raise FileNotFoundError(f"проект {project_id} не найден")
        with open(ypath, encoding="utf-8") as f:
            return load_request(f.read())

    def delete(self, project_id: str) -> None:
        ypath, mpath = self._paths(project_id)
        for p in (ypath, mpath):
            if os.path.isfile(p):
                os.remove(p)

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
                title, stamp = raw.split("|", 1)
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

"""Opt-in, private PDF bundles associated with immutable pilot versions."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid

from app.intake.pilot_objects import PilotObjectStore, SnapshotConflict, SnapshotLimit, checksum
from app.intake.studio_intake import IntakeError

MAX_FILES = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
USER_QUOTA = 200 * 1024 * 1024
GLOBAL_QUOTA = 2 * 1024 * 1024 * 1024
CONSENT_VERSION = "pilot-expertise-pdf-v1"


def filename(value: str) -> str:
    name = unicodedata.normalize("NFC", value).strip()
    if (not name.lower().endswith(".pdf") or len(name) > 160 or len(name) < 5
            or any(c in name for c in '/\\') or any(unicodedata.category(c).startswith("C") for c in name)):
        raise IntakeError("Нужны PDF с именами до 160 символов, без путей и управляющих знаков.")
    return name


def probe(path: Path) -> int:
    try:
        result = subprocess.run([sys.executable, "-m", "app.intake.pilot_pdf_probe", str(path)],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        return int(json.loads(result.stdout)["pages"])
    except (subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise IntakeError("PDF повреждён, защищён паролем или слишком сложен для проверки. Экспортируйте обычный PDF без пароля (до 2000 страниц).") from exc


def receipt(row):
    return {"bundle_id": row["id"], "object_id": row["object_id"], "version": row["version_number"],
            "url": f"/studio/pilot-objects/{row['object_id']}/versions/{row['version_number']}#bundle-{row['id']}"}


class PilotAttachmentStore:
    def __init__(self):
        self.objects = PilotObjectStore()
        self.access = self.objects.access
        self.root = self.access.root / "bundles"
        self.root.mkdir(mode=0o700, exist_ok=True)
        with self.access.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pilot_bundles (
                    id TEXT PRIMARY KEY, object_id TEXT NOT NULL, version_number INTEGER NOT NULL,
                    user_id TEXT NOT NULL, request_id TEXT NOT NULL, intent_sha256 TEXT NOT NULL,
                    note TEXT NOT NULL, expertise_ref TEXT NOT NULL, status TEXT NOT NULL,
                    consent_version TEXT NOT NULL, created REAL NOT NULL, bytes INTEGER NOT NULL,
                    files_json TEXT NOT NULL,
                    UNIQUE(user_id,request_id), UNIQUE(user_id,intent_sha256)
                );
                CREATE INDEX IF NOT EXISTS pilot_bundles_version ON pilot_bundles(object_id,version_number);
                CREATE INDEX IF NOT EXISTS pilot_bundles_user ON pilot_bundles(user_id,created);
                CREATE TRIGGER IF NOT EXISTS pilot_bundle_immutable BEFORE UPDATE ON pilot_bundles
                    BEGIN SELECT RAISE(ABORT, 'pilot bundle is immutable'); END;
            """)

    def author(self, user, object_id, number):
        obj, _ = self.objects.version(user, object_id, number)
        if obj["user_id"] != user.id:
            raise FileNotFoundError

    @staticmethod
    def previous(db, user, request_id, intent):
        row = db.execute("SELECT * FROM pilot_bundles WHERE user_id=? AND request_id=?", (user.id, request_id)).fetchone()
        if row and row["intent_sha256"] != intent:
            raise SnapshotConflict("Этот запрос уже сохранён с другими файлами или описанием. Обновите страницу.")
        return row or db.execute("SELECT * FROM pilot_bundles WHERE user_id=? AND intent_sha256=?", (user.id, intent)).fetchone()

    def add(self, user, *, object_id, number, request_id, note, expertise_ref, uploads):
        self.author(user, object_id, number)
        if not 1 <= len(uploads) <= MAX_FILES:
            raise IntakeError("Выберите от 1 до 10 PDF.")
        total, files = 0, []
        for raw_name, content in uploads:
            name = filename(raw_name)
            if not content.startswith(b"%PDF-") or not 0 < len(content) <= MAX_FILE_BYTES:
                raise IntakeError("Каждый файл должен быть PDF размером не более 20 МБ.")
            total += len(content)
            files.append({"name": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        if total > MAX_TOTAL_BYTES:
            raise IntakeError("Общий размер комплекта не должен превышать 40 МБ.")
        if len({row["name"].casefold() for row in files}) != len(files):
            raise IntakeError("Имена файлов в одном комплекте должны различаться.")
        note, expertise_ref = note.strip(), expertise_ref.strip()
        intent = checksum({"object_id": object_id, "version": number, "note": note,
                           "expertise_ref": expertise_ref, "consent": CONSENT_VERSION,
                           "files": sorted(files, key=lambda f: (f["name"], f["sha256"]))})
        with self.access.connect() as db:
            if row := self.previous(db, user, request_id, intent):
                return receipt(row)
        if shutil.disk_usage(self.root).free < total + 1024 * 1024 * 1024:
            raise SnapshotLimit("Недостаточно свободного места. Обратитесь к владельцу ЗАРИ.")
        bundle_id, final, committed = uuid.uuid4().hex, None, False
        try:
            with tempfile.TemporaryDirectory(prefix=".upload-", dir=self.root) as temporary:
                stage = Path(temporary)
                for row, (_, content) in zip(files, uploads):
                    row["id"] = uuid.uuid4().hex
                    path = stage / (row["id"] + ".pdf")
                    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, "wb") as out:
                        out.write(content)
                        out.flush()
                        os.fsync(out.fileno())
                    row["pages"] = probe(path)
                with self.access.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if row := self.previous(db, user, request_id, intent):
                        return receipt(row)
                    now = time.time()
                    if db.execute("SELECT COUNT(*) FROM pilot_bundles WHERE user_id=? AND created>?", (user.id, now - 3600)).fetchone()[0] >= 5:
                        raise SnapshotLimit("Не более 5 новых комплектов в час. Сохранённые запросы можно повторить.")
                    if db.execute("SELECT COUNT(*) FROM pilot_bundles WHERE object_id=? AND version_number=?", (object_id, number)).fetchone()[0] >= 10:
                        raise SnapshotLimit("У этой версии уже 10 комплектов. Сохраните новую версию объекта.")
                    used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM pilot_bundles WHERE user_id=?", (user.id,)).fetchone()[0]
                    all_used = db.execute("SELECT COALESCE(SUM(bytes),0) FROM pilot_bundles").fetchone()[0]
                    if used + total > USER_QUOTA or all_used + total > GLOBAL_QUOTA:
                        raise SnapshotLimit("Лимит хранения комплектов достигнут. Обратитесь к владельцу ЗАРИ.")
                    db.execute("INSERT INTO pilot_bundles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (bundle_id, object_id, number, user.id, request_id, intent, note, expertise_ref,
                                "passed_declared", CONSENT_VERSION, now, total, json.dumps(files, ensure_ascii=False)))
                    final = self.root / bundle_id
                    stage.rename(final)
                committed = True
        finally:
            if final and not committed and final.exists():
                shutil.rmtree(final)
        return receipt({"id": bundle_id, "object_id": object_id, "version_number": number})

    def list(self, user, object_id, number):
        self.objects.version(user, object_id, number)
        with self.access.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM pilot_bundles WHERE object_id=? AND version_number=? ORDER BY created DESC,id", (object_id, number))]
        for row in rows:
            row["files"] = json.loads(row.pop("files_json"))
            row["date"] = datetime.fromtimestamp(row["created"], timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        return rows

    def download(self, user, bundle_id, file_id):
        if not all(re.fullmatch(r"[a-f0-9]{32}", value) for value in (bundle_id, file_id)):
            raise FileNotFoundError
        with self.access.connect() as db:
            row = db.execute("SELECT * FROM pilot_bundles WHERE id=? AND (?=1 OR user_id=?)", (bundle_id, int(user.role == "admin"), user.id)).fetchone()
        if not row:
            raise FileNotFoundError
        self.objects.version(user, row["object_id"], row["version_number"])
        file = next((item for item in json.loads(row["files_json"]) if item["id"] == file_id), None)
        if not file:
            raise FileNotFoundError
        path = self.root / bundle_id / (file_id + ".pdf")
        if not path.is_file():
            raise IntakeError("Файл комплекта недоступен. Обратитесь к владельцу.")
        with path.open("rb") as source:
            if path.stat().st_size != file["bytes"] or hashlib.file_digest(source, "sha256").hexdigest() != file["sha256"]:
                raise IntakeError("Нарушена целостность файла. Скачивание остановлено.")
        return path, file

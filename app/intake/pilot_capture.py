"""Atomic, opt-in baseline capture of numerical results and actual generated PDFs.

Input paths come only from the renderer's server-side manifest, never a client.
Source uploads are deliberately excluded. A failed capture never claims success.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from app.intake.pilot_admin import PARTICIPATION, PilotAdminStore
from app.intake.pilot_objects import PilotObjectStore, SnapshotLimit, checksum, make_snapshot
from app.intake.studio_intake import IntakeError, accepted_values

MAX_FILE = 20 * 1024**2
MAX_BUNDLE = 80 * 1024**2
MAX_USER = 500 * 1024**2
MAX_TOTAL = 4 * 1024**3


class PilotCaptureStore:
    def __init__(self):
        self.archive = PilotObjectStore()
        self.access = self.archive.access
        self.root = self.access.root / "generated"
        self.root.mkdir(mode=0o700, exist_ok=True)
        with self.access.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pilot_drafts (
                    user_id TEXT NOT NULL, draft_id TEXT NOT NULL, object_id TEXT NOT NULL,
                    PRIMARY KEY(user_id,draft_id)
                );
                CREATE TABLE IF NOT EXISTS pilot_generated (
                    object_id TEXT NOT NULL, version_number INTEGER NOT NULL, user_id TEXT NOT NULL,
                    bundle_id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, bytes INTEGER NOT NULL,
                    files_json TEXT NOT NULL, PRIMARY KEY(object_id,version_number)
                );
                CREATE TRIGGER IF NOT EXISTS pilot_generated_immutable BEFORE UPDATE ON pilot_generated
                    BEGIN SELECT RAISE(ABORT, 'generated baseline is immutable'); END;
            """)

    def capture(self, user, did: str, draft: dict, kind: str, files=()):
        if draft.get("study") or not PilotAdminStore().has_consent(user):
            return None
        if kind not in {"calculation", "preview", "package"}:
            raise ValueError("Unknown capture kind")
        snapshot = make_snapshot(draft)
        bundle_id = uuid.uuid4().hex
        stage = self.root / (".pending-" + bundle_id)
        stage.mkdir(mode=0o700)
        final = self.root / bundle_id
        moved, committed = False, False
        try:
            descriptors, total = [], 0
            for path, metadata in files:
                path = Path(path)
                if len(descriptors) >= 30 or path.suffix.lower() != ".pdf" or path.name != metadata["name"] or path.is_symlink():
                    raise IntakeError("Недопустимый файл выдачи для архива пилота.")
                fid, sha, size = uuid.uuid4().hex, hashlib.sha256(), 0
                target = stage / (fid + ".pdf")
                with path.open("rb") as source, target.open("xb") as dest:
                    os.chmod(target, 0o600)
                    if source.read(5) != b"%PDF-":
                        raise IntakeError("Выдача не является PDF.")
                    source.seek(0)
                    while chunk := source.read(1024**2):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_FILE or total > MAX_BUNDLE:
                            raise SnapshotLimit("PDF превышают лимит архива: 20 МБ на файл, 80 МБ на комплект.")
                        sha.update(chunk)
                        dest.write(chunk)
                    dest.flush()
                    os.fsync(dest.fileno())
                descriptors.append({"id": fid, "name": path.name, "sha256": sha.hexdigest(), "bytes": size,
                                    "state": str(metadata.get("state", kind)), "state_note": str(metadata.get("state_note", ""))})
            if kind != "calculation" and not descriptors:
                raise IntakeError("Нет PDF для сохранения выдачи пилота.")
            snapshot["scope"] = ("Версия исходных и результатов пилота. Исходные документы не скопированы. "
                                 + ("Точные PDF выдачи сохранены отдельно ниже. " if descriptors else "PDF в этой версии не формировались. ")
                                 + "Не является заключением экспертизы.")
            semantic = {k: v for k, v in snapshot.items() if k != "draft_revision"}
            manifest = [{k: v for k, v in row.items() if k != "id"} for row in descriptors]
            intent = checksum({"draft": did, "snapshot": semantic, "kind": kind, "files": manifest})
            with self.access.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                previous = self.archive._previous(db, user, intent[:32], intent)
                if previous:
                    from app.intake.pilot_objects import receipt
                    return receipt(previous)
                used = db.execute("SELECT COALESCE(SUM(bytes),0),COALESCE(SUM(CASE WHEN user_id=? THEN bytes ELSE 0 END),0) FROM pilot_generated", (user.id,)).fetchone()
                if used[0]+total > MAX_TOTAL or used[1]+total > MAX_USER or shutil.disk_usage(self.root).free < total + 1024**3:
                    raise SnapshotLimit("Архив пилота заполнен. Обратитесь к владельцу; рабочий результат сохранён.")
                mapping = db.execute("SELECT object_id FROM pilot_drafts WHERE user_id=? AND draft_id=?", (user.id, did)).fetchone()
                title = str(accepted_values(draft).get("object_name") or f"Объект {did[:8]}")[:120]
                result = self.archive.add(user, request_id=intent[:32], intent=intent,
                    object_id=mapping[0] if mapping else None, title=title,
                    note={"calculation":"Автоматически: расчёт", "preview":"Автоматически: предварительные PDF, не выпуск", "package":"Автоматически: выданный комплект"}[kind],
                    snapshot=snapshot, db=db, consent_version=PARTICIPATION)
                if not mapping:
                    db.execute("INSERT INTO pilot_drafts VALUES(?,?,?)", (user.id, did, result["object_id"]))
                if descriptors:
                    stage.rename(final)
                    moved = True
                    db.execute("INSERT INTO pilot_generated VALUES(?,?,?,?,?,?,?)", (result["object_id"], result["version"], user.id, bundle_id, kind, total, json.dumps(descriptors, ensure_ascii=False)))
            committed = True
            return result
        finally:
            if stage.exists():
                shutil.rmtree(stage)
            if moved and not committed:
                shutil.rmtree(final)

    def generated(self, user, object_id, number):
        self.archive.version(user, object_id, number)
        with self.access.connect() as db:
            row = db.execute("SELECT * FROM pilot_generated WHERE object_id=? AND version_number=?", (object_id, number)).fetchone()
        if not row:
            return None
        return {**dict(row), "files": json.loads(row["files_json"])}

    def file(self, user, bundle_id, file_id):
        with self.access.connect() as db:
            row = db.execute("SELECT * FROM pilot_generated WHERE bundle_id=? AND (user_id=? OR ?=1)", (bundle_id, user.id, int(user.role == "admin"))).fetchone()
        if not row:
            raise FileNotFoundError
        metadata = next((f for f in json.loads(row["files_json"]) if f["id"] == file_id), None)
        if not metadata:
            raise FileNotFoundError
        path = self.root / row["bundle_id"] / (metadata["id"] + ".pdf")
        with path.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != metadata["sha256"]:
            raise IntakeError("Нарушена целостность сохранённого PDF.")
        return path, metadata

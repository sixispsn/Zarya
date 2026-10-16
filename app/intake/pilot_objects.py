"""Explicitly shared, append-only pilot snapshots. No uploaded files or PDF quotes."""
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import json
import os
import time
import uuid

from app.intake.pilot_access import AccessStore, Principal
from app.intake.studio_intake import FIELDS, IntakeError, accepted_values, field_state

CONSENT_VERSION = "pilot-snapshot-v1"
PROJECT_KEYS = ("state", "missing", "can_release", "can_preview", "preview_notes",
                "sewer_scheme", "flows", "meters", "meter_error", "head", "pumps",
                "fire", "storm", "storm_note", "issues", "quality", "warnings", "status",
                "hydraulics", "hot_hydraulics", "gost_blockers", "suction_check")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def checksum(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def build_id() -> str:
    return os.environ.get("ZARYA_BUILD_COMMIT", "local")[:100]


def calculation_stamp(draft: dict) -> dict:
    values = accepted_values(draft)
    stamp = {"build": build_id()}
    if draft.get('suction_check'):
        from app.schemas.pump_suction import persisted_suction
        from app.pz.suction_check import dependency_stamp
        values = {**values, 'suction_check': persisted_suction(draft)}
        stamp['suction_dependencies'] = dependency_stamp()
    return {**stamp, "inputs_sha256": checksum(values)}


def make_snapshot(draft: dict) -> dict:
    if draft.get("study"):
        raise IntakeError("Учебный пример не является объектом пилота. Вернитесь к своему проекту.")
    inputs, unresolved = [], []
    for field in FIELDS:
        if field.key == "object_name":
            continue  # Only the explicitly provided alias identifies the shared object.
        row = field_state(draft, field)
        common = {"key": field.key, "label": field.label, "unit": field.unit, "status": row["status"]}
        if row["status"] in {"confirmed", "default"}:
            inputs.append({**common, "value": row["value"], "source_kind": row.get("source", {}).get("kind")})
        else:
            unresolved.append(common)  # No candidate values, quotes, document IDs/names.
    current = bool(draft.get("calculation") and draft.get("project_calculation") is not None
                   and draft.get("calculation_stamp") == calculation_stamp(draft))
    if draft.get('suction_check'):
        from app.schemas.pump_suction import persisted_suction
        inputs.append(dict(key='suction_check', label='Проверка всасывания одного режима',
                           unit='', status='confirmed', source_kind='manual',
                           value=persisted_suction(draft)))
    return {
        "schema_version": 1, "build": build_id(), "draft_revision": draft["revision"],
        "inputs": inputs, "unresolved": unresolved,
        "results": {"state": "current" if current else "needs_recalculation",
                    "demand": draft["calculation"] if current else None,
                    "project": {k: v for k, v in draft["project_calculation"].items() if k in PROJECT_KEYS} if current else None},
        "scope": "Снимок исходных и численных результатов. PDF, схемы и исходные документы не приложены. Не является заключением экспертизы.",
    }


class SnapshotConflict(Exception):
    pass


class SnapshotLimit(Exception):
    pass


def receipt(row) -> dict:
    return {"object_id": row["object_id"], "version": row["number"], "sha256": row["sha256"],
            "url": f"/studio/pilot-objects/{row['object_id']}/versions/{row['number']}"}


class PilotObjectStore:
    def __init__(self):
        self.access = AccessStore()
        with self.access.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pilot_objects (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL, user_name TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pilot_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, object_id TEXT NOT NULL,
                    number INTEGER NOT NULL, user_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    intent_sha256 TEXT NOT NULL, snapshot TEXT NOT NULL, sha256 TEXT NOT NULL,
                    note TEXT NOT NULL, consent_version TEXT NOT NULL, created REAL NOT NULL,
                    UNIQUE(object_id,number), UNIQUE(user_id,request_id), UNIQUE(user_id,intent_sha256)
                );
                CREATE INDEX IF NOT EXISTS pilot_objects_owner ON pilot_objects(user_id,seq);
                CREATE INDEX IF NOT EXISTS pilot_versions_rate ON pilot_versions(user_id,created);
                CREATE TRIGGER IF NOT EXISTS pilot_version_immutable BEFORE UPDATE ON pilot_versions
                    BEGIN SELECT RAISE(ABORT, 'pilot version is immutable'); END;
            """)

    @staticmethod
    def _previous(db, user: Principal, request_id: str, intent: str):
        row = db.execute("SELECT * FROM pilot_versions WHERE user_id=? AND request_id=?",
                         (user.id, request_id)).fetchone()
        if row and row["intent_sha256"] != intent:
            raise SnapshotConflict("Повтор запроса содержит другие данные. Откройте окно сохранения заново.")
        return row or db.execute("SELECT * FROM pilot_versions WHERE user_id=? AND intent_sha256=?",
                                 (user.id, intent)).fetchone()

    def previous(self, user: Principal, request_id: str, intent: str):
        with self.access.connect() as db:
            row = self._previous(db, user, request_id, intent)
            return receipt(row) if row else None

    def add(self, user: Principal, *, request_id: str, intent: str, object_id: str | None,
            title: str, note: str, snapshot: dict, db=None, consent_version=CONSENT_VERSION) -> dict:
        raw, sha, now = canonical(snapshot), checksum(snapshot), time.time()
        if len(raw.encode()) > 1_000_000:
            raise IntakeError("Снимок слишком большой: предел 1 МБ.")
        own_transaction = db is None
        with self.access.connect() if own_transaction else nullcontext(db) as db:
            if own_transaction:
                db.execute("BEGIN IMMEDIATE")
            previous = self._previous(db, user, request_id, intent)
            if previous:
                return receipt(previous)
            limit = 20 if consent_version == CONSENT_VERSION else 120
            if db.execute("SELECT COUNT(*) FROM pilot_versions WHERE user_id=? AND created>?", (user.id, now - 3600)).fetchone()[0] >= limit:
                raise SnapshotLimit(f"Не более {limit} новых версий в час. Повтор сохранённого запроса доступен.")
            if object_id:
                # Admins may read shared objects but cannot append on behalf of a tester.
                if not db.execute("SELECT 1 FROM pilot_objects WHERE id=? AND user_id=?", (object_id, user.id)).fetchone():
                    raise FileNotFoundError
            else:
                if not title:
                    raise IntakeError("Укажите название или псевдоним объекта.")
                if db.execute("SELECT COUNT(*) FROM pilot_objects WHERE user_id=?", (user.id,)).fetchone()[0] >= 100:
                    raise SnapshotLimit("Достигнут предел 100 объектов пилота.")
                object_id = uuid.uuid4().hex
                db.execute("INSERT INTO pilot_objects(id,user_id,user_name,title,created) VALUES(?,?,?,?,?)",
                           (object_id, user.id, user.name, title, now))
            number = db.execute("SELECT COALESCE(MAX(number),0)+1 FROM pilot_versions WHERE object_id=?", (object_id,)).fetchone()[0]
            if number > 1000:
                raise SnapshotLimit("Достигнут предел 1000 версий объекта.")
            db.execute("INSERT INTO pilot_versions(object_id,number,user_id,request_id,intent_sha256,snapshot,sha256,note,consent_version,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (object_id, number, user.id, request_id, intent, raw, sha, note, consent_version, now))
            return receipt({"object_id": object_id, "number": number, "sha256": sha})

    def objects(self, user: Principal, *, own_only=False, before: int | None = None):
        with self.access.connect() as db:
            rows = [dict(row) for row in db.execute("""SELECT o.*,
                (SELECT MAX(number) FROM pilot_versions v WHERE v.object_id=o.id) AS versions
                FROM pilot_objects o WHERE (?=1 OR o.user_id=?) AND (? IS NULL OR o.seq<?)
                ORDER BY o.seq DESC LIMIT 51""", (int(user.role == "admin" and not own_only), user.id, before, before))]
        return rows[:50], rows[49]["seq"] if len(rows) > 50 else None

    def object(self, user: Principal, object_id: str) -> dict:
        with self.access.connect() as db:
            row = db.execute("SELECT * FROM pilot_objects WHERE id=? AND (?=1 OR user_id=?)",
                             (object_id, int(user.role == "admin"), user.id)).fetchone()
        if not row:
            raise FileNotFoundError
        return dict(row)

    def versions(self, user: Principal, object_id: str, before: int | None = None):
        obj = self.object(user, object_id)
        with self.access.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT number,note,created,sha256 FROM pilot_versions WHERE object_id=? AND (? IS NULL OR number<?) ORDER BY number DESC LIMIT 51", (object_id, before, before))]
        for row in rows[:50]:
            row["date"] = datetime.fromtimestamp(row["created"], timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        return obj, rows[:50], rows[49]["number"] if len(rows) > 50 else None

    def version(self, user: Principal, object_id: str, number: int):
        obj = self.object(user, object_id)
        with self.access.connect() as db:
            row = db.execute("SELECT * FROM pilot_versions WHERE object_id=? AND number=?", (object_id, number)).fetchone()
        if not row:
            raise FileNotFoundError
        result = dict(row)
        result["snapshot"] = json.loads(result["snapshot"])
        if checksum(result["snapshot"]) != result["sha256"]:
            raise IntakeError("Нарушена целостность сохранённой версии. Обратитесь к владельцу.")
        return obj, result

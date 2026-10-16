"""Owner-only invitations and explicit participation; never persist access keys."""
import json
import secrets
import time
import uuid

from app.intake.pilot_access import AccessStore, Principal, digest

PARTICIPATION = "pilot-auto-archive-v1"


class AdminConflict(ValueError):
    pass


class PilotAdminStore:
    def __init__(self):
        self.access = AccessStore()
        with self.access.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pilot_members (
                    user_id TEXT PRIMARY KEY, accepted_version TEXT, accepted_at REAL
                );
                CREATE TABLE IF NOT EXISTS pilot_admin_audit (
                    owner_id TEXT NOT NULL, request_id TEXT NOT NULL, intent TEXT NOT NULL,
                    operation TEXT NOT NULL, user_id TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(owner_id,request_id)
                );
            """)

    def needs_consent(self, user: Principal) -> bool:
        with self.access.connect() as db:
            row = db.execute("SELECT accepted_version FROM pilot_members WHERE user_id=?", (user.id,)).fetchone()
        return row is not None and row[0] != PARTICIPATION

    def has_consent(self, user: Principal) -> bool:
        with self.access.connect() as db:
            return bool(db.execute("SELECT 1 FROM pilot_members WHERE user_id=? AND accepted_version=?",
                                   (user.id, PARTICIPATION)).fetchone())

    def accept(self, user: Principal):
        with self.access.connect() as db:
            db.execute("INSERT INTO pilot_members VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET accepted_version=excluded.accepted_version,accepted_at=excluded.accepted_at",
                       (user.id, PARTICIPATION, time.time()))

    def users(self):
        with self.access.connect() as db:
            return [dict(r) for r in db.execute("""SELECT u.id,u.name,u.role,u.disabled,u.key_expires,
                m.accepted_version,m.accepted_at FROM users u LEFT JOIN pilot_members m ON m.user_id=u.id
                ORDER BY u.role,u.name""")]

    def operate(self, owner: Principal, *, request_id: str, operation: str,
                name: str = "", days: int = 30, user_id: str | None = None):
        if owner.role != "admin":
            raise PermissionError
        if operation not in {"issue", "reissue", "revoke"} or not 1 <= days <= 90:
            raise ValueError("Проверьте действие и срок доступа.")
        name = name.strip()
        if operation == "issue" and (not name or user_id):
            raise ValueError("Укажите имя нового участника.")
        if operation != "issue" and not user_id:
            raise ValueError("Выберите участника.")
        intent = digest(json.dumps([operation, name, days, user_id], ensure_ascii=False))
        now = time.time()
        with self.access.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM users WHERE id=? AND role='admin' AND disabled=0 AND key_expires>?", (owner.id, now)).fetchone():
                raise PermissionError
            previous = db.execute("SELECT intent,user_id FROM pilot_admin_audit WHERE owner_id=? AND request_id=?",
                                  (owner.id, request_id)).fetchone()
            if previous:
                if previous["intent"] != intent:
                    raise AdminConflict("Запрос уже выполнен с другими параметрами.")
                return {"user_id": previous["user_id"], "key": None, "repeated": True}
            if db.execute("SELECT COUNT(*) FROM pilot_admin_audit WHERE owner_id=? AND created>?", (owner.id, now-3600)).fetchone()[0] >= 30:
                raise AdminConflict("Не более 30 операций с приглашениями в час.")
            if operation != "issue":
                target = db.execute("SELECT name,role FROM users WHERE id=?", (user_id,)).fetchone()
                if not target or target["role"] != "tester" or user_id == owner.id:
                    raise ValueError("Здесь можно менять только доступ тестеров, не владельца.")
                name = target["name"]
            elif db.execute("SELECT COUNT(*) FROM users WHERE role='tester'").fetchone()[0] >= 100:
                raise AdminConflict("Достигнут предел 100 участников.")
            key = None
            if operation == "revoke":
                db.execute("UPDATE users SET disabled=1 WHERE id=?", (user_id,))
            else:
                key = "zarya_" + secrets.token_urlsafe(32)
                if operation == "issue":
                    user_id = uuid.uuid4().hex
                    db.execute("INSERT INTO users(id,name,role,key_hash,key_expires) VALUES(?,?,'tester',?,?)",
                               (user_id, name, digest(key), now + days*86400))
                else:
                    db.execute("UPDATE users SET key_hash=?,key_expires=?,disabled=0 WHERE id=?",
                               (digest(key), now + days*86400, user_id))
                db.execute("INSERT OR IGNORE INTO pilot_members(user_id) VALUES(?)", (user_id,))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            db.execute("INSERT INTO pilot_admin_audit VALUES(?,?,?,?,?,?)",
                       (owner.id, request_id, intent, operation, user_id, now))
        return {"user_id": user_id, "key": key, "repeated": False}

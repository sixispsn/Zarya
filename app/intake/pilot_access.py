"""Small closed-pilot identity store. Random keys, never human passwords.

Keys and session tokens have 256 bits of entropy; only SHA-256 digests persist.
This is deliberately opt-in: it does not claim existing anonymous drafts.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

SESSION_SECONDS = 7 * 24 * 3600
IDLE_SECONDS = 12 * 3600
REMEMBER_SECONDS = 30 * 24 * 3600


def enabled() -> bool:
    return os.environ.get("ZARYA_PILOT_ENABLED", "0") == "1"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    id: str
    name: str
    role: str
    draft_id: str | None


class AccessStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get(
            "ZARYA_PILOT_DIR", str(Path.home() / ".zarya" / "pilot")
        ))
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "access.sqlite3"
        # Restrict creation before SQLite opens it (no umask-dependent exposure).
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL, key_expires REAL NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0, draft_id TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    expires REAL NOT NULL, seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    address_hash TEXT PRIMARY KEY, started REAL NOT NULL,
                    count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS remembered_sessions (
                    token_hash TEXT PRIMARY KEY
                );
                CREATE TRIGGER IF NOT EXISTS forget_deleted_session
                    AFTER DELETE ON sessions BEGIN
                    DELETE FROM remembered_sessions WHERE token_hash=OLD.token_hash;
                    END;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def issue(self, name: str, *, role: str = "tester", days: int = 30,
              user_id: str | None = None) -> tuple[str, str]:
        if role not in {"tester", "admin"} or not name.strip() or not 1 <= days <= 90:
            raise ValueError("Нужны имя, роль tester/admin и срок от 1 до 90 дней.")
        key = "zarya_" + secrets.token_urlsafe(32)
        with self.connect() as db:
            if user_id:
                if not db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
                    raise ValueError("Участник не найден.")
                db.execute("UPDATE users SET name=?,role=?,key_hash=?,key_expires=?,disabled=0 WHERE id=?",
                           (name.strip(), role, digest(key), time.time() + days * 86400, user_id))
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            else:
                user_id = uuid.uuid4().hex
                db.execute("INSERT INTO users(id,name,role,key_hash,key_expires) VALUES(?,?,?,?,?)",
                           (user_id, name.strip(), role, digest(key), time.time() + days * 86400))
        return user_id, key

    def list_users(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,role,key_expires,disabled FROM users ORDER BY name"
            )]

    def revoke(self, user_id: str):
        with self.connect() as db:
            if db.execute("UPDATE users SET disabled=1 WHERE id=?", (user_id,)).rowcount != 1:
                raise ValueError("Участник не найден.")
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def login(self, key: str, address: str, *, remember_device: bool = True) -> str | None:
        now = time.time()
        with self.connect() as db:
            # Persist throttling across workers/restarts. Limit all attempts, not
            # only failures; do not disclose whether an account exists.
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM attempts WHERE started<?", (now - 900,))
            db.execute("""DELETE FROM sessions WHERE expires<=? OR
                (seen<=? AND NOT EXISTS (SELECT 1 FROM remembered_sessions r WHERE r.token_hash=sessions.token_hash))""",
                (now, now - IDLE_SECONDS))
            address_hash = digest(address)
            row = db.execute("SELECT count FROM attempts WHERE address_hash=?", (address_hash,)).fetchone()
            if row and row["count"] >= 20:
                raise TooManyAttempts
            db.execute("INSERT INTO attempts VALUES(?,?,1) ON CONFLICT(address_hash) DO UPDATE SET count=count+1",
                       (address_hash, now))
            user = db.execute("SELECT id,key_expires FROM users WHERE key_hash=? AND disabled=0 AND key_expires>?",
                              (digest(key), now)).fetchone()
            if not user:
                return None
            token = secrets.token_urlsafe(32)
            duration = REMEMBER_SECONDS if remember_device else SESSION_SECONDS
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                       (digest(token), user["id"], min(now + duration, user["key_expires"]), now))
            if remember_device:
                db.execute("INSERT INTO remembered_sessions VALUES(?)", (digest(token),))
        return token

    def cookie_max_age(self, token: str) -> int:
        """Cookie and server session end together, never after the access key."""
        with self.connect() as db:
            row = db.execute("SELECT expires FROM sessions WHERE token_hash=?", (digest(token),)).fetchone()
        return max(0, int(row[0] - time.time())) if row else 0

    def authenticate(self, token: str) -> Principal | None:
        if len(token) != 43:
            return None
        now = time.time()
        with self.connect() as db:
            row = db.execute("""SELECT u.id,u.name,u.role,u.draft_id FROM sessions s
                JOIN users u ON u.id=s.user_id
                LEFT JOIN remembered_sessions r ON r.token_hash=s.token_hash
                WHERE s.token_hash=? AND s.expires>?
                AND (r.token_hash IS NOT NULL OR s.seen>?) AND u.disabled=0 AND u.key_expires>?""",
                (digest(token), now, now - IDLE_SECONDS, now)).fetchone()
            if not row:
                return None
            db.execute("UPDATE sessions SET seen=? WHERE token_hash=?", (now, digest(token)))
            return Principal(**dict(row))

    def logout(self, token: str):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))

    def active_draft(self, user_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT draft_id FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
            if not row:
                raise ValueError("Участник не найден.")
            return row["draft_id"]

    def set_draft(self, user_id: str, draft_id: str):
        with self.connect() as db:
            db.execute("UPDATE users SET draft_id=? WHERE id=? AND disabled=0", (draft_id, user_id))


class TooManyAttempts(Exception):
    pass

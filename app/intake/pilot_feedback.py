"""Private, text-only pilot feedback. Never collects project files or inputs."""
from datetime import datetime, timezone
import os
import time

from app.intake.pilot_access import AccessStore, Principal

CATEGORIES = {"calculation": "Расчёт", "documents": "ПЗ и схемы", "interface": "Интерфейс", "other": "Другое"}


class FeedbackLimit(Exception):
    pass


class FeedbackConflict(Exception):
    pass


class FeedbackStore:
    def __init__(self):
        self.access = AccessStore()
        with self.access.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL, user_name TEXT NOT NULL,
                request_id TEXT NOT NULL, category TEXT NOT NULL,
                message TEXT NOT NULL, build TEXT NOT NULL, created REAL NOT NULL,
                UNIQUE(user_id, request_id)
            )""")

    def add(self, user: Principal, request_id: str, category: str, message: str) -> str:
        now = time.time()
        with self.access.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT id,category,message FROM feedback WHERE user_id=? AND request_id=?",
                                  (user.id, request_id)).fetchone()
            if previous:
                if previous["category"] != category or previous["message"] != message:
                    raise FeedbackConflict
                return f"ZR-{previous['id']:06d}"
            count = db.execute("SELECT COUNT(*) FROM feedback WHERE user_id=? AND created>?",
                               (user.id, now - 3600)).fetchone()[0]
            if count >= 20:
                raise FeedbackLimit
            result = db.execute("INSERT INTO feedback(user_id,user_name,request_id,category,message,build,created) VALUES(?,?,?,?,?,?,?)",
                                (user.id, user.name, request_id, category, message,
                                 os.environ.get("ZARYA_BUILD_COMMIT", "local")[:100], now))
            return f"ZR-{result.lastrowid:06d}"

    def page(self, before: int | None = None) -> tuple[list[dict], int | None]:
        with self.access.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT id,user_name,category,message,build,created FROM feedback WHERE (? IS NULL OR id<?) ORDER BY id DESC LIMIT 51",
                (before, before))]
        next_before = rows[49]["id"] if len(rows) > 50 else None
        for row in rows[:50]:
            row["ticket"] = f"ZR-{row['id']:06d}"
            row["category_label"] = CATEGORIES[row["category"]]
            row["date"] = datetime.fromtimestamp(row["created"], timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        return rows[:50], next_before

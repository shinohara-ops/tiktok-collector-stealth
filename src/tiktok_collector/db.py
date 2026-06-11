from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime


EXCLUDED_STATUSES = {"skipped", "skipped_ai"}


class CollectorDB:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _has_column(self, table: str, column: str) -> bool:
        cur = self.conn.execute(f"PRAGMA table_info({table})")
        return any(str(row[1]) == column for row in cur.fetchall())

    def _ensure_column(self, table: str, column: str, ddl: str):
        if not self._has_column(table, column):
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _init(self):
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS processed (
            unique_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            reason TEXT,
            profile_url TEXT,
            post_url TEXT,
            screenshot_path TEXT,
            created_at TEXT NOT NULL
        )
        """)

        # 既存DBを壊さないため、必要な列だけ後から追加する。
        self._ensure_column("processed", "negative_feedback_done", "negative_feedback_done INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("processed", "negative_feedback_at", "negative_feedback_at TEXT")
        self._ensure_column("processed", "negative_feedback_error", "negative_feedback_error TEXT")
        self._ensure_column("processed", "seen_count", "seen_count INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("processed", "last_seen_at", "last_seen_at TEXT")

        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            unique_id TEXT,
            created_at TEXT NOT NULL
        )
        """)
        self.conn.commit()

    def get(self, unique_id: str) -> dict | None:
        if not unique_id:
            return None
        cur = self.conn.execute("SELECT * FROM processed WHERE unique_id=?", (unique_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def seen(self, unique_id: str) -> bool:
        return self.get(unique_id) is not None

    def is_excluded_status(self, status: str) -> bool:
        return str(status or "") in EXCLUDED_STATUSES

    def needs_negative_feedback(self, unique_id: str) -> bool:
        row = self.get(unique_id)
        if not row:
            return False
        if not self.is_excluded_status(row.get("status", "")):
            return False
        return int(row.get("negative_feedback_done") or 0) == 0

    def touch_seen(self, unique_id: str):
        if not unique_id:
            return
        self.conn.execute("""
        UPDATE processed
        SET seen_count = COALESCE(seen_count, 0) + 1,
            last_seen_at = ?
        WHERE unique_id = ?
        """, (datetime.now().isoformat(), unique_id))
        self.conn.commit()

    def mark(self, unique_id: str, status: str, reason: str = "", profile_url: str = "", post_url: str = "", screenshot_path: str = ""):
        if not unique_id:
            return

        now = datetime.now().isoformat()
        existing = self.get(unique_id) or {}
        negative_feedback_done = int(existing.get("negative_feedback_done") or 0)
        negative_feedback_at = existing.get("negative_feedback_at") or None
        negative_feedback_error = existing.get("negative_feedback_error") or None
        seen_count = int(existing.get("seen_count") or 0)

        self.conn.execute("""
        INSERT OR REPLACE INTO processed(
            unique_id, status, reason, profile_url, post_url, screenshot_path, created_at,
            negative_feedback_done, negative_feedback_at, negative_feedback_error, seen_count, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            unique_id, status, reason, profile_url, post_url, screenshot_path, now,
            negative_feedback_done, negative_feedback_at, negative_feedback_error, seen_count, now,
        ))
        self.conn.commit()

    def mark_negative_feedback_success(self, unique_id: str):
        if not unique_id:
            return
        now = datetime.now().isoformat()
        self.conn.execute("""
        UPDATE processed
        SET negative_feedback_done = 1,
            negative_feedback_at = ?,
            negative_feedback_error = '',
            seen_count = COALESCE(seen_count, 0) + 1,
            last_seen_at = ?
        WHERE unique_id = ?
        """, (now, now, unique_id))
        self.conn.commit()

    def mark_negative_feedback_error(self, unique_id: str, error: str):
        if not unique_id:
            return
        now = datetime.now().isoformat()
        self.conn.execute("""
        UPDATE processed
        SET negative_feedback_error = ?,
            seen_count = COALESCE(seen_count, 0) + 1,
            last_seen_at = ?
        WHERE unique_id = ?
        """, (str(error or "")[:500], now, unique_id))
        self.conn.commit()

    def event(self, level: str, message: str, unique_id: str = ""):
        self.conn.execute(
            "INSERT INTO events(level, message, unique_id, created_at) VALUES (?, ?, ?, ?)",
            (level, message, unique_id, datetime.now().isoformat())
        )
        self.conn.commit()

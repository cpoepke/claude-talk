"""Session store — SQLite-backed, replaces session-store.sh."""

import json
from datetime import datetime, timezone
from pathlib import Path

from .db import DB


class SessionStore:
    """Manages voice chat sessions in SQLite."""

    def __init__(self, db: DB):
        self.db = db
        self._migrate_json()

    def _migrate_json(self):
        """Import from legacy sessions.json if it exists."""
        legacy = Path.home() / ".claude-talk/sessions.json"
        if not legacy.exists():
            return
        try:
            data = json.loads(legacy.read_text())
            for sid, info in data.get("sessions", {}).items():
                self.db.execute(
                    "INSERT OR IGNORE INTO sessions (session_id, status, personality, audio_server_port, started_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, info.get("status", "stopped"), info.get("personality"),
                     info.get("audio_server_port", 8150), info.get("started_at")),
                )
            self.db.commit()
            legacy.rename(legacy.with_suffix(".json.bak"))
        except Exception:
            pass

    def claim(self, session_id: str, personality: str = "unknown") -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO sessions (session_id, status, personality, started_at, updated_at) "
            "VALUES (?, 'active', ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET status='active', personality=?, started_at=?, updated_at=?",
            (session_id, personality, now, now, personality, now, now),
        )
        self.db.commit()

    def release(self, session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "UPDATE sessions SET status='stopped', updated_at=? WHERE session_id=?",
            (now, session_id),
        )
        self.db.commit()

    def is_active(self, session_id: str) -> bool:
        row = self.db.execute(
            "SELECT status FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return row is not None and row["status"] == "active"

    def get_active(self) -> str | None:
        row = self.db.execute(
            "SELECT session_id FROM sessions WHERE status='active' LIMIT 1"
        ).fetchone()
        return row["session_id"] if row else None

    def list_sessions(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM sessions").fetchall()
        return [dict(r) for r in rows]

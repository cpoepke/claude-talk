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

    def claim(self, session_id: str, personality: str = "unknown", voice: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO sessions (session_id, status, personality, voice, started_at, updated_at) "
            "VALUES (?, 'active', ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET status='active', personality=?, voice=?, started_at=?, updated_at=?",
            (session_id, personality, voice, now, now, personality, voice, now, now),
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

    def check_or_claim(self, session_id: str) -> bool:
        """Check if session is active; if old state file says active but session isn't claimed, claim it.
        Returns True if this session is active, False otherwise."""
        # Check if already active
        if self.is_active(session_id):
            return True

        # Migration: check old state file
        state_file = Path.home() / ".claude-talk/state"
        if state_file.exists():
            content = state_file.read_text()
            for line in content.splitlines():
                if line.strip().startswith("SESSION="):
                    _, _, value = line.partition("=")
                    if value.strip() == "active":
                        # Old state says active but this session isn't claimed — claim it
                        # Load active personality and voice
                        from .config import Config
                        from .personality import get_active_personality
                        personality = get_active_personality() or "unknown"
                        voice = Config().get("VOICE")
                        self.claim(session_id, personality, voice)
                        return True

        return False

    def update_personality(self, session_id: str, personality: str, voice: str | None = None) -> None:
        """Update personality and voice for a session."""
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "UPDATE sessions SET personality=?, voice=?, updated_at=? WHERE session_id=?",
            (personality, voice, now, session_id),
        )
        self.db.commit()

    def get_personality(self, session_id: str) -> dict | None:
        """Get personality and voice for a session."""
        row = self.db.execute(
            "SELECT personality, voice FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row:
            return {"personality": row["personality"], "voice": row["voice"]}
        return None

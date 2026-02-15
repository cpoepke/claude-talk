"""SQLite storage layer for claude-talk."""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".claude-talk/claude-talk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'stopped',
    personality TEXT,
    voice TEXT,
    audio_server_port INTEGER DEFAULT 8150,
    started_at TEXT,
    updated_at TEXT
);
"""


class DB:
    """Thin wrapper around sqlite3 with WAL mode and auto-schema."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate_voice_column()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _migrate_voice_column(self):
        """Add voice column if it doesn't exist."""
        try:
            self.execute("SELECT voice FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            self.execute("ALTER TABLE sessions ADD COLUMN voice TEXT")
            self.commit()

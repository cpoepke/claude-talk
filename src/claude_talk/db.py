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
    is_primary INTEGER DEFAULT 0,
    tmux_target TEXT,
    started_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    from_session_id TEXT,
    text TEXT NOT NULL,
    route_type TEXT NOT NULL,
    created_at TEXT,
    read INTEGER DEFAULT 0,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
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
        """Add voice, is_primary, and tmux_target columns if they don't exist."""
        try:
            self.execute("SELECT voice FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            self.execute("ALTER TABLE sessions ADD COLUMN voice TEXT")
            self.commit()

        try:
            self.execute("SELECT is_primary FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            self.execute("ALTER TABLE sessions ADD COLUMN is_primary INTEGER DEFAULT 0")
            self.commit()

        try:
            self.execute("SELECT tmux_target FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            self.execute("ALTER TABLE sessions ADD COLUMN tmux_target TEXT")
            self.commit()

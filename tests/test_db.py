"""Tests for SQLite storage layer."""

from claude_talk.db import DB


def test_create_db(tmp_path):
    db_path = tmp_path / "test.db"
    with DB(db_path) as db:
        # Tables should exist
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchall()
        assert len(rows) == 1


def test_wal_mode(tmp_path):
    db_path = tmp_path / "test.db"
    with DB(db_path) as db:
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


def test_insert_and_query(tmp_path):
    db_path = tmp_path / "test.db"
    with DB(db_path) as db:
        db.execute(
            "INSERT INTO sessions (session_id, status) VALUES (?, ?)",
            ("test-1", "active"),
        )
        db.commit()
        row = db.execute(
            "SELECT status FROM sessions WHERE session_id=?", ("test-1",)
        ).fetchone()
        assert row["status"] == "active"


def test_creates_parent_dirs(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "test.db"
    with DB(db_path) as db:
        assert db_path.exists()

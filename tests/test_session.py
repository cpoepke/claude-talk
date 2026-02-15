"""Tests for session store."""

from claude_talk.db import DB
from claude_talk.session import SessionStore


def _make_store(tmp_path):
    db = DB(tmp_path / "test.db")
    return SessionStore(db), db


def test_claim_and_is_active(tmp_path):
    store, db = _make_store(tmp_path)
    store.claim("sess-1", "claude")
    assert store.is_active("sess-1")
    assert not store.is_active("nonexistent")


def test_release(tmp_path):
    store, db = _make_store(tmp_path)
    store.claim("sess-1")
    store.release("sess-1")
    assert not store.is_active("sess-1")


def test_get_active(tmp_path):
    store, db = _make_store(tmp_path)
    assert store.get_active() is None
    store.claim("sess-1")
    assert store.get_active() == "sess-1"


def test_list_sessions(tmp_path):
    store, db = _make_store(tmp_path)
    store.claim("a", "claude")
    store.claim("b", "jarvis")
    sessions = store.list_sessions()
    assert len(sessions) == 2
    ids = {s["session_id"] for s in sessions}
    assert ids == {"a", "b"}


def test_reclaim_updates(tmp_path):
    store, db = _make_store(tmp_path)
    store.claim("sess-1", "claude")
    store.release("sess-1")
    store.claim("sess-1", "jarvis")
    assert store.is_active("sess-1")
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["personality"] == "jarvis"


def test_migrate_json(tmp_path, monkeypatch):
    """Test migration from legacy sessions.json."""
    import json
    from pathlib import Path

    # Create a fake home dir
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    ct_dir = fake_home / ".claude-talk"
    ct_dir.mkdir()

    # Write legacy file
    legacy = ct_dir / "sessions.json"
    legacy.write_text(json.dumps({
        "sessions": {
            "old-sess": {"status": "active", "personality": "claude", "audio_server_port": 8150}
        }
    }))

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    db = DB(tmp_path / "test.db")
    store = SessionStore(db)

    # Should have migrated
    assert store.is_active("old-sess")
    # Legacy file should be renamed
    assert not legacy.exists()
    assert legacy.with_suffix(".json.bak").exists()


def test_unique_personality_enforcement(tmp_path):
    """Test that personalities are unique across active sessions."""
    store, db = _make_store(tmp_path)
    # First claim succeeds
    store.claim("session-1", "bonnie", "Fiona")
    assert store.is_active("session-1")

    # Second claim with same personality fails
    import pytest
    with pytest.raises(ValueError, match="already claimed"):
        store.claim("session-2", "bonnie", "Fiona")

    # Different personality succeeds
    store.claim("session-2", "sheila", "Karen")
    assert store.is_active("session-2")


def test_is_personality_available(tmp_path):
    """Test personality availability checking."""
    store, db = _make_store(tmp_path)
    # Unknown is always available
    assert store.is_personality_available("unknown")

    # Unclaimed personality is available
    assert store.is_personality_available("bonnie")

    # Claimed personality is not available
    store.claim("session-1", "bonnie", "Fiona")
    assert not store.is_personality_available("bonnie")

    # But available if excluding the session that has it
    assert store.is_personality_available("bonnie", exclude_session="session-1")


def test_update_personality_uniqueness(tmp_path):
    """Test that update_personality enforces uniqueness."""
    import pytest
    store, db = _make_store(tmp_path)
    store.claim("session-1", "bonnie", "Fiona")
    store.claim("session-2", "sheila", "Karen")

    # Can update to same personality (no-op)
    store.update_personality("session-1", "bonnie", "Fiona")

    # Cannot update to another active session's personality
    with pytest.raises(ValueError, match="already claimed"):
        store.update_personality("session-1", "sheila", "Karen")

    # Can update to unclaimed personality
    store.update_personality("session-1", "vex", "Zarvox")
    info = store.get_personality("session-1")
    assert info["personality"] == "vex"

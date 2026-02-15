"""Tests for personality management."""

from pathlib import Path

import claude_talk.personality as pm


def _setup_personalities(tmp_path, monkeypatch):
    """Set up fixture personality files."""
    p_dir = tmp_path / "personalities"
    p_dir.mkdir()
    monkeypatch.setattr(pm, "PERSONALITIES_DIR", p_dir)
    monkeypatch.setattr(pm, "ACTIVE_FILE", tmp_path / "active-personality")
    monkeypatch.setattr(pm, "PERSONALITY_FILE", tmp_path / "personality.md")
    monkeypatch.setattr(pm, "CONFIG_FILE", tmp_path / "config.env")

    # Create test personalities
    (p_dir / "claude.md").write_text(
        "# Voice Assistant Personality\n\n"
        "## Identity\n- Name: Claude\n\n"
        "## Voice\n- Voice: Daniel (Enhanced)\n\n"
        "## Conversational Style\n- Style: Witty & playful\n"
    )
    (p_dir / "vex.md").write_text(
        "# Voice Assistant Personality\n\n"
        "## Identity\n- Name: Vex\n\n"
        "## Voice\n- Voice: Zarvox\n\n"
        "## Conversational Style\n- Style: Alien & quirky\n"
    )
    return p_dir


def test_list_personalities(tmp_path, monkeypatch):
    _setup_personalities(tmp_path, monkeypatch)
    plist = pm.list_personalities()
    assert len(plist) == 2
    names = {p["name"] for p in plist}
    assert names == {"claude", "vex"}


def test_load_personality(tmp_path, monkeypatch):
    _setup_personalities(tmp_path, monkeypatch)
    info = pm.load_personality("claude")
    assert info["voice"] == "Daniel (Enhanced)"
    assert info["identity_name"] == "Claude"
    assert info["style"] == "Witty & playful"


def test_switch_personality(tmp_path, monkeypatch):
    _setup_personalities(tmp_path, monkeypatch)
    # Write a config.env
    config = tmp_path / "config.env"
    config.write_text("VOICE=Daniel\nOTHER=yes\n")

    info = pm.switch_personality("vex")
    assert info["voice"] == "Zarvox"

    # Check active file
    assert (tmp_path / "active-personality").read_text() == "vex"

    # Check personality.md was copied
    assert "Vex" in (tmp_path / "personality.md").read_text()

    # Check config.env was updated
    assert "VOICE=Zarvox" in config.read_text()


def test_get_active_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "ACTIVE_FILE", tmp_path / "nope")
    assert pm.get_active_personality() is None


def test_get_active(tmp_path, monkeypatch):
    active = tmp_path / "active-personality"
    active.write_text("claude\n")
    monkeypatch.setattr(pm, "ACTIVE_FILE", active)
    assert pm.get_active_personality() == "claude"


def test_load_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "PERSONALITIES_DIR", tmp_path / "empty")
    monkeypatch.setattr(pm, "ACTIVE_FILE", tmp_path / "nope")
    assert pm.load_personality("nope") == {}

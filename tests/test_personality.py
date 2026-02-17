"""Tests for personality management."""

from pathlib import Path

import claude_talk.personality as pm


def _setup_personalities(tmp_path, monkeypatch):
    """Set up fixture personality files."""
    p_dir = tmp_path / "personalities"
    p_dir.mkdir()
    monkeypatch.setattr(pm, "PERSONALITIES_DIR", p_dir)

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


def test_load_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "PERSONALITIES_DIR", tmp_path / "empty")
    assert pm.load_personality("nope") == {}

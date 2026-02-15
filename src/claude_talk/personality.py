"""Personality file loading and switching."""

import re
import shutil
from pathlib import Path

from .db import DB
from .session import SessionStore

PERSONALITIES_DIR = Path.home() / ".claude-talk/personalities"
ACTIVE_FILE = Path.home() / ".claude-talk/active-personality"
PERSONALITY_FILE = Path.home() / ".claude-talk/personality.md"
CONFIG_FILE = Path.home() / ".claude-talk/config.env"


def load_personality(name: str | None = None) -> dict:
    """Load a personality by name. Returns dict with name, voice, style, content."""
    if name is None:
        name = get_active_personality()
    if name is None:
        return {}

    path = PERSONALITIES_DIR / f"{name}.md"
    if not path.exists():
        return {}

    content = path.read_text()
    return _parse_personality(content, name)


def _parse_personality(content: str, name: str) -> dict:
    """Extract structured data from personality markdown."""
    result = {"name": name, "content": content}

    # Extract voice
    voice_match = re.search(r"^- Voice:\s*(.+)$", content, re.MULTILINE)
    if voice_match:
        result["voice"] = voice_match.group(1).strip()

    # Extract style
    style_match = re.search(r"^- Style:\s*(.+)$", content, re.MULTILINE)
    if style_match:
        result["style"] = style_match.group(1).strip()

    # Extract identity name
    identity_match = re.search(r"^- Name:\s*(.+)$", content, re.MULTILINE)
    if identity_match:
        result["identity_name"] = identity_match.group(1).strip()

    return result


def switch_personality(name: str, update_session: bool = True) -> dict:
    """Switch active personality. Returns personality dict.

    Args:
        name: Personality name
        update_session: If True, also update the active session's personality/voice
    """
    path = PERSONALITIES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Personality '{name}' not found")

    content = path.read_text()
    info = _parse_personality(content, name)

    # Copy to personality.md
    shutil.copy2(path, PERSONALITY_FILE)

    # Update active-personality
    ACTIVE_FILE.write_text(name)

    # Update voice in config.env
    voice = info.get("voice")
    if voice:
        _update_config_voice(voice)

    # Update active session if requested
    if update_session:
        store = SessionStore(DB())
        session_id = store.get_active()
        if session_id:
            store.update_personality(session_id, name, voice)

    return info


def _update_config_voice(voice: str):
    """Update VOICE= line in config.env."""
    if not CONFIG_FILE.exists():
        return
    lines = CONFIG_FILE.read_text().splitlines()
    found = False
    quoted = f'"{voice}"' if " " in voice else voice
    for i, line in enumerate(lines):
        if line.startswith("VOICE="):
            lines[i] = f"VOICE={quoted}"
            found = True
            break
    if not found:
        lines.append(f"VOICE={quoted}")
    CONFIG_FILE.write_text("\n".join(lines) + "\n")


def list_personalities() -> list[dict]:
    """List all saved personalities with metadata."""
    if not PERSONALITIES_DIR.exists():
        return []
    result = []
    active = get_active_personality()
    for path in sorted(PERSONALITIES_DIR.glob("*.md")):
        name = path.stem
        content = path.read_text()
        info = _parse_personality(content, name)
        info["active"] = name == active
        result.append(info)
    return result


def get_active_personality() -> str | None:
    """Get the name of the active personality."""
    if ACTIVE_FILE.exists():
        name = ACTIVE_FILE.read_text().strip()
        if name:
            return name
    return None


def load_session_personality(session_id: str) -> dict:
    """Load personality for a specific session. Falls back to global if not set."""
    store = SessionStore(DB())
    session_info = store.get_personality(session_id)

    if session_info and session_info.get("personality"):
        # Load session's personality
        return load_personality(session_info["personality"])

    # Fall back to global active personality
    return load_personality()

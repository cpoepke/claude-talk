"""Personality file loading and switching.

Database is the single source of truth for session personalities.
Global files (personality.md, active-personality) are DEPRECATED - only used for migration.
Personalities/*.md are templates. Each session tracks its own personality in the database.
"""

import re
from pathlib import Path

from .db import DB
from .session import SessionStore

PERSONALITIES_DIR = Path.home() / ".claude-talk/personalities"


def load_personality(name: str) -> dict:
    """Load a personality template by name from personalities/ directory."""
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

    # Extract Kokoro voice ID (overrides macOS voice resolution when present)
    kokoro_match = re.search(r"^- Kokoro Voice:\s*(.+)$", content, re.MULTILINE)
    if kokoro_match:
        result["kokoro_voice"] = kokoro_match.group(1).strip()

    # Extract TTS engine preference (kokoro or say)
    engine_match = re.search(r"^- TTS Engine:\s*(.+)$", content, re.MULTILINE)
    if engine_match:
        result["tts_engine"] = engine_match.group(1).strip().lower()

    # Extract style
    style_match = re.search(r"^- Style:\s*(.+)$", content, re.MULTILINE)
    if style_match:
        result["style"] = style_match.group(1).strip()

    # Extract identity name
    identity_match = re.search(r"^- Name:\s*(.+)$", content, re.MULTILINE)
    if identity_match:
        result["identity_name"] = identity_match.group(1).strip()

    # Extract display name (with emoji)
    display_match = re.search(r"^- Display Name:\s*(.+)$", content, re.MULTILINE)
    if display_match:
        result["display_name"] = display_match.group(1).strip()
    else:
        # Fallback to identity_name if no display name
        result["display_name"] = result.get("identity_name", name)

    # Extract emoji
    emoji_match = re.search(r"^- Emoji:\s*(.+)$", content, re.MULTILINE)
    if emoji_match:
        result["emoji"] = emoji_match.group(1).strip()

    # Extract color code for statusline display
    color_match = re.search(r"^- Color:\s*(.+)$", content, re.MULTILINE)
    if color_match:
        result["color"] = color_match.group(1).strip()
    else:
        # Default to magenta if no color specified
        result["color"] = "95"

    return result


def switch_personality(session_id: str, name: str) -> dict:
    """Switch personality for a specific session.

    Args:
        session_id: Session ID to update
        name: Personality name from personalities/ directory

    Returns:
        Personality dict with name, voice, style, etc.
    """
    path = PERSONALITIES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Personality '{name}' not found")

    content = path.read_text()
    info = _parse_personality(content, name)

    # Update session's personality in database
    voice = info.get("voice")
    store = SessionStore(DB())
    store.update_personality(session_id, name, voice)

    return info


def list_personalities() -> list[dict]:
    """List all personality templates from personalities/ directory."""
    if not PERSONALITIES_DIR.exists():
        return []
    result = []
    for path in sorted(PERSONALITIES_DIR.glob("*.md")):
        name = path.stem
        content = path.read_text()
        info = _parse_personality(content, name)
        result.append(info)
    return result


def load_session_personality(session_id: str) -> dict:
    """Load personality for a specific session from database (single source of truth)."""
    store = SessionStore(DB())
    session_info = store.get_personality(session_id)

    if session_info and session_info.get("personality"):
        personality_name = session_info["personality"]
        if personality_name != "unknown":
            return load_personality(personality_name)

    # No valid personality - return empty
    return {}

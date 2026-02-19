"""Speech routing logic - detect personality names and broadcast keywords."""

import re
from .db import DB
from .session import SessionStore


# Broadcast keywords
BROADCAST_KEYWORDS = [
    "team", "everybody", "everyone", "you all", "folks", "all of you",
    "hey team", "listen up", "attention everyone"
]


def parse_route(text: str, store: SessionStore | None = None) -> tuple[str, str | None, str]:
    """Parse transcription to determine routing.

    Returns:
        (route_type, target_session_id, cleaned_text)

    route_type can be:
        - "broadcast": message for all sessions
        - "direct": message for specific personality
        - "primary": message for primary session (no name detected)
    """
    text_lower = text.lower().strip()

    # Check for broadcast keywords
    for keyword in BROADCAST_KEYWORDS:
        if keyword in text_lower:
            # Keep full text — teammates should hear the natural phrasing
            return ("broadcast", None, text)

    # Check for personality names
    if store is None:
        store = SessionStore(DB())
    sessions = store.list_sessions()

    for session in sessions:
        if session["status"] != "active":
            continue
        personality = session.get("personality", "").lower()
        if not personality or personality == "unknown":
            continue

        # Look for personality name at start of message
        # e.g., "Bonnie, what's the status?"
        pattern = r'\b' + re.escape(personality) + r'\b[,:]?\s*'
        match = re.search(pattern, text_lower)
        if match:
            # Keep full text including name — feels more natural for the personality
            return ("direct", session["session_id"], text)

    # No name detected - route to primary
    return ("primary", None, text)


def get_target_sessions(route_type: str, target_session_id: str | None, store: SessionStore | None = None) -> list[str]:
    """Get list of session IDs to route message to.

    Args:
        route_type: "broadcast", "direct", or "primary"
        target_session_id: session_id for direct routing

    Returns:
        List of session_ids to send message to
    """
    if store is None:
        store = SessionStore(DB())

    if route_type == "broadcast":
        # Send to all active sessions with valid IDs
        sessions = store.list_sessions()
        return [
            s["session_id"] for s in sessions
            if s["status"] == "active" and s["session_id"]
        ]

    elif route_type == "direct":
        # Send to specific session
        return [target_session_id] if target_session_id else []

    elif route_type == "primary":
        # Send to primary session
        primary = store.get_primary()
        return [primary] if primary else []

    return []

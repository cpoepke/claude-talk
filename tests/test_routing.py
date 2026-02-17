"""Tests for routing logic."""

import pytest

from claude_talk.db import DB
from claude_talk.routing import get_target_sessions, parse_route
from claude_talk.session import SessionStore


@pytest.fixture
def db(tmp_path):
    db = DB(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def sessions(db):
    """Create test sessions."""
    store = SessionStore(db)
    store.claim("session-1", "bonnie", "Fiona (Enhanced)")
    store.claim("session-2", "sheila", "Karen (Premium)")
    store.set_primary("session-1")
    return store


def test_parse_route_direct(sessions):
    route_type, target_id, cleaned = parse_route("Bonnie, what's up?", store=sessions)
    assert route_type == "direct"
    assert target_id is not None
    assert cleaned == "what's up?"


def test_parse_route_broadcast(sessions):
    route_type, target_id, cleaned = parse_route("Hey team, listen up!", store=sessions)
    assert route_type == "broadcast"
    assert target_id is None
    assert "Hey" in cleaned or "listen up" in cleaned


def test_parse_route_primary(sessions):
    route_type, target_id, cleaned = parse_route("What's the weather?", store=sessions)
    assert route_type == "primary"
    assert target_id is None
    assert cleaned == "What's the weather?"


def test_get_target_sessions_direct(sessions):
    targets = get_target_sessions("direct", "test-session-id", store=sessions)
    assert targets == ["test-session-id"]


def test_get_target_sessions_broadcast(sessions):
    targets = get_target_sessions("broadcast", None, store=sessions)
    assert len(targets) == 2


def test_get_target_sessions_primary(sessions):
    targets = get_target_sessions("primary", None, store=sessions)
    assert targets == ["session-1"]

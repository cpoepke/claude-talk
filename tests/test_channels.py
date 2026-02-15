"""Tests for channel and message management."""

import pytest

from claude_talk.channels import ChannelManager
from claude_talk.db import DB
from claude_talk.session import SessionStore


@pytest.fixture
def db(tmp_path):
    db = DB(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def manager(db):
    return ChannelManager(db)


@pytest.fixture
def sessions(db):
    """Create test sessions."""
    store = SessionStore(db)
    store.claim("session-1", "bonnie", "Fiona (Enhanced)")
    store.claim("session-2", "sheila", "Karen (Premium)")
    return store


def test_create_channel(manager):
    channel_id = manager.create_channel("session-1")
    assert channel_id is not None
    assert len(channel_id) > 0


def test_get_or_create_channel(manager):
    channel_id1 = manager.get_or_create_channel("session-1")
    channel_id2 = manager.get_or_create_channel("session-1")
    assert channel_id1 == channel_id2  # Same channel returned


def test_send_message(manager):
    channel_id = manager.create_channel("session-1")
    message_id = manager.send_message(channel_id, "Hello", "direct")
    assert message_id > 0


def test_get_unread_messages(manager):
    channel_id = manager.create_channel("session-1")
    manager.send_message(channel_id, "Message 1", "direct")
    manager.send_message(channel_id, "Message 2", "direct")

    messages = manager.get_unread_messages(channel_id)
    assert len(messages) == 2
    assert messages[0]["text"] == "Message 1"
    assert messages[1]["text"] == "Message 2"


def test_mark_read(manager):
    channel_id = manager.create_channel("session-1")
    message_id = manager.send_message(channel_id, "Test", "direct")

    messages = manager.get_unread_messages(channel_id)
    assert len(messages) == 1

    manager.mark_read(message_id)
    messages = manager.get_unread_messages(channel_id)
    assert len(messages) == 0


def test_broadcast(manager, sessions):
    manager.broadcast("Team message", "broadcast")

    # Both sessions should receive the message
    channel1 = manager.get_or_create_channel("session-1")
    channel2 = manager.get_or_create_channel("session-2")

    messages1 = manager.get_unread_messages(channel1)
    messages2 = manager.get_unread_messages(channel2)

    assert len(messages1) == 1
    assert len(messages2) == 1
    assert messages1[0]["text"] == "Team message"
    assert messages2[0]["text"] == "Team message"


def test_broadcast_excludes_sender(manager, sessions):
    manager.broadcast("Test", "broadcast", from_session_id="session-1")

    # session-1 (sender) should NOT receive the message
    channel1 = manager.get_or_create_channel("session-1")
    messages1 = manager.get_unread_messages(channel1)
    assert len(messages1) == 0

    # session-2 should receive it
    channel2 = manager.get_or_create_channel("session-2")
    messages2 = manager.get_unread_messages(channel2)
    assert len(messages2) == 1

"""Channel and message management for inter-session communication."""

import uuid
from datetime import datetime, timezone

from .db import DB


class ChannelManager:
    """Manages channels and messages for session communication."""

    def __init__(self, db: DB):
        self.db = db

    def create_channel(self, session_id: str) -> str:
        """Create a channel for a session. Returns channel_id."""
        channel_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO channels (channel_id, session_id, created_at) VALUES (?, ?, ?)",
            (channel_id, session_id, now),
        )
        self.db.commit()
        return channel_id

    def get_channel(self, session_id: str) -> str | None:
        """Get channel_id for a session."""
        row = self.db.execute(
            "SELECT channel_id FROM channels WHERE session_id=?", (session_id,)
        ).fetchone()
        return row["channel_id"] if row else None

    def get_or_create_channel(self, session_id: str) -> str:
        """Get or create channel for a session."""
        channel_id = self.get_channel(session_id)
        if not channel_id:
            channel_id = self.create_channel(session_id)
        return channel_id

    def send_message(
        self,
        channel_id: str,
        text: str,
        route_type: str,
        from_session_id: str | None = None
    ) -> int:
        """Send a message to a channel. Returns message_id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.db.execute(
            "INSERT INTO messages (channel_id, from_session_id, text, route_type, created_at, read) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (channel_id, from_session_id, text, route_type, now),
        )
        self.db.commit()
        return cursor.lastrowid

    def get_unread_messages(self, channel_id: str) -> list[dict]:
        """Get unread messages for a channel."""
        rows = self.db.execute(
            "SELECT * FROM messages WHERE channel_id=? AND read=0 ORDER BY created_at",
            (channel_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, message_id: int):
        """Mark a message as read."""
        self.db.execute(
            "UPDATE messages SET read=1 WHERE message_id=?", (message_id,)
        )
        self.db.commit()

    def broadcast(self, text: str, route_type: str = "broadcast", from_session_id: str | None = None):
        """Broadcast a message to all active sessions."""
        # Get all active sessions
        rows = self.db.execute(
            "SELECT session_id FROM sessions WHERE status='active'"
        ).fetchall()

        for row in rows:
            session_id = row["session_id"]
            # Skip sender if specified
            if from_session_id and session_id == from_session_id:
                continue
            channel_id = self.get_or_create_channel(session_id)
            self.send_message(channel_id, text, route_type, from_session_id)

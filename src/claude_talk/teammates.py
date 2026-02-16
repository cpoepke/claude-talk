"""Teammate spawning and management for multi-personality voice sessions."""

import json
import subprocess
import sys
from pathlib import Path

from .config import Config
from .db import DB
from .personality import load_personality
from .session import SessionStore


class TeammateManager:
    """Manages Claude Code teammates for voice personalities."""

    def __init__(self, db: DB):
        self.db = db
        self.session_store = SessionStore(db)
        self.config = Config()

    def spawn_teammate(self, personality: str, session_id: str | None = None) -> dict:
        """Spawn a Claude Code teammate with a specific personality.

        Args:
            personality: Personality name to spawn
            session_id: Optional session ID to associate (creates new if None)

        Returns:
            Dict with teammate info (session_id, personality, voice, tmux_target)
        """
        # Load personality config
        try:
            personality_info = load_personality(personality)
        except FileNotFoundError:
            print(f"Error: Personality '{personality}' not found", file=sys.stderr)
            sys.exit(1)

        voice = personality_info.get("voice")
        personality_file = Path.home() / ".claude-talk" / "personalities" / f"{personality}.md"

        # Generate session ID if not provided
        if not session_id:
            import uuid
            session_id = str(uuid.uuid4())

        # Create tmux session for this teammate
        tmux_session = f"claude-{personality}"
        tmux_result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", tmux_session],
            capture_output=True,
            text=True,
        )

        if tmux_result.returncode != 0:
            # Session might already exist - that's okay
            if "duplicate session" not in tmux_result.stderr:
                print(f"Error creating tmux session: {tmux_result.stderr}", file=sys.stderr)
                sys.exit(1)

        # Get the pane ID
        pane_result = subprocess.run(
            ["tmux", "display-message", "-t", tmux_session, "-p", "#{pane_id}"],
            capture_output=True,
            text=True,
        )

        if pane_result.returncode != 0:
            print(f"Error getting tmux pane: {pane_result.stderr}", file=sys.stderr)
            sys.exit(1)

        pane_id = pane_result.stdout.strip()
        tmux_target = f"{tmux_session}:{pane_id}"

        # Claim session in database
        self.session_store.claim(session_id, personality, voice, is_primary=False)
        self.session_store.set_tmux_target(session_id, tmux_target)

        # Build claude command with personality loaded
        project_dir = Path(__file__).parent.parent.parent
        claude_cmd = f"cd {project_dir} && claude --context-file {personality_file}"

        # Send command to tmux pane
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_target, claude_cmd, "Enter"],
            check=True,
        )

        print(f"✅ Spawned teammate: {personality} (tmux: {tmux_target})", file=sys.stderr)

        return {
            "session_id": session_id,
            "personality": personality,
            "voice": voice,
            "tmux_target": tmux_target,
            "tmux_session": tmux_session,
        }

    def spawn_all_personalities(self) -> list[dict]:
        """Spawn teammates for all available personalities.

        Returns:
            List of teammate info dicts
        """
        personalities_dir = Path.home() / ".claude-talk" / "personalities"

        if not personalities_dir.exists():
            print("Error: No personalities directory found", file=sys.stderr)
            return []

        teammates = []
        for personality_file in personalities_dir.glob("*.md"):
            personality = personality_file.stem

            # Skip if already active
            if not self.session_store.is_personality_available(personality):
                print(f"⏭️  Skipping {personality} (already active)", file=sys.stderr)
                continue

            try:
                teammate = self.spawn_teammate(personality)
                teammates.append(teammate)
            except Exception as e:
                print(f"⚠️  Failed to spawn {personality}: {e}", file=sys.stderr)
                continue

        return teammates

    def list_teammates(self) -> list[dict]:
        """List all active teammates.

        Returns:
            List of teammate info from database
        """
        sessions = self.session_store.list_sessions()
        active_teammates = [s for s in sessions if s["status"] == "active" and s["personality"] != "unknown"]
        return active_teammates

    def kill_teammate(self, session_id: str) -> None:
        """Stop a teammate and release its session.

        Args:
            session_id: Session ID to kill
        """
        # Get tmux target before releasing
        tmux_target = self.session_store.get_tmux_target(session_id)

        # Release session
        self.session_store.release(session_id)

        # Kill tmux session if it exists
        if tmux_target:
            tmux_session = tmux_target.split(":")[0]
            subprocess.run(
                ["tmux", "kill-session", "-t", tmux_session],
                capture_output=True,
            )
            print(f"✅ Killed teammate: {session_id} (tmux: {tmux_session})", file=sys.stderr)
        else:
            print(f"✅ Released teammate: {session_id}", file=sys.stderr)

    def kill_all_teammates(self) -> None:
        """Kill all active teammates."""
        teammates = self.list_teammates()
        for teammate in teammates:
            self.kill_teammate(teammate["session_id"])

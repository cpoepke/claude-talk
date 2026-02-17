"""Teammate spawning and management for multi-personality voice sessions."""

import math
import os
import subprocess
import sys
import uuid
from pathlib import Path

from .config import Config
from .db import DB
from .personality import load_personality
from .session import SessionStore


def _get_current_tmux_session() -> str | None:
    """Get the current tmux session name."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _auto_grid(n: int) -> tuple[int, int]:
    """Calculate grid dimensions (cols, rows) for n panes."""
    if n <= 0:
        return (0, 0)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return (cols, rows)


def _get_current_claude_flags() -> str:
    """Extract flags from the current Claude Code session to inherit."""
    try:
        # Get current process command line
        pid = os.getpid()
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, check=True,
        )
        cmd = result.stdout.strip()

        # Extract common flags to inherit
        flags = []
        if "--dangerously-skip-permissions" in cmd:
            flags.append("--dangerously-skip-permissions")
        if "--model" in cmd:
            # Extract model value
            parts = cmd.split("--model")
            if len(parts) > 1:
                model_part = parts[1].strip().split()[0]
                flags.append(f"--model {model_part}")

        return " ".join(flags)
    except Exception:
        return ""


class TeammateManager:
    """Manages Claude Code teammates for voice personalities."""

    TEAMMATE_WINDOW = "teammates"

    def __init__(self, db: DB):
        self.db = db
        self.session_store = SessionStore(db)
        self.config = Config()

    def available_personalities(self) -> list[str]:
        """List all available personality names."""
        personalities_dir = Path.home() / ".claude-talk" / "personalities"
        if not personalities_dir.exists():
            return []
        return sorted(p.stem for p in personalities_dir.glob("*.md"))

    def spawn_team(self, personalities: list[str]) -> list[dict]:
        """Spawn multiple teammates in an auto-fit tmux grid.

        Creates a new tmux window with panes arranged in a grid layout.
        Each pane runs Claude Code with a unique personality.

        Args:
            personalities: List of unique personality names to spawn

        Returns:
            List of teammate info dicts
        """
        # Validate uniqueness
        if len(personalities) != len(set(personalities)):
            print("Error: Duplicate personalities not allowed", file=sys.stderr)
            sys.exit(1)

        # Validate all personalities exist and are available
        for name in personalities:
            try:
                load_personality(name)
            except FileNotFoundError:
                print(f"Error: Personality '{name}' not found", file=sys.stderr)
                sys.exit(1)
            if not self.session_store.is_personality_available(name):
                print(f"Error: Personality '{name}' already active", file=sys.stderr)
                sys.exit(1)

        tmux_session = _get_current_tmux_session()
        if not tmux_session:
            print("Error: Not running inside tmux", file=sys.stderr)
            sys.exit(1)

        n = len(personalities)
        project_dir = Path(__file__).parent.parent.parent
        inherited_flags = _get_current_claude_flags()

        # Get current window target
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_index}"],
            capture_output=True, text=True, check=True,
        )
        window_idx = result.stdout.strip()
        window_target = f"{tmux_session}:{window_idx}"

        # Split current window into panes for each teammate
        for _ in range(n):
            subprocess.run(
                ["tmux", "split-window", "-t", window_target],
                capture_output=True, text=True, check=True,
            )

        # Apply auto-fit tiled layout and ensure mouse mode is on
        subprocess.run(
            ["tmux", "select-layout", "-t", window_target, "tiled"],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["tmux", "set-option", "-t", window_target, "mouse", "on"],
            capture_output=True, text=True,
        )

        # Get all pane indices — last N are the new ones
        result = subprocess.run(
            ["tmux", "list-panes", "-t", window_target, "-F", "#{pane_index}"],
            capture_output=True, text=True, check=True,
        )
        all_pane_indices = result.stdout.strip().splitlines()
        # The original pane(s) come first; new panes are the last N
        pane_indices = all_pane_indices[-n:]

        teammates = []
        for i, name in enumerate(personalities):
            pane_idx = pane_indices[i]
            tmux_target = f"{window_target}.{pane_idx}"

            personality_info = load_personality(name)
            voice = personality_info.get("voice")
            display_name = personality_info.get("display_name", name)
            personality_file = Path.home() / ".claude-talk" / "personalities" / f"{name}.md"

            session_id = str(uuid.uuid4())
            self.session_store.claim(session_id, name, voice, is_primary=False)
            self.session_store.set_tmux_target(session_id, tmux_target)

            # Set pane title for easy identification
            subprocess.run(
                ["tmux", "select-pane", "-t", tmux_target, "-T", display_name],
                check=True,
            )

            # Launch Claude with personality in this pane
            claude_cmd = f"cd {project_dir} && claude {inherited_flags} --append-system-prompt \"$(cat {personality_file})\""
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_target, claude_cmd],
                check=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_target, "C-m"],
                check=True,
            )

            print(f"Spawned {name} -> {tmux_target}", file=sys.stderr)
            teammates.append({
                "session_id": session_id,
                "personality": name,
                "display_name": display_name,
                "voice": voice,
                "tmux_target": tmux_target,
            })

        # Wait for Claude instances to start, then send greeting
        import time
        wait_time = int(self.config.get("TEAMMATE_STARTUP_WAIT", 12))
        print(f"Waiting {wait_time}s for Claude instances to start...", file=sys.stderr)
        time.sleep(wait_time)

        team_roster = ", ".join(t["display_name"] for t in teammates)
        print(f"Sending greetings to {len(teammates)} teammates...", file=sys.stderr)
        for t in teammates:
            greeting = (
                f"You are {t['display_name']} on a voice team with: {team_roster}. "
                f"Introduce yourself in one sentence, in character."
            )
            from .tmux import send_to_session
            success = send_to_session(t["tmux_target"], greeting)
            if success:
                print(f"  ✓ Sent greeting to {t['personality']}", file=sys.stderr)
            else:
                print(f"  ✗ Failed to send greeting to {t['personality']}", file=sys.stderr)

        return teammates

    def list_teammates(self) -> list[dict]:
        """List all active non-primary teammates."""
        sessions = self.session_store.list_sessions()
        return [
            s for s in sessions
            if s["status"] == "active"
            and s["personality"] != "unknown"
            and not s.get("is_primary")
        ]

    def kill_teammate(self, session_id: str) -> None:
        """Stop a teammate and release its session."""
        tmux_target = self.session_store.get_tmux_target(session_id)
        self.session_store.release(session_id)

        if tmux_target:
            # Send graceful shutdown (Ctrl+D to exit Claude)
            subprocess.run(
                ["tmux", "send-keys", "-t", tmux_target, "C-d"],
                capture_output=True,
            )
            # Wait for graceful shutdown (including SessionStop hooks)
            import time
            time.sleep(2.5)
            # If pane still exists, kill it
            result = subprocess.run(
                ["tmux", "list-panes", "-F", "#{pane_id}"],
                capture_output=True, text=True,
            )
            pane_id = tmux_target.split(".")[-1]
            if pane_id in result.stdout:
                subprocess.run(
                    ["tmux", "kill-pane", "-t", tmux_target],
                    capture_output=True,
                )
            print(f"Stopped teammate: {session_id[:8]} ({tmux_target})", file=sys.stderr)
        else:
            print(f"Released teammate: {session_id[:8]}", file=sys.stderr)

    def kill_all_teammates(self) -> None:
        """Kill all active teammates."""
        teammates = self.list_teammates()
        for teammate in teammates:
            self.kill_teammate(teammate["session_id"])

        print(f"Killed {len(teammates)} teammates", file=sys.stderr)

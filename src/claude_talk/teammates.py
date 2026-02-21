"""Teammate spawning and management for multi-personality voice sessions."""

import math
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .config import Config
from .db import DB
from .personality import load_personality
from .session import SessionStore
from .tmux import (
    get_current_pane,
    get_current_session,
    get_window_index,
    has_session,
    kill_pane,
    list_panes,
    pane_exists,
    select_layout,
    select_pane,
    send_keys,
    send_to_session,
    set_option,
    set_pane_title,
    split_window,
)


def _auto_grid(n: int) -> tuple[int, int]:
    """Calculate grid dimensions (cols, rows) for n panes."""
    if n <= 0:
        return (0, 0)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return (cols, rows)


def _get_current_claude_flags() -> str:
    """Extract flags from the parent Claude Code process to inherit."""
    try:
        # Walk up process tree to find the claude process
        pid = os.getpid()
        for _ in range(10):  # max 10 levels up
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "ppid=,command="],
                capture_output=True, text=True, check=True,
            )
            line = result.stdout.strip()
            parts = line.split(None, 1)
            if len(parts) < 2:
                break
            ppid, cmd = parts[0], parts[1]
            if "/claude" in cmd and "claude-talk" not in cmd:
                # Found the Claude Code process
                flags = []
                if "--dangerously-skip-permissions" in cmd:
                    flags.append("--dangerously-skip-permissions")
                if "--model" in cmd:
                    model_parts = cmd.split("--model")
                    if len(model_parts) > 1:
                        model_val = model_parts[1].strip().split()[0]
                        flags.append(f"--model {model_val}")
                return " ".join(flags)
            pid = int(ppid)
        return ""
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

        Creates new panes in the current window arranged in a tiled layout.
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

        # Clean up stale sessions before checking availability
        for s in self.session_store.list_sessions():
            if s["status"] != "active":
                continue
            stale_target = s.get("tmux_target")
            if not stale_target:
                self.session_store.release(s["session_id"])
                continue
            if not has_session(stale_target):
                self.session_store.release(s["session_id"])
                print(f"Released stale session {s['session_id'][:8]}... (pane gone)", file=sys.stderr)

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

        tmux_session = get_current_session()
        if not tmux_session:
            print("Error: Not running inside tmux.", file=sys.stderr)
            print("Teammates require tmux. Start Claude Code inside a tmux session:", file=sys.stderr)
            print("  tmux new-session && claude", file=sys.stderr)
            sys.exit(1)

        n = len(personalities)
        project_dir = Path(__file__).parent.parent.parent
        inherited_flags = _get_current_claude_flags()

        window_idx = get_window_index()
        if not window_idx:
            print("Error: Could not determine tmux window index", file=sys.stderr)
            sys.exit(1)
        window_target = f"{tmux_session}:{window_idx}"

        # Remember original pane to select back after spawning
        original_pane = get_current_pane()

        # Record existing pane IDs BEFORE splitting (IDs are stable, indices shift)
        existing_pane_ids = set(list_panes(window_target))

        # Split current window into panes for each teammate
        new_pane_ids: list[str] = []
        for _ in range(n):
            pane_id = split_window(window_target)
            if pane_id:
                new_pane_ids.append(pane_id)
            else:
                print("Error: Failed to split window", file=sys.stderr)
                sys.exit(1)

        # Apply auto-fit tiled layout and ensure mouse mode is on
        select_layout(window_target, "tiled")
        set_option(tmux_session, "mouse", "on")

        teammates = []
        for i, name in enumerate(personalities):
            pane_id = new_pane_ids[i]  # stable ID like %17

            personality_info = load_personality(name)
            display_name = personality_info.get("display_name", name)

            # Set pane title for easy identification
            set_pane_title(pane_id, display_name)

            # Launch Claude in this pane (in the project dir so it picks up skills/hooks)
            claude_cmd = f"cd {shlex.quote(str(project_dir))} && claude {inherited_flags}"
            send_to_session(pane_id, claude_cmd)

            print(f"Spawned {name} -> {pane_id}", file=sys.stderr)
            teammates.append({
                "personality": name,
                "display_name": display_name,
                "tmux_target": pane_id,
            })

        # Wait for Claude instances to start, then send /claude-talk:start <personality>
        import time
        wait_time = int(self.config.get("TEAMMATE_STARTUP_WAIT", 12))
        print(f"Waiting {wait_time}s for Claude instances to start...", file=sys.stderr)
        time.sleep(wait_time)

        print(f"Starting voice for {len(teammates)} teammates...", file=sys.stderr)
        for t in teammates:
            success = send_to_session(t["tmux_target"], f"/claude-talk:start {t['personality']}")
            if success:
                print(f"  Started {t['personality']} ({t['tmux_target']})", file=sys.stderr)
            else:
                print(f"  Failed to start {t['personality']} ({t['tmux_target']})", file=sys.stderr)

        # Select back to original pane so user has focus
        if original_pane:
            select_pane(original_pane)

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
            send_keys(tmux_target, "C-d")
            # Wait for graceful shutdown (including SessionStop hooks)
            import time
            time.sleep(2.5)
            # If pane still exists, kill it
            if pane_exists(tmux_target):
                kill_pane(tmux_target)
            print(f"Stopped teammate: {session_id[:8]} ({tmux_target})", file=sys.stderr)
        else:
            print(f"Released teammate: {session_id[:8]}", file=sys.stderr)

    def kill_all_teammates(self) -> None:
        """Kill all active teammates."""
        teammates = self.list_teammates()
        for teammate in teammates:
            self.kill_teammate(teammate["session_id"])

        print(f"Killed {len(teammates)} teammates", file=sys.stderr)

    def get_current_personality(self) -> str | None:
        """Detect the current pane's personality from the session DB.

        Looks up the current tmux pane ID, finds the active session
        using that pane as its tmux_target, and returns the personality name.
        """
        pane_id = os.environ.get("TMUX_PANE", "").strip() or get_current_pane()
        if not pane_id:
            return None
        for s in self.session_store.list_sessions():
            if s["status"] == "active" and s.get("tmux_target") == pane_id:
                p = s.get("personality")
                return p if p and p != "unknown" else None
        return None

    def send_message(self, from_personality: str, to_personality: str, text: str) -> bool:
        """Send a text message from one teammate to another via tmux.

        Uses queued=True so the message waits for the recipient's pane to be
        idle (no active Claude output) before injecting.
        """
        # Find recipient's active session and tmux target
        target = None
        for s in self.session_store.list_sessions():
            if (s["status"] == "active"
                    and s.get("personality") == to_personality
                    and s.get("tmux_target")):
                target = s["tmux_target"]
                break

        if not target:
            print(f"Error: No active session for personality '{to_personality}'", file=sys.stderr)
            return False

        formatted = f"Teammate {from_personality} said: {text}"
        return send_to_session(target, formatted, queued=True)

    def broadcast_message(self, from_personality: str, text: str) -> list[str]:
        """Broadcast a text message to all other active teammates via tmux.

        Uses queued=True so each message waits for the recipient's pane to be
        idle before injecting.
        """
        delivered = []
        formatted = f"Teammate {from_personality} said to the team: {text}"

        for s in self.session_store.list_sessions():
            if (s["status"] == "active"
                    and s.get("personality") != from_personality
                    and s.get("personality") != "unknown"
                    and s.get("tmux_target")):
                if send_to_session(s["tmux_target"], formatted, queued=True):
                    delivered.append(s["personality"])

        return delivered

"""Teammate spawning and management for multi-personality voice sessions."""

import math
import os
import subprocess
import sys
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

        # Clean up stale sessions before checking availability
        for s in self.session_store.list_sessions():
            if s["status"] != "active":
                continue
            stale_target = s.get("tmux_target")
            if not stale_target:
                self.session_store.release(s["session_id"])
                continue
            result = subprocess.run(
                ["tmux", "has-session", "-t", stale_target],
                capture_output=True,
            )
            if result.returncode != 0:
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

        tmux_session = _get_current_tmux_session()
        if not tmux_session:
            print("Error: Not running inside tmux.", file=sys.stderr)
            print("Teammates require tmux. Start Claude Code inside a tmux session:", file=sys.stderr)
            print("  tmux new-session && claude", file=sys.stderr)
            sys.exit(1)

        n = len(personalities)
        project_dir = Path(__file__).parent.parent.parent
        inherited_flags = _get_current_claude_flags()

        # Get current window and pane targets
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_index}"],
            capture_output=True, text=True, check=True,
        )
        window_idx = result.stdout.strip()
        window_target = f"{tmux_session}:{window_idx}"

        # Remember original pane to select back after spawning
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_id}"],
            capture_output=True, text=True, check=True,
        )
        original_pane = result.stdout.strip()

        # Record existing pane IDs BEFORE splitting (IDs are stable, indices shift)
        result = subprocess.run(
            ["tmux", "list-panes", "-t", window_target, "-F", "#{pane_id}"],
            capture_output=True, text=True, check=True,
        )
        existing_pane_ids = set(result.stdout.strip().splitlines())

        # Split current window into panes for each teammate
        new_pane_ids: list[str] = []
        for _ in range(n):
            # -P -F prints the new pane's ID immediately
            result = subprocess.run(
                ["tmux", "split-window", "-t", window_target, "-P", "-F", "#{pane_id}"],
                capture_output=True, text=True, check=True,
            )
            new_pane_ids.append(result.stdout.strip())

        # Apply auto-fit tiled layout and ensure mouse mode is on
        subprocess.run(
            ["tmux", "select-layout", "-t", window_target, "tiled"],
            capture_output=True, text=True,
        )
        # Enable mouse at session level so all panes are clickable
        subprocess.run(
            ["tmux", "set-option", "-t", tmux_session, "mouse", "on"],
            capture_output=True, text=True,
        )

        teammates = []
        for i, name in enumerate(personalities):
            pane_id = new_pane_ids[i]  # stable ID like %17

            personality_info = load_personality(name)
            display_name = personality_info.get("display_name", name)

            # Set pane title for easy identification (use pane ID, not index)
            subprocess.run(
                ["tmux", "select-pane", "-t", pane_id, "-T", display_name],
                check=True,
            )

            # Launch Claude in this pane (in the project dir so it picks up skills/hooks)
            claude_cmd = f"cd {project_dir} && claude {inherited_flags}"
            subprocess.run(
                ["tmux", "send-keys", "-t", pane_id, claude_cmd],
                check=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", pane_id, "C-m"],
                check=True,
            )

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
        from .tmux import send_to_session
        for t in teammates:
            success = send_to_session(t["tmux_target"], f"/claude-talk:start {t['personality']}")
            if success:
                print(f"  ✓ Started {t['personality']} ({t['tmux_target']})", file=sys.stderr)
            else:
                print(f"  ✗ Failed to start {t['personality']} ({t['tmux_target']})", file=sys.stderr)

        # Select back to original pane so user has focus
        subprocess.run(
            ["tmux", "select-pane", "-t", original_pane],
            capture_output=True, text=True,
        )

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

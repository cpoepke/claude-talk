"""Tmux integration for sending transcriptions to Claude sessions.

Provides both sync (subprocess) and async (control mode) paths:
- Sync helpers are used by CLI callers and teammate management
- The async TmuxControlClient (set via set_async_client) is used by the
  audio server for zero-subprocess message delivery and idle detection
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tmux_control import TmuxControlClient

# ── Async control-mode client singleton ──────────────────────────────────────

_async_client: TmuxControlClient | None = None


def set_async_client(client: TmuxControlClient) -> None:
    """Register the async control-mode client (called by audio server on startup)."""
    global _async_client
    _async_client = client


def get_async_client() -> TmuxControlClient | None:
    """Get the registered async client, or None if not connected."""
    if _async_client and _async_client.connected:
        return _async_client
    return None


# ── Core send function ───────────────────────────────────────────────────────


def send_to_session(tmux_target: str, text: str, queued: bool = False) -> bool:
    """Send text to a tmux session as keyboard input.

    If an async control-mode client is connected and we're inside an event
    loop, routes through it (zero subprocess overhead). Otherwise falls back
    to sync subprocess calls.

    Args:
        tmux_target: Tmux target (session name, pane ID like %5, or session:pane)
        text: Text to send
        queued: If True, wait for the pane to be idle before sending
                (teammate messages). If False (default), send immediately
                (voice transcriptions — preserves barge-in).

    Returns:
        True if successful, False otherwise
    """
    client = get_async_client()
    if client:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside a running event loop (audio server context).
            # Schedule the send as a fire-and-forget task — the control client
            # writes to stdin which is near-instant, and callers (like
            # send_transcription_to_claude) only log the result.
            asyncio.ensure_future(_async_send(client, tmux_target, text, queued))
            return True

    # Sync fallback (CLI callers, no async client)
    return _sync_send(tmux_target, text)


async def _async_send(client: TmuxControlClient, target: str, text: str, queued: bool) -> bool:
    """Send via the async control-mode client."""
    if queued:
        return await client.send_queued(target, text)
    else:
        return await client.send_to_pane(target, text)


def _sync_send(tmux_target: str, text: str) -> bool:
    """Send via tmux subprocess calls (sync fallback)."""
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", tmux_target],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Error: tmux session '{tmux_target}' not found", file=sys.stderr)
            return False

        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_target, "-l", text],
            check=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_target, "Enter"],
            check=True,
        )

        return True

    except FileNotFoundError:
        print("Error: tmux not installed", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error sending to tmux: {e}", file=sys.stderr)
        return False


# ── Tmux query helpers ───────────────────────────────────────────────────────


def get_current_session() -> str | None:
    """Get the current tmux session name."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def get_current_pane() -> str | None:
    """Get the current tmux pane ID."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_id}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def get_window_index() -> str | None:
    """Get the current tmux window index."""
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{window_index}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def list_panes(window_target: str | None = None) -> list[str]:
    """List pane IDs for a window (or all panes if no target)."""
    cmd = ["tmux", "list-panes", "-F", "#{pane_id}"]
    if window_target:
        cmd += ["-t", window_target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [p for p in result.stdout.strip().splitlines() if p]
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []


def split_window(window_target: str) -> str | None:
    """Split a window and return the new pane ID."""
    try:
        result = subprocess.run(
            ["tmux", "split-window", "-t", window_target, "-P", "-F", "#{pane_id}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def select_layout(window_target: str, layout: str = "tiled") -> bool:
    """Apply a layout to a window."""
    try:
        subprocess.run(
            ["tmux", "select-layout", "-t", window_target, layout],
            capture_output=True, text=True, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def set_pane_title(pane_id: str, title: str) -> bool:
    """Set the title of a tmux pane."""
    try:
        subprocess.run(
            ["tmux", "select-pane", "-t", pane_id, "-T", title],
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def select_pane(pane_id: str) -> bool:
    """Focus a tmux pane."""
    try:
        subprocess.run(
            ["tmux", "select-pane", "-t", pane_id],
            capture_output=True, text=True, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def kill_pane(pane_id: str) -> bool:
    """Kill a tmux pane."""
    try:
        subprocess.run(
            ["tmux", "kill-pane", "-t", pane_id],
            capture_output=True, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def pane_exists(pane_id: str) -> bool:
    """Check if a tmux pane exists."""
    all_panes = list_panes()
    return pane_id in all_panes


def set_option(target: str, option: str, value: str) -> bool:
    """Set a tmux option on a target (session/window)."""
    try:
        subprocess.run(
            ["tmux", "set-option", "-t", target, option, value],
            capture_output=True, text=True, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def send_keys(target: str, keys: str) -> bool:
    """Send raw keys (not literal) to a pane. Use for control sequences like C-d."""
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", target, keys],
            capture_output=True, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def has_session(target: str) -> bool:
    """Check if a tmux session/pane target exists."""
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", target],
            capture_output=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False

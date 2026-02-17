"""Tmux integration for sending transcriptions to Claude sessions."""

import subprocess
import sys


def send_to_session(tmux_target: str, text: str) -> bool:
    """Send text to a tmux session as keyboard input.

    Args:
        tmux_target: Tmux target (session name or session:pane)
        text: Text to send

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if session exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", tmux_target],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Error: tmux session '{tmux_target}' not found", file=sys.stderr)
            return False

        # Send the text, brief pause, then Enter
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_target, text],
            check=True,
        )
        import time
        time.sleep(0.1)
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


def get_current_session() -> str | None:
    """Get the current tmux session name.

    Returns:
        Session name or None if not in tmux
    """
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def get_current_pane() -> str | None:
    """Get the current tmux pane ID.

    Returns:
        Pane ID or None if not in tmux
    """
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

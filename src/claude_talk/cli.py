"""Click-based CLI entry point for claude-talk."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from .config import Config
from .db import DB
from .session import SessionStore
from .teammates import TeammateManager


@click.group()
def cli():
    """Claude Talk — voice conversation plugin for Claude Code."""


# ── Server commands ──────────────────────────────────────────────────────────


@cli.group()
def server():
    """Audio server management."""


@server.command()
@click.option("--spawn-teammates", is_flag=True, help="Spawn teammates for all personalities on startup")
@click.option("--personalities", help="Comma-separated list of personalities to spawn (default: all)")
def start(spawn_teammates, personalities):
    """Start the audio server and wait for readiness."""
    config = Config()
    wlk_venv = config.get("WLK_VENV")
    wlk_venv = os.path.expanduser(wlk_venv)
    port = config.get_int("AUDIO_SERVER_PORT", 8150)

    project_dir = Path(__file__).parent.parent.parent
    server_script = project_dir / "src/audio-server.py"

    activate = Path(wlk_venv) / "bin/activate"
    if not activate.exists():
        click.echo(f"WLK venv not found at {wlk_venv}", err=True)
        sys.exit(1)

    # Spawn teammates if requested
    if spawn_teammates:
        click.echo("Spawning teammates...", err=True)
        manager = _get_teammate_manager()

        if personalities:
            # Spawn specific personalities
            for personality in personalities.split(","):
                personality = personality.strip()
                try:
                    manager.spawn_teammate(personality)
                except Exception as e:
                    click.echo(f"Failed to spawn {personality}: {e}", err=True)
        else:
            # Spawn all personalities
            manager.spawn_all_personalities()

    # Start in background using the venv's python
    python = Path(wlk_venv) / "bin/python3"
    subprocess.Popen(
        [str(python), str(server_script)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for readiness
    import urllib.request
    for _ in range(15):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/status", timeout=1)
            click.echo("Audio server ready")
            return
        except Exception:
            time.sleep(1)

    click.echo("Audio server failed to start", err=True)
    sys.exit(1)


@server.command()
def stop():
    """Stop the audio server."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(f"http://localhost:{port}/stop", method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


@server.command()
@click.option("--json", "output_json", is_flag=True, help="Output full status as JSON")
def status(output_json):
    """Check if the audio server is running. With --json, output full status."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://localhost:{port}/status", timeout=2) as response:
            if output_json:
                click.echo(response.read().decode())
            else:
                click.echo("running")
    except Exception:
        if output_json:
            click.echo("{}", err=True)
        sys.exit(1)


@server.command("set-voice")
@click.argument("voice")
def set_voice(voice):
    """Set the TTS voice on the audio server."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{port}/voice",
            data=json.dumps({"voice": voice}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = urllib.request.urlopen(req, timeout=2)
        result = json.loads(response.read())
        click.echo(json.dumps(result))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("speak")
@click.argument("text")
@click.option("--timeout", default=3600, help="Request timeout in seconds")
def speak(text, timeout):
    """Speak text via TTS and capture user response."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{port}/speak",
            data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(response.read())
        click.echo(json.dumps(result))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("queue-speak")
@click.argument("text")
@click.argument("session_id")
@click.option("--timeout", default=3600, help="Request timeout in seconds for response")
def queue_speak(text, session_id, timeout):
    """Queue TTS message with session's voice, then wait for response."""
    from .db import DB
    from .session import SessionStore

    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)

    # Get session's voice from database
    store = SessionStore(DB())
    session_info = store.get_personality(session_id)
    if not session_info:
        click.echo(f"Error: Session {session_id} not found", err=True)
        sys.exit(1)

    voice = session_info.get("voice") or config.get("VOICE", "Daniel")

    try:
        import urllib.request

        # Queue the message
        req = urllib.request.Request(
            f"http://localhost:{port}/queue-speak",
            data=json.dumps({
                "text": text,
                "voice": voice,
                "session_id": session_id
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        response = urllib.request.urlopen(req, timeout=5)
        queue_result = json.loads(response.read())
        click.echo(f"Queued (position: {queue_result.get('queue_size', '?')})", err=True)

        # Wait for response
        response = urllib.request.urlopen(
            f"http://localhost:{port}/queue-response/{session_id}",
            timeout=timeout
        )
        result = json.loads(response.read())
        click.echo(json.dumps(result))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("listen")
@click.option("--timeout", default=3600, help="Request timeout in seconds")
def listen(timeout):
    """Listen for user speech (blocking)."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        response = urllib.request.urlopen(f"http://localhost:{port}/listen", timeout=timeout)
        result = json.loads(response.read())
        click.echo(json.dumps(result))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("queue-listen")
def queue_listen():
    """Queue a background listen operation."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{port}/queue-listen",
            data=b"",
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
        click.echo("Queued")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("volume")
def get_volume():
    """Get current system volume (0-100)."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(f"http://localhost:{port}/volume")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            click.echo(data.get("volume", 50))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("volume-up")
def volume_up():
    """Increase system volume by 10%."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{port}/volume/up",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            click.echo(data.get("volume", 50))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@server.command("volume-down")
def volume_down():
    """Decrease system volume by 10%."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{port}/volume/down",
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            click.echo(data.get("volume", 50))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ── Session commands ─────────────────────────────────────────────────────────


@cli.group()
def session():
    """Voice session management."""


def _get_store() -> SessionStore:
    return SessionStore(DB())


def _get_teammate_manager() -> TeammateManager:
    return TeammateManager(DB())


@session.command()
@click.argument("session_id")
@click.argument("personality", default="unknown")
@click.option("--voice", default=None, help="TTS voice for this session")
def claim(session_id, personality, voice):
    """Claim a voice session with specific personality and voice."""
    store = _get_store()
    store.claim(session_id, personality, voice)

    # Auto-detect and set tmux target
    tmux_env = os.environ.get("TMUX", "")
    tmux_pane = os.environ.get("TMUX_PANE", "")

    if tmux_env and tmux_pane:
        session_name = tmux_env.split(",")[0].split("/")[-1]
        tmux_target = f"{session_name}:{tmux_pane}"
        store.set_tmux_target(session_id, tmux_target)
        click.echo(f"Session {session_id} claimed (tmux: {tmux_target})", err=True)
    else:
        click.echo(f"Session {session_id} claimed", err=True)


@session.command("claim-active")
@click.argument("session_id")
@click.option("--personality", help="Personality to claim (uses DEFAULT_PERSONALITY if not specified)")
def claim_active(session_id, personality):
    """Claim a voice session with a personality from config."""
    config = Config()

    # Get personality to use
    if not personality:
        personality = config.get("DEFAULT_PERSONALITY", "claude")

    # Load voice from personality template
    voice = None
    if personality != "unknown":
        from .personality import load_personality
        info = load_personality(personality)
        voice = info.get("voice")

    # Fallback to config voice
    if not voice:
        voice = config.get("VOICE")

    store = _get_store()
    try:
        store.claim(session_id, personality, voice)
        click.echo(f"Session {session_id[:8]}... claimed with {personality} ({voice})", err=True)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo(f"Tip: Use --personality to specify a different personality", err=True)
        sys.exit(1)


@session.command()
@click.argument("session_id")
def release(session_id):
    """Release a voice session."""
    store = _get_store()
    store.release(session_id)
    click.echo(f"Session {session_id} released", err=True)


@session.command("is-active")
@click.argument("session_id")
def is_active(session_id):
    """Check if a session is active. Exit 0 if yes, 1 if no."""
    store = _get_store()
    if not store.is_active(session_id):
        sys.exit(1)


@session.command("check-or-claim")
@click.argument("session_id")
def check_or_claim(session_id):
    """Check if session is active; claim it if old state file says active. Exit 0 if active, 1 if not."""
    store = _get_store()
    if not store.check_or_claim(session_id):
        sys.exit(1)


@session.command("list")
def list_sessions():
    """List all sessions."""
    store = _get_store()
    sessions = store.list_sessions()
    click.echo(json.dumps(sessions, indent=2))


@session.command()
def active():
    """Get the active session ID."""
    store = _get_store()
    sid = store.get_active()
    if sid:
        click.echo(sid)
    else:
        sys.exit(1)


@session.command("update-personality")
@click.argument("session_id")
@click.argument("personality")
@click.option("--voice", default=None, help="TTS voice")
def update_personality(session_id, personality, voice):
    """Update personality and voice for a session."""
    store = _get_store()
    store.update_personality(session_id, personality, voice)
    click.echo(f"Updated session {session_id} personality to {personality}", err=True)


@session.command("get-personality")
@click.argument("session_id")
def get_personality(session_id):
    """Get personality and voice for a session."""
    store = _get_store()
    info = store.get_personality(session_id)
    if info:
        click.echo(json.dumps(info))
    else:
        sys.exit(1)


@session.command("set-tmux-target")
@click.argument("session_id")
@click.argument("tmux_target", required=False)
def set_tmux_target(session_id, tmux_target):
    """Set tmux target for sending transcriptions. Auto-detects from env if not provided."""
    if not tmux_target:
        # Auto-detect from environment
        tmux_env = os.environ.get("TMUX", "")
        tmux_pane = os.environ.get("TMUX_PANE", "")

        if not tmux_env:
            click.echo("Error: Not in tmux session and no target provided", err=True)
            sys.exit(1)

        # Extract session from TMUX env (format: /tmp/tmux-501/default,12345,0)
        session_name = tmux_env.split(",")[0].split("/")[-1] if tmux_env else None

        if session_name and tmux_pane:
            tmux_target = f"{session_name}:{tmux_pane}"
        elif session_name:
            tmux_target = session_name
        else:
            click.echo("Error: Could not detect tmux session", err=True)
            sys.exit(1)

    store = _get_store()
    store.set_tmux_target(session_id, tmux_target)
    click.echo(f"Set tmux target for {session_id}: {tmux_target}", err=True)


@session.command("get-tmux-target")
@click.argument("session_id")
def get_tmux_target(session_id):
    """Get tmux target for a session."""
    store = _get_store()
    target = store.get_tmux_target(session_id)
    if target:
        click.echo(target)
    else:
        sys.exit(1)


# ── Teammate commands ────────────────────────────────────────────────────────


@cli.group()
def teammate():
    """Multi-personality teammate management."""


@teammate.command("spawn")
@click.argument("personalities", nargs=-1)
@click.option("--all", "spawn_all_flag", is_flag=True, help="Spawn all available personalities")
def spawn_team(personalities, spawn_all_flag):
    """Spawn teammates in a tmux grid. Interactive selection if no args given."""
    manager = _get_teammate_manager()
    available = manager.available_personalities()

    if not available:
        click.echo("No personalities found in ~/.claude-talk/personalities/", err=True)
        sys.exit(1)

    if spawn_all_flag:
        selected = [p for p in available if manager.session_store.is_personality_available(p)]
    elif personalities:
        selected = list(personalities)
    else:
        # Interactive selection
        click.echo("Available personalities:")
        for i, name in enumerate(available, 1):
            status = "" if manager.session_store.is_personality_available(name) else " (active)"
            click.echo(f"  {i}. {name}{status}")
        click.echo()
        choices = click.prompt(
            "Enter numbers or names (comma-separated), or 'all'",
            type=str,
        )
        if choices.strip().lower() == "all":
            selected = [p for p in available if manager.session_store.is_personality_available(p)]
        else:
            selected = []
            for part in choices.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(available):
                        selected.append(available[idx])
                elif part in available:
                    selected.append(part)

    if not selected:
        click.echo("No personalities selected", err=True)
        sys.exit(1)

    # Ensure uniqueness
    if len(selected) != len(set(selected)):
        click.echo("Error: Duplicate personalities not allowed", err=True)
        sys.exit(1)

    click.echo(f"Spawning {len(selected)} teammates: {', '.join(selected)}", err=True)
    teammates = manager.spawn_team(selected)
    click.echo(json.dumps(teammates, indent=2))


@teammate.command("list")
def list_teammates():
    """List all active teammates."""
    manager = _get_teammate_manager()
    teammates = manager.list_teammates()
    click.echo(json.dumps(teammates, indent=2))


@teammate.command("kill")
@click.argument("session_id")
def kill_teammate(session_id):
    """Kill a teammate by session ID."""
    manager = _get_teammate_manager()
    manager.kill_teammate(session_id)


@teammate.command("kill-all")
def kill_all():
    """Kill all active teammates."""
    manager = _get_teammate_manager()
    manager.kill_all_teammates()


# ── Config commands ──────────────────────────────────────────────────────────


@cli.command("config")
@click.argument("setting", required=False)
def config_cmd(setting):
    """Show or set config. Use KEY=VALUE to set."""
    if setting and "=" in setting:
        key, _, val = setting.partition("=")
        config_file = Path.home() / ".claude-talk/config.env"
        if config_file.exists():
            lines = config_file.read_text().splitlines()
        else:
            lines = []
        found = False
        quoted = f'"{val}"' if " " in val else val
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={quoted}"
                found = True
                break
        if not found:
            lines.append(f"{key}={quoted}")
        config_file.write_text("\n".join(lines) + "\n")
        click.echo(f"{key}={val}")
    else:
        config = Config()
        for k, v in sorted(config.values.items()):
            click.echo(f"{k}={v}")


# ── Device commands ──────────────────────────────────────────────────────────


@cli.command()
def devices():
    """List audio devices."""
    from .devices import get_defaults, list_devices
    devs = list_devices()
    din, dout = get_defaults()
    click.echo("Audio Devices:")
    for d in devs:
        flags = []
        if d["input_channels"] > 0:
            flags.append(f"{d['input_channels']}in")
        if d["output_channels"] > 0:
            flags.append(f"{d['output_channels']}out")
        marker = ""
        if d["index"] == din:
            marker += " ← default input"
        if d["index"] == dout:
            marker += " ← default output"
        click.echo(f"  [{d['index']}] {d['name']} ({', '.join(flags)}){marker}")


# ── Voice commands ───────────────────────────────────────────────────────────


@cli.command()
@click.option("--enhanced", is_flag=True, help="Show only Enhanced/Premium voices")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def voices(enhanced, as_json):
    """List macOS TTS voices."""
    from .voices import list_enhanced_voices, list_voices
    vlist = list_enhanced_voices() if enhanced else list_voices()
    if as_json:
        click.echo(json.dumps(vlist, indent=2))
    else:
        for v in vlist:
            tag = " [Enhanced]" if v.get("enhanced") else ""
            click.echo(f"  {v['name']}  {v['lang']}{tag}")


# ── Personality commands ─────────────────────────────────────────────────────


@cli.group()
def personality():
    """Personality management."""


@personality.command("list")
def personality_list():
    """List available personality templates."""
    from .personality import list_personalities
    plist = list_personalities()
    if not plist:
        click.echo("No personalities found.")
        return
    for p in plist:
        voice = p.get("voice", "?")
        style = p.get("style", "?")
        click.echo(f"  {p['name']:<20} {style:<25} {voice}")


@personality.command()
@click.argument("name")
@click.option("--session-id", help="Session ID (uses primary if not specified)")
def switch(name, session_id):
    """Switch personality for a session."""
    from .personality import switch_personality
    from .db import DB
    from .session import SessionStore

    # Get session to update
    if not session_id:
        store = SessionStore(DB())
        session_id = store.get_primary()
        if not session_id:
            click.echo("No primary session found. Specify --session-id explicitly.", err=True)
            sys.exit(1)

    try:
        info = switch_personality(session_id, name)
        voice = info.get("voice", "?")
        click.echo(f"Switched session {session_id[:8]}... to {name} (voice: {voice})")
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@personality.command("show")
@click.argument("session_id", required=False)
def show(session_id):
    """Show personality for a session."""
    from .db import DB
    from .session import SessionStore

    # Get session
    if not session_id:
        store = SessionStore(DB())
        session_id = store.get_primary()
        if not session_id:
            click.echo("No primary session found.", err=True)
            sys.exit(1)

    store = SessionStore(DB())
    info = store.get_personality(session_id)
    if info:
        click.echo(f"Session {session_id[:8]}...: {info.get('personality', '?')} (voice: {info.get('voice', '?')})")
    else:
        click.echo("Session not found.", err=True)
        sys.exit(1)


@personality.command("display")
@click.argument("session_id", required=False)
@click.option("--color", is_flag=True, help="Output color code for statusline")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def personality_display(session_id, color, output_json):
    """Show personality display name for a session (for statusline)."""
    from .personality import load_session_personality
    from .db import DB
    from .session import SessionStore
    import json as json_lib

    # Get session
    if not session_id:
        store = SessionStore(DB())
        session_id = store.get_primary()
        if not session_id:
            click.echo("(none)", err=True)
            sys.exit(1)

    info = load_session_personality(session_id)
    if not info:
        click.echo("(none)", err=True)
        sys.exit(1)

    if output_json:
        output = {
            "display_name": info.get("display_name", info.get("identity_name", "(none)")),
            "color": info.get("color", "95"),
        }
        click.echo(json_lib.dumps(output))
    elif color:
        click.echo(info.get("color", "95"))
    elif info.get("display_name"):
        click.echo(info["display_name"])
    elif info.get("identity_name"):
        click.echo(info["identity_name"])
    else:
        click.echo("(none)", err=True)
        sys.exit(1)


# ── State commands ───────────────────────────────────────────────────────────


def _state_lock_acquire(lock_dir: Path, retries: int = 50) -> bool:
    """Acquire lock via mkdir (atomic on macOS, no flock needed)."""
    for _ in range(retries):
        try:
            lock_dir.mkdir()
            return True
        except FileExistsError:
            import time
            time.sleep(0.1)
    # Stale lock - force remove and retry once
    import shutil
    shutil.rmtree(lock_dir, ignore_errors=True)
    try:
        lock_dir.mkdir()
        return True
    except FileExistsError:
        return False


def _state_lock_release(lock_dir: Path):
    """Release lock."""
    import shutil
    shutil.rmtree(lock_dir, ignore_errors=True)


def _state_read_file(state_file: Path) -> dict:
    """Read state file into dict."""
    state = {}
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                state[k.strip()] = v.strip()
    return state


def _state_write_file(state_file: Path, state: dict):
    """Write state dict to file."""
    state_file.write_text("\n".join(f"{k}={v}" for k, v in state.items()) + "\n")


@cli.group()
def state():
    """Session state management."""


@state.command("set")
@click.argument("key")
@click.argument("value")
def state_set(key, value):
    """Set a state key-value pair."""
    state_file = Path.home() / ".claude-talk/state"
    lock_dir = state_file.parent / ".state.lock"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    if not _state_lock_acquire(lock_dir):
        click.echo("Failed to acquire state lock", err=True)
        sys.exit(1)

    try:
        state_dict = _state_read_file(state_file)
        state_dict[key] = value
        _state_write_file(state_file, state_dict)
    finally:
        _state_lock_release(lock_dir)


@state.command("get")
@click.argument("key")
def state_get(key):
    """Get a state value by key."""
    state_file = Path.home() / ".claude-talk/state"
    if not state_file.exists():
        sys.exit(1)

    state_dict = _state_read_file(state_file)
    value = state_dict.get(key)
    if value is None:
        sys.exit(1)
    click.echo(value)


@state.command("is-muted")
def state_is_muted():
    """Check if microphone is muted (exit 0 if muted, 1 if not)."""
    state_file = Path.home() / ".claude-talk/state"
    if not state_file.exists():
        sys.exit(1)

    state_dict = _state_read_file(state_file)
    if state_dict.get("MUTED") == "true":
        sys.exit(0)
    else:
        sys.exit(1)


# ── Hook commands ────────────────────────────────────────────────────────────


@cli.group()
def hook():
    """Hook implementations."""


@hook.command("stop")
def hook_stop():
    """Stop hook: speak response, capture user speech, inject into conversation."""
    from .hooks.voice_stop import run
    run()


# ── Channel commands ─────────────────────────────────────────────────────────


@cli.group()
def channel():
    """Channel and message management."""


@channel.command("send")
@click.argument("session_id")
@click.argument("text")
@click.option("--from-session", default=None, help="Sender session ID")
def channel_send(session_id, text, from_session):
    """Send a message to a session's channel."""
    from .channels import ChannelManager
    from .db import DB

    manager = ChannelManager(DB())
    channel_id = manager.get_or_create_channel(session_id)
    message_id = manager.send_message(channel_id, text, "direct", from_session)
    click.echo(f"Message {message_id} sent to channel {channel_id}", err=True)


@channel.command("broadcast")
@click.argument("text")
@click.option("--from-session", default=None, help="Sender session ID")
def channel_broadcast(text, from_session):
    """Broadcast a message to all active sessions."""
    from .channels import ChannelManager
    from .db import DB

    manager = ChannelManager(DB())
    manager.broadcast(text, "broadcast", from_session)
    click.echo("Message broadcast to all sessions", err=True)


@channel.command("poll")
@click.argument("session_id")
def channel_poll(session_id):
    """Poll for unread messages in a session's channel."""
    from .channels import ChannelManager
    from .db import DB

    manager = ChannelManager(DB())
    channel_id = manager.get_or_create_channel(session_id)
    messages = manager.get_unread_messages(channel_id)

    if messages:
        click.echo(json.dumps(messages))
        # Mark all as read
        for msg in messages:
            manager.mark_read(msg["message_id"])
    else:
        sys.exit(1)  # No messages


@channel.command("route")
@click.argument("text")
def channel_route(text):
    """Parse text and determine routing (for testing)."""
    from .routing import parse_route, get_target_sessions

    route_type, target_session_id, cleaned_text = parse_route(text)
    target_sessions = get_target_sessions(route_type, target_session_id)

    result = {
        "route_type": route_type,
        "target_session_id": target_session_id,
        "cleaned_text": cleaned_text,
        "target_sessions": target_sessions,
    }
    click.echo(json.dumps(result, indent=2))

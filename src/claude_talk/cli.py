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


@click.group()
def cli():
    """Claude Talk — voice conversation plugin for Claude Code."""


# ── Server commands ──────────────────────────────────────────────────────────


@cli.group()
def server():
    """Audio server management."""


@server.command()
def start():
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
def status():
    """Check if the audio server is running. Exit 0 if yes, 1 if no."""
    config = Config()
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    try:
        import urllib.request
        urllib.request.urlopen(f"http://localhost:{port}/status", timeout=2)
        click.echo("running")
    except Exception:
        sys.exit(1)


# ── Session commands ─────────────────────────────────────────────────────────


@cli.group()
def session():
    """Voice session management."""


def _get_store() -> SessionStore:
    return SessionStore(DB())


@session.command()
@click.argument("session_id")
@click.argument("personality", default="unknown")
def claim(session_id, personality):
    """Claim a voice session."""
    store = _get_store()
    store.claim(session_id, personality)
    click.echo(f"Session {session_id} claimed", err=True)


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
    """List saved personalities."""
    from .personality import list_personalities
    plist = list_personalities()
    if not plist:
        click.echo("No personalities found.")
        return
    for p in plist:
        marker = " ✓" if p.get("active") else ""
        voice = p.get("voice", "?")
        style = p.get("style", "?")
        click.echo(f"  {p['name']:<20} {style:<25} {voice}{marker}")


@personality.command()
@click.argument("name")
def switch(name):
    """Switch active personality."""
    from .personality import switch_personality
    try:
        info = switch_personality(name)
        click.echo(f"Switched to {name}. Voice: {info.get('voice', '?')}")
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@personality.command()
def active():
    """Show the active personality name."""
    from .personality import get_active_personality
    name = get_active_personality()
    if name:
        click.echo(name)
    else:
        click.echo("(none)", err=True)
        sys.exit(1)


# ── State commands ───────────────────────────────────────────────────────────


@cli.command("state")
@click.argument("action", type=click.Choice(["set"]))
@click.argument("key")
@click.argument("value")
def state_cmd(action, key, value):
    """Set session state (legacy compat)."""
    state_file = Path.home() / ".claude-talk/state"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Read existing state
    state = {}
    if state_file.exists():
        for line in state_file.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                state[k.strip()] = v.strip()
    state[key] = value
    state_file.write_text("\n".join(f"{k}={v}" for k, v in state.items()) + "\n")

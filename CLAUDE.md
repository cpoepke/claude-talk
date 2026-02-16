# Claude Talk

Voice conversation plugin for Claude Code. **macOS (Apple Silicon) only.**

## How it works

Mic -> sounddevice (gain) -> WebSocket -> WhisperLiveKit (MLX Metal GPU) -> text -> Claude -> response -> macOS `say` TTS -> speaker

All processing is local except the Claude API call.

## Skills

- `/claude-talk:install` - Install dependencies + personalize (name, voice, personality)
- `/claude-talk:start` - Start voice chat (uses Stop hook loop)
- `/claude-talk:stop` - Stop voice chat
- `/claude-talk:chat` - Quick single voice exchange (no teammate)
- `/claude-talk:config` - View/edit configuration
- `/claude-talk:personality` - Manage personalities (list, create, switch, edit, delete, export, import)
- `/claude-talk:help` - Show help

## CLI

`claude-talk` binary (installed via `pip install -e .` into WLK venv):
- `claude-talk server start|stop|status` - Audio server lifecycle
- `claude-talk session claim|claim-active|release|is-active|check-or-claim|list|active` - Session management (SQLite-backed)
- `claude-talk session update-personality|get-personality` - Per-session personality tracking
- `claude-talk config [KEY=VALUE]` - View/set config
- `claude-talk devices` - List audio devices
- `claude-talk voices [--enhanced]` - List macOS TTS voices
- `claude-talk personality list|switch|active` - Personality management
- `claude-talk state set KEY VALUE` - Set session state (legacy compat)

## Principles

**Keep logic in Python, not shell:**
- ALL business logic goes in Python package (`src/claude_talk/`)
- Skills and hooks should ONLY call `claude-talk` CLI commands
- NEVER extract/parse config files in bash (use `claude-talk` commands instead)
- If you need to combine multiple pieces of data, add a Python CLI command
- Example: Don't do `grep VOICE config.env | cut -d= -f2` in bash — add a `claude-talk config get VOICE` command

**Thin hooks:**
- Hooks should be minimal bash that calls Python CLI
- No logic beyond calling `claude-talk` commands
- All state management through Python CLI commands

## Key paths

- `src/claude_talk/` - Python package (config, db, session, personality, devices, voices, cli)
- `src/audio-server.py` - Audio server (TTS, capture, barge-in, WLK)
- `.claude/hooks/voice-stop.sh` - Stop hook (voice conversation loop)
- `config/defaults.env` - Default configuration
- `~/.claude-talk/config.env` - User overrides (created by install)
- `~/.claude-talk/claude-talk.db` - SQLite database (sessions, future: channels/messages)
- `~/.claude-talk/personality.md` - Active personality (created by install)
- `~/.claude-talk/personalities/` - Saved personalities directory (includes 9 defaults)
- `~/.claude-talk/active-personality` - Name of active personality
- `~/.claude-talk/venvs/` - Python virtual environments
- `personalities/` - Default personality templates (copied during install)
- `tests/` - Unit tests (`pytest tests/`)

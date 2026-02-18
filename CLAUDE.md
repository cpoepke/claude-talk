# Claude Talk

Voice conversation plugin for Claude Code. **macOS (Apple Silicon) only.**

## How it works

Mic -> sounddevice (gain) -> webrtcvad -> whisper.cpp (Metal GPU) -> text -> Claude -> response -> Kokoro TTS (MLX Metal GPU) -> speaker

All processing is local except the Claude API call.

## Skills

- `/claude-talk:install` - Install dependencies + personalize (name, voice, personality)
- `/claude-talk:start` - Start voice chat (tmux routing)
- `/claude-talk:stop` - Stop voice chat
- `/claude-talk:chat` - Quick single voice exchange (no teammate)
- `/claude-talk:config` - View/edit configuration
- `/claude-talk:personality` - Manage personalities (list, create, switch, edit, delete, export, import)
- `/claude-talk:help` - Show help

## CLI

`claude-talk` binary (installed via `pip install -e .` into WLK venv):
- `claude-talk server start|stop|status|speak|set-voice|volume|volume-up|volume-down|mute|unmute` - Audio server lifecycle & controls
- `claude-talk session register` - Register current session for tmux routing (reads env/files, no args)
- `claude-talk session claim|claim-active|release|activate|is-active|list|active` - Session management (SQLite-backed)
- `claude-talk session update-personality|get-personality|set-tmux-target` - Per-session metadata
- `claude-talk config [KEY=VALUE]` - View/set config
- `claude-talk devices` - List audio devices
- `claude-talk tts warmup|voices|test` - TTS model management and testing
- `claude-talk voices [--enhanced]` - List macOS TTS voices (legacy)
- `claude-talk personality list|switch|active` - Personality management
- `claude-talk state set KEY VALUE` - Set session state (legacy compat)

## Principles

**Keep logic in Python, not shell:**
- ALL business logic goes in Python package (`src/claude_talk/`)
- Skills and hooks should ONLY call `claude-talk` CLI commands — minimal bash, no logic
- NEVER extract/parse config files in bash (use `claude-talk` commands instead)
- If you need to combine multiple pieces of data, add a Python CLI command
- Example: Don't do `grep VOICE config.env | cut -d= -f2` in bash — add a `claude-talk config get VOICE` command

**One command per skill step:**
- Each step in a SKILL.md should call ONE `claude-talk` CLI command
- All context detection (session ID, tmux pane, personality, voice) must be encapsulated in Python
- Skills should never contain grep/sed/awk parsing, conditional logic, or multi-line bash scripts
- Example: `claude-talk session register` handles all session setup internally

**Thin hooks:**
- Hooks should be a single bash line calling one `claude-talk` command
- No logic beyond calling `claude-talk` commands
- All state management through Python CLI commands

## Key paths

- `src/claude_talk/` - Python package (config, db, session, personality, devices, voices, cli)
- `src/audio-server.py` - Audio server (Kokoro TTS, whisper.cpp STT, VAD, barge-in)
- `.claude/hooks/session-track.sh` - UserPromptSubmit hook (writes CLAUDE_SESSION_ID to current-session file)
- `.claude/settings.json` - Registers hooks
- `config/defaults.env` - Default configuration
- `~/.claude-talk/config.env` - User overrides (created by install)
- `~/.claude-talk/claude-talk.db` - SQLite database (sessions, future: channels/messages)
- `~/.claude-talk/current-session` - Current session ID (written by UserPromptSubmit hook)
- `~/.claude-talk/personality.md` - Active personality (created by install)
- `~/.claude-talk/personalities/` - Saved personalities directory (includes 9 defaults)
- `~/.claude-talk/active-personality` - Name of active personality
- `~/.claude-talk/venvs/` - Python virtual environments
- `personalities/` - Default personality templates (copied during install)
- `tests/` - Unit tests (`pytest tests/`)

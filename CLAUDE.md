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

## Key paths

- `src/audio-server.py` - Audio server (TTS, capture, barge-in, WLK)
- `.claude/hooks/voice-stop.sh` - Stop hook (voice conversation loop)
- `config/defaults.env` - Default configuration
- `~/.claude-talk/config.env` - User overrides (created by install)
- `~/.claude-talk/personality.md` - Active personality (created by install)
- `~/.claude-talk/personalities/` - Saved personalities directory
- `~/.claude-talk/active-personality` - Name of active personality
- `~/.claude-talk/venvs/` - Python virtual environments

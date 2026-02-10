# Claude Talk

Voice conversation plugin for Claude Code. **macOS (Apple Silicon) only.**

## How it works

Mic -> sounddevice (gain) -> WebSocket -> WhisperLiveKit (MLX Metal GPU) -> text -> Claude -> response -> macOS `say` TTS -> speaker

All processing is local except the Claude API call.

## Skills

- `/claude-talk:install` - Install dependencies + personalize (name, voice, personality)
- `/claude-talk:start` - Start voice chat (spawns audio teammate)
- `/claude-talk:stop` - Stop voice chat
- `/claude-talk:chat` - Quick single voice exchange (no teammate)
- `/claude-talk:config` - View/edit configuration
- `/claude-talk:help` - Show help

## Key paths

- `scripts/` - Audio capture and transcription scripts
- `config/defaults.env` - Default configuration
- `~/.claude-talk/config.env` - User overrides (created by install)
- `~/.claude-talk/personality.md` - Name, voice, and personality (created by install)
- `~/.claude-talk/venvs/` - Python virtual environments

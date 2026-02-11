---
name: help
description: Show help for claude-talk voice chat commands.
disable-model-invocation: true
---

# Voice Chat Help

Display this help text to the user:

---

**claude-talk** - Voice conversation with Claude Code (macOS only)

### Quick Start
```
/claude-talk:install    # One-time setup + personalization
/claude-talk:start      # Start talking!
```

### Commands

| Command | Description |
|---------|-------------|
| `/claude-talk:install` | Install dependencies + choose name, voice, and personality |
| `/claude-talk:start` | Start voice chat with continuous listening |
| `/claude-talk:stop` | Stop voice chat session |
| `/claude-talk:mute` | Pause microphone capture |
| `/claude-talk:unmute` | Resume microphone capture |
| `/claude-talk:chat` | Quick single voice exchange |
| `/claude-talk:config` | View/edit settings (e.g., `/claude-talk:config VOICE=Karen`) |
| `/claude-talk:help` | Show this help |

### Requirements
- macOS with Apple Silicon (M1/M2/M3/M4)
- Python 3.12
- Working microphone

### Configuration
Settings are in `~/.claude-talk/config.env`. Key settings:
- `AUDIO_DEVICE` - Mic index (find with `python3 -c "import sounddevice; print(sounddevice.query_devices())"`)
- `MIC_GAIN` - Mic gain multiplier (built-in mic needs ~8.0, USB mics ~1.0)
- `VOICE` - TTS voice (Daniel, Karen, Moira, Samantha)
- `CAPTURE_MODE` - `wlk` (streaming, default) or `vad` (legacy batch)

### Personality
Your assistant personality is in `~/.claude-talk/personality.md`. Re-run `/claude-talk:install` to change it.

### Troubleshooting
- **No speech detected**: Check `AUDIO_DEVICE` index and `MIC_GAIN`
- **Whisper hallucinations**: Increase `MIC_GAIN` or lower `VAD_THRESHOLD`
- **Echo in capture**: The speak-and-capture script handles this, but increase `SILENCE_SECS` if needed
- **Server won't start**: Check if port 8090 is in use: `lsof -i :8090`

---

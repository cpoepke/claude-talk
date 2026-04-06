---
name: help
description: "Display available claude-talk voice chat commands, configuration options, and usage examples. Use when the user asks for help with claude-talk, voice mode commands, how to use voice chat, or wants to see available voice options."
disable-model-invocation: true
---

# Voice Chat Help

Display this help text to the user:

---

**claude-talk** — Voice conversation with Claude Code (macOS only)

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
| `/claude-talk:louder` | Increase system volume by 10% |
| `/claude-talk:quieter` | Decrease system volume by 10% |
| `/claude-talk:volume` | Set system volume to a specific level (0–100) |
| `/claude-talk:chat` | Quick single voice exchange |
| `/claude-talk:config` | View/edit settings (e.g., `/claude-talk:config KOKORO_VOICE=bm_daniel`) |
| `/claude-talk:personality` | Manage personalities (list, create, switch, edit, delete, export, import) |
| `/claude-talk:teammate` | Spawn voice teammates in separate tmux panes |
| `/claude-talk:help` | Show this help |

### Requirements
- macOS with Apple Silicon (M1/M2/M3/M4)
- Python 3.12
- Working microphone

### Configuration
Settings are in `~/.claude-talk/config.env`. Key settings:
- `AUDIO_DEVICE` — Mic index (find with `claude-talk devices`)
- `MIC_GAIN` — Mic gain multiplier (built-in mic needs ~8.0, USB mics ~1.0)
- `KOKORO_VOICE` — Kokoro TTS voice ID (e.g., `bm_daniel`, `af_heart`)
- `KOKORO_SPEED` — TTS speed multiplier (default 1.0)

### Personalities
Manage multiple personalities with `/claude-talk:personality`. Personalities are saved in `~/.claude-talk/personalities/`. See `/claude-talk:personality` for subcommands (list, create, switch, edit, delete, export, import).

### Interrupt (speak over TTS)
Requires BlackHole 2ch virtual audio device. See the [interrupt setup guide](../../docs/interrupt/setup.md) for configuration. When available, you can interrupt TTS mid-sentence by speaking.

### Troubleshooting
- **No speech detected**: Check `AUDIO_DEVICE` index and `MIC_GAIN`
- **Whisper hallucinations**: Increase `MIC_GAIN` or adjust `VAD_AGGRESSIVENESS` (0–3)
- **Interrupt not working**: Ensure system output is set to Multi-Output Device
- **Server won't start**: Check if another audio-server process is running (`lsof -i :8090`)

---

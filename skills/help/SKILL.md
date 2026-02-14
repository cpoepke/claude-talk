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
| `/claude-talk:personality` | Manage personalities (list, create, switch, edit, delete) |
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

### Personalities
Manage multiple personalities with `/claude-talk:personality`:
- `/claude-talk:personality` — list all saved personalities
- `/claude-talk:personality create` — create a new personality
- `/claude-talk:personality switch <name>` — switch active personality
- `/claude-talk:personality edit [name]` — edit a personality
- `/claude-talk:personality delete <name>` — delete a personality
- `/claude-talk:personality export [name]` — print personality file
- `/claude-talk:personality import` — import from markdown or file

Personalities are saved in `~/.claude-talk/personalities/`. The active one is copied to `~/.claude-talk/personality.md`.

### Barge-In (interrupt TTS by speaking)
Requires BlackHole 2ch virtual audio device:
1. `brew install --cask blackhole-2ch`
2. Open Audio MIDI Setup → `+` → Create Multi-Output Device
3. Check "Built-in Output" (first) and "BlackHole 2ch" (no drift correction)
4. Set Multi-Output Device as system output

BlackHole is auto-detected. When available, you can interrupt TTS mid-sentence by speaking.

### Troubleshooting
- **No speech detected**: Check `AUDIO_DEVICE` index and `MIC_GAIN`
- **Whisper hallucinations**: Increase `MIC_GAIN` or lower `VAD_THRESHOLD`
- **Barge-in not working**: Ensure system output is set to Multi-Output Device (not just speakers)
- **Server won't start**: Check if port 8090 is in use: `lsof -i :8090`

---

---
name: config
description: View or edit voice chat configuration. Shows current settings and allows changes.
disable-model-invocation: true
argument-hint: "[setting=value]"
---

# Voice Chat Configuration

View or update voice chat settings.

## If no arguments ($ARGUMENTS is empty)

Show the current configuration by reading these files in order:
1. `~/.claude-talk/config.env` (user overrides)
2. Find CLAUDE_TALK_DIR and read `<CLAUDE_TALK_DIR>/config/defaults.env` (defaults)

Also read `~/.claude-talk/active-personality` and show the active personality name (e.g., "Active personality: **witty-jarvis**"). If the file doesn't exist, show "Active personality: (none — run `/claude-talk:personality` to set up)".

Display a clear summary of all settings with their current effective values, noting which are defaults and which are user-set.

If the audio server is running, fetch live status for device and barge-in info:
```bash
curl -s http://localhost:8150/status 2>/dev/null
```
If it returns JSON, display:
- **Input device**: name and index, whether auto-detected
- **Output device**: name and index
- **Barge-in**: enabled/disabled, BlackHole device index if available

Also show audio devices and active input/output. Run:
```bash
source "$HOME/.claude-talk/venvs/wlk/bin/activate" && python3 -c "
import sounddevice as sd
devices = sd.query_devices()
din, dout = sd.default.device
print('Audio Devices:')
for i, d in enumerate(devices):
    flags = []
    if d['max_input_channels'] > 0: flags.append(f\"{d['max_input_channels']}in\")
    if d['max_output_channels'] > 0: flags.append(f\"{d['max_output_channels']}out\")
    marker = ''
    if i == din: marker += ' ← default input'
    if i == dout: marker += ' ← default output'
    print(f'  [{i}] {d[\"name\"]} ({', '.join(flags)}){marker}')
"
```

Show the active AUDIO_DEVICE setting and what it resolves to (if "auto" or unset, note that auto-detection is active).

Also show available TTS voices:
```bash
say -v '?' | head -20
```

## If arguments provided ($ARGUMENTS is not empty)

Parse the argument as `KEY=VALUE` (e.g., `VOICE=Karen`, `MIC_GAIN=4.0`, `AUDIO_DEVICE=2`, `AUDIO_DEVICE=auto`).

Update `~/.claude-talk/config.env` by adding or replacing the line with that key.

Confirm the change to the user.

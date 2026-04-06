---
name: config
description: "View, edit, or reset voice chat configuration including voice, mic gain, audio device, and TTS settings. Use when the user asks about voice settings, wants to change voice configuration, adjust audio preferences, or check current claude-talk settings."
disable-model-invocation: true
argument-hint: "[setting=value]"
---

# Voice Chat Configuration

View or update claude-talk voice chat settings.

## If no arguments ($ARGUMENTS is empty)

Show the current configuration:

1. Read `~/.claude-talk/config.env` (user overrides) and `<CLAUDE_TALK_DIR>/config/defaults.env` (defaults). Find CLAUDE_TALK_DIR from the config or by locating the plugin directory.

2. Read `~/.claude-talk/active-personality` and show the active personality name. If missing, show "Active personality: (none — run `/claude-talk:personality` to set up)".

3. Display all settings with effective values, marking which are defaults vs user-set.

4. Show audio server status, devices, and active AUDIO_DEVICE resolution:
   ```bash
   source ~/.claude-talk/venvs/wlk/bin/activate && claude-talk server status
   claude-talk devices
   ```

5. Show available TTS voices:
   ```bash
   claude-talk tts voices
   ```

## If arguments provided ($ARGUMENTS is not empty)

Parse the argument as `KEY=VALUE` (e.g., `KOKORO_VOICE=bm_daniel`, `MIC_GAIN=4.0`, `AUDIO_DEVICE=2`).

Update `~/.claude-talk/config.env` using the CLI:
```bash
source ~/.claude-talk/venvs/wlk/bin/activate && claude-talk config KEY=VALUE
```

Verify the change took effect:
```bash
claude-talk config KEY
```

Confirm the new effective value to the user.

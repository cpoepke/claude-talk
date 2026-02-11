---
name: mute
description: Mute the microphone during a voice chat session. The capture loop pauses until unmuted.
disable-model-invocation: true
---

# Mute Microphone

Pause microphone capture during a voice chat session.

## Steps

1. Read `~/.claude-talk/config.env` to get `CLAUDE_TALK_DIR`.

2. Check that a voice session is active (Bash):
   ```bash
   source "<CLAUDE_TALK_DIR>/scripts/state.sh" && [[ "$(voice_state_read SESSION)" == "active" ]] && echo "active" || echo "inactive"
   ```
   If inactive, tell the user: "No voice chat session is active. Start one with `/claude-talk:start`."

3. Set muted state (Bash):
   ```bash
   source "<CLAUDE_TALK_DIR>/scripts/state.sh" && voice_state_write MUTED=true STATUS=muted
   ```

4. Confirm: "Microphone muted. Run `/claude-talk:unmute` to resume."

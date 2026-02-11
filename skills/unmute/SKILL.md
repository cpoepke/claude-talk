---
name: unmute
description: Unmute the microphone during a voice chat session. Resumes capture on the next loop cycle.
disable-model-invocation: true
---

# Unmute Microphone

Resume microphone capture during a voice chat session.

## Steps

1. Read `~/.claude-talk/config.env` to get `CLAUDE_TALK_DIR`.

2. Check that a voice session is active (Bash):
   ```bash
   source "<CLAUDE_TALK_DIR>/scripts/state.sh" && [[ "$(voice_state_read SESSION)" == "active" ]] && echo "active" || echo "inactive"
   ```
   If inactive, tell the user: "No voice chat session is active. Start one with `/claude-talk:start`."

3. Clear muted state (Bash):
   ```bash
   source "<CLAUDE_TALK_DIR>/scripts/state.sh" && voice_state_write MUTED=false STATUS=listening
   ```

4. Confirm: "Microphone unmuted. Listening for speech."

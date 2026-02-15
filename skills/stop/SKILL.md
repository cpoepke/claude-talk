---
name: stop
description: Stop voice chat. Shuts down the audio server and deactivates the voice session.
disable-model-invocation: true
---

# Stop Voice Chat

Gracefully shut down the voice chat session.

## Steps

1. Get CLAUDE_TALK_DIR from config (current directory if it contains scripts/, or from ~/.claude-talk/config.env):
   ```bash
   if [ -d scripts/lib ]; then
     CLAUDE_TALK_DIR="$(pwd)"
   else
     CLAUDE_TALK_DIR=$(grep CLAUDE_TALK_DIR ~/.claude-talk/config.env 2>/dev/null | cut -d= -f2 | tr -d '"')
   fi
   ```

2. Deactivate session and stop server (use Bash):
   ```bash
   bash "$CLAUDE_TALK_DIR/scripts/lib/set-session-state.sh" stopped && \
   bash "$CLAUDE_TALK_DIR/scripts/lib/stop-audio-server.sh"
   ```

3. Confirm to the user: "Voice chat stopped."

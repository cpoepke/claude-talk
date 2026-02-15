---
name: stop
description: Stop voice chat. Shuts down the audio server and deactivates the voice session.
disable-model-invocation: true
---

# Stop Voice Chat

Gracefully shut down the voice chat session.

## Steps

1. Release the active session and stop server (use Bash):
   ```bash
   source ~/.claude-talk/venvs/wlk/bin/activate
   # Get the active session and release it
   ACTIVE_SESSION=$(claude-talk session active 2>/dev/null)
   if [ -n "$ACTIVE_SESSION" ]; then
     claude-talk session release "$ACTIVE_SESSION"
   fi
   # Also clear old state file for backwards compatibility
   claude-talk state set SESSION stopped
   # Stop audio server
   claude-talk server stop
   ```

2. Confirm to the user: "Voice chat stopped."

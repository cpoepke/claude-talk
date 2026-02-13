---
name: stop
description: Stop voice chat. Shuts down the audio server and deactivates the voice session.
disable-model-invocation: true
---

# Stop Voice Chat

Gracefully shut down the voice chat session.

## Steps

1. Deactivate the voice session (this breaks the Stop hook loop):
   ```bash
   echo "SESSION=stopped" > "$HOME/.claude-talk/state"
   ```

2. Stop the audio server:
   ```bash
   curl -s -X POST http://localhost:8150/stop
   ```

3. Confirm to the user: "Voice chat stopped."

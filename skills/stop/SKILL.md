---
name: stop
description: Stop voice chat. Shuts down the audio capture teammate and transcription server.
disable-model-invocation: true
---

# Stop Voice Chat

Gracefully shut down the voice chat session.

## Steps

1. Update voice state. Read `~/.claude-talk/config.env` to get `CLAUDE_TALK_DIR`, then run (Bash):
   ```bash
   source "<CLAUDE_TALK_DIR>/scripts/state.sh" && voice_state_write SESSION=stopped STATUS=idle MUTED=false
   ```

2. Send a shutdown request to the "audio-loop" teammate:
   ```
   SendMessage type: "shutdown_request", recipient: "audio-loop"
   ```

3. Wait for shutdown confirmation.

4. Signal the WLK auto-restart loop to stop, then kill the server:
   ```bash
   touch /tmp/voice_chat/wlk.stop
   pkill -f "wlk.*--port" || true
   pkill -f "whisper-server.*--port" || true
   pkill -f "start-whisper-server" || true
   ```

5. Delete the team using TeamDelete.

6. Confirm to the user: "Voice chat stopped."

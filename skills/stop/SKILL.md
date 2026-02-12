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

2. Kill capture processes and the whisper server FIRST (this unblocks the audio-mate's foreground Bash call).
   Wait briefly after killing to ensure processes actually exit:
   ```bash
   touch /tmp/voice_chat/wlk.stop
   pkill -f "capture-utterance" || true
   pkill -f "wlk-capture" || true
   pkill -f "wlk.*--port" || true
   pkill -f "whisper-server.*--port" || true
   pkill -f "start-whisper-server" || true
   sleep 0.5
   # Verify and force-kill any survivors
   pkill -9 -f "wlk-capture" 2>/dev/null || true
   pkill -9 -f "wlk.*--port" 2>/dev/null || true
   ```

3. Send a shutdown request to the "audio-mate" teammate:
   ```
   SendMessage type: "shutdown_request", recipient: "audio-mate"
   ```

4. Wait for shutdown confirmation.

5. Delete the team using TeamDelete.

6. Confirm to the user: "Voice chat stopped."

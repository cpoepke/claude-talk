---
name: stop
description: Stop voice chat. Shuts down the audio capture teammate and transcription server.
disable-model-invocation: true
---

# Stop Voice Chat

Gracefully shut down the voice chat session.

## Steps

1. Send a shutdown request to the "audio-mate" teammate:
   ```
   SendMessage type: "shutdown_request", recipient: "audio-mate"
   ```

2. Wait for shutdown confirmation.

3. Kill the WhisperLiveKit server process:
   ```bash
   pkill -f "wlk.*--port" || true
   pkill -f "whisper-server.*--port" || true
   ```

4. Delete the team using TeamDelete.

5. Confirm to the user: "Voice chat stopped."

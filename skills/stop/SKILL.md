---
name: stop
description: Stop voice chat. Shuts down the audio capture teammate and transcription server.
disable-model-invocation: true
---

# Stop Voice Chat

Gracefully shut down the voice chat session.

## Steps

1. Stop the audio server (this unblocks audio-mate's HTTP calls):
   ```bash
   curl -s -X POST http://localhost:8150/stop
   ```
   Wait briefly for graceful shutdown:
   ```bash
   sleep 1
   ```

2. Send a shutdown request to the "audio-mate" teammate:
   ```
   SendMessage type: "shutdown_request", recipient: "audio-mate"
   ```

3. Wait for shutdown confirmation.

4. Delete the team using TeamDelete.

5. Confirm to the user: "Voice chat stopped."

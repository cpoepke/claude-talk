---
name: chat
description: Quick single voice exchange. Captures one utterance and responds via TTS. No persistent session needed.
disable-model-invocation: true
---

# Quick Voice Chat

Single voice exchange without starting a full voice chat session. Good for quick questions.

## Prerequisites

The audio server must be running. If not, start it first by following the audio server startup steps from the start skill.

## Steps

1. Check if audio server is running:
   ```bash
   curl -s http://localhost:8150/status >/dev/null 2>&1
   ```
   If it fails, tell the user the audio server isn't running and they should start a voice chat session first with `/claude-talk:start`, or you can start the server for them.

2. Capture one utterance (use Bash with timeout 60000):
   ```bash
   curl -s http://localhost:8150/listen
   ```
   Parse the JSON response to extract the "text" field.

3. If text is empty, "(silence)", or "(muted)", tell the user no speech was detected.

4. Otherwise, respond conversationally to what the user said. Keep the response natural and concise.

5. Speak the response via TTS (use Bash):
   ```bash
   curl -s -X POST http://localhost:8150/speak -H 'Content-Type: application/json' -d '{"text":"<your response>"}'
   ```

6. Show the exchange to the user:
   - "You said: <transcription>"
   - "Response: <your response>"

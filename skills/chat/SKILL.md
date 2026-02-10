---
name: chat
description: Quick single voice exchange. Captures one utterance and responds via TTS. No persistent session needed.
disable-model-invocation: true
---

# Quick Voice Chat

Single voice exchange without starting a full voice chat session. Good for quick questions.

## Prerequisites

The WhisperLiveKit server must be running. If not, start it first:
```
bash "<CLAUDE_TALK_DIR>/scripts/start-whisper-server.sh" &
```

## Steps

1. Load config: read `~/.claude-talk/config.env` for `CLAUDE_TALK_DIR`, then source `<CLAUDE_TALK_DIR>/config/defaults.env`.

2. Capture one utterance (use Bash with timeout 60000):
   ```
   bash "<CLAUDE_TALK_DIR>/scripts/capture-and-print.sh"
   ```

3. Read the stdout output. If empty or "(silence)", tell the user no speech was detected.

4. Otherwise, respond conversationally to what the user said. Keep the response natural and concise.

5. Speak the response via TTS (use Bash):
   ```
   say -v "$VOICE" "<your response>"
   ```
   Use the VOICE from config (default: Daniel).

6. Show the exchange to the user:
   - "You said: <transcription>"
   - "Response: <your response>"

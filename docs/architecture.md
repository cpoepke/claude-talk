# Architecture

## Voice capture

The system uses two capture modes:

- **WLK (default)** - Streams mic audio via WebSocket to WhisperLiveKit, which runs Whisper via MLX on the Metal GPU. Transcription is real-time, word-by-word. End of utterance is detected when the transcription text stabilizes for 2 seconds.

- **VAD (legacy)** - Energy-based voice activity detection captures audio locally, then sends the complete WAV to a whisper-cpp HTTP server for batch transcription. Simpler but higher latency.

## Stop hook architecture

`/claude-talk:start` activates a **Stop hook** that drives the voice conversation loop with zero extra Claude API overhead:

```
Claude responds with text
    |
    v
Stop hook fires (bash script)
    |
    v
Extract last assistant message from transcript JSONL
    |
    v
POST /speak-and-listen (TTS + mic capture, with barge-in)
    |
    v
User speaks → transcription returned
    |
    v
Hook returns decision:"block" with reason:"The user said aloud: <text>"
    |
    v
Claude sees the speech as context, responds → Stop hook fires → loop
```

The hook is a bash script (`.claude/hooks/voice-stop.sh`). It makes HTTP calls to the audio server — no Claude API calls, no context accumulation. The loop breaks when `SESSION` in `~/.claude-talk/state` is set to `stopped` (via `/claude-talk:stop`).

### Server-side buffering

To minimize the gap between hook invocations (while Claude is thinking), the hook calls `POST /queue-listen` before returning. This starts a background capture on the audio server. When the next `/speak-and-listen` fires, it checks for buffered speech first — if the user already spoke during the thinking gap, it skips capture and just does TTS.

## Audio server

`src/audio-server.py` is a FastAPI server that handles all audio operations:

| Endpoint | Description |
| -------- | ----------- |
| `GET /listen` | Block until user speaks, return transcription |
| `POST /speak-and-listen` | TTS + capture in one call (checks buffer first) |
| `POST /speak` | TTS only |
| `POST /queue-listen` | Start background capture for buffering |
| `GET /status` | Current state |
| `POST /mute` / `POST /unmute` | Mic control |
| `POST /stop` | Graceful shutdown |

The server manages the WLK subprocess with auto-restart and serializes capture operations with an async lock.

## Barge-in (interrupt mid-speech)

You can interrupt Claude while it's talking by speaking. Uses Geigel double-talk detection with BlackHole 2ch as a reference signal. See [barge-in setup guide](barge-in-setup.md) for installation and configuration.

## Echo prevention

The audio server sequences TTS and capture: it speaks the response first, waits for it to finish, then starts sending mic audio to WLK. When barge-in is enabled, the mic stream starts during TTS but audio is only sent to WLK after TTS finishes (or after barge-in is detected).

## Microphone gain

MacBook Pro built-in microphones produce very weak int16 signals (ambient RMS ~50, speech ~200). An 8x gain multiplier is applied before sending to WhisperLiveKit. External USB mics typically need ~1.0-2.0x. Too much gain (10x+) causes clipping, which Whisper interprets as `[Music]`.

# Architecture

## Voice capture

The system uses two capture modes:

- **WLK (default)** - Streams mic audio via WebSocket to WhisperLiveKit, which runs Whisper via MLX on the Metal GPU. Transcription is real-time, word-by-word. End of utterance is detected when the transcription text stabilizes for 2 seconds.

- **VAD (legacy)** - Energy-based voice activity detection captures audio locally, then sends the complete WAV to a whisper-cpp HTTP server for batch transcription. Simpler but higher latency.

## Tmux routing architecture

`/claude-talk:start` registers the current tmux session for **audio routing**:

```
Claude calls: claude-talk server speak "response text"
    |
    v
Audio server plays TTS
    |
    v
Audio server captures mic (WhisperLiveKit)
    |
    v
Transcription complete
    |
    v
Audio server looks up tmux target for active session
    |
    v
tmux send-keys <target> "The user said aloud: <text>"
    |
    v
Transcription injected as user message
    |
    v
Claude responds → calls server speak → loop
```

Each Claude response **must explicitly call** `claude-talk server speak` for TTS. The audio server tracks which tmux session/pane to route transcriptions back to via SQLite session management. This enables multiple personalities to run simultaneously in different tmux panes, each with their own routing target.

Session registration happens automatically during `/claude-talk:start`:
- Extracts tmux session, window, and pane ID
- Claims session in SQLite with personality and voice
- Sets tmux target (format: `session:window.pane`)
- Audio server uses this target for `tmux send-keys`

## Audio server

`src/audio-server.py` is a FastAPI server that handles all audio operations:

| Endpoint | Description |
| -------- | ----------- |
| `POST /speak` | Play TTS, then capture and route back via tmux |
| `GET /listen` | Block until user speaks, return transcription |
| `GET /status` | Current state (device, mic, interrupt) |
| `POST /mute` / `POST /unmute` | Mic control |
| `POST /stop` | Graceful shutdown |

The server manages the WLK subprocess with auto-restart, serializes capture operations with an async lock, and handles tmux routing of transcriptions back to the appropriate Claude session.

## Interrupt (interrupt mid-speech)

You can interrupt Claude while it's talking by speaking. Uses Geigel double-talk detection with BlackHole 2ch as a reference signal. See [interrupt setup guide](interrupt-setup.md) for installation and configuration.

## Echo prevention

The audio server sequences TTS and capture: it speaks the response first, waits for it to finish, then starts sending mic audio to WLK. When interrupt is enabled, the mic stream starts during TTS but audio is only sent to WLK after TTS finishes (or after interrupt is detected).

## Microphone gain

MacBook Pro built-in microphones produce very weak int16 signals (ambient RMS ~50, speech ~200). An 8x gain multiplier is applied before sending to WhisperLiveKit. External USB mics typically need ~1.0-2.0x. Too much gain (10x+) causes clipping, which Whisper interprets as `[Music]`.

## Resilience & error handling

The audio server implements four layers of fault tolerance to handle WhisperLiveKit instability:

### 1. Exception handling for websocket operations

WebSocket send operations (`ws.send()`) are wrapped in try-catch blocks. When WLK crashes or closes the connection mid-stream (error 1011), the exception is caught and triggers a graceful shutdown instead of propagating unchecked and causing cascade failures.

### 2. Fast failure detection

WLK unresponsiveness timeout reduced from 10 seconds to 3 seconds. When WLK stops responding during capture, the system detects it faster and ends the capture, minimizing speech loss. The shorter timeout also improves user experience by failing fast instead of leaving the user waiting in silence.

### 3. Connection retry with exponential backoff

WebSocket connection attempts retry up to 3 times with exponential backoff:
- Attempt 1: 5s timeout
- Attempt 2: 10s timeout, 0.5s delay
- Attempt 3: 15s timeout, 1s delay

This handles transient network failures and WLK startup delays without requiring manual intervention.

### 4. Frame rate limiting

To prevent overwhelming WLK's processing buffer during long TTS responses, a 10ms pause is injected every 50 frames (~5 seconds of audio). This prevents buffer saturation that triggers connection closure (error 1011).

### Why these improvements matter

Long assistant responses (200+ audio frames) can cause WLK to become unresponsive or close the websocket connection. Without resilience mechanisms, this results in:
- Unhandled exceptions crashing the audio server
- 10+ seconds of user speech lost while waiting for timeout
- Failed transcriptions requiring manual session restart

With these improvements, the system gracefully handles WLK instability, preserves partial transcriptions when possible, and recovers automatically from transient failures.

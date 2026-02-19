# Architecture

## Overview

```
Mic -> sounddevice (gain) -> webrtcvad -> whisper.cpp (Metal GPU) -> text -> Claude -> response -> Kokoro TTS (MLX Metal GPU) -> speaker
```

All processing runs locally on Apple Silicon (Metal GPU), except the Claude API call. The audio server (`src/audio-server.py`) is a single Python process that handles STT, TTS, VAD, barge-in detection, and session routing.

## Audio server

`src/audio-server.py` is a raw asyncio Unix socket server. No HTTP, no FastAPI, no uvicorn.

- **Socket**: `~/.claude-talk/audio-server.sock` (Unix domain, permissions `0600`)
- **Protocol**: JSON-lines over Unix socket (one JSON object per line, newline-delimited)
- **Session lifecycle**: Persistent `session_connect` connections for ref counting. Auto-shuts down the whisper engine when the last session disconnects (5s grace period). Server process stays alive for reconnection.

### Commands

| Command | Description |
| ------- | ----------- |
| `speak` | Fire-and-forget TTS with barge-in support; pauses global listener during playback |
| `status` | Current state (idle/listening/speaking), device info, volume |
| `voice` | Change TTS voice |
| `volume` / `volume_up` / `volume_down` / `set_volume` | System volume control (via osascript) |
| `mute` / `unmute` | Mic control |
| `devices` | List audio devices |
| `session_connect` | Persistent session connection (ref counting, keeps socket open) |
| `stop` | Graceful shutdown |

## Speech-to-text: whisper.cpp (pywhispercpp)

`WhisperEngine` class in `audio-server.py` loads the whisper.cpp model directly in-process via `pywhispercpp.model.Model`. No subprocess, no WebSocket, no separate server.

- **Model**: Configured via `WHISPER_MODEL` config key (default: `base.en`)
- **Loading**: Model loaded in an executor thread at startup (~0.5-2s)
- **Transcription**: `transcribe()` runs in executor thread with an async lock (one transcription at a time)
- **Initial prompt**: Built from personality names so Whisper recognizes them as vocabulary
- **GPU**: Runs on Metal GPU via whisper.cpp's native Metal support

## Text-to-speech: Kokoro TTS (MLX-Audio)

`KokoroTTS` class in `src/claude_talk/tts.py` provides neural TTS via MLX-Audio.

- **Model**: `mlx-community/Kokoro-82M-bf16` (configurable via `KOKORO_MODEL`)
- **GPU**: Runs on Metal GPU via MLX
- **Voices**: 54 voices across 9 languages (American, British, Japanese, Chinese, Spanish, French, Hindi, Italian, Portuguese)
- **Voice ID format**: `{lang}{gender}_{name}` (e.g., `bm_daniel`, `af_heart`)
- **Chunk-interruptible**: Generation iterates chunks; checks a stop flag between each chunk so barge-in can halt generation mid-sentence
- **Sample rate**: 24kHz output
- **Playback**: `sounddevice.OutputStream` with callback-based streaming; supports stop via `sd.CallbackStop`
- **Voice mapping**: Legacy macOS `say` voice names (e.g., "Daniel") are mapped to Kokoro voice IDs via a static lookup table

## Voice activity detection: webrtcvad

`VoiceActivityDetector` class in `audio-server.py` uses Google's WebRTC VAD for speech boundary detection.

- **Frame size**: 20ms frames at 16kHz (320 samples)
- **Aggressiveness**: Configurable 0-3 via `VAD_AGGRESSIVENESS` (default: 2)
- **Silence threshold**: Configurable via `VAD_SILENCE_FRAMES` (default: 50 frames = 1 second of silence)
- **Lookback buffer**: Preserves 100ms (5 frames) of leading audio before speech onset, preventing clipped consonants
- **Safety cap**: 30s maximum recording (1500 frames) to prevent runaway captures
- **Output**: Concatenated speech frames as float32 PCM, passed directly to `WhisperEngine.transcribe()`

## Tmux routing architecture

`/claude-talk:start` registers the current tmux session for audio routing:

```
Claude calls: claude-talk server speak "response text"
    |
    v
Audio server plays TTS (Kokoro, Metal GPU)
    |
    v
Audio server captures mic (sounddevice + webrtcvad + whisper.cpp)
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
Claude responds -> calls server speak -> loop
```

Each Claude response must explicitly call `claude-talk server speak` for TTS. The audio server tracks which tmux session/pane to route transcriptions back to via SQLite session management. This enables multiple personalities to run simultaneously in different tmux panes, each with their own routing target.

Session registration happens automatically during `/claude-talk:start`:
- Extracts tmux session, window, and pane ID
- Claims session in SQLite with personality and voice
- Sets tmux target (format: `session:window.pane`)
- Audio server uses this target for `tmux send-keys`

### Global listener

A continuously-running `_global_listener()` coroutine captures mic audio in the background. When the `speak` command fires:

1. The listener is paused (active capture cancelled)
2. TTS plays through speakers
3. During TTS, barge-in monitoring runs in parallel (if enabled)
4. After TTS finishes (or on barge-in), the listener resumes

This avoids serializing speak+listen into separate commands and enables uninterrupted conversation flow.

## Barge-in (interrupt mid-speech)

Users can interrupt Claude while it is speaking. Uses **Geigel double-talk detection** with BlackHole 2ch as a reference signal.

- **Reference stream**: BlackHole 2ch loopback captures what the speakers are playing
- **Detection**: Compares raw mic RMS to reference RMS ratio. Echo bleed is typically 5-12% of reference; real speech is 40%+
- **Dynamic calibration**: First ~750ms of TTS measures actual echo bleed ratio; thresholds auto-adjust
- **Spike counting**: Requires 3+ consecutive high-ratio frames (with slow decay) to trigger
- **On trigger**: TTS generation and playback are immediately stopped; buffered mic frames from the trigger point are replayed into the capture pipeline so no speech is lost

See [interrupt setup guide](interrupt-setup.md) for BlackHole installation and configuration.

## Echo prevention

Multiple layers prevent TTS audio from being picked up by the mic and mis-transcribed:

1. **Sequencing**: The global listener pauses during TTS. After TTS finishes naturally, capture waits for the reference stream to go silent, plus a 1.5s hardware buffer/reverb tail delay, then flushes contaminated mic frames.

2. **Speex AEC**: When BlackHole is available, `SpeexAEC` (via libspeexdsp) performs acoustic echo cancellation on mic frames using the reference signal. Applied both during barge-in buffering and post-TTS capture.

3. **Energy gate**: Post-TTS captures enforce a 3-second energy gate (configurable). Frames below 1000 RMS are suppressed. Requires 3+ consecutive loud frames to pass (prevents isolated noise spikes from opening the gate).

4. **Text-level echo filter**: `_strip_tts_echo()` compares transcription text against the last TTS text. Strips leading runs of matching words, then applies fuzzy matching (>30% word overlap = echo). Applied both after barge-in captures and in the global listener within 15s of TTS.

5. **Whisper hallucination filter**: Regex strips bracketed/parenthesized annotations (e.g., `[Music]`, `(inaudible)`) that Whisper produces on noise or silence.

## Microphone gain

MacBook Pro built-in microphones produce weak int16 signals (ambient RMS ~50, speech ~200). An 8x gain multiplier (configurable via `MIC_GAIN`) is applied via `sounddevice` before VAD processing. External USB mics typically need ~1.0-2.0x. Excessive gain (10x+) causes clipping, which Whisper interprets as `[Music]`.

## Dependencies

Core runtime dependencies:

| Package | Purpose |
| ------- | ------- |
| `pywhispercpp` | In-process whisper.cpp bindings (STT, Metal GPU) |
| `mlx-audio` | Kokoro TTS model loading and generation (Metal GPU) |
| `webrtcvad` | Voice activity detection |
| `sounddevice` | Mic capture and audio playback |
| `numpy` | Audio buffer manipulation |

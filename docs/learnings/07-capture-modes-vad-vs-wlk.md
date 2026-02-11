# Capture Modes: VAD vs WLK Streaming

## Two approaches to speech capture

We implemented two capture modes, each with different tradeoffs.

## VAD Mode (legacy)

**File**: `scripts/vad-capture.py`

**How it works**:
1. Continuously read mic audio in 100ms blocks
2. Calculate RMS energy of each block
3. When energy exceeds threshold (200), start recording
4. When energy drops below threshold for 1.8 seconds, stop recording
5. Send complete WAV to whisper-cpp HTTP server for batch transcription
6. Return full transcription

**Pros**:
- Simple, no streaming infrastructure needed
- Works with any Whisper HTTP server
- Low CPU usage while waiting for speech

**Cons**:
- Higher latency (must wait for complete utterance + batch transcription)
- Energy-based VAD is crude - misses quiet speech, triggers on non-speech noise
- Requires whisper-cpp server running separately

**Settings**:
- `VAD_THRESHOLD=200` (raw int16 RMS)
- `SILENCE_SECS=1.8`
- Hallucination filter: max amplitude < 650

## WLK Streaming Mode (recommended)

**File**: `scripts/wlk-capture.py`

**How it works**:
1. Open WebSocket connection to WhisperLiveKit
2. Start streaming mic audio (boosted by gain multiplier) in 100ms chunks
3. Receive real-time transcription updates via WebSocket
4. Monitor transcription text for stability
5. When text unchanged for 2.0 seconds and minimum length met, utterance is complete
6. Return accumulated transcription

**Pros**:
- Real-time, word-by-word transcription
- Lower perceived latency (transcription happens during speech, not after)
- Text-stability detection is more robust than energy-based VAD
- Single process (WLK server handles everything)

**Cons**:
- Requires WhisperLiveKit running with MLX backend
- More complex async code (WebSocket + audio streaming)
- Higher sustained GPU usage during capture

**Settings**:
- `MIC_GAIN=8.0` (applied before WebSocket send)
- `SILENCE_SECS=2.0` (text stability timeout)
- Hallucination filter: strips `[Music]`, `[INAUDIBLE]`, `[BLANK_AUDIO]`

## Why WLK is the default

The text-stability approach for end-of-utterance detection is fundamentally more reliable than energy-based VAD:

- Energy VAD can't distinguish speech from a cough, keyboard typing, or chair squeak
- Energy VAD misses quiet, whispery speech
- Text stability: if Whisper transcribes real words that stay stable, it's real speech. Period.

The streaming also means the transcription is ready almost instantly when the user stops talking, versus waiting for a full batch transcription pass.

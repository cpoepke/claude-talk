# Echo Prevention: Sequencing TTS and Capture

## Problem

When the assistant speaks a response via macOS TTS (`say` command) and the microphone is active, the mic picks up the TTS audio. This creates a feedback loop:

1. User says "Hello"
2. Assistant responds "Hi there, how can I help?"
3. Mic captures "Hi there, how can I help?" as the next user utterance
4. Assistant responds to its own previous response
5. Infinite loop of the assistant talking to itself

## Solution

`speak-and-capture.sh` sequences TTS and capture - they never run concurrently:

```bash
# Step 1: Speak response (blocking - waits for TTS to finish)
say -v "$VOICE" "$REPLY"

# Step 2: Settle time (let mic adjust after TTS stops)
sleep 0.3

# Step 3: NOW start microphone capture
./capture-utterance.sh "$OUTPUT_FILE"
```

The key insight: macOS `say` is **synchronous** - it blocks until speech is complete. So we know exactly when TTS finishes and can add a small settle buffer before starting capture.

## Why 300ms settle time?

After TTS stops, the microphone hardware and audio subsystem need a moment to return to baseline. Without the settle time, the first ~200ms of capture sometimes includes residual TTS audio or a volume spike. 300ms was determined experimentally as sufficient on MacBook Pro.

## Alternative approaches considered

- **Hardware echo cancellation**: Not available via sounddevice/PortAudio on macOS
- **Software AEC**: Complex, adds latency, unreliable with built-in speakers
- **Volume ducking**: Lower mic gain during TTS - still picks up loud speech
- **Sequential (our approach)**: Simple, reliable, zero false positives

## AEC Approach (for interrupt)

The sequential approach works perfectly when capture follows TTS. But **interrupt** requires concurrent TTS + capture, so AEC becomes necessary.

The audio server uses **SpeexDSP AEC** with a BlackHole loopback reference signal:
- Frame size: 20ms (320 samples) — critical for filter adaptation quality
- Filter length: 500ms (8000 samples) — covers room reverb tails
- Reference signal: TTS audio via BlackHole 2ch virtual loopback

AEC cleans the mic signal in the send path (to WLK). Interrupt detection uses raw mic vs reference ratio (Geigel method) since it needs the echo signal for comparison.

A text echo filter (`_strip_tts_echo`) acts as a safety net, removing TTS fragments from transcription even if AEC misses some bleed. See `docs/learnings/09-interrupt-aec-tuning.md` for details.

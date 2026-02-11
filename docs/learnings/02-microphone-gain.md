# MacBook Pro Microphone Gain

## Problem

WhisperLiveKit produced no transcription or hallucinated garbage when using the MacBook Pro built-in microphone, even in a quiet room with clear speech.

## Discovery

The MacBook Pro built-in microphone produces extremely weak raw int16 signals:

- **Ambient noise**: RMS ~50 (out of 32768 max)
- **Clear speech**: RMS ~200
- **Loud speech**: RMS ~400

This is less than 1% of the full int16 range. WhisperLiveKit (and Whisper in general) expects significantly stronger signals.

## Solution

Apply an **8x gain multiplier** to the raw int16 audio before sending to WhisperLiveKit:

```python
boosted = np.clip(indata.astype(np.float64) * 8.0, -32768, 32767).astype(np.int16)
```

This is done in `wlk-capture.py` before sending audio over the WebSocket.

## Sweet spot

| Gain | Result |
|------|--------|
| 1x | No transcription / silence |
| 4x | Inconsistent, misses quiet speech |
| **8x** | **Reliable transcription** |
| 10x+ | Clipping -> Whisper outputs `[Music]` |

## External microphones

USB/external microphones typically produce much stronger signals and need gain of 1.0-2.0x. The `MIC_GAIN` setting in `~/.claude-talk/config.env` lets users adjust this.

## Hallucination filter

Even with proper gain, near-silence can trigger Whisper hallucinations. We filter these by checking maximum amplitude:

```python
max_amplitude = float(np.max(np.abs(audio)))
if max_amplitude < 650:  # ~0.02 * 32768
    text = ""  # Discard - likely hallucination
```

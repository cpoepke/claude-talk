# Whisper Model Selection and Hallucinations

## Problem

The Whisper `base.en` model aggressively hallucinates on silence or low-amplitude audio, producing phantom text like:

- "Thank you for watching."
- "Please subscribe."
- "..."
- Random words or phrases

This is a known issue with smaller Whisper models, especially when fed low-energy audio.

## Solution

Use `small.en` or larger. The `small.en` model:
- Much lower hallucination rate on silence
- Still fast enough for real-time on Apple Silicon (MLX acceleration)
- ~465MB model size (acceptable)

## Model comparison on MacBook Pro (M4 Pro)

| Model | Size | Hallucination rate | Speed | Recommendation |
|-------|------|-------------------|-------|----------------|
| `base.en` | ~140MB | Very high | Fastest | Don't use |
| **`small.en`** | **~465MB** | **Low** | **Fast** | **Use this** |
| `medium.en` | ~1.5GB | Very low | Moderate | Overkill for real-time |
| `large-v3` | ~3GB | Minimal | Slow | Not needed |

## Additional hallucination filtering

Even with `small.en`, we apply two filters:

1. **Amplitude check** (VAD mode): Discard transcription if max amplitude < 650/32768
2. **Known hallucination strings** (WLK mode): Strip `[Music]`, `[INAUDIBLE]`, `[BLANK_AUDIO]` from output

## WhisperLiveKit vs whisper-cpp

Both use the same underlying Whisper models but differ in backend:

- **WhisperLiveKit**: Uses `mlx-whisper` (Apple MLX framework). Native Metal GPU acceleration. Real-time streaming via WebSocket.
- **whisper-cpp**: Uses GGML format models. Also Metal-accelerated. Batch processing via HTTP API.

WhisperLiveKit is preferred because streaming gives real-time word-by-word output, enabling faster end-of-utterance detection.

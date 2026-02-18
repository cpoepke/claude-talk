# Voice Cloning A/B Experiment

Comparing accent fidelity for 5 personalities where Kokoro lacks the needed accent (Irish, Scottish, Australian, Indian English).

## Models Under Test

| Model | Type | How it works |
|---|---|---|
| **macOS say** | Reference only | Native accented voices (Fiona, Moira, Karen, Rishi) |
| **Kokoro-82M** | Baseline | Pre-built voices, no accent cloning — British/American fallback |
| **CSM-1B** | Voice clone | Sesame's model, clones from reference WAV |
| **Qwen3-TTS** | Voice clone | Alibaba's model, clones from reference WAV + transcript |

## Test Phrase

> "Hello, I'm [name]. Let me tell you something interesting about the world today."

## Listening Comparison

### Bonnie (Scottish, ref: Fiona)

| File | Model | Accent? | Quality | Latency | Notes |
|---|---|---|---|---|---|
| `reference-fiona.wav` | macOS say | Native | Synth | — | Ground truth |
| `01-kokoro-bf_emma.wav` | Kokoro | British | — | — | Fallback, no Scottish |
| `02-csm1b-fiona-clone.wav` | CSM-1B | ? | — | — | |
| `03-qwen3-fiona-clone.wav` | Qwen3-TTS | ? | — | — | |

**Pick:** _____________

### Maeve (Irish, ref: Moira)

| File | Model | Accent? | Quality | Latency | Notes |
|---|---|---|---|---|---|
| `reference-moira.wav` | macOS say | Native | Synth | — | Ground truth |
| `01-kokoro-bf_alice.wav` | Kokoro | British | — | — | Fallback, no Irish |
| `02-csm1b-moira-clone.wav` | CSM-1B | ? | — | — | |
| `03-qwen3-moira-clone.wav` | Qwen3-TTS | ? | — | — | |

**Pick:** _____________

### Sheila (Australian, ref: Karen)

| File | Model | Accent? | Quality | Latency | Notes |
|---|---|---|---|---|---|
| `reference-karen.wav` | macOS say | Native | Synth | — | Ground truth |
| `01-kokoro-af_nova.wav` | Kokoro | American | — | — | Fallback, no Australian |
| `02-csm1b-karen-clone.wav` | CSM-1B | ? | — | — | |
| `03-qwen3-karen-clone.wav` | Qwen3-TTS | ? | — | — | |

**Pick:** _____________

### Tash (Australian, ref: Karen)

| File | Model | Accent? | Quality | Latency | Notes |
|---|---|---|---|---|---|
| `reference-karen.wav` | macOS say | Native | Synth | — | Ground truth |
| `01-kokoro-af_heart.wav` | Kokoro | American | — | — | Fallback, no Australian |
| `02-csm1b-karen-clone.wav` | CSM-1B | ? | — | — | |
| `03-qwen3-karen-clone.wav` | Qwen3-TTS | ? | — | — | |

**Pick:** _____________

### Vikram (Indian English, ref: Rishi)

| File | Model | Accent? | Quality | Latency | Notes |
|---|---|---|---|---|---|
| `reference-rishi.wav` | macOS say | Native | Synth | — | Ground truth |
| `01-kokoro-bm_george.wav` | Kokoro | British | — | — | Fallback, no Indian |
| `02-csm1b-rishi-clone.wav` | CSM-1B | ? | — | — | |
| `03-qwen3-rishi-clone.wav` | Qwen3-TTS | ? | — | — | |

**Pick:** _____________

## Latency Summary

_Auto-populated after running generate.py — see `latency.txt` for raw data._

| Personality | Kokoro | CSM-1B | Qwen3-TTS |
|---|---|---|---|
| Bonnie | — | — | — |
| Maeve | — | — | — |
| Sheila | — | — | — |
| Tash | — | — | — |
| Vikram | — | — | — |

## Accent Fidelity Notes

- **CSM-1B:** _Does it actually pick up the accent from the reference? Or just the timbre?_
- **Qwen3-TTS:** _Same question — accent transfer vs. just voice style?_
- **Key question:** _Is "cloned accent" good enough, or do we need native accent models?_

## Decision

| Personality | Winner | Reason |
|---|---|---|
| Bonnie | | |
| Maeve | | |
| Sheila | | |
| Tash | | |
| Vikram | | |

## How to Run

```bash
~/.claude-talk/venvs/wlk/bin/python3 experiments/voice-cloning/generate.py
```

Models will be downloaded automatically on first run (~2GB for CSM-1B, ~1.5GB for Qwen3-TTS).

## How to Listen

```bash
# Quick listen to all variants for one personality
for f in experiments/voice-cloning/bonnie/*.wav; do
    echo "--- $(basename $f) ---"
    afplay "$f"
    sleep 0.5
done
```

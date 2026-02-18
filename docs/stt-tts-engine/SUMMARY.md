# STT/TTS Engine Comparison — Summary & Recommendation

**Date:** 2026-02-18
**Context:** claude-talk uses WhisperLiveKit (WLK) v0.2.17 for STT + macOS `say` for TTS. WLK is showing reliability issues and declining maintenance. This evaluation compares 6 alternatives against our 18 requirements.

---

## Quick Verdict

| Engine | STT | TTS | STS | Viable? | One-line |
|--------|:---:|:---:|:---:|:-------:|----------|
| **WhisperLiveKit** (current) | Yes | -- | -- | Baseline | WebSocket streaming, MLX, Silero VAD. Aging. |
| **MLX-Audio** | Yes | **Yes** | **Yes** | **Hybrid** | **Only candidate with STS.** Best TTS on Apple Silicon. REST-only, no live mic pipeline. |
| **WhisperKit** | Yes | -- | -- | **Yes** | Best CoreML/ANE optimization. Swift-first, SSE not WebSocket. |
| **whisper.cpp** | Yes | -- | -- | **Yes** | Most mature. Zero deps. No WebSocket, sliding-window streaming. |
| **Lightning-SimulWhisper** | Yes | -- | -- | Risky | Best streaming algo (AlignAtt). NC license, incomplete VAD, 3 devs. |
| **Voxtral.c** | Yes | -- | -- | No | 19GB RAM, 13 days old, no vocab biasing. Watch list. |
| **lightning-whisper-mlx** | Batch | -- | -- | No | Abandoned, batch-only, broken quantization. |

---

## Comparison Matrix

### Core Capabilities

| Requirement | WLK (current) | MLX-Audio | WhisperKit | whisper.cpp | L-SimulWhisper | Voxtral.c | l-whisper-mlx |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Real-time streaming STT | **SimulStream** | Partial | **SSE stream** | Sliding window | **AlignAtt** | **Causal** | None |
| TTS | -- | **16 models** | -- | -- | -- | -- | -- |
| Speech-to-Speech | -- | **3 models** | -- | -- | -- | -- | -- |
| Barge-in / AEC | -- | -- | -- | -- | -- | -- | -- |
| Keyword / vocab bias | **static-init-prompt** | Partial | prompt | prompt (224 tok) | **static-init-prompt** | -- | -- |
| VAD | **Silero v6** | Sortformer | Built-in | **Silero v6.2** | Incomplete | Basic | -- |

### Apple Silicon

| Requirement | WLK | MLX-Audio | WhisperKit | whisper.cpp | L-SimulWhisper | Voxtral.c | l-whisper-mlx |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| MLX/Metal | Yes | **Yes** | Via CoreML | **Yes** | **Yes** | **Yes (MPS)** | Yes |
| CoreML/ANE | -- | -- | **Yes** | Yes | **Yes** | -- | -- |
| Memory (small model) | ~1 GB | ~1.2 GB | **<2 GB** | **~150 MB (Q5)** | ~1 GB | **19 GB** | ~1 GB |
| Thermal | Moderate | Unknown | **Low (0.3W)** | **Cool (<30C)** | Low (5-8W) | Unknown | Unknown |

### Architecture & Integration

| Requirement | WLK | MLX-Audio | WhisperKit | whisper.cpp | L-SimulWhisper | Voxtral.c | l-whisper-mlx |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Protocol | **WebSocket** | REST | HTTP+SSE | HTTP | TCP | C API/stdin | None |
| Multi-client | Yes | Yes (HTTP) | Yes (Vapor) | Yes (HTTP) | Unknown | No | No |
| Python integration | Subprocess | **Native** | OpenAI SDK | pywhispercpp | Script | FFI needed | **Native** |
| Install | pip+venv | pip | brew / Xcode | cmake / pip | git clone | make | pip |

### Quality & Models

| Requirement | WLK | MLX-Audio | WhisperKit | whisper.cpp | L-SimulWhisper | Voxtral.c | l-whisper-mlx |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Best WER (English) | ~2.5% (large-v3) | **1.99%** (Qwen3) | **2.0%** (stream) | ~2.5% (large-v3) | ~2.5%+degradation | 4.9% (480ms) | ~2.5% |
| Distil models | Yes | Yes | **Yes** | Partial | No | No | Yes |
| Quantization | -- | **3/4/6/8-bit** | **Yes** | **Q4/Q5/Q8** | -- | -- | Broken |
| Languages | 99+ | 99+ | 99+ | 99+ | 99+ | 13 | 99+ |
| Diarization | Sortformer | **VibeVoice** | Paid (SpeakerKit) | Experimental | -- | -- | -- |
| Hallucination filter | External | Unknown | **Built-in** | **Built-in+VAD** | CIF truncation | Unknown | Basic |
| Timestamps | Segment | **Word-level** | **Word-level** | **Word-level** | **Word-level** | -- | Segment |

### Project Health & Trust

| Requirement | WLK | MLX-Audio | WhisperKit | whisper.cpp | L-SimulWhisper | Voxtral.c | l-whisper-mlx |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Stars | ~500 | ~6,000 | ~4,300 | **~46,800** | 475 | 1,341 | 874 |
| Contributors | ~10 | 33 | 35 | **740** | 3 | 2 | 3 |
| License | MIT | MIT | MIT | MIT | **NC only** | MIT | **None** |
| Last activity | Mid-2025 | Jan 2026 | Jan 2026 | Jan 2025 | Feb 2026 | Feb 2026 | May 2024 |
| Maintenance | Declining | **Active** | **Active** | **Active** | Young | 13 days old | **Abandoned** |
| Dependencies | Heavy | Medium | Low (Swift) | **Zero** | Heavy | **Zero** | Heavy |

---

## Eliminated Candidates

### lightning-whisper-mlx — REJECTED
Batch-only inference, no streaming, no mic input, no VAD, no WebSocket. Abandoned since May 2024 with 15 unanswered issues. Quantization (headline feature) is broken. No license specified.

### Voxtral.c — WATCH LIST
Compelling architecture (pure C, zero deps, causal streaming) but 19GB memory footprint is a dealbreaker. No vocab biasing means personality routing breaks. 13 days old, 2 contributors. Revisit if smaller model variants emerge.

### Lightning-SimulWhisper — WATCH LIST
Best streaming algorithm (AlignAtt with CoreML Neural Engine) but PolyForm Noncommercial license blocks any commercial use. Incomplete VAD, unresolved streaming transcript gaps, 3 contributors. Worth monitoring if license changes.

---

## Viable Candidates — Detailed Analysis

### Option A: WhisperKit (STT replacement)

**Strengths:**
- Best Apple Silicon optimization (CoreML + ANE, 0.3W per forward pass)
- Smallest memory footprint (<2 GB peak, quantized models from 547 MB)
- ICML 2025 paper, backed by Argmax Inc with funding
- 2.0% WER confirmed in streaming mode
- `brew install whisperkit-cli` — no Python needed
- OpenAI-compatible API — easy integration pattern

**Challenges:**
- Swift-first — our codebase is Python
- HTTP+SSE, not WebSocket — requires rewriting audio streaming client
- No TTS — still need separate solution
- CoreML memory growth over long sessions (~2.4 GB to 3.3 GB in 40 min)

**Integration path:** Run `whisperkit-cli serve` as subprocess, replace WS client with HTTP+SSE client, feed audio via POST.

### Option B: whisper.cpp (STT replacement)

**Strengths:**
- Most battle-tested (46.8k stars, 740 contributors, MIT)
- Zero external dependencies — single binary + model file
- Best quantization (Q4/Q5/Q8, base.en at 57 MB disk, ~150 MB RAM)
- Silero VAD v6.2 built-in
- Metal + CoreML/ANE support
- pywhispercpp Python bindings with callbacks
- Coolest thermal profile (<30C sustained)

**Challenges:**
- No true simultaneous streaming — sliding window approximation
- No WebSocket — HTTP server or subprocess
- Server mode has documented memory leaks
- Distil model support is incomplete

**Integration path:** Use pywhispercpp library with callback API for tightest Python integration, or subprocess `whisper-stream` piped to our audio server.

### Option C: MLX-Audio (TTS replacement — and the only STS candidate)

**Strengths:**
- **Only engine with Speech-to-Speech** — Liquid2.5-Audio, SAM-Audio, MossFormer2 SE. No other candidate offers STS at all. This is a fundamentally different architecture: audio in → audio out without a text intermediate, preserving prosody and emotion.
- 16 TTS models — massive upgrade over macOS `say`
- Kokoro: 54 voice presets, 82M model, streaming, 8 languages
- Voice cloning (CSM, Qwen3-TTS)
- Emotion control (Qwen3-TTS)
- Streaming TTS (Marvis, Chatterbox)
- OpenAI-compatible REST API
- Also has STT (Whisper, Qwen3-ASR at 1.99% WER)

**Challenges:**
- REST-only, no WebSocket for STT streaming
- No live mic pipeline for STT — file/chunk based
- Pinned `transformers == 5.0.0rc3` (release candidate)
- Known streaming bugs (VibeVoice #482, audio dropout #464)
- Solo maintainer (bus factor ~1)

**Integration path:** Use as TTS engine via Python API or REST server. Keep separate STT engine for real-time mic streaming.

---

## Recommendation

### Short-term: Hybrid approach (lowest risk, highest impact)

**Keep WLK for STT** (it works, just needs our backoff/restart fixes) **+ adopt MLX-Audio Kokoro for TTS** (replaces macOS `say`).

Why:
- macOS `say` is the weakest link in voice quality — Kokoro with 54 voices is a transformative upgrade
- WLK's STT is functional with our fixes (exponential backoff, model preflight)
- No architecture changes needed for STT path
- TTS integration is simpler (Python API, no streaming protocol change)
- Can be done in a day

### Medium-term: whisper.cpp for STT

**Replace WLK with whisper.cpp** via pywhispercpp library.

Why:
- Zero-dependency core — eliminates WLK's heavy Python dependency tree
- Built-in Silero VAD v6.2 — better than WLK's aging integration
- Quantized models (57 MB base.en) — dramatically smaller footprint
- Most mature codebase in the comparison (46.8k stars, 740 contributors)
- pywhispercpp gives us Python callbacks without rewriting our architecture
- Sliding window streaming is "good enough" — our text-stability end-of-utterance detection already handles the gap

The integration would replace `WLKManager` subprocess with pywhispercpp in-process, eliminating the WebSocket layer entirely. Audio flows directly from sounddevice → pywhispercpp → text, simplifying the pipeline.

### Long-term: Monitor WhisperKit and Lightning-SimulWhisper

- **WhisperKit** if they add WebSocket support or we decide SSE is acceptable
- **Lightning-SimulWhisper** if the license changes to MIT (upstream SimulStreaming already did)
- **Voxtral.c** if smaller model variants emerge and the project matures

---

## Next Steps

1. **Now:** Integrate MLX-Audio Kokoro as TTS replacement for macOS `say`
2. **Next:** Prototype whisper.cpp via pywhispercpp as STT replacement
3. **Evaluate:** Compare pywhispercpp streaming quality vs WLK in real conversations
4. **Decide:** If whisper.cpp streaming is acceptable, migrate off WLK entirely

---

## Individual Reports

- [lightning-simulwhisper.md](./lightning-simulwhisper.md) — AlignAtt streaming, CoreML+MLX, NC license
- [mlx-audio.md](./mlx-audio.md) — Full STT/TTS/STS, 26+ models, REST-only
- [whisperkit.md](./whisperkit.md) — CoreML/ANE native, Swift-first, MIT
- [whisper-cpp.md](./whisper-cpp.md) — C/C++ reference, zero deps, 46.8k stars
- [voxtral-c.md](./voxtral-c.md) — Pure C, Mistral 4B, 19GB RAM
- [lightning-whisper-mlx.md](./lightning-whisper-mlx.md) — Batch-only, abandoned

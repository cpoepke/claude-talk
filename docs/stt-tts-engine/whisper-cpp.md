# whisper.cpp -- STT/TTS Engine Evaluation

> **Project:** [github.com/ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp)
> **Version evaluated:** v1.8.3 (January 15, 2025)
> **Evaluation date:** February 18, 2026
> **Summary:** The most established C/C++ port of OpenAI Whisper. Zero-dependency core with Metal/CoreML Apple Silicon acceleration. STT only -- no TTS. HTTP server mode but no native WebSocket streaming. Excellent model coverage with quantization. Mature but some server-mode stability concerns.

---

## Table of Contents

1. [Models](#1-models)
2. [Speech-to-Speech](#2-speech-to-speech)
3. [Barge-in / Interruption](#3-barge-in--interruption)
4. [Keyword / Wake Word](#4-keyword--wake-word)
5. [TTS](#5-tts)
6. [Apple Silicon](#6-apple-silicon)
7. [Real-time Streaming](#7-real-time-streaming)
8. [VAD](#8-vad)
9. [Audio Input](#9-audio-input)
10. [Language](#10-language)
11. [Diarization](#11-diarization)
12. [Transcription Quality](#12-transcription-quality)
13. [Architecture](#13-architecture)
14. [Reliability](#14-reliability)
15. [TTS Quality](#15-tts-quality)
16. [Project Health](#16-project-health)
17. [Dependencies](#17-dependencies)
18. [Privacy](#18-privacy)

---

## 1. Models

### Available Sizes

| Model | Parameters | Disk (F16) | Disk (Q5_0) | RAM (approx) |
|-------|-----------|-----------|-------------|---------------|
| tiny / tiny.en | 39M | 75 MiB | 31 MiB | ~273 MB |
| base / base.en | 74M | 142 MiB | 57 MiB | ~388 MB |
| small / small.en | 244M | 466 MiB | 182 MiB | ~743 MB |
| medium / medium.en | 749M | 1.5 GiB | 515 MiB | ~1.7 GB |
| large-v1 | 1550M | 2.9 GiB | 1.1 GiB | ~3.9 GB |
| large-v2 | 1550M | 2.9 GiB | 1.1 GiB | ~3.9 GB |
| large-v3 | 1550M | 2.9 GiB | 1.1 GiB | ~3.9 GB |
| large-v3-turbo | 809M | 1.5 GiB | 547 MiB | ~2.0 GB |

`.en` suffixes denote English-only variants (slightly better for English). Multilingual models support 99+ languages.

### Quality (WER)

OpenAI's published WER benchmarks (on LibriSpeech test-clean, English):

| Model | WER (approx) |
|-------|-------------|
| tiny.en | ~5.6% |
| base.en | ~4.2% |
| small.en | ~3.0% |
| medium.en | ~2.7% |
| large-v2 | ~2.7% |
| large-v3 | ~2.5% |
| large-v3-turbo | ~2.6% |

Real-world WER is higher depending on noise, accent, and domain. The turbo model offers near-large-v3 accuracy at roughly 8x faster inference due to pruned decoder layers.

### Speed (RTF on Apple Silicon)

Benchmark data from the whisper.cpp issue tracker (M1 Pro, processing a standard test audio):

| Model | Encode Time | Approx RTF |
|-------|------------|------------|
| tiny | 102 ms | ~0.01x |
| base | 220 ms | ~0.02x |
| small | 685 ms | ~0.06x |
| medium | 1928 ms | ~0.16x |
| large | 3350 ms | ~0.28x |

With Metal GPU acceleration, these improve further. The large-v3-turbo model is significantly faster than large-v3 with minimal quality loss.

### Quantization

Supported quantization modes: **Q4_0, Q4_1, Q4_2, Q5_0, Q5_1, Q8_0**

Quantization reduces disk size by 2-4x and memory footprint proportionally. Example: base.en drops from ~388 MB to ~150 MB (Q5_0) or ~120 MB (Q4_0) in RAM.

### Distilled Models

Initial support for [distil-whisper](https://huggingface.co/distil-whisper) models exists, but the chunk-based transcription strategy is **not implemented**, leading to sub-optimal quality. Use with caution.

### Custom / LoRA

whisper.cpp itself does **not** support LoRA adapters or fine-tuning natively. However:

- LoRA fine-tuning can be done on the PyTorch Whisper model using PEFT/HuggingFace (separate workflow)
- The fine-tuned model can then be converted to GGML format via `convert-pt-to-ggml.py`
- No runtime LoRA merging -- adapters must be baked into the model at conversion time

---

## 2. Speech-to-Speech

**No native STS capability.**

The `talk-llama` example demonstrates a voice conversation pipeline (Whisper STT -> LLaMA LLM -> external TTS), but this is a demo application, not an integrated STS engine. The TTS step relies on external tools (`say` on macOS, third-party engines like Eleven Labs).

There is no end-to-end speech-to-speech model or streaming voice transformation.

---

## 3. Barge-in / Interruption

**No built-in barge-in or AEC (Acoustic Echo Cancellation).**

- The `stream` example uses SDL2 for mic capture but does not implement duplex audio or echo cancellation
- No interrupt hooks in the C API -- `whisper_full()` runs to completion on its audio buffer
- The `whisper_encoder_begin_callback` can theoretically abort encoding before it starts, but this is not a true barge-in mechanism
- Graceful shutdown is handled via Ctrl+C / SDL event polling, not mid-utterance interruption
- For barge-in, you would need to manage audio capture externally and cancel/restart whisper processing

**Relevance to claude-talk:** Our current architecture uses external barge-in logic. whisper.cpp would require the same external management -- no improvement over current WhisperLiveKit approach.

---

## 4. Keyword / Wake Word

### Initial Prompt (Vocabulary Biasing)

whisper.cpp supports the `--prompt` / `initial_prompt` parameter to bias transcription toward specific vocabulary:

```bash
whisper-cli -m model.bin -f audio.wav --prompt "Claude, transcription, whisper"
```

Limitations:
- Maximum 224 tokens
- Attention mechanism assigns higher weight to tokens at the end of longer prompts
- Not a true keyword spotting system -- it biases the decoder, not guarantees

### Confidence Scores

Token-level probabilities are available via the C API:
- `whisper_token_data.p` -- token probability
- `whisper_token_data.plog` -- log probability
- `whisper_token_data.pt` -- timestamp probability
- CLI: `--print-colors` shows color-coded confidence
- CLI: `--word-thold N` filters low-confidence words

### Wake Word Detection

**No built-in wake word / keyword spotting.** Research projects like CB-Whisper add keyword-spotting modules, but these are not part of whisper.cpp. For wake word detection, a separate library (e.g., Porcupine, openWakeWord) would be needed.

---

## 5. TTS

**No TTS capability whatsoever.**

whisper.cpp is purely a speech-to-text engine. The `talk-llama` example shells out to external TTS:
- macOS: `say` command
- Windows: `SpeechSynthesizer`
- Third-party: Eleven Labs, etc.

No parallel TTS streams, no streaming TTS, no voice synthesis.

---

## 6. Apple Silicon

### Metal GPU Support

**Yes, built-in.** Metal acceleration is enabled by default on macOS builds:

```bash
cmake -B build
cmake --build build -j
# Metal is auto-detected on macOS
```

Metal accelerates both encoder and decoder inference. This is the recommended acceleration path for Apple Silicon.

### Core ML / Apple Neural Engine (ANE)

**Yes, supported.** Core ML enables running the encoder on the Apple Neural Engine:

```bash
# Build with CoreML
cmake -B build -DWHISPER_COREML=ON
cmake --build build -j

# Generate CoreML model
pip install ane_transformers openai-whisper coremltools
python models/convert-whisper-to-coreml.py --model base.en
```

Performance characteristics:
- **3-6x faster** than CPU-only for encoder inference
- First run is slow (ANE compilation of CoreML model, cached afterward)
- macOS Sonoma (14+) recommended -- older versions may produce hallucinations
- GPU is the default compute unit; ANE compilation can be slow for large models

### Memory Footprint

| Model | F16 RAM | Q5_0 RAM | Q4_0 RAM |
|-------|---------|----------|----------|
| base.en | ~388 MB | ~150 MB | ~120 MB |
| medium.en | ~1.7 GB | ~515 MB | ~400 MB |
| large-v3 | ~3.9 GB | ~1.1 GB | ~900 MB |

Quantized models are practical on 8 GB machines. The base.en Q5_0 model fits comfortably alongside other processes.

### Thermal

Testing shows whisper.cpp runs cool on Apple Silicon:
- base.en Q5_1: consistently under 30 C CPU temperature
- M-series chips handle sustained workloads without thermal throttling
- The AMX coprocessor (used by Accelerate framework) is particularly power-efficient

---

## 7. Real-time Streaming

### Stream Example

The `whisper-stream` binary captures audio from the mic via SDL2 and transcribes in near-real-time:

```bash
# Build with SDL2 support
cmake -B build -DWHISPER_SDL2=ON
cmake --build build -j

# Sliding window mode (500ms steps, 5s context)
./build/bin/whisper-stream -m models/ggml-base.en.bin -t 8 --step 500 --length 5000

# VAD mode (transcribe only on speech)
./build/bin/whisper-stream -m models/ggml-base.en.bin -t 6 --step 0 --length 30000 -vth 0.6
```

### Operating Modes

| Mode | Trigger | Latency | Use Case |
|------|---------|---------|----------|
| Sliding window | Fixed interval (e.g., 500ms) | step_ms + inference time | Continuous dictation |
| VAD mode | Silence detection | Variable (speech end + inference) | Command-style input |

### First-Word Latency

- Sliding window: ~500ms (step interval) + ~20-200ms (inference, model-dependent)
- VAD mode: speech end detection + inference time
- With base.en on M1: effective first-word latency ~600-800ms in sliding window mode

### Partial Results

The sliding window mode maintains context across chunks via `pcmf32_old` buffer. Tokens from the last full segment are used as prompt for the next iteration. This is "pseudo-streaming" -- not true simultaneous decode, but overlapping windows.

### Protocol

- **No WebSocket protocol** in the official codebase
- The `stream` example is a local CLI tool using SDL2 for audio capture
- The `server` example is HTTP-only (POST multipart form data)
- Community projects add WebSocket wrappers, but these are not upstream
- A [feature request for HTTP streaming](https://github.com/ggml-org/whisper.cpp/issues/3225) exists but is not implemented

### Simultaneous Decoding

Not supported. The Whisper architecture processes audio in fixed-length windows (up to 30 seconds). There is no true token-by-token streaming decode -- results come in complete segments.

---

## 8. VAD

### Built-in VAD

whisper.cpp has **two VAD options**:

#### 1. Simple Energy-based VAD (legacy)

Built into the `stream` example via `vad_simple()`:
- Energy threshold-based detection
- Configurable via `--vad-thold` and `--freq-thold`
- Lightweight but not very accurate

#### 2. Silero VAD (v6.2.0, integrated in v1.8.3+)

Full neural VAD integrated into the core library:

```bash
# Download Silero VAD model
./models/download-vad-model.sh silero-v6.2.0

# Use with CLI
whisper-cli -m model.bin -f audio.wav --vad --vad-model models/silero-v6.2.0.bin
```

C API functions:
- `whisper_vad_detect_speech()` -- detect speech presence
- `whisper_vad_segments_from_samples()` -- identify segment boundaries
- Parameters: `min_silence_duration_ms`, `max_speech_duration_s`, threshold

Silero VAD characteristics:
- Model size: ~1.8 MB
- Processing speed: ~1 ms per 30 ms chunk
- Reduces hallucinations by skipping silence
- Significantly improves transcription speed on sparse audio

### Silence Detection

Both VAD modes support silence detection. The Silero VAD provides more reliable silence boundaries than the simple energy detector.

---

## 9. Audio Input

### PCM Format

- **Required format:** 32-bit float PCM (`float *`)
- **Sample rate:** 16,000 Hz (fixed, defined as `WHISPER_SAMPLE_RATE`)
- **Channels:** Mono (single channel)
- Helper function: `whisper_pcm_to_mel()` converts PCM to log mel spectrogram

### CLI Input

The CLI tool (`whisper-cli`) accepts:
- 16-bit WAV files natively
- Other formats via FFmpeg conversion (`--convert` flag in server mode)

### Microphone Capture

The `stream` example uses SDL2 for audio capture:
- Configurable capture device via `--capture` device ID
- `whisper-cli --list-devices` or the `stream` example lists available audio devices
- No built-in gain control -- rely on OS-level gain or external processing

### Multi-device

SDL2 supports device selection by ID. No built-in multi-device mixing or routing.

---

## 10. Language

### Multi-language Support

Whisper supports **99+ languages** via multilingual models (any model without `.en` suffix).

### Auto-detection

```c
// C API
whisper_lang_auto_detect(ctx, offset_ms, n_threads, lang_probs);
// Returns language ID with probability array for all supported languages
```

CLI: `--language auto` enables auto-detection.

### Translation

Built-in translation to English:

```bash
whisper-cli -m ggml-large-v3.bin -f audio.wav --translate
```

- Source: any of 99+ languages
- Target: **English only** (limitation of the Whisper model architecture)
- No arbitrary language-to-language translation

### English-only Models

The `.en` variants (tiny.en, base.en, small.en, medium.en) are optimized for English and slightly more accurate for English-only use cases.

---

## 11. Diarization

### Tinydiarize (Experimental)

whisper.cpp supports speaker segmentation via [tinydiarize](https://github.com/akashmjn/tinydiarize) fine-tuned models:

```bash
# Download tinydiarize model
./models/download-ggml-model.sh small.en-tdrz

# Run with diarization
whisper-cli -m models/ggml-small.en-tdrz.bin -f audio.wav -tdrz
```

Characteristics:
- Marks speaker turns with `[SPEAKER_TURN]` tokens
- Uses both voice and semantic context for speaker separation
- Available for **small.en only** (fine-tuned model)
- "Near-perfect speaker turn precision at fairly decent recall" on earnings call benchmarks
- Less than 10% extra inference cost
- **Experimental** -- not production-grade diarization

### Limitations

- No speaker identification (cannot label "Speaker A" vs "Speaker B")
- Only detects turn boundaries, not speaker count or identity
- Limited to the small.en-tdrz model
- Not available for multilingual models

---

## 12. Transcription Quality

### Hallucination Filtering

Multiple mechanisms to combat hallucinations:

| Mechanism | Parameter | Default | Description |
|-----------|-----------|---------|-------------|
| Entropy threshold | `--entropy-thold` | 2.40 | Decoder fails if entropy exceeds threshold |
| Log probability threshold | `--logprob-thold` | -1.00 | Decoder fails if log prob below threshold |
| VAD preprocessing | `--vad` | off | Skip silence to avoid "Thank you for watching" hallucinations |
| Temperature fallback | `--temperature-inc` | 0.2 | Retry with higher temperature on decoder failure |

### Punctuation

Whisper models produce punctuation naturally as part of the decoding process. No separate punctuation model needed.

### Timestamps

- **Segment-level timestamps:** Default output format
- **Word-level timestamps:** Enabled via `--max-len 1` (outputs one word per segment with timing)
- Token-level timing data available via C API (`t0`, `t1` fields in `whisper_token_data`)

### Confidence Scores

- Per-token probability (`p`), log probability (`plog`)
- Timestamp token probability (`pt`)
- Word threshold filtering: `--word-thold 0.01` (default)
- Visual confidence: `--print-colors` for color-coded output

---

## 13. Architecture

### Deployment Modes

| Mode | Binary | Protocol | Use Case |
|------|--------|----------|----------|
| CLI tool | `whisper-cli` | stdin/files | Batch transcription |
| Streaming | `whisper-stream` | SDL2 mic | Real-time local dictation |
| Server | `whisper-server` | HTTP (POST) | Multi-client service |
| Library | `libwhisper` | C API | Embedded integration |
| Talk demo | `whisper-talk-llama` | SDL2 mic + LLaMA | Voice conversation demo |

### Server Architecture

```
Client (HTTP POST) --> whisper-server --> Worker threads --> Response (JSON)
```

- HTTP-only, no WebSocket
- Configurable threads (`-t`) and processors (`-p`)
- Single model loaded in memory, shared across requests
- Supports runtime model swapping via `/load` endpoint

### Multi-client

The server handles concurrent requests via threading. No documented connection limit, but practical limit depends on model size and available compute. No request queuing or priority system documented.

### Crash Isolation

- CLI/stream: subprocess model -- crash affects only that process
- Server: single process -- a crash takes down all active connections
- Library: runs in-process -- crash propagates to host application
- No built-in sandboxing or process isolation

### Python Integration

**pywhispercpp** (v1.4.1, Dec 2025) provides Python bindings:

```python
from pywhispercpp.model import Model

model = Model('base.en')
segments = model.transcribe('file.wav')
for segment in segments:
    print(segment.text)
```

Install: `pip install pywhispercpp`
With CoreML: `WHISPER_COREML=1 pip install git+https://github.com/absadiki/pywhispercpp`

Features:
- Almost all `whisper.h` functions exposed
- Real-time transcription with callbacks
- Multiple output formats (SRT, VTT, CSV, TXT)
- CLI tool (`pwcpp`) and GUI (`pwcpp-gui`)

### WebSocket

**No native WebSocket support.** Community wrappers exist:
- [whisper-cpp-server](https://github.com/litongjava/whisper-cpp-server) -- C++ WebSocket server
- [whisper-websocket-server](https://github.com/rpdrewes/whisper-websocket-server) -- Python wrapper

These are third-party, not maintained by the whisper.cpp team.

---

## 14. Reliability

### Crash Recovery

- **No built-in crash recovery** in any mode
- Server mode: no auto-restart, no graceful degradation
- Recommendation: use a process manager (systemd, launchd, supervisord)

### Preflight Validation

- Model file integrity checked on load (GGML magic number validation)
- No explicit preflight / self-test command
- The `for-tests-` model files exist for CI testing

### Health Check

- Server mode: no `/health` endpoint documented
- The k6 `bench.js` script can be used for load testing
- No built-in heartbeat or liveness probe

### Memory Leaks

**Known issues:**
- Server mode: documented memory leak where memory does not return to previous level after requests ([Issue #2605](https://github.com/ggerganov/whisper.cpp/issues/2605))
- Windows server: handle leak causing empty responses after ~6-7 requests ([Issue #3358](https://github.com/ggml-org/whisper.cpp/issues/3358))
- HIP (AMD): residual GPU memory (~200 MB) after context free
- VAD memory leak fixed in v1.8.3
- Previous memory leak fixes introduced segfaults in stream mode ([Issue #904](https://github.com/ggml-org/whisper.cpp/issues/904))

**Assessment:** The core library (single-invocation CLI) is stable. The long-running server mode has documented resource leak issues that require monitoring and periodic restarts in production.

### Zero Runtime Allocations

The core inference engine advertises "zero runtime memory allocations" -- all memory is pre-allocated at model load time. This design improves predictability but does not prevent leaks in the server scaffolding.

---

## 15. TTS Quality

**Not applicable.** whisper.cpp has no TTS capability.

The `talk-llama` demo uses external TTS:
- macOS `say` command (built-in, limited quality)
- Third-party engines (Eleven Labs, etc.)

No voice quality, latency, or streaming characteristics to evaluate within whisper.cpp itself.

---

## 16. Project Health

| Metric | Value |
|--------|-------|
| **Stars** | ~46,800 |
| **Forks** | ~5,200 |
| **Contributors** | ~740 |
| **Commits** | ~4,005 |
| **Open issues** | ~990 |
| **License** | MIT |
| **Latest release** | v1.8.3 (January 15, 2025) |
| **Organization** | [ggml-org](https://github.com/ggml-org) (same org as llama.cpp) |
| **Creator** | Georgi Gerganov |

### Recent Activity

- v1.8.3 (Jan 2025): Silero VAD v6.2.0, 12x integrated graphics perf boost, server improvements
- v1.8.2 (Oct 2024): CPU computation bug fixes
- v1.8.1 (Oct 2024): Vulkan build fixes, memory leak fixes
- v1.8.0 (Sep 2024): Flash attention as default, substantial cross-platform perf gains

### Documentation

- README with build instructions and feature overview
- Per-example READMEs (stream, server, talk-llama)
- Model README with sizes and download instructions
- C header (`whisper.h`) is well-documented with inline comments
- No dedicated documentation site
- Community wiki / discussions on GitHub

### Ecosystem

- Same team/org as **llama.cpp** (the dominant local LLM inference engine)
- Available via Conan Center, npm, PyPI (pywhispercpp)
- Docker images for CUDA, Vulkan, MUSA
- WASM build for browser-based transcription

---

## 17. Dependencies

### Core Library

**Zero external dependencies** for the core C/C++ library. This is a headline feature:

```bash
# Minimal build (no audio capture, no server)
cmake -B build
cmake --build build -j
```

Build requirements:
- C/C++ compiler (gcc, clang, MSVC)
- CMake 3.14+
- No Python, no Rust, no Go required

### Optional Dependencies

| Feature | Dependency | Notes |
|---------|-----------|-------|
| Mic capture | SDL2 | Required for `stream` and `talk` examples |
| CoreML | Python + coremltools | One-time model conversion only |
| CUDA | NVIDIA CUDA toolkit | GPU acceleration on NVIDIA |
| FFmpeg | ffmpeg binary | Audio format conversion in server mode |
| Vulkan | Vulkan SDK | GPU acceleration (cross-platform) |

### Disk Footprint

| Component | Size |
|-----------|------|
| Built binary (whisper-cli) | ~2-5 MB |
| libwhisper shared library | ~3-8 MB |
| Model (base.en, Q5_1) | 57 MB |
| Model (base.en, F16) | 142 MB |
| Model (large-v3-turbo, Q5_0) | 547 MB |
| Silero VAD model | ~1.8 MB |

Total minimal footprint: **~60 MB** (binary + base.en Q5_1 model)

### Python (pywhispercpp)

```bash
pip install pywhispercpp  # Pre-built CPU wheels
# Or from source with Metal:
pip install git+https://github.com/absadiki/pywhispercpp
```

Requires: Python >= 3.8. The pip install builds whisper.cpp from source (includes CMake invocation).

### Offline Capability

**Fully offline** after model download. No network calls during inference. Models can be downloaded once and cached locally. The `download-ggml-model.sh` script fetches from Hugging Face.

---

## 18. Privacy

### Fully Local

**Yes, 100% local inference.** All processing happens on-device:

- No network calls during transcription
- No telemetry, analytics, or usage tracking in the codebase
- No phone-home, license checks, or update pings
- Audio data never leaves the machine
- MIT license with no usage restrictions

### Code Audit

The codebase is open source (MIT), actively reviewed by 740+ contributors. No evidence of any data collection, telemetry, or external communication in the source code.

### Model Provenance

Models are derived from OpenAI's Whisper (Apache 2.0 licensed). The GGML conversions are hosted on Hugging Face by the project maintainer. No additional licensing restrictions.

---

## Comparison Summary for claude-talk

### Strengths

- **Zero dependencies** for core library -- simplest possible deployment
- **Excellent Apple Silicon support** via Metal and CoreML/ANE
- **Mature and battle-tested** -- 46.8k stars, 740 contributors, MIT license
- **Best quantization support** -- Q4/Q5/Q8 models dramatically reduce memory
- **Silero VAD built-in** -- reduces hallucinations and speeds up sparse audio
- **Fully offline, fully private** -- no telemetry, no network calls
- **Tiny footprint** -- ~60 MB total for binary + quantized model
- **Same ecosystem as llama.cpp** -- familiar tooling and conventions

### Weaknesses

- **No WebSocket support** -- HTTP-only server, no streaming protocol
- **No true streaming decode** -- sliding window approximation, not token-by-token
- **No TTS** -- requires external TTS engine (we already use `say`)
- **No barge-in / AEC** -- same limitation as most STT engines
- **Server stability concerns** -- memory leaks, handle leaks in long-running mode
- **No health check endpoint** -- need external monitoring
- **Distilled model support is incomplete** -- sub-optimal quality

### Key Differences from Current WhisperLiveKit Setup

| Feature | WhisperLiveKit (current) | whisper.cpp |
|---------|------------------------|-------------|
| Runtime | Python + MLX | C/C++ native |
| Protocol | WebSocket | HTTP (or subprocess) |
| Streaming | True WebSocket streaming | Sliding window via SDL2 |
| GPU accel | MLX (Metal) | Metal + CoreML/ANE |
| VAD | External | Built-in Silero VAD |
| Memory | Higher (Python overhead) | Lower (C/C++, quantized models) |
| TTS | None | None |
| Install | pip + venv | CMake build or pywhispercpp pip |
| Server mode | Built-in WS server | HTTP server (no WS) |

### Recommendation

whisper.cpp is a strong candidate if you want **lower memory usage** and **simpler deployment** (single binary + model file). The built-in Silero VAD is a significant advantage. However, the **lack of native WebSocket streaming** means the current claude-talk architecture (which uses WebSocket for real-time streaming from mic to transcriber) would need to be rearchitected to use either:

1. **Subprocess mode** -- pipe audio to whisper-cli and parse stdout (simplest)
2. **Library mode** -- use pywhispercpp with callbacks (most flexible)
3. **HTTP server mode** -- POST audio chunks to whisper-server (least ideal for real-time)

The subprocess or library approach would be the best fit for claude-talk's voice conversation use case.

---

## References

- [whisper.cpp GitHub](https://github.com/ggml-org/whisper.cpp)
- [whisper.cpp Releases](https://github.com/ggml-org/whisper.cpp/releases)
- [Benchmark Results (Issue #89)](https://github.com/ggml-org/whisper.cpp/issues/89)
- [pywhispercpp on PyPI](https://pypi.org/project/pywhispercpp/)
- [pywhispercpp GitHub](https://github.com/absadiki/pywhispercpp)
- [Silero VAD Integration (Issue #3003)](https://github.com/ggml-org/whisper.cpp/issues/3003)
- [Tinydiarize (PR #1058)](https://github.com/ggml-org/whisper.cpp/pull/1058)
- [Server Memory Leak (Issue #2605)](https://github.com/ggerganov/whisper.cpp/issues/2605)
- [Server Handle Leak (Issue #3358)](https://github.com/ggml-org/whisper.cpp/issues/3358)
- [CoreML/ANE Discussion (#548)](https://github.com/ggml-org/whisper.cpp/discussions/548)
- [Vocabulary Biasing Discussion (#1979)](https://github.com/ggml-org/whisper.cpp/issues/1979)
- [WebSocket Feature Request (#1158)](https://github.com/ggerganov/whisper.cpp/issues/1158)
- [Apple Silicon Whisper Benchmarks](https://www.voicci.com/blog/apple-silicon-whisper-performance.html)
- [Mac Whisper Speed Test](https://github.com/anvanvan/mac-whisper-speedtest)
- [Whisper.cpp on Mac mini M4](https://itblog.today/blog/building/whisper-metal.html)
- [Sotto Blog: Whisper.cpp on Apple Silicon](https://sotto.to/blog/whisper-cpp-apple-silicon)
- [OpenAI Whisper Model Card](https://github.com/openai/whisper)

# Lightning-SimulWhisper - Evaluation Report

**Repository:** [altalt-org/Lightning-SimulWhisper](https://github.com/altalt-org/Lightning-SimulWhisper)
**Tagline:** "An MLX/CoreML implementation of SimulStreaming. ~15x increase in performance"
**Evaluated:** 2026-02-18

Lightning-SimulWhisper is an open-source speech-to-text engine from altalt-org (the team behind the "Alt" transcription app). It combines Apple's MLX framework with CoreML Neural Engine acceleration to deliver real-time simultaneous (streaming) Whisper transcription on Apple Silicon. It is based on the [SimulStreaming](https://github.com/ufal/SimulStreaming) project from Charles University (UFAL) and the [Simul-Whisper paper](https://arxiv.org/abs/2406.10052) (2024 SOTA in simultaneous speech transcription).

---

## 1. Models

### Supported Sizes/Variants

| Model | Parameters | Approx. RAM | CoreML Encode Latency |
|-------|-----------|-------------|----------------------|
| tiny / tiny.en | 39M | ~400 MB | ~50 ms (est.) |
| base / base.en | 74M | ~500 MB | ~150 ms |
| small / small.en | 244M | ~1 GB | ~200 ms |
| medium / medium.en | 769M | ~2.5 GB | ~271 ms |
| large-v1 | 1550M | ~5 GB | ~400 ms |
| large-v2 | 1550M | ~5 GB | ~400 ms |
| large-v3 | 1550M | ~5 GB | ~400 ms |
| large-v3-turbo | 809M | ~3 GB | Not benchmarked |

Both English-only (`.en`) and multilingual variants are supported. Models auto-download if not present locally.

### Quality (WER)

Lightning-SimulWhisper does not publish its own WER benchmarks. The underlying Simul-Whisper paper reports these streaming WER degradation numbers vs. offline Whisper (on LibriSpeech at 1-second chunk size):

| Model | Avg. WER Degradation (streaming vs. offline) |
|-------|----------------------------------------------|
| base | +7.68% absolute |
| small | +3.23% absolute |
| medium | +1.46% absolute (min 0.77%) |
| large-v2 | +2.34% absolute |

The medium model hits a sweet spot: comparable to large on clean speech with minimal streaming degradation.

### Speed (RTF on M-series)

The project claims ~15x decoder speedup (MLX vs. PyTorch) and ~18x encoder speedup (CoreML vs. PyTorch). On an M2 MacBook Pro, the medium and large-v3-turbo models run in real time -- the original SimulStreaming could barely manage the base model.

Concrete CoreML encoder latencies (per chunk):
- Without CoreML (MLX encoder): ~800-1000 ms
- With CoreML (Neural Engine): ~271 ms for medium

No formal RTF numbers are published, but the system is documented as real-time capable for medium on M2+.

### Distil Model Support

**Not explicitly supported.** The model list includes only standard OpenAI Whisper variants. The related project "Lightning Whisper MLX" (different project, same ecosystem) supports distil-small.en, distil-medium.en, distil-large-v2, and distil-large-v3, but Lightning-SimulWhisper's model loading code does not list these. The upstream SimulStreaming project mentions compatibility with "smaller distilled models" is possible but not tested.

### Custom / LoRA Models

**Not supported.** No fine-tuning, LoRA, or custom model loading mechanism is documented. The system loads standard Whisper weights converted to MLX format.

---

## 2. Speech-to-Speech (STS)

**No STS capability.** This is a pure speech-to-text (STT) engine. There is no speech synthesis, voice conversion, or speech-to-speech pipeline. It does support simultaneous translation (speech in language A -> text in language B) via Whisper's translate task, but output is always text.

---

## 3. Barge-in / Interruption

### Built-in AEC (Acoustic Echo Cancellation)

**None.** No echo cancellation is implemented. The system assumes clean microphone input.

### Duplex Audio

**No.** The system is unidirectional -- microphone input to text output. There is no simultaneous playback/capture coordination.

### Interrupt Hooks

**Not built-in.** The streaming architecture produces partial results continuously, which an external system could use to implement interruption logic, but Lightning-SimulWhisper itself has no interrupt/barge-in concept. The VAD silence detection (`--vad_silence_ms`, default 500 ms) could be used as a primitive signal, but it is not designed for barge-in.

---

## 4. Keyword / Wake Word

### Vocabulary Biasing

**Partial.** The `--static_init_prompt` parameter provides a non-scrolling context prompt that persists across chunks. This can bias transcription toward specific terminology (e.g., product names, technical terms), similar to how WhisperLiveKit uses static prompts for vocabulary hints.

### Init Prompt

**Yes.** Two prompt mechanisms:
- `--init_prompt`: Initial prompt in target language (scrolls out of context window)
- `--static_init_prompt`: Persistent prompt that never scrolls, useful for consistent terminology

### Confidence Scores

**Not exposed.** The Whisper decoder internally computes log probabilities, but Lightning-SimulWhisper does not surface per-token or per-word confidence scores in its output.

### Wake Word Detection

**None.** No dedicated wake word / keyword spotting mode.

---

## 5. TTS (Text-to-Speech)

**No TTS capability whatsoever.** This is a pure STT engine. No text-to-speech, no voice synthesis, no audio output generation.

---

## 6. Apple Silicon

### MLX / Metal / CoreML Support

This is the project's primary strength. The architecture is a hybrid:

1. **Mel spectrogram generation** -- MLX (runs on Metal GPU)
2. **Encoder** -- CoreML with Apple Neural Engine (ANE) acceleration (up to 18x speedup)
3. **Decoder** -- MLX with Metal GPU (up to 15x speedup)

CoreML compute unit options:
- `ALL` -- Use all available hardware (CPU + GPU + Neural Engine)
- `CPU_AND_NE` -- CPU + Neural Engine (recommended for power efficiency)
- `CPU_ONLY` -- CPU only (debugging)

### Memory Footprint

Not formally benchmarked. Based on Whisper model sizes and MLX overhead:
- tiny: ~400 MB
- base: ~500 MB
- medium: ~2.5 GB
- large-v3: ~5 GB

MLX supports optional memory logging via `MLX_MEMORY_LOG` environment variable.

### Thermal

CoreML Neural Engine acceleration significantly reduces thermal output:
- MLX encoder: ~15-20W power draw, fans usually active
- CoreML encoder: ~5-8W power draw, fans generally silent

The `CPU_AND_NE` compute unit setting is recommended for optimal power/thermal behavior.

---

## 7. Real-time Streaming

### Simultaneous Decoding

**Yes -- this is the core feature.** Uses the AlignAtt (Attention-Guided) simultaneous decoding policy from the Simul-Whisper paper. Unlike chunked approaches that wait for complete segments, AlignAtt monitors cross-attention alignment to decide when to emit tokens. Decoding stops when the attention peak approaches the audio boundary.

Key parameter: `--frame_threshold` (default: 25 frames / 500 ms) controls how close attention can get to the audio edge before stopping.

### Partial Results

**Yes.** The system emits partial transcription results as audio arrives. Tokens are output incrementally during processing of each audio chunk. Incomplete Unicode characters are buffered to prevent rendering artifacts.

### First-word Latency

Latency is generally 1-2x the chunk length:
- Most tokens appear after the current chunk (1-chunk latency)
- Some tokens are delayed to the next chunk (2-chunk latency)
- With a 1-second chunk: first words typically appear in 1-2 seconds
- CoreML first-inference cold start adds 2-3 seconds (model compilation), subsequent inferences are fast

### Protocol

The server mode (`simulstreaming_whisper_server.py`) delegates to `whisper_streaming`'s server infrastructure, which uses **raw TCP sockets** (not WebSocket). Audio is sent as raw PCM; transcription text is returned over the same TCP connection.

Example client connection:
```bash
arecord -f S16_LE -c1 -r 16000 -t raw -D default | nc localhost 43001
```

The `websockets` dependency is listed in requirements.txt, suggesting WebSocket support may exist or be planned, but the documented server uses TCP.

---

## 8. VAD (Voice Activity Detection)

### Built-in VAD

**Partially implemented.** The codebase includes:

- **Silero VAD Controller (VAC):** Uses the bundled Silero VAD model (in `silero_model/`) with configurable chunk sizes. Requires `torchaudio` dependency.
- **Silence detection:** `--vad_silence_ms` parameter (default: 500 ms) sets minimum silence duration before detecting end of speech.

However, the code contains a comment `"VAD not implemented"` in the `use_vad()` method of the main class, suggesting the VAD integration is incomplete or a placeholder. The Silero model files are present but the integration may not be fully wired up.

### Silence Detection

Configurable via `--vad_silence_ms` (default: 500 ms minimum silence duration).

---

## 9. Audio Input

### PCM Support

**Yes.** Expects 16 kHz, mono, 16-bit signed little-endian PCM (S16_LE). This is standard Whisper input format.

### Sample Rate

**16,000 Hz** (16 kHz), hardcoded per Whisper requirements.

### Gain Control

**Not built-in.** No automatic gain control (AGC) or manual gain adjustment. Input audio is processed as-is.

### Multi-device

**Not supported.** Uses PyAudio for microphone input with default device selection. No multi-device routing or device selection API.

### Audio Buffer Configuration

- `--audio_max_len`: Maximum audio buffer length (default: 30.0 seconds)
- `--audio_min_len`: Minimum audio before processing begins (default: 0.0 seconds)
- `--min_chunk_size`: Minimum chunk size for streaming (must be < `audio_max_len`)

---

## 10. Language

### Multi-language

**Yes.** Supports all languages that Whisper supports (~99 languages). Language is specified via `--language` / `--lan` parameter using ISO codes (en, de, cs, ko, etc.).

### Auto-detect

**Yes.** When no language is specified, Whisper's automatic language detection is used. A dedicated language identification module exists in the codebase.

### Translation

**Yes.** Supports Whisper's translate task (speech in any language -> English text). This is configurable via the `--task` parameter (transcribe vs. translate). The upstream SimulStreaming project has been extended with full translation support for simultaneous speech translation.

---

## 11. Diarization

**No speaker diarization.** The system produces a single transcript stream with no speaker identification, segmentation, or labeling. Would need to be combined with an external diarization tool (e.g., pyannote.audio) for speaker identification.

---

## 12. Transcription Quality

### Hallucination Filtering

**Partial -- via CIF truncation detection.** The CIF (Connectionist Intermediate Firing) model detects word boundaries and truncates incomplete/unreliable words at chunk edges. This addresses a key problem with streaming Whisper: hallucinated tokens at segment boundaries.

CIF model checkpoints are provided for tiny, base, small, and medium. **No CIF model for large-v3** -- the project notes this explicitly.

Configuration:
- `--cif_ckpt_path`: Path to CIF model checkpoint
- `--never_fire`: Override setting (default: False)

### Punctuation

**Yes.** Standard Whisper punctuation is preserved. The system uses Whisper's tokenizer which includes punctuation tokens.

### Timestamps

**Yes -- word-level timestamps.** The `timestamped_text()` method returns tuples of `(begin_time, end_time, word_text)` based on cross-attention alignment ("most attended frames"). Frame-to-second conversion uses 0.02s per frame. Non-decreasing timestamp enforcement is applied.

### Confidence Scores

**Not exposed** in the output API. Internal log probabilities exist in the decoder but are not surfaced.

### Unicode Handling

Robust handling of incomplete Unicode sequences. The `hide_incomplete_unicode()` method buffers partial multi-byte characters to prevent U+FFFD replacement character artifacts in streaming output.

---

## 13. Architecture

### Deployment Model

**Python script / subprocess.** Not a library with a clean API -- it is a collection of Python scripts designed to be run as processes:
- `simulstreaming_whisper.py` -- Main CLI for file/microphone transcription
- `simulstreaming_whisper_server.py` -- TCP server mode (thin wrapper around whisper_streaming server)

### WebSocket

**Not directly.** The server uses raw TCP via `whisper_streaming`'s server infrastructure. The `websockets` Python package is listed as a dependency but the primary server interface is TCP. No native WebSocket endpoint is documented.

### Multi-client

**Unknown / not documented.** The TCP server inherits behavior from `whisper_streaming`'s `main_server`, which does not document concurrent client handling. Likely single-client based on the architecture.

### Crash Isolation

**Process-level only.** Running as a separate process provides OS-level crash isolation. No internal watchdog, restart logic, or crash recovery is implemented.

### Module Structure

```
simul_whisper/
  __init__.py
  config.py              # AlignAttConfig and argument parsing
  coreml_encoder.py      # CoreML Neural Engine encoder
  eow_detection.py       # CIF end-of-word / truncation detection
  generation_progress.py # Token generation tracking
  simul_whisper.py       # Core simultaneous decoding engine
  mlx_whisper/           # MLX model implementations
whisper_streaming/       # Inherited from ufal/whisper_streaming
scripts/                 # CoreML model generation, testing
```

---

## 14. Reliability

### Crash Recovery

**None.** No automatic restart, health monitoring, or recovery mechanism. If the process crashes, it stays down.

### Preflight Validation

**Partial.** The CoreML encoder validates model file existence and provides helpful error messages with generation commands. Model downloads are automatic if weights are missing. But there is no comprehensive preflight check (audio devices, permissions, memory availability, etc.).

### Health Check

**None.** No health check endpoint, heartbeat, or liveness probe.

### Memory Leaks

**Unknown.** MLX memory logging is available via `MLX_MEMORY_LOG` environment variable, but no leak detection or long-running stability testing is documented. The 30-second `audio_max_len` buffer provides implicit memory bounding.

---

## 15. TTS Quality

**Not applicable.** Lightning-SimulWhisper has zero TTS capability. No voice synthesis, no audio output generation.

---

## 16. Project Health

| Metric | Value |
|--------|-------|
| **GitHub Stars** | 475 |
| **Forks** | 39 |
| **Contributors** | 3 (predict-woo, Gldkslfmsd, and one other) |
| **Total Commits** | 71 |
| **Open Issues** | 2 |
| **Last Commit** | February 9, 2026 |
| **First Commit** | ~July 2025 |
| **Releases** | None published |
| **License** | PolyForm Noncommercial 1.0.0 |
| **PyPI Package** | **None** -- install from source only |
| **Documentation** | README.md, COREML_QUICKSTART.md, USAGE_COREML.md |
| **Tests** | `tests/` directory exists |
| **CI/CD** | `.github/` directory exists (details unknown) |

### License Warning

The **PolyForm Noncommercial License 1.0.0** restricts usage to noncommercial purposes only (personal research, education, nonprofit). Commercial use requires separate licensing from the altalt-org team. This is a significant constraint compared to MIT/Apache-licensed alternatives.

**Note:** Issue #2 on the repo ("SimulStreaming now under MIT") suggests the upstream SimulStreaming project moved to MIT, but Lightning-SimulWhisper itself remains under PolyForm Noncommercial.

### Open Issues

1. **"missing transcript for streaming audio"** (#4, Dec 2025) -- Transcription gaps during streaming
2. **"SimulStreaming now under MIT"** (#2, Oct 2025) -- License discussion

---

## 17. Dependencies

### Install Complexity

**Medium-high.** No PyPI package; must clone from GitHub and install from source.

```bash
git clone https://github.com/altalt-org/Lightning-SimulWhisper.git
cd Lightning-SimulWhisper
pip install -r requirements.txt

# For CoreML acceleration (recommended):
pip install coremltools ane_transformers

# Generate CoreML encoder models:
git submodule update --init  # whisper.cpp
./scripts/generate_coreml_encoder.sh medium
```

CoreML model generation requires `whisper.cpp` as a git submodule and additional build steps.

### Core Dependencies

| Package | Purpose | Weight |
|---------|---------|--------|
| `mlx` | Apple ML framework | Light (~50 MB) |
| `torch` | PyTorch (for Silero VAD) | Heavy (~2 GB) |
| `torchaudio` | Audio processing for VAD | Medium (~200 MB) |
| `librosa` | Audio analysis | Medium (~100 MB) |
| `pyaudio` | Microphone input | Light (requires PortAudio) |
| `websockets` | WebSocket protocol | Light |
| `onnxruntime` | ONNX inference | Medium (~200 MB) |
| `tiktoken` | Tokenization | Light |
| `tqdm` | Progress bars | Light |
| `triton` | GPU compiler (>=2.0.0,<3, Linux x86_64 only) | N/A on macOS |
| `coremltools` | CoreML model tools (optional) | Medium (~150 MB) |
| `ane_transformers` | Neural Engine transforms (optional) | Light |

### Disk Footprint

- Dependencies: ~3-4 GB (dominated by PyTorch)
- Whisper models: 75 MB (tiny) to 3 GB (large-v3)
- CoreML encoder models: ~200 MB - 1.5 GB per model size
- whisper.cpp submodule: ~500 MB
- **Total estimated: 5-10 GB** depending on model selection

**Note:** The README states "zero pytorch dependencies" but `torch` and `torchaudio` are listed in requirements.txt. The claim refers to the core inference path (MLX replaces PyTorch for Whisper), but PyTorch is still required for Silero VAD. The docs note that removing `torchaudio` from requirements disables Silero VAD controller functionality.

### Offline Capability

**Fully offline after initial setup.** Models must be downloaded once (auto-download on first use). CoreML models must be generated locally. After that, no network access is required for inference.

---

## 18. Privacy

### Fully Local

**Yes.** All audio processing happens on-device. No audio data leaves the machine. The project description emphasizes local-only processing.

### Telemetry

**None detected.** No telemetry, analytics, or phone-home code is present in the codebase. The project is open source and can be audited.

### Data Retention

**None.** No audio or transcript logging by default. Data exists only in memory during processing.

### Network Access

Only required for initial model download. Zero network calls during inference.

---

## Summary: Fit for Claude Talk

### Strengths

- **Best-in-class Apple Silicon optimization** -- CoreML + MLX hybrid is purpose-built for M-series
- **True simultaneous streaming** -- AlignAtt policy emits tokens as audio arrives, not after chunks complete
- **Low power consumption** -- Neural Engine at ~5-8W vs. 15-20W for GPU-only
- **Word-level timestamps** -- From cross-attention alignment
- **Truncation detection** -- CIF model reduces streaming hallucinations
- **Translation support** -- Speech-to-English text for any input language
- **Fully local / private** -- No data leaves the device

### Weaknesses

- **No TTS** -- Claude Talk needs a separate TTS solution regardless
- **No WebSocket server** -- TCP-only server; would need a WebSocket wrapper for Claude Talk's architecture
- **No barge-in / AEC** -- Would need external interrupt logic
- **No diarization** -- Single speaker only
- **No confidence scores** -- Cannot filter low-confidence transcriptions
- **PolyForm Noncommercial license** -- Restricts commercial use
- **PyTorch still required** -- "Zero PyTorch" claim is misleading; torch needed for Silero VAD (~2 GB dependency)
- **No PyPI package** -- Source-only install with multi-step CoreML setup
- **VAD appears incomplete** -- Code contains "VAD not implemented" comment
- **Small community** -- 3 contributors, 71 commits, minimal HN engagement
- **Open bug for streaming gaps** -- Issue #4 "missing transcript for streaming audio" is unresolved
- **No distil model support** -- Cannot use lighter distilled variants
- **No crash recovery / health checks** -- Process dies silently

### Comparison with WhisperLiveKit (Current Claude Talk Engine)

| Feature | Lightning-SimulWhisper | WhisperLiveKit |
|---------|----------------------|----------------|
| Streaming approach | AlignAtt simultaneous | Chunked + local agreement |
| Protocol | TCP | WebSocket + FastAPI |
| Apple Silicon | CoreML + MLX (native) | MLX (via faster-whisper) |
| Neural Engine | Yes (CoreML) | No |
| First-word latency | 1-2x chunk length | Chunk length + processing |
| VAD | Incomplete (Silero placeholder) | Silero VAD (integrated) |
| TTS | None | None |
| WebSocket | No (TCP only) | Yes (native) |
| License | PolyForm Noncommercial | MIT |
| PyPI | No | Yes |
| Distil models | No | Yes |
| Multi-client | Unknown | Yes |
| Barge-in hooks | No | No (external) |

### Verdict

Lightning-SimulWhisper offers genuinely superior Apple Silicon optimization (CoreML Neural Engine is a real differentiator for power and thermal) and a more sophisticated streaming strategy (AlignAtt vs. chunked). However, for Claude Talk integration, the lack of WebSocket support, the noncommercial license, incomplete VAD, and unresolved streaming bugs make it a riskier choice than WhisperLiveKit today. The small contributor base (3 people) and the fact that it is a side-release from a commercial app ("Alt") raise sustainability questions.

**Recommendation:** Monitor for maturity. If the license changes (upstream SimulStreaming is now MIT) and WebSocket support is added, this could become a compelling upgrade path for the encoding/decoding layer while keeping WhisperLiveKit's server infrastructure.

---

## Sources

- [Lightning-SimulWhisper GitHub Repository](https://github.com/altalt-org/Lightning-SimulWhisper)
- [Simul-Whisper Paper (arXiv:2406.10052)](https://arxiv.org/abs/2406.10052)
- [SimulStreaming (UFAL)](https://github.com/ufal/SimulStreaming)
- [Whisper Streaming (UFAL)](https://github.com/ufal/whisper_streaming)
- [Hacker News Discussion](https://news.ycombinator.com/item?id=45620534)
- [CoreML Quickstart Guide](https://github.com/altalt-org/Lightning-SimulWhisper/blob/main/COREML_QUICKSTART.md)
- [CoreML Usage Guide](https://github.com/altalt-org/Lightning-SimulWhisper/blob/main/USAGE_COREML.md)
- [Whisper Model Memory Requirements Discussion](https://github.com/openai/whisper/discussions/5)
- [Whisper Performance on Apple Silicon Benchmarks](https://www.voicci.com/blog/apple-silicon-whisper-performance.html)

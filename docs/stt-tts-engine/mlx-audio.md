# MLX-Audio Evaluation Report

**Project:** [Blaizzy/mlx-audio](https://github.com/Blaizzy/mlx-audio)
**Version evaluated:** 0.3.1 (released January 29, 2026)
**Evaluation date:** 2026-02-18

MLX-Audio is a combined TTS, STT, and STS (speech-to-speech) library built on Apple's MLX framework. Unlike single-purpose tools like WhisperLiveKit (STT only) or macOS `say` (TTS only), it aims to be a unified audio pipeline for Apple Silicon.

---

## 1. Models

### STT Models (10 implementations)

| Model | Size | Languages | Notable Features |
|-------|------|-----------|-----------------|
| **Whisper** (OpenAI) | Various (tiny to large-v3-turbo) | 99+ | Most battle-tested; AlignAtt streaming added in v0.2.10 |
| **Qwen3-ASR** (Alibaba) | 0.6B / 1.7B | ZH, EN, JA, KO + more | Best quantization story; 4-bit is 4.68x faster |
| **Qwen3-ForcedAligner** | 0.6B | ZH, EN, JA, KO + more | Word-level timestamp alignment |
| **Parakeet** (NVIDIA) | 0.6B | EN (v2), 25 EU languages (v3) | Word-level timestamps, streaming |
| **Voxtral Realtime** (Mistral) | 4B | Multiple | Streaming-native, configurable latency (240ms-2.4s) |
| **Voxtral** (Mistral) | 3B | Multiple | Batch transcription |
| **VibeVoice-ASR** (Microsoft) | 9B | Multiple | Diarization + timestamps, up to 60 min audio |
| **GLM-ASR** | Unknown | Unknown | Added v0.2.9 |
| **LASR CTC** | Unknown | Unknown | CTC-based architecture |
| **Wav2Vec** | Unknown | Unknown | Facebook's self-supervised model |

### Quality (WER) -- Qwen3-ASR benchmarks on M4 Pro

| Model | LibriSpeech test-clean | test-other | RTF |
|-------|----------------------|------------|-----|
| 0.6B fp16 | **2.29%** WER | 4.20% WER | 0.0957 |
| 0.6B 4-bit | 2.72% WER | -- | 0.02 (4.68x faster) |
| 1.7B fp16 | **1.99%** WER | 3.45% WER | 0.2708 |

MLX vs PyTorch parity: 67% of samples produce identical text output; MLX is 0.81 percentage points better on aggregate multilingual WER.

### Speed (RTF on M-series)

| Model | Hardware | Short clip | 10s clip | RTF |
|-------|----------|-----------|----------|-----|
| Qwen3-ASR 0.6B fp16 | M4 Pro | 0.46s | 0.83s | 0.08x |
| Qwen3-ASR 0.6B 4-bit | M4 Pro | 0.13s | 0.18s | 0.02x |
| Whisper large-v3-turbo | M4 Max | -- | -- | ~55x faster than real-time |
| Whisper large-v3 | M4 Max | -- | -- | ~24x faster than real-time |

### Quantization & Custom Models

- Full quantization support: 3-bit, 4-bit, 6-bit, 8-bit, fp16, bf16
- Models hosted on HuggingFace (`mlx-community/` org) with `mlx_audio.convert` for custom conversions
- **LoRA/fine-tuning:** Not documented in mlx-audio itself. The underlying `mlx-lm` dependency supports LoRA, but mlx-audio does not expose fine-tuning APIs for audio models.

### TTS Models (16 implementations)

| Model | Size | Languages | Notable Features |
|-------|------|-----------|-----------------|
| **Kokoro** | 82M | EN, JA, ZH, FR, ES, IT, PT, HI | 54 voice presets, speed control |
| **Qwen3-TTS** | 0.6B-1.7B | ZH, EN, JA, KO + more | Voice design, emotion control, cloning |
| **CSM** (Sesame) | 1B | EN | Voice cloning from reference audio |
| **Dia** | 1.6B | EN | Dialogue-focused |
| **OuteTTS** | 0.6B | EN | Efficient |
| **Spark** | 0.5B | EN, ZH | -- |
| **Chatterbox** | Unknown | 16 languages | Speaker embedding, audio streaming |
| **Soprano** | 80M | EN | Lightweight |
| **Marvis** | 250M | EN (+ planned multilingual) | Streaming-native, 414MB quantized |
| **Bark** | Unknown | Unknown | -- |
| **IndexTTS** | Unknown | Unknown | Added v0.2.4 |
| **Pocket TTS** | Unknown | Unknown | Added v0.3.0rc1 |
| **Sesame** | Unknown | Unknown | RoPE caching, batched vocoding |
| **VoxCPM** | Unknown | Unknown | Voice cloning support |
| **Llama** | Unknown | Unknown | LLM-based TTS |
| **VibeVoice (TTS)** | Unknown | Unknown | -- |

---

## 2. Speech-to-Speech (STS)

**Yes, mlx-audio has STS capability.** This is a differentiator -- most competitors do not.

| Model | Description | Use Case |
|-------|-------------|----------|
| **Liquid2.5-Audio** (LFM) | 1.5B unified model | STS, TTS, STT in one model |
| **SAM-Audio** | Text-guided source separation | Extract specific sounds from audio |
| **MossFormer2 SE** | Speech enhancement | Noise removal / cleanup |

Additionally, the project includes a `voice_pipeline.py` in the STS module, suggesting a pipeline abstraction for chaining STT -> processing -> TTS.

**Relevance to claude-talk:** Could potentially replace the current macOS `say` + WhisperLiveKit split with a single library. However, the STS models are newer and less battle-tested than the individual STT/TTS components.

---

## 3. Barge-in / Interruption

**No built-in barge-in or interruption support.**

- No AEC (acoustic echo cancellation) built in
- No duplex audio processing (simultaneous mic input + speaker output)
- No interrupt hooks or callbacks
- Voxtral Realtime supports full-duplex streaming-input/streaming-output at the model level (80ms audio chunks), but mlx-audio does not expose this as a barge-in mechanism
- The STS optional dependency includes `webrtcvad`, which could theoretically be used for detecting speech during playback, but this is not wired up as an interruption system

**Verdict:** You would need to build barge-in yourself, similar to the current claude-talk architecture. The library provides building blocks (VAD, streaming STT) but not the orchestration.

---

## 4. Keyword / Wake Word

**No built-in wake word or keyword detection.**

- VibeVoice-ASR supports a `context` parameter for hotwords/vocabulary biasing: `context="MLX, Apple Silicon, PyTorch"` -- this biases the model toward recognizing these terms but is not wake-word detection
- Whisper supports `initial_prompt` for vocabulary biasing (standard Whisper feature)
- No confidence scores exposed in most STT model outputs
- No dedicated keyword spotting model

**For wake word detection**, you would need a separate library like Porcupine or OpenWakeWord.

---

## 5. TTS

**Yes, TTS is a core capability** -- 16 model implementations.

### Key TTS Features

- **Streaming TTS:** Supported via `--stream` flag and programmatic API. Marvis and Chatterbox are streaming-native.
- **Parallel streams:** Unknown / not documented. The OpenAI-compatible API serves one request at a time per model instance.
- **Voice cloning:** CSM, Qwen3-TTS, VoxCPM support cloning from reference audio (~10s sample)
- **Speed control:** Kokoro supports `speed` parameter (1.0 = normal)
- **54 voice presets** in Kokoro alone across 8 languages
- **Emotion control:** Qwen3-TTS supports emotion-aware synthesis

### TTS Code Example

```python
from mlx_audio.tts.utils import load_model

model = load_model("mlx-community/Kokoro-82M-bf16")
for result in model.generate(
    text="Hello from MLX-Audio!",
    voice="af_heart",
    speed=1.0,
    lang_code="a"
):
    audio = result.audio  # mx.array, ready for playback
```

### CLI TTS

```bash
mlx_audio.tts.generate \
  --model mlx-community/Kokoro-82M-bf16 \
  --text "Hello!" \
  --voice af_heart \
  --speed 1.2 \
  --lang_code a \
  --play
```

---

## 6. Apple Silicon

**This is the project's raison d'etre.** Apple Silicon is the only supported platform.

| Aspect | Details |
|--------|---------|
| **MLX framework** | Core dependency (mlx >= 0.25.2), uses Metal GPU acceleration |
| **Metal/GPU** | All inference runs on Metal GPU via MLX |
| **CoreML** | Not used directly; MLX has its own Metal backend |
| **Supported chips** | M1, M2, M3, M4 (all variants: base, Pro, Max, Ultra) |
| **Intel Macs** | Not supported |
| **Linux/Windows** | Not supported |
| **Memory footprint** | Qwen3-ASR 0.6B: ~1.2 GB; 1.7B: ~3.4 GB; Marvis quantized: 414 MB |
| **Quantization** | 3/4/6/8-bit reduces memory proportionally |
| **Thermal** | Unknown / not documented. MLX is generally more power-efficient than PyTorch on Apple Silicon |
| **Unified memory** | Models sit in unified memory, shared between CPU and GPU -- no copies needed |

### Swift Package

A separate [mlx-audio-swift](https://github.com/Blaizzy/mlx-audio-swift) package exists for native iOS/macOS integration, making this viable for iOS apps as well.

---

## 7. Real-time Streaming

### STT Streaming

| Model | Streaming Support | Mechanism | Latency Control |
|-------|------------------|-----------|-----------------|
| Whisper | Yes (AlignAtt) | Chunk-based SimulStreaming | -- |
| Voxtral Realtime | Yes (native) | 80ms audio chunk incremental | `transcription_delay_ms` (240ms-2.4s) |
| Parakeet | Yes | `stream=True` parameter | -- |
| VibeVoice-ASR | Yes | `stream_transcribe()` method | -- |
| Qwen3-ASR | Unknown | -- | -- |

### TTS Streaming

- Marvis TTS: Streaming-native, processes text chunks as they arrive
- Chatterbox: Audio streaming + chunking
- General: `--stream` CLI flag available

### Protocol

- **REST API** (FastAPI + uvicorn): OpenAI-compatible endpoints
- **No native WebSocket support** in the built-in server
- First-word latency: Not formally benchmarked. ChipChat (a separate project using MLX components) achieves ~920ms end-to-end for ASR+LLM+TTS pipeline on M2 Ultra.

### Partial Results

Voxtral Realtime provides true incremental partial results (each 80ms chunk yields updated text). Other models return chunk-level results when streaming.

---

## 8. VAD (Voice Activity Detection)

**Yes, mlx-audio includes VAD.**

| Component | Details |
|-----------|---------|
| **Sortformer v1** | NVIDIA's end-to-end diarization, up to 4 speakers |
| **Sortformer v2.1** | Streaming variant with AOSC compression |
| **webrtcvad** | Listed as STS dependency; available for basic VAD |
| **Built-in silence detection** | Unknown / not documented as a standalone feature |
| **Silero VAD** | Not included (would need separate installation) |

The VAD module (`mlx_audio/vad/`) contains Sortformer models specifically, which are primarily diarization models that include VAD as a byproduct. For simple speech/no-speech detection, you would likely use `webrtcvad` (included in the `[sts]` extras) or bring your own Silero VAD.

---

## 9. Audio Input

| Aspect | Details |
|--------|---------|
| **Audio loading** | Uses `miniaudio` + `ffmpeg` (refactored in v0.3.0rc1, replacing `soundfile`) |
| **PCM support** | WAV natively; MP3/FLAC via ffmpeg |
| **Sample rate** | Model-dependent; librosa handles resampling |
| **Gain control** | `pyloudnorm` dependency for loudness normalization |
| **Multi-device** | `sounddevice` dependency supports device selection |
| **Live microphone** | Not built into the library itself; `sounddevice` can be used for capture |
| **Long-form audio** | VibeVoice-ASR handles up to 60 minutes |

**Note:** mlx-audio is primarily a file-based processing library. Real-time microphone capture requires additional integration (e.g., using `sounddevice` to capture audio and feed it to the models).

---

## 10. Language Support

### STT Language Coverage

| Model | Languages |
|-------|-----------|
| Whisper | 99+ languages |
| Parakeet v3 | 25 European languages |
| Qwen3-ASR | ZH, EN, JA, KO + more |
| Voxtral | Multiple (unspecified count) |
| VibeVoice-ASR | Multiple (unspecified count) |

### TTS Language Coverage

| Model | Languages |
|-------|-----------|
| Kokoro | EN, JA, ZH, FR, ES, IT, PT, HI (8 languages) |
| Qwen3-TTS | ZH, EN, JA, KO + more |
| Chatterbox | 16 languages (EN, ES, FR, DE, IT, PT, PL, TR, RU, NL, CS, AR, ZH, JA, HU, KO) |
| Most others | English only |

### Auto-detection

- Whisper has built-in language auto-detection
- Most other models require explicit language specification

### Translation

- Whisper supports translation (any language to English)
- Other models: Unknown / not documented

---

## 11. Diarization

**Yes, mlx-audio has built-in diarization.**

| Model | Capability |
|-------|-----------|
| **VibeVoice-ASR** (Microsoft 9B) | Speaker identification with timestamps, JSON output with speaker IDs |
| **Sortformer v1** (NVIDIA) | End-to-end diarization, up to 4 concurrent speakers |
| **Sortformer v2.1** (NVIDIA) | Streaming diarization with AOSC compression |

### VibeVoice-ASR Diarization Example

```python
from mlx_audio.stt.utils import load
model = load("mlx-community/VibeVoice-ASR-bf16")
result = model.generate(
    audio="meeting.wav",
    max_tokens=8192,
    temperature=0.0
)
print(result.text)  # JSON with speaker IDs + timestamps
```

This is a significant advantage -- diarization is typically a separate, complex pipeline.

---

## 12. Transcription Quality

| Feature | Support |
|---------|---------|
| **Hallucination filtering** | Unknown / not documented. Standard Whisper temperature fallback applies. |
| **Punctuation** | Model-dependent; Whisper and Qwen3-ASR include punctuation |
| **Word-level timestamps** | Qwen3-ForcedAligner (dedicated model), Parakeet, VibeVoice-ASR |
| **Sentence-level timestamps** | Parakeet (`result.sentences`), VibeVoice-ASR |
| **Confidence scores** | Unknown / not documented for most models |
| **Hotword biasing** | VibeVoice-ASR `context` parameter; Whisper `initial_prompt` |

### Forced Alignment Example

```python
from mlx_audio.stt import load
aligner = load("mlx-community/Qwen3-ForcedAligner-0.6B-8bit")
result = aligner.generate(
    "audio.wav",
    text="I have a dream",
    language="English"
)
for item in result:
    print(f"[{item.start_time:.2f}s - {item.end_time:.2f}s] {item.text}")
```

---

## 13. Architecture

| Aspect | Details |
|--------|---------|
| **Type** | Python library with optional REST server |
| **Server** | FastAPI + uvicorn, started via `mlx_audio.server` |
| **Protocol** | HTTP REST (OpenAI-compatible); **no WebSocket** |
| **Multi-client** | FastAPI supports concurrent HTTP requests, but model inference is single-threaded on GPU |
| **Crash isolation** | Library runs in-process; server runs as a separate process |
| **Subprocess support** | No built-in subprocess isolation; models load into the calling process |
| **Modular imports** | `pip install mlx-audio[stt]` / `[tts]` / `[sts]` -- load only what you need |

### OpenAI-Compatible API Endpoints

```
POST /v1/audio/speech          -- TTS (text -> audio)
POST /v1/audio/transcriptions  -- STT (audio -> text)
GET  /v1/models                -- List loaded models
POST /v1/models                -- Load a model
DELETE /v1/models              -- Unload a model
```

### Server Startup

```bash
mlx_audio.server --host 0.0.0.0 --port 8000 --verbose
```

---

## 14. Reliability

| Aspect | Details |
|--------|---------|
| **Crash recovery** | Unknown / not documented. No auto-restart mechanism. |
| **Preflight validation** | Unknown / not documented |
| **Health check endpoint** | Unknown / not documented (standard FastAPI, but no `/health` route documented) |
| **Memory leaks** | v0.3.0 included "Metal kernel crash fix and memory optimization for long audio" for VibeVoice, suggesting memory issues were found and addressed |
| **Known issues** | 57 open issues; streaming bugs reported (VibeVoice streaming doesn't work -- issue #482); Qwen3-TTS audio dropout (issue #464); partial transcripts from Qwen3-ASR (issue #459) |
| **Test suite** | `pytest` + `pytest-asyncio` in dev dependencies; `tests/` directories in each module |

### Known Reliability Concerns

- Streaming for VibeVoice-ASR is reported broken (issue #482)
- Qwen3-TTS can produce audio with missing middle portions (issue #464)
- PyPI package was missing tiktoken assets, causing model failures (issue #479)
- Installation can fail with Python 3.13 and uv (issue #452)
- numpy ABI incompatibility reported with uvx/uv (issue #420)

---

## 15. TTS Quality

| Aspect | Details |
|--------|---------|
| **Voices** | 54 presets in Kokoro alone; voice cloning in CSM, Qwen3-TTS, VoxCPM |
| **Voice quality** | Kokoro: "fast, high-quality"; CSM voice cloning is stochastic (quality varies between runs) |
| **Latency** | Kokoro 82M is very fast (small model). Marvis streaming provides near-real-time. No formal latency benchmarks published. |
| **Streaming TTS** | Supported via `--stream` flag; Marvis and Chatterbox are streaming-native |
| **Speed control** | Kokoro `speed` parameter (e.g., 1.2 for faster) |
| **Emotion** | Qwen3-TTS supports emotion control |
| **Naturalness** | Voice cloning quality "sometimes sounds exactly like the sample, other times produces weird background noise or slamming sounds" (per user reports) |

### Voice Cloning Example

```bash
mlx_audio.tts.generate \
  --model mlx-community/csm-1b \
  --text "Hello from Sesame." \
  --ref_audio ./reference_voice.wav \
  --play
```

Recommended: trim reference audio to ~10 seconds, use temperature 0.4, top_p 0.9, top_k 50.

---

## 16. Project Health

| Metric | Value |
|--------|-------|
| **GitHub stars** | ~6,000 |
| **Forks** | ~444 |
| **Contributors** | 33 |
| **Total commits** | 328+ |
| **Releases** | 16 (v0.1.0 through v0.3.1) |
| **Open issues** | 57 |
| **Open PRs** | 23 |
| **License** | MIT |
| **Last release** | v0.3.1 -- January 29, 2026 |
| **Release cadence** | Very active; multiple releases per month in late 2025 / early 2026 |
| **Primary author** | Prince Canuma (Blaizzy) |
| **Documentation** | README-driven; model-specific READMEs; no dedicated docs site |
| **CI/CD** | GitHub Actions for publishing and testing |

**Assessment:** Very actively maintained, rapid feature additions, but a solo-maintainer-driven project with many open issues. The breadth of model support (26+ models) is impressive but raises questions about maintenance depth per model.

---

## 17. Dependencies

### Core Dependencies (11 packages)

```
mlx >= 0.25.2
mlx-lm == 0.30.5
transformers == 5.0.0rc3
numpy >= 1.26.4
numba >= 0.60.0
huggingface_hub >= 0.27.0
librosa == 0.11.0
sounddevice == 0.5.3
miniaudio >= 1.61
pyloudnorm >= 0.2.0
tqdm >= 4.67.1
```

### External Requirements

- **ffmpeg** (for MP3/FLAC; WAV works without it)
- **Python >= 3.10** (enforced)
- **Apple Silicon Mac** (M1+)

### Install Complexity

Moderate. The pinned `transformers == 5.0.0rc3` (a release candidate) is concerning for stability. `mlx-lm == 0.30.5` is also pinned tightly. Lazy imports mitigate startup time.

### Disk Footprint

| Configuration | Estimate |
|---------------|----------|
| Package only (wheel) | ~783 KB |
| Base + deps | ~500 MB |
| Base + STT deps | ~800 MB |
| Base + TTS deps | ~1.2 GB |
| All features | ~1.5 GB |
| + Models (varies) | +200 MB to +18 GB per model |

### Offline Operation

Models must be downloaded from HuggingFace on first use. Once cached locally (`~/.cache/huggingface/`), the library works fully offline. No runtime network calls for inference.

---

## 18. Privacy

| Aspect | Details |
|--------|---------|
| **Fully local** | Yes. All inference runs on-device via MLX/Metal. No cloud calls. |
| **Telemetry** | None documented. Open-source codebase can be audited. |
| **Network calls** | Only for model downloads from HuggingFace Hub (first use only) |
| **Data transmission** | None. Audio never leaves the device during processing. |
| **Model source** | HuggingFace `mlx-community` organization; open weights |
| **Auditability** | MIT license; full source available |

**Verdict:** Excellent privacy posture. Equivalent to WhisperLiveKit in this regard -- fully local, no telemetry, open source.

---

## Summary: Relevance to claude-talk

### Advantages over current WhisperLiveKit + macOS `say` stack

1. **Unified library** -- one dependency for both STT and TTS instead of two separate systems
2. **Much better TTS** -- 16 models with voice cloning, emotion control, streaming vs. macOS `say`
3. **Model diversity** -- can swap between Whisper, Qwen3-ASR, Parakeet, Voxtral without changing code
4. **Diarization built in** -- useful if multi-speaker scenarios arise
5. **Quantization support** -- run larger models on constrained hardware
6. **OpenAI-compatible API** -- drop-in for any tool expecting OpenAI audio endpoints

### Disadvantages / Gaps

1. **No WebSocket support** -- claude-talk's current architecture uses WebSocket via WhisperLiveKit. mlx-audio only offers REST.
2. **No barge-in** -- would still need custom orchestration for interruption
3. **No live microphone pipeline** -- file-based processing; real-time mic requires external integration
4. **No VAD-driven streaming** -- unlike WhisperLiveKit which streams from mic with VAD, mlx-audio processes files/chunks
5. **Reliability concerns** -- streaming bugs (VibeVoice #482), audio dropout (#464), partial transcripts (#459)
6. **Pinned pre-release dependency** -- `transformers == 5.0.0rc3` is a release candidate
7. **Solo maintainer risk** -- impressive velocity but bus-factor of ~1
8. **No wake word** -- same as current stack

### Bottom Line

MLX-Audio is the most feature-rich audio library for Apple Silicon, but it is primarily a **batch/file processing library with a REST API**, not a **real-time streaming pipeline**. For claude-talk's use case (live microphone -> real-time STT -> Claude -> streaming TTS -> speaker), the current WhisperLiveKit approach provides better real-time characteristics. However, mlx-audio's TTS capabilities are vastly superior to macOS `say` and could be worth integrating as a TTS replacement while keeping WhisperLiveKit for STT.

A hybrid approach -- WhisperLiveKit for real-time STT + mlx-audio Kokoro/Marvis for TTS -- could give the best of both worlds.

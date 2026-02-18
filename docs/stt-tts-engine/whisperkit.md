# WhisperKit -- Evaluation Report

> **Engine:** [WhisperKit](https://github.com/argmaxinc/WhisperKit) by Argmax, Inc.
> **Type:** Speech-to-Text (STT) only
> **Primary language:** Swift (with Python tooling via [whisperkittools](https://github.com/argmaxinc/whisperkittools))
> **License:** MIT
> **Last evaluated:** 2026-02-18

---

## Summary

WhisperKit is a Swift-native, on-device speech recognition framework that deploys OpenAI Whisper models optimized for Apple Silicon via CoreML and the Apple Neural Engine (ANE). It is purpose-built for iOS and macOS, providing real-time streaming transcription, word-level timestamps, VAD, and an OpenAI-compatible local HTTP server. WhisperKit is **STT only** -- it has no TTS or speech-to-speech capability.

---

## 1. Models

### Sizes and Variants

WhisperKit provides **32 pre-converted CoreML model variants** on [HuggingFace](https://huggingface.co/argmaxinc/whisperkit-coreml), covering the full Whisper family:

| Model | Multilingual | English-only | Quantized | Turbo |
|-------|:---:|:---:|:---:|:---:|
| tiny | Yes | Yes (.en) | -- | -- |
| base | Yes | Yes (.en) | -- | -- |
| small | Yes | Yes (.en) | Yes (~216-217 MB) | -- |
| medium | Yes | Yes (.en) | -- | -- |
| large-v2 | Yes | -- | Yes (~949 MB) | Yes (+ quantized ~955 MB) |
| large-v3 | Yes | -- | Yes (~947 MB) | Yes (+ quantized ~954 MB) |
| large-v3-v20240930 | Yes | -- | Yes (~547-626 MB) | Yes (+ quantized ~632 MB) |

### Distil-Whisper Support

Yes. Four distil variants available:
- `distil-whisper_distil-large-v3` (full, ~1510 MB)
- `distil-whisper_distil-large-v3_594MB` (quantized)
- `distil-whisper_distil-large-v3_turbo`
- `distil-whisper_distil-large-v3_turbo_600MB` (quantized turbo)

### Quality (WER)

From the [ICML 2025 paper](https://arxiv.org/html/2507.10860v1) and Argmax benchmarks:

| Model / Config | Dataset | WER |
|---|---|---|
| large-v3 (CoreML) | LibriSpeech test.clean | 2.44% |
| large-v3 Turbo | LibriSpeech test.clean | 2.41% |
| Confirmed stream (large-v3 Turbo) | LibriSpeech test.clean | 2.0% |
| Streaming encoder (d750 distill) | LibriSpeech test.clean | +0.32% vs original |
| OD-MBP quantized | Various | +0.03% to +0.37% WER vs full |
| small.en | Earnings22 (long-form) | 12.8% |

Benchmark results are also published to [whisperkit-evals on HuggingFace](https://huggingface.co/datasets/argmaxinc/whisperkit-evals), generated automatically on a cluster of Apple Silicon Macs via GitHub Actions CI.

### Speed (RTF on M-series)

From the ICML 2025 paper (M3 Max, Neural Engine):
- **Text Decoder forward pass:** 4.6 ms (45% improvement via stateful models, down from 8.4 ms)
- **Hypothesis text latency:** ~0.45s mean per-word
- **Confirmed text latency:** ~1.7s mean per-word
- **Streaming encoder latency:** 218 ms (down from 612 ms, 65% improvement via block-diagonal attention)

From Argmax blog (M4 Mac mini, Earnings22):
- **WhisperKit small.en speed factor:** 35x real-time
- **Argmax Pro SDK speed factor:** 359x real-time

### Custom / LoRA / Fine-tuned Models

Yes. The [whisperkittools](https://github.com/argmaxinc/whisperkittools) Python package supports:
- Converting any PyTorch Whisper model (including LoRA fine-tuned) to CoreML format
- Publishing custom models to HuggingFace
- Loading custom models via `WhisperKitConfig(modelRepo: "username/your-model-repo")`

```python
# Generate CoreML model from fine-tuned Whisper
whisperkit-generate-model --model-version <model-version> --output-dir <output-dir>
```

```swift
// Load custom model in Swift
let config = WhisperKitConfig(
    model: "large-v3",
    modelRepo: "username/your-fine-tuned-repo"
)
let pipe = try await WhisperKit(config)
```

---

## 2. Speech-to-Speech

**No.** WhisperKit is purely STT. No speech-to-speech, voice conversion, or audio generation capability. You would need to pair it with a separate TTS engine (e.g., macOS `say`, Bark, Coqui, etc.) for a full voice pipeline.

---

## 3. Barge-in / Interruption

**No built-in support.**

- No acoustic echo cancellation (AEC)
- No full-duplex audio handling
- No interrupt hooks or barge-in detection
- WhisperKit is a speech recognition engine, not an audio conversation framework

Barge-in would need to be implemented at the application level by monitoring VAD state and interrupting TTS playback externally. The streaming API with partial results could help detect when a user starts speaking, but there is no built-in mechanism for this.

---

## 4. Keyword / Wake Word

**Partial support via Whisper's prompt mechanism.**

- WhisperKit supports the `prompt` parameter in both the Swift API and the local server API, which can bias the model toward recognizing specific vocabulary, names, or jargon
- No dedicated keyword spotting or wake word detection
- No vocabulary biasing beyond the prompt mechanism
- Confidence scores available via `logprobs` parameter in the server API (token-level log probabilities)
- No `no_speech_prob` or per-segment confidence exposed at the API level beyond logprobs

For dedicated wake word detection, a separate engine like Picovoice Porcupine would be needed.

```swift
// Bias toward specific vocabulary via prompt
let options = DecodingOptions(promptTokens: tokenizer.encode(text: "Claude Talk, WhisperKit"))
```

---

## 5. TTS

**None.** WhisperKit is STT only. No text-to-speech capability whatsoever.

Argmax has no TTS product. For a full voice pipeline, pair with a separate TTS solution.

---

## 6. Apple Silicon

**Best-in-class Apple Silicon support.** This is WhisperKit's primary differentiator.

| Feature | Status |
|---|---|
| CoreML | Yes -- primary inference engine |
| Apple Neural Engine (ANE) | Yes -- native acceleration, near-peak hardware utilization |
| Metal GPU | Via CoreML backend |
| MLX | Not directly (whisperkittools supports MLX pipeline for evaluation, but WhisperKit itself uses CoreML) |
| Memory footprint | Peak RAM < 2 GB (designed for universal device support) |
| Model disk size | 0.6 GB (quantized large-v3) to 3.1 GB (full large-v3) |
| SDK overhead | < 5 MB additional app size |
| Energy | Stateful models: 0.3W per forward pass (75% reduction from 1.5W) |
| Thermal | Low -- ANE is designed for sustained workloads with < 10W power target |
| Min platform | macOS 14.0+ (Sonoma), iOS 17+, watchOS, visionOS |
| Min hardware | Any Apple Silicon (M1+, A14+); 8 GB RAM sufficient |

---

## 7. Real-time Streaming

**Yes -- first-class streaming support.**

### Streaming Architecture

WhisperKit uses a two-tier streaming output based on the LocalAgreement policy:

1. **Hypothesis text** -- low-latency intermediate results (~0.45s per-word latency)
2. **Confirmed text** -- stable, finalized transcription (~1.7s per-word latency)

### Protocol

- **Local server:** HTTP REST API (OpenAI-compatible) with Server-Sent Events (SSE) for streaming
- **No WebSocket support** -- uses SSE over HTTP
- **CLI streaming:** `whisperkit-cli transcribe --stream` for live microphone input

### Partial Results

Yes. SSE streaming provides progressive partial transcription results as they become available.

### First-word Latency

- Hypothesis text: ~0.45s mean per-word (from ICML paper)
- Streaming encoder: 218ms forward pass latency

```bash
# CLI streaming from microphone
swift run whisperkit-cli transcribe \
    --model-path "Models/whisperkit-coreml/openai_whisper-large-v3" \
    --stream

# Server mode with SSE streaming
BUILD_ALL=1 swift run whisperkit-cli serve --model large-v3
```

```python
# Python client via OpenAI SDK
from openai import OpenAI
client = OpenAI(base_url="http://localhost:50060/v1")
result = client.audio.transcriptions.create(
    file=open("audio.wav", "rb"),
    model="large-v3",
    stream=True  # SSE streaming
)
```

---

## 8. VAD (Voice Activity Detection)

**Yes -- built-in.**

WhisperKit includes a configurable `voiceActivityDetector` component. Configuration is available through `DecodingOptions`:

| Parameter | Default | Description |
|---|---|---|
| `noSpeechThreshold` | 0.6 | Probability threshold for non-speech detection |
| `compressionRatioThreshold` | 2.4 | Repetitive text / hallucination rejection |
| `logProbThreshold` | -1.0 | Average log probability failure threshold |
| `firstTokenLogProbThreshold` | -1.5 | First token probability failure threshold |

The VAD implementation is integrated into the transcription pipeline. In v0.13.0, async VAD support and segment discovery callbacks were added, enabling event-driven speech detection.

WhisperKit does **not** use Silero VAD -- it has its own integrated VAD implementation via CoreML.

---

## 9. Audio Input

| Feature | Status |
|---|---|
| PCM support | Yes -- 16 kHz, mono, Float32 PCM frames |
| Sample rate | 16 kHz (auto-resampled from hardware rate) |
| Formats | WAV, MP3, M4A, FLAC (file input); raw PCM (streaming) |
| Gain control | Not built-in -- handled by AVAudioEngine / application level |
| Multi-device | Not built-in -- single audio input via AVAudioEngine; multi-device would need application-level routing |
| Microphone | Via AVAudioEngine on macOS/iOS with automatic resampling to 16 kHz |

The local server accepts audio files via multipart POST. For live microphone streaming, the CLI tool or Swift API uses AVAudioEngine to capture and resample audio.

---

## 10. Language

| Feature | Status |
|---|---|
| Multi-language | Yes -- 99 languages (same as Whisper) |
| Auto-detect | Yes -- `detectLanguage: true` (default when prefill disabled) |
| Manual language | Yes -- via language code parameter |
| Translation | Yes -- audio-to-English translation (no other target languages) |

Multilingual models (non-.en variants) support all 99 Whisper languages. English-only models (.en) are available for tiny, base, small, and medium.

From the ICML paper, fine-tuning on a 5-language subset (English, German, Japanese, Chinese, French) maintained < 1% WER degradation.

---

## 11. Diarization

**Not built-in to WhisperKit.**

Argmax offers a separate product, [SpeakerKit](https://www.argmaxinc.com/blog/speakerkit), for on-device speaker diarization:
- ~4 minutes of audio diarized in ~1 second on iPhone
- ~10 MB total model size
- Matches Pyannote error rates across 13 datasets
- Works modularly with WhisperKit to produce "who spoke what and when"
- **Not open source** -- available via Argmax SDK license subscription
- Speaker identification (voiceprint extraction) is listed as an upcoming feature

SpeakerKit is a separate paid product, not part of the MIT-licensed WhisperKit.

---

## 12. Transcription Quality

| Feature | Status |
|---|---|
| Hallucination filtering | Yes -- `compressionRatioThreshold` (default 2.4), `logProbThreshold` (-1.0), temperature fallback with `temperatureIncrementOnFallback` (0.2), `temperatureFallbackCount` (5) |
| Punctuation | Yes -- Whisper models include punctuation in output |
| Timestamps | Yes -- segment-level and word-level (`wordTimestamps: true`) |
| Confidence scores | Yes -- `logprobs` parameter in server API provides token-level log probabilities |
| Suppress tokens | Yes -- `supressTokens` array, `suppressBlank` flag |
| Window clipping | Yes -- `windowClipTime` (default 1.0s) trims window end to prevent hallucinations |
| Prompt guidance | Yes -- `promptTokens` / `prefixTokens` for style and context |

```swift
let options = DecodingOptions(
    wordTimestamps: true,
    compressionRatioThreshold: 2.4,
    logProbThreshold: -1.0,
    noSpeechThreshold: 0.6,
    temperature: 0.0,
    temperatureIncrementOnFallback: 0.2,
    temperatureFallbackCount: 5
)
```

---

## 13. Architecture

| Aspect | Details |
|---|---|
| Type | Swift library (primary), CLI tool, local HTTP server |
| Process model | In-process library (Swift); out-of-process via CLI or HTTP server |
| Protocol | HTTP REST (OpenAI-compatible) + SSE for streaming; **no WebSocket** |
| Multi-client | Server mode supports concurrent connections (Vapor-based HTTP server) |
| Crash isolation | Server mode provides process isolation; library mode runs in-process |
| Build system | Swift Package Manager; Homebrew for CLI |

### Server Mode

The local server (`whisperkit-cli serve`) is built on [Vapor](https://vapor.codes/) and implements the OpenAI Audio API specification:

- `POST /v1/audio/transcriptions` -- transcribe audio
- `POST /v1/audio/translations` -- translate to English
- Configurable host, port, model, verbose logging
- SSE streaming for real-time results
- JSON and verbose_json response formats (no plain text, SRT, or VTT)

### Deployment Options

1. **Swift library** -- embed directly in iOS/macOS app (2 lines of code)
2. **CLI tool** -- `brew install whisperkit-cli` or `swift run whisperkit-cli`
3. **HTTP server** -- local server with OpenAI-compatible API
4. **Python client** -- via OpenAI SDK pointing to local server

---

## 14. Reliability

| Feature | Status |
|---|---|
| Crash recovery | Unknown / not documented -- no built-in watchdog or auto-restart |
| Preflight validation | Model auto-download with verification; `prewarm` option for sequential load/unload to reduce peak memory |
| Health check | Unknown / not documented -- no `/health` endpoint mentioned |
| Memory leaks | Known CoreML memory growth issue over long sessions (~2.4 GB to 3.3 GB over ~40 min); `prewarm` mode helps manage peak memory |
| Model prewarming | Yes -- `prewarm: true` loads models sequentially to reduce peak memory usage |
| CI testing | Automated benchmarks on Apple Silicon Mac cluster via GitHub Actions |

The `prewarm` configuration option is notable: it sequentially loads and unloads models to reduce peak memory, which helps on memory-constrained devices.

---

## 15. TTS Quality

**N/A.** WhisperKit has no TTS capability.

---

## 16. Project Health

| Metric | Value |
|---|---|
| GitHub stars | ~4,300 |
| Contributors | 35 |
| Commits | ~187 (across 34 releases) |
| Latest release | v0.15.0 (November 7, 2024) |
| Last repo activity | January 28, 2026 (issues/PRs actively maintained) |
| License | MIT |
| Documentation | README, CONTRIBUTING.md, Swift Package Index docs, ICML 2025 paper |
| Homebrew installs | ~1,311/year, 227/90d, 70/30d |
| HuggingFace downloads | ~4.2M/month (models) |
| Academic paper | [ICML 2025](https://arxiv.org/html/2507.10860v1) -- "WhisperKit: On-device Real-time ASR with Billion-Scale Transformers" |

### Notable Developments
- **WWDC 2025:** Apple introduced SpeechAnalyzer; Argmax plans integration
- **Jan 2026:** WhisperKit Android launched in collaboration with Qualcomm
- **Argmax SDK:** Commercial Pro tier with ~5x higher transcription speed vs open source WhisperKit

The project is backed by a commercial company (Argmax, Inc.) with venture funding, indicating long-term sustainability. The open-source release cadence slowed in late 2024 (last tag v0.15.0 in Nov 2024), but repo activity continues in 2026.

---

## 17. Dependencies

### Swift (primary)

| Dependency | Notes |
|---|---|
| Xcode 15.0+ | Build requirement |
| macOS 14.0+ (Sonoma) | Runtime requirement |
| Swift Package Manager | Package management |
| swift-transformers | Tokenizer dependency (v1.1.2+) |
| Vapor | Server mode only |
| CoreML framework | Apple system framework -- no external dependency |

**Install (Homebrew):**
```bash
brew install whisperkit-cli
# No Xcode needed for pre-built CLI
```

**Install (from source):**
```bash
git clone https://github.com/argmaxinc/whisperkit.git
cd whisperkit
make setup
make download-model MODEL=large-v3
```

### Python (whisperkittools)

| Dependency | Notes |
|---|---|
| Python 3.11 | Required |
| Xcode | Required for CoreML compilation |
| conda/pip | Package management |
| ffmpeg | Optional, for whisper.cpp pipeline |

```bash
conda create -n whisperkit python=3.11 -y && conda activate whisperkit
pip install -e .
# Optional: pip install -e '.[evals,pipelines]'
```

### Disk Footprint

| Component | Size |
|---|---|
| CLI binary (Homebrew) | ~50 MB (estimated) |
| SDK overhead | < 5 MB |
| Models | 39 MB (tiny) to 3.1 GB (large-v3 full) |
| Quantized large-v3 | ~547-954 MB |
| Quantized distil-large-v3 | ~594-600 MB |

### Offline Operation

Models must be downloaded once from HuggingFace (or bundled with app). After download, all inference is fully offline. No network required at runtime.

---

## 18. Privacy

| Feature | Status |
|---|---|
| Fully local | Yes -- all inference on-device via CoreML/ANE |
| No cloud dependency | Yes -- no audio leaves the device (after model download) |
| No telemetry | No evidence of telemetry or analytics in the open-source codebase |
| No data collection | Audio is processed locally and not transmitted anywhere |
| Model download | One-time download from HuggingFace (or pre-bundled) |

WhisperKit's entire value proposition is on-device, private inference. The MIT license imposes no usage restrictions. There is no indication of any phone-home, telemetry, or analytics in the open-source code.

---

## Relevance to claude-talk

### Potential Fit

WhisperKit could replace WhisperLiveKit as the STT engine in claude-talk, with significant architectural differences:

| Aspect | WhisperLiveKit (current) | WhisperKit |
|---|---|---|
| Language | Python (MLX) | Swift (CoreML) |
| Protocol | WebSocket | HTTP + SSE (no WebSocket) |
| Backend | MLX on Metal GPU | CoreML on Neural Engine |
| Integration | Python subprocess | CLI tool or HTTP server |
| Streaming | WebSocket frames | SSE events |
| Python API | Native | Via OpenAI SDK to local server |

### Key Advantages over WhisperLiveKit
- **Neural Engine acceleration** -- dedicated hardware, lower power, less thermal impact
- **Quantized models** -- 0.6 GB vs multi-GB, lower memory footprint
- **Proven production quality** -- ICML paper, 4.2M monthly HuggingFace downloads
- **Homebrew install** -- `brew install whisperkit-cli`, no Python venv needed for CLI
- **OpenAI-compatible API** -- drop-in server replacement

### Key Disadvantages vs WhisperLiveKit
- **No WebSocket** -- would require rewriting the audio streaming path from WebSocket to HTTP+SSE or feeding audio files
- **Swift-first** -- less natural integration with Python codebase
- **No barge-in** -- same limitation as current setup
- **No TTS** -- same as current (handled by macOS `say`)
- **Server mode requires BUILD_ALL=1** -- more complex build than `pip install`
- **CoreML-only** -- no MLX path (though MLX is available via whisperkittools for evaluation)

### Integration Path

The most practical integration would be:
1. Run `whisperkit-cli serve` as a background process
2. Send audio via HTTP POST to `localhost:50060/v1/audio/transcriptions`
3. Use SSE streaming for real-time partial results
4. Replace the current WebSocket client with an HTTP+SSE client

This would require significant refactoring of the audio server's streaming architecture, which currently relies on WebSocket connections to WhisperLiveKit.

---

## Sources

- [WhisperKit GitHub Repository](https://github.com/argmaxinc/WhisperKit)
- [whisperkittools GitHub Repository](https://github.com/argmaxinc/whisperkittools)
- [WhisperKit CoreML Models on HuggingFace](https://huggingface.co/argmaxinc/whisperkit-coreml)
- [ICML 2025 Paper: WhisperKit: On-device Real-time ASR with Billion-Scale Transformers](https://arxiv.org/html/2507.10860v1)
- [Argmax Blog: WhisperKit](https://www.argmaxinc.com/blog/whisperkit)
- [Argmax Blog: Apple SpeechAnalyzer and Argmax WhisperKit](https://www.argmaxinc.com/blog/apple-and-argmax)
- [Argmax Blog: SpeakerKit](https://www.argmaxinc.com/blog/speakerkit)
- [whisperkit-cli Homebrew Formula](https://formulae.brew.sh/formula/whisperkit-cli)
- [WhisperKit Benchmarks (HuggingFace Space)](https://huggingface.co/spaces/argmaxinc/whisperkit-benchmarks)
- [WhisperKit Evals Dataset](https://huggingface.co/datasets/argmaxinc/whisperkit-evals)
- [Swift Package Index: WhisperKit](https://swiftpackageindex.com/argmaxinc/WhisperKit)

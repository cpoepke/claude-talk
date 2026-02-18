# lightning-whisper-mlx — Evaluation Report

> **Project**: [mustafaaljadery/lightning-whisper-mlx](https://github.com/mustafaaljadery/lightning-whisper-mlx)
> **Version**: 0.0.10 (April 2, 2024)
> **PyPI**: [lightning-whisper-mlx](https://pypi.org/project/lightning-whisper-mlx/)
> **Evaluated**: 2026-02-18

## Executive Summary

lightning-whisper-mlx is a **batch inference accelerator** for OpenAI Whisper on Apple Silicon, built on Apple's MLX framework. It claims 10x faster throughput than whisper.cpp and 4x faster than the standard mlx-whisper implementation, achieved through batched decoding, distilled models, and quantization.

**Critical caveat**: This is NOT a streaming/real-time solution. It transcribes complete audio files. There is no microphone input, no WebSocket server, no partial results, and no VAD. It is a fast offline transcriber — nothing more.

**Verdict for claude-talk**: Not directly usable. Would require substantial wrapper engineering (chunked audio capture, VAD, WebSocket server, partial result simulation) to approximate real-time behavior, at which point you are essentially rebuilding WhisperLiveKit. The project is also effectively unmaintained (last commit May 2024, 15 open issues with no responses).

---

## 1. Models

| Aspect | Detail |
|--------|--------|
| **Sizes** | tiny, base, small, medium, large, large-v2, large-v3 |
| **Distil variants** | distil-small.en, distil-medium.en, distil-large-v2, distil-large-v3 |
| **Quantization** | None (full precision), 4-bit, 8-bit |
| **Model source** | HuggingFace Hub (mlx-community repos, mustafaaljadery/distil-whisper-mlx) |
| **Model format** | MLX `.npz` weights + `config.json` |
| **Turbo model** | Not supported (open issue [#19](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/19)) |
| **Custom/LoRA** | Not supported |
| **WER** | Not independently benchmarked by the project. Uses standard Whisper model weights, so WER should match OpenAI baselines (large-v3 ~10.3% avg across Common Voice benchmarks). Distil models trade some accuracy for speed. |
| **Speculative decoding** | Listed as "coming soon" — never shipped |

### Speed (RTF on M-series)

The project claims 10x faster than whisper.cpp and 4x faster than mlx-whisper, but independent benchmarks tell a different story:

| Benchmark | Hardware | Model | Time | Notes |
|-----------|----------|-------|------|-------|
| [mac-whisper-speedtest](https://github.com/anvanvan/mac-whisper-speedtest) | M4 24GB | large | 1.82s | 6th of 9 implementations tested |
| Same benchmark | M4 24GB | whisper.cpp | 1.23s | Faster than lightning-whisper-mlx |
| Same benchmark | M4 24GB | fluidaudio-coreml | 0.19s | 9x faster than lightning-whisper-mlx |

The 10x claim appears to be based on the author's own benchmarks with specific configurations and has not been independently reproduced at that magnitude. On the M4, whisper.cpp actually outperforms it on the large model.

### Code Example

```python
from lightning_whisper_mlx import LightningWhisperMLX

whisper = LightningWhisperMLX(model="distil-medium.en", batch_size=12, quant=None)
result = whisper.transcribe(audio_path="/path/to/audio.mp3")
print(result['text'])
```

Quantized:
```python
whisper = LightningWhisperMLX(model="large-v3", batch_size=6, quant="4bit")
```

---

## 2. Speech-to-Speech (STS)

**None.** This is a speech-to-text only library. No STS capability whatsoever.

---

## 3. Barge-in / Interruption

**None.** No audio capture, no duplex audio, no AEC (acoustic echo cancellation), no interrupt hooks. The library processes complete audio files from disk.

To implement barge-in, you would need to build:
- Continuous microphone capture (sounddevice/PyAudio)
- VAD to detect speech onset/offset
- Chunked file writing + repeated `transcribe()` calls
- Your own interrupt signaling mechanism

---

## 4. Keyword / Wake Word

**None.** No vocabulary biasing, no initial prompt/hotword support, no confidence scores exposed per-token.

The `transcribe()` function accepts a `language` parameter but no `initial_prompt` or `hotwords` parameter. The underlying `DecodingOptions` dataclass has `suppress_tokens` but no positive biasing.

Open issue [#8](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/8) requests kwargs passthrough to the transcribe function, which would theoretically allow passing init_prompt — but it remains unimplemented.

---

## 5. TTS

**None.** This is a speech-to-text library only. No TTS capability.

---

## 6. Apple Silicon

| Aspect | Detail |
|--------|--------|
| **MLX** | Yes — core framework, all computation via MLX ops |
| **Metal GPU** | Yes — MLX uses Metal under the hood |
| **CoreML** | No (the fork [Lightning-SimulWhisper](https://github.com/altalt-org/Lightning-SimulWhisper) adds CoreML encoder support) |
| **Unified Memory** | Leveraged for model loading; batch_size constrained by available unified memory |
| **Memory footprint** | Depends on model + quantization. 4-bit large-v3 fits comfortably in 8GB. Full-precision large may need 16GB+ with high batch sizes. Open issue [#5](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/5) requests memory freeing. |
| **Thermal** | Not documented. Batch inference will spike GPU utilization briefly. |

### Known MLX Memory Issues (upstream)

These affect all MLX-based Whisper implementations including lightning-whisper-mlx:
- [OOM on files >1GB](https://github.com/ml-explore/mlx-examples/issues/1366) — GPU `kIOGPUCommandBufferCallbackErrorOutOfMemory`
- [Memory leak with word_timestamps](https://github.com/ml-explore/mlx-examples/issues/1254) — memory grows with each chunk when `word_timestamps=True`
- [MP3 stalling](https://github.com/ml-explore/mlx-examples/issues/958) — ffmpeg subprocess hangs on some MP3 files

---

## 7. Real-time Streaming

**Not supported.** This is the fundamental limitation.

| Aspect | Detail |
|--------|--------|
| **Streaming** | No |
| **Partial results** | No |
| **First-word latency** | N/A — processes complete files only |
| **Protocol** | None — Python library, no server |
| **WebSocket** | No |
| **Simultaneous decode** | No — sequential batch processing of 30s chunks |

### Could it be wrapped for streaming?

Theoretically yes, with significant effort:

1. **Chunked approach**: Capture N seconds of audio, write to temp file, call `transcribe()`, repeat. This gives latency = chunk_duration + inference_time. With a 2s chunk on distil-small.en, you might achieve ~2.5s latency — poor for conversation.

2. **The fork exists**: [Lightning-SimulWhisper](https://github.com/altalt-org/Lightning-SimulWhisper) implements the AlignAtt policy for simultaneous streaming using MLX + CoreML, achieving real-time on medium/large-v3-turbo models on M2. This is the proper streaming solution if you want MLX-based Whisper streaming.

3. **WhisperLiveKit comparison**: WLK already provides WebSocket streaming, VAD, partial results, and proper buffering. Wrapping lightning-whisper-mlx to match WLK's feature set would essentially mean rebuilding WLK.

---

## 8. VAD (Voice Activity Detection)

**None.** No built-in VAD or silence detection at the audio capture level.

The transcribe pipeline does include a `no_speech_threshold` (default 0.6) that filters out segments where the model detects no speech, but this operates on already-segmented 30s chunks during decoding — it is not a real VAD for audio capture.

---

## 9. Audio Input

| Aspect | Detail |
|--------|--------|
| **Input method** | File path only (`audio_path` parameter) |
| **Formats** | Any format ffmpeg supports (decoded via `ffmpeg` subprocess) |
| **PCM support** | Not directly — audio is loaded via ffmpeg, converted to s16le PCM internally |
| **Sample rate** | Resampled to 16kHz internally |
| **Channels** | Downmixed to mono internally |
| **Gain control** | None |
| **Multi-device** | No — no device input support at all |
| **Microphone** | No — file-based only |
| **numpy/mlx array input** | The underlying `transcribe_audio()` accepts numpy or mlx arrays, but the public API only exposes file path input |

### Audio Pipeline (from source)

```
audio file -> ffmpeg subprocess (decode to s16le PCM, 16kHz, mono)
           -> numpy int16 -> mlx float32 (normalized /32768.0)
           -> pad/trim to 30s chunks
           -> mel spectrogram (STFT -> mel filterbank -> log scale)
           -> Whisper encoder -> decoder -> text
```

**Dependency**: Requires `ffmpeg` CLI in PATH.

---

## 10. Language

| Aspect | Detail |
|--------|--------|
| **Multi-language** | Yes — supports all Whisper languages via multilingual models |
| **Language parameter** | `whisper.transcribe(audio_path, language="fr")` |
| **Auto-detect** | Yes — runs language detection if `language=None` |
| **Translation** | Yes — `DecodingOptions` supports `task="translate"` (translate to English), but NOT exposed in the public `transcribe()` API |
| **English-only models** | distil-small.en, distil-medium.en (faster, English only) |

Open issue [#16](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/16) confirms language specification was added but may have limited testing.

---

## 11. Diarization

**None.** No speaker identification or diarization capability.

Open issue [#6](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/6) requests speaker diarization — no response from maintainer.

---

## 12. Transcription Quality

| Aspect | Detail |
|--------|--------|
| **Hallucination filtering** | Basic — `compression_ratio_threshold` (2.4) and `logprob_threshold` (-1.0) trigger temperature fallback. Known issue [#15](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/15) reports "Thanks for watching!" hallucinations. |
| **Punctuation** | Yes — `prepend_punctuations` and `append_punctuations` parameters for merging |
| **Timestamps** | Segment-level timestamps in output. Word-level timestamps requested in issue [#17](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/17) — not yet implemented in public API. |
| **Confidence scores** | `avg_logprob` and `no_speech_prob` per segment in `DecodingResult`, but not exposed in the simplified public API |
| **Temperature fallback** | Yes — tries multiple temperatures (0.0 -> 0.2 -> 0.4 -> ... -> 1.0) when quality thresholds fail |
| **Output formats** | Text only. Issue [#12](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/12) requests VTT/JSON — unimplemented. |
| **Truncation bug** | Issue [#21](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/21) reports missing transcription at the end of audio files |

### Output Structure

```python
{
    "text": "full transcription text",
    "segments": [
        {
            "id": 0,
            "start": 0.0,
            "end": 5.2,
            "text": "segment text",
            "tokens": [50364, ...],
            "avg_logprob": -0.23,
            "no_speech_prob": 0.01,
            "compression_ratio": 1.4
        },
        ...
    ],
    "language": "en"
}
```

---

## 13. Architecture

| Aspect | Detail |
|--------|--------|
| **Type** | Python library (imported, runs in-process) |
| **Server** | None — no HTTP/WebSocket/gRPC server |
| **Multi-client** | No — single-threaded, in-process |
| **Crash isolation** | None — crashes take down the host process |
| **Process model** | Single process, single thread. ffmpeg spawned as subprocess for audio decoding. |
| **Model caching** | `ModelHolder` class caches loaded models to avoid redundant loading |
| **Model storage** | Downloads to `./mlx_models/{model_name}/` relative to CWD (not configurable) |

### File Structure

```
lightning_whisper_mlx/
  __init__.py          # Exports LightningWhisperMLX
  lightning.py         # Main class, model selection, HuggingFace download
  transcribe.py        # Core transcription pipeline
  audio.py             # Audio loading (ffmpeg), mel spectrogram
  decoding.py          # Greedy/beam search decoding, language detection
  load_models.py       # Model weight loading
  whisper.py           # Whisper model architecture (MLX)
  torch_whisper.py     # PyTorch Whisper variant
  tokenizer.py         # Token handling
  timing.py            # Performance timing
  assets/
    mel_filters.npz    # Pre-computed mel filterbank
```

### Model Download Concern

Models are downloaded to `./mlx_models/` relative to CWD, which means:
- Different CWDs cause duplicate downloads
- No global cache (unlike HuggingFace's default `~/.cache/huggingface/`)
- Disk usage multiplies if used from multiple directories

---

## 14. Reliability

| Aspect | Detail |
|--------|--------|
| **Crash recovery** | None — library, not a service |
| **Preflight validation** | Checks model name and quant parameter validity |
| **Health check** | None |
| **Memory leaks** | Upstream MLX issue with `word_timestamps=True`. No memory management in lightning-whisper-mlx itself (issue [#5](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/5)). |
| **Quantization bugs** | Issue [#24](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/24) — `ValueError: Matrix dimension mismatch` with quantized models (May 2025, unresolved) |
| **Quantization broken** | Issue [#11](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/11) — transcription fails with quantization enabled (Apr 2024, unresolved) |
| **HuggingFace dependency** | Checks HuggingFace on every instantiation (issue [#22](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/22) — no offline-first mode) |

**Bottom line**: Two of the three headline features (quantization is broken, speculative decoding never shipped) are non-functional. The main value proposition (batched decoding of distilled models) works.

---

## 15. TTS Quality

**N/A** — No TTS capability.

---

## 16. Project Health

| Metric | Value |
|--------|-------|
| **GitHub stars** | ~874 |
| **Forks** | 62 |
| **Contributors** | 3 (1 primary author + 2 minor PRs) |
| **Total commits** | 17 |
| **First commit** | March 24, 2024 |
| **Last commit** | May 8, 2024 |
| **Last PyPI release** | 0.0.10, April 2, 2024 |
| **Open issues** | 15 (no closed issues visible) |
| **Issue response rate** | Essentially zero — maintainer does not respond to issues |
| **License** | Not specified (neither in repo nor on PyPI) |
| **Documentation** | README only, minimal. No API docs. |
| **CI/CD** | None visible |
| **Tests** | One file (`test.py`) with a single test case |

### Commit History

Most of the 17 commits are from April 2, 2024 (initial push + typo fixes). One meaningful external PR merged May 8, 2024. No activity since.

**Assessment**: Effectively abandoned. The author (Mustafa Aljadery) appears to have moved on. No issue triage, no bug fixes for critical bugs (quantization broken since April 2024), no turbo model support despite request.

---

## 17. Dependencies

### Direct Dependencies (from setup.py)

| Package | Notes |
|---------|-------|
| `mlx` | Apple MLX framework (Apple Silicon only) |
| `torch` | PyTorch — heavy dependency (~2GB), unclear why needed alongside MLX |
| `huggingface_hub` | Model downloading |
| `numpy` | Array operations |
| `scipy` | Signal processing |
| `numba` | JIT compilation |
| `tqdm` | Progress bars |
| `more-itertools` | Iteration utilities |
| `tiktoken==0.3.3` | Tokenizer (pinned to specific old version) |

### Dependency Concerns

- **PyTorch + MLX together**: Extremely heavy. PyTorch alone is ~2GB. Both frameworks loaded simultaneously is wasteful.
- **Pinned tiktoken**: `tiktoken==0.3.3` is very old (current is 0.7+). May cause conflicts with other packages.
- **numba**: Heavy dependency with LLVM backend, adds significant install time.
- **ffmpeg**: Required CLI tool, not listed as a Python dependency. Must be installed separately.

### Install Complexity

```bash
pip install lightning-whisper-mlx  # Pulls in ~3-4GB of dependencies
brew install ffmpeg                # Required separately
```

**Disk footprint estimate**: ~3-4GB for dependencies + 0.5-3GB per model depending on size/quantization.

### Offline Capability

Partial. After initial model download from HuggingFace, transcription works offline. However, `LightningWhisperMLX.__init__()` calls `hf_hub_download()` on every instantiation, which checks HuggingFace even if the model is already cached locally (issue [#22](https://github.com/mustafaaljadery/lightning-whisper-mlx/issues/22)).

---

## 18. Privacy

| Aspect | Detail |
|--------|--------|
| **Fully local inference** | Yes — all Whisper inference runs locally on Apple Silicon |
| **Network calls** | HuggingFace Hub on model init (model download + version check). No telemetry observed in source code. |
| **Telemetry** | None visible in source code |
| **Audio sent externally** | No — audio is processed locally |
| **Model storage** | Local (`./mlx_models/` relative to CWD) |

Privacy is good once models are cached, with the caveat that every instantiation touches HuggingFace.

---

## Comparison: lightning-whisper-mlx vs WhisperLiveKit (current claude-talk engine)

| Feature | lightning-whisper-mlx | WhisperLiveKit |
|---------|----------------------|----------------|
| **Streaming** | No | Yes (WebSocket) |
| **Real-time** | No (batch only) | Yes |
| **Partial results** | No | Yes |
| **VAD** | No | Yes (Silero VAD) |
| **Microphone input** | No | Yes |
| **WebSocket server** | No | Yes |
| **Barge-in** | No | Possible via architecture |
| **Init prompt** | No | Yes |
| **Multi-client** | No | Yes |
| **Apple Silicon optimized** | Yes (MLX) | Yes (MLX via faster-whisper or mlx-whisper) |
| **Maintained** | No (last commit May 2024) | Yes |

---

## Notable Fork: Lightning-SimulWhisper

[Lightning-SimulWhisper](https://github.com/altalt-org/Lightning-SimulWhisper) is a separate project that implements **simultaneous streaming** on MLX + CoreML:

- Uses the AlignAtt policy for streaming speech recognition
- 18x faster encoding via CoreML Neural Engine
- 15x faster decoding via MLX vs PyTorch
- Supports medium and large-v3-turbo in real-time on M2
- Has optional VAD (via torchaudio)
- CoreML encoder + MLX decoder hybrid architecture

This is conceptually closer to what claude-talk needs, but is a distinct project — not a drop-in wrapper around lightning-whisper-mlx.

---

## Final Assessment

### Strengths
- Very fast batch transcription for offline files
- Good model variety including distilled variants
- Simple API (3 lines of code to transcribe)
- Fully local inference

### Weaknesses
- **Not streaming** — fundamental architectural mismatch for voice conversation
- **Effectively abandoned** — no maintenance since May 2024, 15 unanswered issues
- **Quantization broken** — one of the three headline features does not work
- **Heavy dependencies** — PyTorch + MLX together is ~4GB
- **No license specified** — legal risk for any serious integration
- **Poor model caching** — downloads to CWD, checks HuggingFace every init
- **Missing transcription content** — known bug where end of audio is lost

### Recommendation for claude-talk

**Do not adopt.** The project is architecturally incompatible with real-time voice conversation (no streaming, no VAD, no microphone input, no partial results). It would require more engineering effort to wrap it for streaming than to continue using WhisperLiveKit, which already provides all of these features. The project's abandoned maintenance status and broken quantization further disqualify it.

If MLX-native batch transcription is needed for a separate use case (e.g., transcribing recorded files), consider the maintained [mlx-whisper](https://pypi.org/project/mlx-whisper/) from the official mlx-community instead.

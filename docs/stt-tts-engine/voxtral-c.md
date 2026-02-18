# Voxtral.c -- Engine Evaluation Report

> **Date:** 2026-02-18
> **Source:** [github.com/antirez/voxtral.c](https://github.com/antirez/voxtral.c)
> **Author:** Salvatore Sanfilippo (antirez), creator of Redis
> **Model:** Mistral Voxtral Mini 4B Realtime 2602
> **License:** MIT (voxtral.c code), Apache 2.0 (model weights)

## Summary

Voxtral.c is a **pure C inference engine** for Mistral's Voxtral Realtime 4B speech-to-text model. Unlike Whisper-based systems, it uses a native streaming transformer architecture with a causal audio encoder and an LLM decoder (based on Ministral-3B). The project is 13 days old, has 1,341 stars, and is essentially a solo effort by antirez. It is **STT-only** -- no TTS, no text generation beyond transcription, no speech-to-speech.

---

## 1. Models

| Aspect | Detail |
|--------|--------|
| **Model** | Voxtral Mini 4B Realtime 2602 (single model, no variants) |
| **Parameters** | ~4B total (0.6B encoder + 3.4B decoder) |
| **Weight format** | BF16, 8.9 GB on disk (safetensors) |
| **Architecture** | 32-layer causal encoder (1280 dim) + 26-layer LLM decoder (3072 dim, Ministral-3 based) |
| **Vocabulary** | 131,072 tokens (Tekken tokenizer) |
| **WER (English, 480ms)** | 4.90% on FLEURS |
| **WER (13-lang avg, 480ms)** | 8.72% on FLEURS |
| **WER (English, offline)** | 3.32% on FLEURS (Voxtral Transcribe V2) |
| **RTF on M3 Max (MPS)** | **0.40** (2.5x real-time) |
| **Distilled variants** | None. Single 4B model only |
| **LoRA / fine-tune** | Not supported. voxtral.c is inference-only; no training code |
| **Custom models** | No. Hardcoded for Voxtral Realtime 4B architecture only |

**WER benchmark detail (FLEURS, 480ms delay):**

| Language | WER |
|----------|-----|
| English | 4.90% |
| Spanish | 3.31% |
| French | 6.42% |
| German | 6.19% |
| Italian | 3.27% |
| Portuguese | 5.03% |
| Dutch | 7.07% |
| Hindi | 12.88% |
| Arabic | 22.53% |
| Chinese | 10.45% |
| Japanese | 9.59% |
| Korean | 15.74% |
| Russian | 6.02% |

**Speed benchmarks (M3 Max, 40-core GPU, MPS):**

| Component | Latency |
|-----------|---------|
| Encoder (3.6s audio) | 284 ms |
| Prefill | 252 ms |
| Decoder step (short clips) | 23.5 ms/step |
| Decoder step (long clips) | 29.8 ms/step |
| Overall RTF | 0.40 |

---

## 2. Speech-to-Speech

**No STS capability.** Voxtral.c is strictly speech-to-text. The Voxtral Realtime 4B model is a transcription model -- it converts audio to text tokens. There is no audio generation, voice synthesis, or speech-to-speech pipeline.

The broader Voxtral family (Voxtral Mini, Voxtral Small 24B) includes multimodal audio *understanding* (audio + text input -> text output), but still no audio *generation*.

---

## 3. Barge-in / Interruption

| Feature | Status |
|---------|--------|
| Built-in AEC | No |
| Duplex audio | No (mic capture is half-duplex, macOS only) |
| Interrupt hooks | No built-in hooks |
| Continuous mode | Yes -- `vox_stream_set_continuous()` auto-restarts decoder on EOS or prolonged silence |
| Stream flush | Yes -- `vox_stream_flush()` forces encoder to process buffered audio (useful for silence-detection-triggered interrupts) |

Barge-in would need to be implemented at the application level. The `vox_stream_flush()` API provides a hook point for external silence/interrupt detection to force processing of buffered audio, but there is no AEC or echo cancellation.

---

## 4. Keyword / Wake Word

| Feature | Status |
|---------|--------|
| Vocabulary biasing | Not supported |
| Init prompt | Not supported (no prompt injection mechanism) |
| Confidence scores | Partial -- alternative token API (`vox_stream_set_alt()` / `vox_stream_get_alt()`) shows competing candidates with probability cutoff |
| Wake word detection | Not supported |

The alternative token feature provides some insight into model uncertainty (up to 4 alternatives per position with configurable probability cutoff), but there is no keyword spotting or vocabulary biasing.

---

## 5. TTS

**No TTS capability.** Voxtral.c is purely a speech recognition (STT) engine. It outputs text tokens only. No voice synthesis, no audio output generation, no parallel TTS streams.

---

## 6. Apple Silicon

| Aspect | Detail |
|--------|--------|
| **Metal/MPS** | Yes -- native Metal Performance Shaders backend, zero external dependencies |
| **MLX** | No (pure C, not Python/MLX) |
| **CoreML** | No |
| **Neural Engine** | No (GPU only via Metal) |
| **Build** | `make mps` -- single command, no package managers |
| **Memory footprint** | ~19 GB total (8.9 GB weights mmap + 8.4 GB GPU cache + 1.8 GB KV cache + 0.2 GB buffers) |
| **Minimum RAM** | 16 GB is tight; 32 GB+ recommended |
| **Thermal** | Unknown / not documented. HN users report "slow" on M1 Max; M3 Max achieves RTF 0.40 |

**Important caveat:** The ~19 GB total memory footprint is significant. Users on 16 GB machines report the system "hangs or is too slow." HN comments indicate M1 Max performance is disappointing compared to M3 Max. The MPS backend uses fused GPU kernels (packed QKV, FFN gate fusion, vectorized float4/half4) that have been progressively optimized.

**Comparison note:** WhisperLiveKit with MLX Whisper uses the Neural Engine and requires ~1-3 GB for the model depending on variant. Voxtral.c's 19 GB footprint is 6-19x larger.

---

## 7. Real-time Streaming

| Feature | Detail |
|---------|--------|
| Streaming architecture | Yes -- native causal encoder, not chunked-offline |
| Partial results | Yes -- `vox_stream_get()` returns tokens incrementally as decoded |
| First-word latency | Configurable 80ms - 2400ms via `vox_set_delay()` (recommended: 480ms) |
| Processing interval | Configurable via `vox_set_processing_interval()` (default 2.0s, min ~0.5s) |
| Protocol | C library API (no WebSocket server built in) |
| Stdin streaming | Yes -- pipe audio via stdin for integration |
| Simultaneous decoding | No -- single-stream, single-client |

**C streaming API example:**

```c
vox_ctx_t *ctx = vox_load("voxtral-model");
vox_set_delay(ctx, 480);

vox_stream_t *s = vox_stream_init(ctx);
vox_set_processing_interval(s, 1.0);
vox_stream_set_continuous(s, 1);

// Feed audio chunks as they arrive
while (has_audio()) {
    float *samples = get_audio_chunk(&n);
    vox_stream_feed(s, samples, n);

    const char *tokens[64];
    int n_tok = vox_stream_get(s, tokens, 64);
    for (int i = 0; i < n_tok; i++)
        printf("%s", tokens[i]);
}

vox_stream_finish(s);
// drain remaining tokens...
vox_stream_free(s);
vox_free(ctx);
```

**CLI streaming example:**

```bash
# Low-latency streaming from stdin
ffmpeg -i mic.wav -f s16le -ar 16000 -ac 1 - | \
  ./voxtral -d voxtral-model --stdin -I 0.5

# Live microphone (macOS only)
./voxtral -d voxtral-model --from-mic
```

---

## 8. VAD

| Feature | Detail |
|---------|--------|
| Built-in VAD | Partial -- silence detection in microphone mode |
| Configurable silence threshold | Unknown / not documented |
| External VAD hookpoint | Yes -- `vox_stream_flush()` can be triggered by external VAD |
| Silero VAD integration | No |
| Energy-based VAD | Unknown (mic mode uses "automatic silence detection") |

The silence detection in microphone mode is implemented internally and not well documented. For streaming via stdin or the C API, silence detection must be handled externally. The `vox_stream_set_continuous()` mode handles EOS and prolonged silence by auto-restarting the decoder.

---

## 9. Audio Input

| Feature | Detail |
|---------|--------|
| PCM support | Yes -- 16-bit signed little-endian (s16le) via stdin |
| WAV support | Yes -- 16-bit PCM, any sample rate (auto-resampled to 16kHz) |
| Sample rate | 16 kHz (auto-resampled from other rates) |
| Gain control | Not built in |
| Multi-device | No -- single microphone input only (macOS AudioQueue) |
| Mel spectrogram | 128 bins, Hann window (400 samples), 160-sample hop, Slaney mel filterbank (0-8000 Hz) |
| ffmpeg integration | Yes -- pipe any format through ffmpeg to stdin |

**ffmpeg pipeline example:**

```bash
ffmpeg -i podcast.mp3 -f s16le -ar 16000 -ac 1 - 2>/dev/null | \
  ./voxtral -d voxtral-model --stdin
```

---

## 10. Language

| Feature | Detail |
|---------|--------|
| Languages supported | 13: Arabic, Chinese, Dutch, English, French, German, Hindi, Italian, Japanese, Korean, Portuguese, Russian, Spanish |
| Auto-detect | Unknown / not documented (model likely infers language from audio) |
| Translation | No -- transcription only, no translation capability |
| Language selection | No explicit language flag in CLI or API |

---

## 11. Diarization

**Not supported in voxtral.c.** The C implementation provides raw transcription output only.

Note: The Voxtral API (cloud service) and Voxtral Transcribe V2 support speaker diarization with word-level timestamps, but this is server-side functionality not available in the local C inference engine.

---

## 12. Transcription Quality

| Feature | Detail |
|---------|--------|
| Hallucination filtering | Not explicitly documented. The broader Voxtral family (DPO variant) claims "fewer hallucinations" |
| Punctuation | Yes -- the model outputs punctuated text natively |
| Word-level timestamps | Not supported in voxtral.c (available in Voxtral Transcribe V2 API) |
| Confidence scores | Partial -- alternative token probabilities via `--alt <cutoff>` flag |
| Alternative hypotheses | Yes -- up to 4 alternatives per token position |
| Long-form quality | English WER: 5.05% (Meanwhile), 10.23% (Earnings-21), 3.17% (TEDLIUM) at 480ms |

**Alternative token example:**

```bash
# Show alternatives when model probability drops below 95%
./voxtral -d voxtral-model -i audio.wav --alt 0.95
```

---

## 13. Architecture

| Aspect | Detail |
|--------|--------|
| Integration model | **C library** (`vox_stream_t` API) + CLI binary |
| WebSocket server | No built-in WebSocket or HTTP server |
| Multi-client | No -- single-stream, single-process |
| Crash isolation | Process-level only (single binary) |
| Server mode | No -- must be embedded or invoked per-transcription |
| Dependencies (MPS) | **Zero** -- pure C + Apple Metal framework |
| Dependencies (BLAS) | OpenBLAS (Linux) or Accelerate (macOS Intel) |
| Build system | Simple Makefile (`make mps` or `make blas`) |

**Key architectural difference from WhisperLiveKit:** voxtral.c is a library/CLI, not a server. There is no WebSocket endpoint, no multi-client support, no HTTP API. Integration requires either:
1. Embedding the C library in your application
2. Piping audio to stdin and reading stdout
3. Building a server wrapper around it

---

## 14. Reliability

| Feature | Detail |
|---------|--------|
| Crash recovery | No built-in crash recovery or watchdog |
| Preflight validation | Unknown / not documented |
| Health check | No health check endpoint (not a server) |
| Memory leaks | Unknown -- project is 13 days old, limited testing |
| Memory-mapped weights | Yes -- near-instant model loading, no weight deserialization |
| Rolling KV cache | Yes -- automatic compaction at 8192-position sliding window prevents unbounded memory growth |
| Chunked encoder | Yes -- overlapping windows bound memory regardless of audio length |

The rolling KV cache and chunked encoder provide structural safeguards against memory exhaustion during long transcriptions. However, the project is very young and has had minimal real-world reliability testing.

---

## 15. TTS Quality

**Not applicable.** Voxtral.c has no TTS capability whatsoever. It is a pure STT engine.

---

## 16. Project Health

| Metric | Value |
|--------|-------|
| **Stars** | 1,341 |
| **Forks** | 78 |
| **Contributors** | 2 (antirez: 43 commits, 3podi: 2 commits) |
| **Open issues** | 10 |
| **Created** | 2026-02-05 |
| **Last commit** | 2026-02-15 |
| **Age** | 13 days |
| **License** | MIT (code), Apache 2.0 (model weights) |
| **Language** | C (100%) |
| **Docs** | README.md, MODEL.md, SPEED.md |
| **Tests** | Unknown / not documented |
| **CI/CD** | Unknown / not documented |

**Assessment:** Extremely young project. High initial interest (1,341 stars in 13 days) driven by antirez's reputation. Essentially a solo project -- only 2 contributors. Rapid iteration (43 commits in 13 days with significant MPS kernel optimizations). No visible test suite or CI. Long-term maintenance is uncertain.

---

## 17. Dependencies

| Aspect | Detail |
|---------|--------|
| **Install complexity (MPS)** | Trivial: `make mps && ./download_model.sh` |
| **Install complexity (BLAS)** | Low: install OpenBLAS, then `make blas` |
| **C dependencies (MPS)** | Zero -- C standard library + Apple Metal framework only |
| **C dependencies (BLAS)** | OpenBLAS or Accelerate |
| **Python** | Not required (Python reference implementation is optional/educational) |
| **Disk footprint** | ~9 GB (model weights) + ~1 MB (binary) |
| **Runtime memory** | ~19 GB (weights + GPU cache + KV cache + buffers) |
| **Offline capable** | Yes -- fully offline after model download |
| **No pip/conda/venv** | Correct -- pure C, compiled binary |
| **No PyPI package** | Correct -- source compilation only |

**Comparison:** WhisperLiveKit requires Python, pip, venv, MLX, PyTorch, and multiple Python packages. Voxtral.c requires only a C compiler and the model weights.

---

## 18. Privacy

| Aspect | Detail |
|---------|--------|
| **Fully local** | Yes -- all inference runs locally, no network calls |
| **Telemetry** | None -- pure C binary, no analytics or phone-home |
| **Data collection** | None |
| **Model download** | One-time HTTPS download from Hugging Face (~8.9 GB) |
| **API keys** | Not required |
| **Network after setup** | Not required -- fully air-gapped capable |

This is one of voxtral.c's strongest points. Being a pure C binary with no runtime dependencies, there is zero possibility of hidden telemetry, analytics, or data exfiltration. The model weights are downloaded once and everything runs locally.

---

## Comparison Summary: Voxtral.c vs WhisperLiveKit (Current claude-talk Engine)

| Dimension | Voxtral.c | WhisperLiveKit + MLX Whisper |
|-----------|-----------|------------------------------|
| **Model size** | 4B params, 8.9 GB | 39M-1.5B params, 0.1-3 GB |
| **Memory** | ~19 GB | ~1-4 GB |
| **WER (English)** | 4.90% (480ms) | ~5-10% (depends on model) |
| **RTF (M-series)** | 0.40 (M3 Max) | ~0.1-0.3 (varies) |
| **Streaming** | Native causal | Chunked with WebSocket |
| **Protocol** | C library / stdin-stdout | WebSocket server |
| **Multi-client** | No | Yes |
| **TTS** | No | No (separate `say` command) |
| **VAD** | Basic silence detection | Silero VAD |
| **Languages** | 13 | 99+ |
| **Diarization** | No | No (but WhisperX available) |
| **Dependencies** | Zero (MPS) | Python + MLX + PyTorch |
| **Install** | `make mps` | pip + venv + multiple packages |
| **Privacy** | Fully local, zero telemetry | Fully local |
| **Maturity** | 13 days old | Years of community use |
| **Barge-in** | No built-in | No built-in (app-level) |
| **Init prompt** | Not supported | Supported (vocabulary biasing) |

---

## Verdict for claude-talk Integration

**Not recommended as a replacement at this time.** Key blockers:

1. **Memory:** 19 GB is prohibitive. Leaves no room for Claude Code, browser, and other apps on 32 GB machines. Impossible on 16 GB.
2. **No WebSocket server:** claude-talk's architecture relies on WebSocket streaming. Voxtral.c would require building a server wrapper.
3. **No init prompt / vocabulary biasing:** claude-talk uses `--static-init-prompt` to pass personality names to Whisper for improved recognition. Voxtral.c has no equivalent.
4. **No TTS:** Still need a separate TTS solution (same as current).
5. **13 days old:** Too early to depend on for a production tool.
6. **Single contributor:** Bus factor of 1.

**Potential future interest:** If voxtral.c matures and the Voxtral model family produces smaller distilled variants (e.g., 1B), the pure C / zero-dependency approach would be very attractive. The streaming C API is clean and the privacy story is excellent. Worth revisiting in 3-6 months.

---

## Sources

- [antirez/voxtral.c GitHub Repository](https://github.com/antirez/voxtral.c)
- [Voxtral Mini 4B Realtime 2602 -- Hugging Face Model Card](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)
- [Voxtral Transcribes at the Speed of Sound -- Mistral AI Blog](https://mistral.ai/news/voxtral-transcribe-2)
- [Hacker News Discussion](https://news.ycombinator.com/item?id=46954049)
- [Voxtral Technical Report (arXiv)](https://arxiv.org/html/2507.13264v1)
- [Redis Creator Built Speech Recognition in Pure C](https://www.abit.ee/en/artificial-intelligence/redis-voxtral-speech-recognition-c-mistral-antirez-machine-learning-ai-en)
- [antirez Twitter Announcement](https://x.com/antirez/status/2019516583811674148)

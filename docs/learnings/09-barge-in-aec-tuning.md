# Barge-In AEC Tuning

## SpeexDSP Frame Size

The AEC frame size must be ~20ms (320 samples at 16kHz) for effective echo cancellation. Using 100ms frames (1600 samples) severely reduces AEC quality — Speex internally processes in small blocks, and oversized frames cause poor filter adaptation.

- **Correct**: `frame_size=320` (20ms), `filter_length=8000` (~500ms, handles room reverb)
- **Wrong**: `frame_size=1600` (100ms), `filter_length=4800` (300ms, too short for reverb tails)

The mic and reference stream `blocksize` must match the AEC frame size.

## Geigel Ratio Detection

Geigel double-talk detection compares raw mic RMS to reference (BlackHole) RMS:

- **Echo only**: ratio ~0.05–0.12 (mic picks up 5-12% of speaker output)
- **Real speech**: ratio 0.40+ (voice dominates over echo)
- **Threshold**: 0.15–0.40 depending on setup (configurable via `BARGE_IN_RATIO`)

Key: use raw mic (pre-AEC) for barge-in detection. AEC-cleaned audio removes the echo signal needed for ratio comparison.

## Separate Reference Queues

Barge-in monitoring and the WLK send path both need reference frames from BlackHole. Using a single shared queue causes contention — whichever consumer drains the queue first starves the other.

Solution: push each ref callback frame to two independent queues (`barge_ref_queue` and `send_ref_queue`).

## Text Echo Filter

Even with proper AEC, some TTS bleed may reach WLK transcription. The `_strip_tts_echo()` method acts as a safety net:
- Finds longest consecutive run of TTS words at start of transcription
- Strips them if ≥3 words match
- Fuzzy fallback: if >50% of transcription words appear in TTS text, treat as echo

## TTS Overlap Prevention

Always kill any previous `say` process before starting a new one. Multiple concurrent TTS processes produce garbled audio and confuse AEC.

## Future: DTLN-AEC

If SpeexDSP proves insufficient, DTLN-AEC is a modern ML-based alternative that runs on CPU and handles non-linear echo better than traditional adaptive filters.

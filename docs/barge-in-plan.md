# Barge-In Implementation Plan

## Goal
Allow the user to interrupt TTS playback by speaking (like ChatGPT voice mode).

## Problem
Laptop speakers and mic are close together. The mic picks up TTS echo, making it impossible to distinguish user speech from echo using energy alone.

## Solution: BlackHole + Geigel Double-Talk Detection

### Prerequisites
1. `brew install --cask blackhole-2ch` (needs sudo + reboot)
2. Create Multi-Output Device in Audio MIDI Setup:
   - Open `/Applications/Utilities/Audio MIDI Setup.app`
   - Click `+` → "Create Multi-Output Device"
   - Check "Built-in Output" (must be first) and "BlackHole 2ch"
   - Set Multi-Output Device as system output
3. `pip install adaptfilt` in WLK venv (fallback if Geigel isn't enough)

### How It Works
1. TTS plays through Multi-Output → goes to speakers AND BlackHole
2. Capture BlackHole stream as clean reference signal (what TTS sounds like)
3. Capture mic stream simultaneously (echo + possible user speech)
4. **Geigel DTD**: Compare mic power vs reference power each frame
   - If `mic_power > threshold * ref_power` → user is speaking → kill TTS → start capture
   - If TTS PID dies naturally → start capture as before (zero gap)

### Implementation Steps

#### Step 1: Detect BlackHole device
- Auto-detect BlackHole device index via `sounddevice.query_devices()`
- Add `BLACKHOLE_DEVICE` to `config/defaults.env` (auto-detected)
- Add `--reference-device` flag to `wlk-capture.py`

#### Step 2: Dual-stream capture in wlk-capture.py
- Open two `sd.InputStream`: mic + BlackHole reference
- Both at 16kHz mono
- Mic stream → audio_queue (for WLK, after TTS ends)
- Reference stream → ref_queue (for DTD comparison)

#### Step 3: Geigel DTD monitor
- New `async def barge_in_monitor()` coroutine
- Runs only when `tts_active`
- Each frame: compare mic RMS vs reference RMS
- Grace period: first 0.5s after TTS starts (let audio stabilize)
- If barge-in detected: kill TTS PID, set tts_done_event, drain queue, start capture

#### Step 4: Update speak-and-capture.sh
- No changes needed (already passes --tts-pid)
- Add --reference-device passthrough from config

#### Step 5: Update install skill
- Add BlackHole install instructions
- Add Multi-Output device setup guide
- Auto-detect BlackHole device index and save to config

### Testing Plan

1. **Basic sanity**: TTS plays, nobody speaks, TTS finishes naturally → capture starts (existing behavior preserved)
2. **Barge-in detection**: TTS plays, user speaks mid-sentence → TTS killed, user speech captured
3. **No false positives**: TTS plays through speakers, mic picks up echo → should NOT trigger barge-in
4. **Threshold tuning**: Test with different volumes and distances
5. **Graceful fallback**: If BlackHole not installed, fall back to current PID-only behavior (no barge-in)

### Fallback: NLMS Adaptive Filter
If Geigel DTD is too noisy (false positives from room reverb), upgrade to NLMS:
- `pip install adaptfilt`
- Replace power comparison with adaptive filter that learns echo path
- Residual energy after echo subtraction = user speech
- More robust but more complex

### What We Already Tried (and Failed)
- **pyaec (Speex AEC)**: Fundamentally broken, distorts signal even with zero reference
- **Energy-based barge-in without reference**: Can't distinguish echo from speech on laptop
- **Warm mic with queue drain**: Echo still leaks through timing gaps

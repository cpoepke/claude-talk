# sox vs ffmpeg for Audio on macOS

## Problem

Early versions of the voice chat system used `sox` (via the `rec` command) for microphone recording. This proved unreliable on macOS.

## sox issues on macOS

- `rec` (sox's recording command) frequently produces empty or corrupted files
- Inconsistent behavior with different audio backends (coreaudio vs portaudio)
- Device selection is finicky - sometimes ignores the specified device
- No clear error messages when recording fails

## ffmpeg for recording

`ffmpeg` with the `avfoundation` input format is much more reliable on macOS:

```bash
ffmpeg -f avfoundation -i ":1" -t 5 -ar 16000 -ac 1 output.wav
```

- Consistent behavior across macOS versions
- Clear device listing: `ffmpeg -f avfoundation -list_devices true -i ""`
- Reliable error messages
- Supports all common audio formats

## What we actually use now

Neither! Both `sox` and `ffmpeg` were used in the early timed-recording approach (`talk.sh`, `talk-ptt.sh`). The current system uses **Python sounddevice** directly:

- `sounddevice.InputStream` for real-time mic access
- Direct int16 numpy arrays - no file I/O overhead
- Streams directly to WebSocket (WLK mode) or buffers in memory (VAD mode)

## Current role of each tool

| Tool | Current use |
|------|-------------|
| **sounddevice** (Python) | All mic recording (primary) |
| **ffmpeg** | Device listing only (`-list_devices`) |
| **sox** | Audio analysis/debugging only (`sox file.wav -n stat`) |
| **say** | macOS TTS output |

## Lesson

For real-time audio on macOS, skip shell tools entirely. Python `sounddevice` (which wraps PortAudio) gives you direct, reliable, low-latency mic access with full control over format, gain, and buffering.

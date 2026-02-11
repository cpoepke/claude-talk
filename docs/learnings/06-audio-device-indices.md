# Audio Device Index Instability on macOS

## Problem

macOS audio device indices are **not stable**. The MacBook Pro built-in microphone might be device `1` one minute and device `3` the next, depending on what apps are running.

## What causes index changes

- **Virtual audio devices**: Zoom, Microsoft Teams, Google Meet, and other video conferencing apps create virtual audio devices that claim low indices
- **Bluetooth devices**: Connecting/disconnecting AirPods or other Bluetooth audio shifts indices
- **USB audio**: Plugging in external mics or audio interfaces changes the numbering
- **App lifecycle**: Some virtual devices appear only when their app is running

## How to check current devices

```bash
# Using sounddevice (Python)
python3 -c "import sounddevice; print(sounddevice.query_devices())"

# Using ffmpeg
ffmpeg -f avfoundation -list_devices true -i ""
```

## Our approach

- `AUDIO_DEVICE` is configurable in `~/.claude-talk/config.env` (default: 1)
- The install script shows all detected devices so the user can identify their mic
- Users must update the config if their device index changes

## What we considered but didn't implement

- **Device name matching**: Query by name ("MacBook Pro Microphone") instead of index. Would be more robust but `sounddevice` device selection by name is unreliable across macOS versions.
- **Auto-detection**: Pick the first non-virtual input device. Hard to distinguish virtual from physical devices programmatically.
- **User prompt on start**: Ask which device each time. Too annoying for regular use.

## Practical advice

If transcription suddenly stops working after a Zoom/Teams call:
1. Run `python3 -c "import sounddevice; print(sounddevice.query_devices())"`
2. Find your actual microphone
3. Update `AUDIO_DEVICE` in `~/.claude-talk/config.env`

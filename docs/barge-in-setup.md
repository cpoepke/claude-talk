# Barge-In Setup Guide

Barge-in lets you interrupt Claude mid-sentence by speaking. Claude stops talking immediately and listens to what you say instead. Without it, you have to wait for Claude to finish before you can respond.

## How it works

The system uses **Geigel double-talk detection** to distinguish your voice from Claude's TTS output:

1. macOS `say` outputs audio to both your speakers AND a virtual loopback device (BlackHole 2ch)
2. During TTS playback, the capture script monitors two audio streams simultaneously:
   - **Mic stream**: Your microphone (contains your voice + TTS echo)
   - **Reference stream**: BlackHole (contains only clean TTS audio)
3. It compares the mic RMS power to the reference RMS power. TTS echo typically shows up as ~5-12% of the reference level. Real speech pushes the ratio above 40%
4. When the ratio exceeds the threshold for 3 consecutive frames, barge-in triggers: TTS is killed and capture switches to normal transcription mode

## Requirements

- **BlackHole 2ch** - Virtual audio loopback driver
- **Multi-Output Device** - macOS aggregate device that sends audio to both speakers and BlackHole

## Installation

### Step 1: Install BlackHole

```bash
brew install blackhole-2ch
```

Or download from [existential.audio/blackhole](https://existential.audio/blackhole/).

### Step 2: Create Multi-Output Device

1. Open **Audio MIDI Setup** (Spotlight: "Audio MIDI Setup" or `/Applications/Utilities/Audio MIDI Setup.app`)
2. Click the **+** button in the bottom left corner
3. Select **Create Multi-Output Device**
4. Check both:
   - **BlackHole 2ch**
   - Your speakers (e.g., "MacBook Pro Speakers" or your external speakers)
5. Make sure your speakers are listed **first** (drag to reorder if needed) - this ensures audio plays through speakers with correct timing
6. Optionally rename it to "Multi-Output (Speakers + BlackHole)" for clarity

### Step 3: Set system output

Go to **System Settings > Sound > Output** and select your new Multi-Output Device.

> **Note:** Multi-Output devices don't show a volume slider in the menu bar. Adjust volume through your speaker device directly in Audio MIDI Setup, or switch back to your normal output when not using voice chat.

## Configuration

Barge-in is **enabled by default**. The script auto-detects BlackHole 2ch. If BlackHole isn't found, barge-in silently disables and voice chat works normally (you just can't interrupt).

Settings in `~/.claude-talk/config.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `BARGE_IN` | `true` | Set to `false` to force-disable barge-in |
| `BLACKHOLE_DEVICE` | (auto) | Explicit device index for BlackHole. Leave unset for auto-detection |
| `BARGE_IN_RATIO` | `0.4` | Mic/reference ratio threshold. Lower = more sensitive, higher = less sensitive |

### Tuning the ratio

The default ratio of `0.4` works well for most setups. If you're having issues:

- **Barge-in triggers too easily** (Claude stops when you didn't speak): Increase to `0.5` or `0.6`
- **Barge-in doesn't trigger** (you have to shout to interrupt): Decrease to `0.3` or `0.2`
- **Echo ratio reference**: TTS echo through the mic is typically 0.05-0.12. Real speech is 0.5+. The threshold sits between these ranges

### Verify BlackHole is detected

Run a capture and check stderr for the auto-detection message:

```bash
source ~/.claude-talk/config.env
source "$CLAUDE_TALK_DIR/config/defaults.env"
python3 -c "import sounddevice; print(sounddevice.query_devices())" | grep -i blackhole
```

You should see a line with "BlackHole 2ch" and at least 2 input channels.

## Troubleshooting

**BlackHole not detected**
- Verify it's installed: `brew list blackhole-2ch`
- Check it appears in Audio MIDI Setup
- Restart your terminal after installation

**Barge-in enabled but not working**
- Confirm your system output is the Multi-Output Device (not just speakers)
- Check that BlackHole is checked in the Multi-Output Device configuration
- Look for "barge-in via ref device" in stderr output during voice chat

**Audio plays but no sound from speakers**
- In Audio MIDI Setup, ensure your speakers are checked in the Multi-Output Device
- Make sure speakers are the first (top) device in the list

**Volume control missing**
- This is normal for Multi-Output Devices in macOS
- Control volume through Audio MIDI Setup or your speaker's own controls
- Some users create a keyboard shortcut to switch between normal output and Multi-Output

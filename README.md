# claude-talk

Talk to Claude Code with your voice. Real-time speech-to-text, conversational AI, and spoken responses - all running locally on your Mac.

> **macOS (Apple Silicon) only** - Requires M1/M2/M3/M4 for MLX-accelerated transcription.

## How it works

```
You speak                                              Claude responds
    |                                                       |
    v                                                       v
   Mic                                                  Speaker
    |                                                       ^
    v                                                       |
 sounddevice (gain boost)                            macOS say (TTS)
    |                                                       ^
    v                                                       |
 WhisperLiveKit -----> transcribed text ----> Claude Code ---+
 (MLX Metal GPU)       (real-time)           (thinks & replies)
```

Everything runs locally except the Claude API call (via your Claude Code subscription). No audio leaves your machine - transcription happens on-device using Apple's Metal GPU.

![claude-talk screenshot](./claude-talk.jpeg)

## Quick start

### Install the plugin

```bash
# Option A: skills.sh
npx skills add cpoepke/claude-talk

# Option B: Claude Code plugin manager
/plugin install cpoepke/claude-talk

# Option C: Clone manually
git clone https://github.com/cpoepke/claude-talk.git
cd claude-talk
```

### Set up

Open Claude Code in the plugin directory (or any project if installed via Option A/B) and run:

```
/claude-talk:install
```

This will:
1. Install Python dependencies (WhisperLiveKit, MLX Whisper, sounddevice)
2. Walk you through a **spoken onboarding** - you'll hear each voice, pick a name, choose a personality style, and fine-tune how your assistant behaves

### Start talking

```
/claude-talk:start
```

Speak into your mic. Claude will listen, think, and respond out loud. Say "stop" or run `/claude-talk:stop` to end the session.

## Onboarding

The install command includes a personality setup where you choose:

| Step | What you pick | How it's presented |
|------|--------------|-------------------|
| **Voice** | Daniel, Karen, Moira, or Samantha | Each voice speaks a unique sentence so you hear the difference |
| **Name** | Claude, Jarvis, Friday, Nova, or custom | Each name is spoken in your chosen voice |
| **Style** | Casual, Professional, Witty, or Calm | Sample sentences in each style, spoken in your voice |
| **Your name** | First name, "Boss", or nothing | How the assistant addresses you |
| **Verbosity** | Short, Balanced, or Thorough | Controls response length |
| **Custom** | Free text | Any extra personality tweaks ("be sarcastic", "talk like a pirate") |

Your personality is saved to `~/.claude-talk/personality.md` and loaded every time you start a voice chat. Re-run `/claude-talk:install` to change it anytime.

## Commands

| Command | Description |
|---------|-------------|
| `/claude-talk:install` | Install dependencies + personality setup |
| `/claude-talk:start` | Start continuous voice chat |
| `/claude-talk:stop` | Stop voice chat |
| `/claude-talk:chat` | Quick single voice exchange (no persistent session) |
| `/claude-talk:config` | View/edit settings |
| `/claude-talk:help` | Show help |

## Requirements

- **macOS** with **Apple Silicon** (M1/M2/M3/M4)
- **Python 3.12** (`brew install python@3.12`)
- **Working microphone**
- **Claude Code** with active subscription
- **Experimental teams feature** - Required for voice chat loop

### Enable teams feature

Claude Talk requires the experimental agent teams feature. Set this environment variable before launching Claude Code:

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true
claude
```

Or add it permanently to your shell config:

```bash
# Add to ~/.zshrc or ~/.bashrc
echo 'export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true' >> ~/.zshrc
source ~/.zshrc
```

The `/claude-talk:install` command will configure this automatically in your `~/.claude/settings.json`.

Optional:
- `ffmpeg` - for listing audio devices
- `sox` - for audio analysis/debugging

## Configuration

Settings live in `~/.claude-talk/config.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `AUDIO_DEVICE` | `1` | Microphone device index |
| `MIC_GAIN` | `8.0` | Gain multiplier (built-in mic needs ~8.0, USB ~1.0) |
| `VOICE` | `Daniel` | macOS TTS voice (use `say -v '?'` to list all; Enhanced variants sound best) |
| `CAPTURE_MODE` | `wlk` | `wlk` (streaming) or `vad` (legacy batch) |
| `SILENCE_SECS` | `2.0` | Seconds of silence to end an utterance |
| `WLK_PORT` | `8090` | WhisperLiveKit server port |

Find your mic device index:
```bash
python3 -c "import sounddevice; print(sounddevice.query_devices())"
```

## Barge-in (interrupt Claude mid-speech)

Barge-in lets you interrupt Claude mid-sentence by speaking. Claude stops talking immediately and listens to what you say instead. Without it, you have to wait for Claude to finish before you can respond.

This requires **BlackHole 2ch** as a virtual audio loopback. Barge-in is enabled by default and silently disables if BlackHole isn't installed.

### Setup

1. Install BlackHole:
   ```bash
   brew install blackhole-2ch
   ```

2. Open **Audio MIDI Setup**, click **+**, select **Create Multi-Output Device**

3. Check both **BlackHole 2ch** and your speakers (speakers should be listed first)

4. Set your system output to the new Multi-Output Device in **System Settings > Sound > Output**

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `BARGE_IN` | `true` | Set to `false` to force-disable |
| `BLACKHOLE_DEVICE` | (auto) | Explicit device index for BlackHole |
| `BARGE_IN_RATIO` | `0.4` | Mic/reference ratio threshold. Lower = more sensitive |

See the [full barge-in guide](docs/barge-in-setup.md) for how the Geigel detection algorithm works, tuning advice, and troubleshooting.

## Architecture

For details on the capture pipeline, team architecture, echo prevention, and microphone gain, see [docs/architecture.md](docs/architecture.md).

## File structure

```
claude-talk/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── skills/
│   ├── install/SKILL.md         # Install + onboarding
│   ├── start/SKILL.md           # Start voice chat
│   ├── stop/SKILL.md            # Stop voice chat
│   ├── chat/SKILL.md            # Quick single exchange
│   ├── config/SKILL.md          # View/edit config
│   └── help/SKILL.md            # Show help
├── agents/
│   └── audio-mate.md            # Capture loop teammate
├── scripts/
│   ├── install.sh               # Dependency installer
│   ├── start-whisper-server.sh  # WLK/whisper-cpp launcher
│   ├── capture-utterance.sh     # Capture one utterance
│   ├── capture-and-print.sh     # Capture + print to stdout
│   ├── speak-and-capture.sh     # TTS then capture (echo prevention)
│   ├── wlk-capture.py           # WebSocket streaming capture
│   └── vad-capture.py           # Energy-based VAD capture
├── config/
│   └── defaults.env             # Default configuration
├── CLAUDE.md                    # Plugin context for Claude
├── LICENSE                      # MIT
└── README.md
```

## Troubleshooting

**No speech detected**
- Check your `AUDIO_DEVICE` index - it changes when virtual audio devices (Zoom, Teams) are active
- Increase `MIC_GAIN` if using a built-in microphone

**Whisper outputs `[Music]` or hallucinations**
- `MIC_GAIN` is too high - lower it
- Or lower `VAD_THRESHOLD` to capture quieter speech

**Echo / hearing own response back**
- The `speak-and-capture.sh` script handles this. If it persists, increase `SILENCE_SECS`

**WhisperLiveKit won't start**
- Check if port 8090 is in use: `lsof -i :8090`
- Kill existing process: `pkill -f "wlk.*--port"`

**Python 3.12 not found**
- `brew install python@3.12`
- WhisperLiveKit requires 3.12 specifically (not 3.13)

## Privacy

All audio processing happens locally on your Mac:
- **Transcription**: WhisperLiveKit runs Whisper via MLX on your Metal GPU - no cloud API
- **TTS**: macOS built-in `say` command - fully offline
- **Only exception**: The transcribed text is sent to Claude's API for the conversational response (same as typing in Claude Code)

No audio recordings are stored. Temporary WAV files are created in `/tmp/` during capture and immediately deleted after transcription.

## License

MIT

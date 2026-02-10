# Claude Voice Chat - Handoff Document

## What We Built

A fully local voice conversation system: speak into the mic, speech is transcribed in real-time via WhisperLiveKit (MLX Metal GPU), sent to Claude Code, and the response is spoken back via macOS TTS.

## Architecture (Current Best)

```
Mic → sounddevice (8x gain) → WebSocket → WhisperLiveKit (MLX/Metal) → text
text → Claude Code (team lead) → response → say -v Daniel → speaker
```

All processing is local except the Claude API call (via subscription).

## Scripts

| Script | Purpose |
|--------|---------|
| `start-whisper-server.sh` | Starts WLK (default) or whisper-cpp server |
| `capture-utterance.sh` | Captures one utterance via WLK WebSocket |
| `capture-and-print.sh` | Wrapper: capture + print to stdout + exit |
| `speak-and-capture.sh` | TTS response, wait, then capture next (no echo) |
| `wlk-capture.py` | Core: streams mic to WLK, detects end-of-utterance |
| `vad-capture.py` | Legacy: energy-based VAD + whisper-cpp HTTP |
| `talk.sh` | Simple timed recording mode |
| `talk-ptt.sh` | Push-to-talk mode |

## Quick Start

```bash
cd ~/Documents/repositories/external/claude-talk

# 1. Start WhisperLiveKit server
./start-whisper-server.sh &       # WLK on port 8090 (MLX Metal GPU)
# or: ./start-whisper-server.sh cpp &  # whisper-cpp on port 8178 (legacy)

# 2. Test single capture
./capture-and-print.sh            # speak, see transcription, exits

# 3. For team voice chat - see "Team Voice Chat" section below
```

## Team Voice Chat

### What Works: Foreground Loop Teammate

The teammate runs captures in the **foreground** (not background), looping continuously:

```
┌─────────────────────────────────────────────┐
│ WhisperLiveKit (port 8090, MLX Metal GPU)   │
│ WebSocket at ws://localhost:8090/asr        │
└──────────────┬──────────────────────────────┘
               │ WebSocket (streaming)
               ▲
┌──────────────┴──────────────────────────────┐
│ Audio Teammate (foreground loop)            │
│ 1. Run capture-and-print.sh (foreground)    │
│ 2. Read stdout → send text to team-lead     │
│ 3. Wait for team-lead reply                 │
│ 4. Run speak-and-capture.sh (foreground)    │
│    - Speaks response via say -v Daniel      │
│    - Then captures next utterance           │
│ 5. Read stdout → go to step 2              │
└──────────────┬──────────────────────────────┘
               │ SendMessage
               ▼
┌─────────────────────────────────────────────┐
│ Team Lead (main Claude)                     │
│ - Free to do coding tasks in parallel       │
│ - Responds conversationally when messaged   │
└─────────────────────────────────────────────┘
```

### Teammate Prompt (copy-paste to spawn)

```
You are a voice capture bot running a foreground loop.

Step 1: Run (foreground, timeout 60000):
  /path/to/capture-and-print.sh
Step 2: If text is "(silence)" → go to Step 1
Step 3: Send text to "team-lead" via SendMessage
Step 4: Wait for team-lead reply
Step 5: Run (foreground, timeout 60000):
  REPLY="response text" /path/to/speak-and-capture.sh
Step 6: Read output → go to Step 2

All Bash commands foreground. Timeout 60000. Never stop looping.
```

### Teammate Experiments Log

We tried 5 different teammate approaches. This is the full history:

#### audio (v1) - Background task, basic prompt
- **Approach**: Teammate runs `capture-utterance.sh` with `run_in_background=true`, goes idle, should wake on task completion
- **Result**: FAILED. Teammate went idle and never reacted to background task completion. Required manual nudging via SendMessage every time.
- **Lesson**: Background task completion notifications don't reliably wake teammates.

#### audio-2 (v2) - Background task, explicit instructions
- **Approach**: Same as v1 but with more detailed prompt about reading output and immediately starting next capture
- **Result**: FAILED. Teammate never even started the background task after being spawned. Went idle immediately.
- **Lesson**: Even explicit "DO IT NOW" instructions don't guarantee the teammate runs the command.

#### audio-3 (v3) - Background task, "mandatory" wording
- **Approach**: Very explicit prompt with "RULE 1, RULE 2" structure, "MANDATORY", "ZERO EXCEPTIONS" language
- **Result**: FAILED. Started the capture successfully, but did not react when it completed. When nudged, admitted: "I just waited for you to give me a nudge."
- **Lesson**: Strong wording doesn't fix the underlying issue - teammates don't process background task completion events.

#### audio-4 (v4) - Background task, "YOU MUST REACT" prompt
- **Approach**: Extremely forceful prompt: "YOU ARE A VOICE CAPTURE BOT", all-caps rules, "you MUST react IMMEDIATELY"
- **Result**: PARTIALLY FAILED. Started capture, but didn't react to completion. After nudge, did relay the transcription and started speak-and-capture. But the next cycle failed again - didn't detect second background task completion.
- **Lesson**: Can sometimes work for one cycle after nudging but never sustains autonomously.

#### audio-5 (v5) - FOREGROUND loop (SUCCESS!)
- **Approach**: Teammate runs capture in **foreground** (no `run_in_background`), with `timeout: 60000`. Loops: capture → send text → wait for reply → speak+capture → repeat.
- **Result**: SUCCESS! Teammate captures, sends transcription, speaks response, and loops back - all autonomously without any nudging.
- **Lesson**: **Foreground execution is the solution.** The teammate stays active during capture (using its Bash timeout), so there's no idle→wake issue. The teammate is "blocked" during capture but that's fine - it has nothing else to do.

#### Summary

| Version | Approach | Started capture? | Reacted to completion? | Autonomous loop? |
|---------|----------|-----------------|----------------------|-----------------|
| audio (v1) | Background task | Yes | No | No |
| audio-2 (v2) | Background task | No | N/A | No |
| audio-3 (v3) | Background task | Yes | No | No |
| audio-4 (v4) | Background task | Yes | No (once after nudge) | No |
| **audio-5 (v5)** | **Foreground loop** | **Yes** | **N/A (foreground)** | **YES** |

### What Also Works: Direct Loop by Team Lead

The team lead can run the loop directly using background tasks:
```
1. Run speak-and-capture.sh in background (run_in_background=true)
2. Task completes → read output → respond
3. Run speak-and-capture.sh again with REPLY="response"
4. Repeat
```
This works perfectly but blocks the team lead from doing other tasks. Use the foreground teammate (v5) instead when you want the team lead free for coding.

## Key Technical Details

### MacBook Pro Mic Gain
- Raw int16 signal is extremely weak (ambient RMS ~50, speech RMS ~200)
- **8x gain required** for WLK to transcribe reliably
- Applied in wlk-capture.py before sending to WebSocket
- Too much gain (10x+) causes clipping → Whisper outputs `[Music]`

### Echo Prevention
- `speak-and-capture.sh` sequences TTS then capture (not concurrent)
- Mic doesn't start until `say` finishes + 300ms settle time
- Without this, every capture includes the previous TTS response

### WLK End-of-Utterance Detection
- Monitors WebSocket transcription stream
- Text stable (unchanged) for 2.0 seconds = utterance complete
- Filters `[Music]`, `[INAUDIBLE]`, `[BLANK_AUDIO]` hallucinations
- Max duration 60 seconds safety cutoff

### Python Environments

| Venv | Location | Packages | For |
|------|----------|----------|-----|
| wlk-env | `/tmp/wlk-env/` | whisperlivekit, mlx-whisper, sounddevice | WLK streaming (primary) |
| voice_env | `/tmp/voice_env/` | sounddevice, numpy, scipy, requests | Legacy VAD capture |

### WhisperLive (Collabora) - BLOCKED
- `pip install whisper-live` fails on Python 3.12 AND 3.13 (macOS arm64)
- Pins `openai-whisper==20240930` which uses deprecated `pkg_resources`
- Newer `openai-whisper==20250625` fixes this but WhisperLive hasn't updated
- Would need Python 3.10 or 3.11, or `--no-deps` with manual overrides
- **WhisperLiveKit is better anyway** - superset with MLX support

## Environment

- **Machine**: MacBook Pro, Apple M4 Pro
- **OS**: macOS 26 (Darwin 25.1.0)
- **Python**: 3.13.5 (system), 3.12.11 (pyenv)
- **Mic**: Device index 1 (MacBook Pro Microphone) - check with `ffmpeg -f avfoundation -list_devices true -i ""`
- **TTS voices**: Daniel (UK), Karen (AU), Moira (IE)

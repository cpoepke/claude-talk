# Architecture

## Voice capture

The system uses two capture modes:

- **WLK (default)** - Streams mic audio via WebSocket to WhisperLiveKit, which runs Whisper via MLX on the Metal GPU. Transcription is real-time, word-by-word. End of utterance is detected when the transcription text stabilizes for 2 seconds.

- **VAD (legacy)** - Energy-based voice activity detection captures audio locally, then sends the complete WAV to a whisper-cpp HTTP server for batch transcription. Simpler but higher latency.

## Team architecture

`/claude-talk:start` spawns a teammate called **audio-mate** that runs a foreground capture loop:

```
audio-mate (haiku, foreground loop)        team-lead (you + Claude)
  |                                           |
  | 1. capture-and-print.sh (blocks)          |
  | 2. read transcription                     |
  | 3. send exact text -----> SendMessage --> receives user's words
  | 4. wait for reply  <----- SendMessage <-- thinks & responds
  | 5. speak-and-capture.sh                   |
  |    (TTS response, then capture next)      |
  | 6. go to step 2                           |
```

The audio-mate uses Haiku for minimal cost (it only relays text, never thinks). The team lead (Opus/Sonnet) handles all the actual conversation.

## Barge-in (interrupt mid-speech)

You can interrupt Claude while it's talking by speaking. Uses Geigel double-talk detection with BlackHole 2ch as a reference signal. See [barge-in setup guide](barge-in-setup.md) for installation and configuration.

## Echo prevention

`speak-and-capture.sh` sequences TTS and capture: it speaks the response first, waits for it to finish + 300ms settle time, then starts the microphone. Without this, the mic picks up the TTS response and feeds it back as the next "user" utterance.

## Microphone gain

MacBook Pro built-in microphones produce very weak int16 signals (ambient RMS ~50, speech ~200). An 8x gain multiplier is applied before sending to WhisperLiveKit. External USB mics typically need ~1.0-2.0x. Too much gain (10x+) causes clipping, which Whisper interprets as `[Music]`.

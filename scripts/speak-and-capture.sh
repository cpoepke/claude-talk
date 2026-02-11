#!/bin/bash
# speak-and-capture.sh - Speak a response via TTS with barge-in support
#
# Runs TTS and mic capture concurrently. If the user starts talking
# while TTS is playing, TTS is interrupted immediately and the user's
# speech is transcribed. If TTS finishes naturally, capture begins
# instantly with zero gap (mic was already warm).
#
# Usage:
#   REPLY="Hello world" ./speak-and-capture.sh
#   ./speak-and-capture.sh "Hello world"
#   ./speak-and-capture.sh              # skip TTS, just capture

set -euo pipefail

# Load config
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_TALK_DIR="${CLAUDE_TALK_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$CLAUDE_TALK_DIR/config/defaults.env"
[[ -f "$HOME/.claude-talk/config.env" ]] && source "$HOME/.claude-talk/config.env"

# Load state helpers
source "$SCRIPT_DIR/state.sh"

REPLY="${REPLY:-${1:-}}"
OUTPUT_FILE="/tmp/voice_chat/utterance_$(date +%s).txt"

if [[ -n "$REPLY" ]]; then
    # State: speaking
    voice_state_write STATUS=speaking

    # Start TTS in background
    say -v "$VOICE" "$REPLY" &
    SAY_PID=$!

    # Start capture with barge-in monitoring
    "$SCRIPT_DIR/capture-utterance.sh" "$OUTPUT_FILE" --tts-pid "$SAY_PID" >/dev/null 2>&1

    # Ensure say is stopped (in case capture ended before TTS)
    # Suppress "Terminated" message from bash
    kill "$SAY_PID" 2>/dev/null && wait "$SAY_PID" 2>/dev/null || true
else
    # No TTS - poll while muted before capturing
    MUTE_WAIT=0
    while is_muted; do
        sleep 1
        MUTE_WAIT=$((MUTE_WAIT + 1))
        if [[ $MUTE_WAIT -ge 55 ]]; then
            echo "(muted)"
            exit 0
        fi
    done

    # State: listening
    voice_state_write STATUS=listening

    # Just capture
    "$SCRIPT_DIR/capture-utterance.sh" "$OUTPUT_FILE" >/dev/null 2>&1
fi

# State: idle
voice_state_write STATUS=idle

# Print result
TEXT=$(cat "$OUTPUT_FILE" 2>/dev/null || echo "")
rm -f "$OUTPUT_FILE"

if [[ -n "$TEXT" && "$TEXT" != *"[Music]"* ]]; then
    echo "$TEXT"
else
    echo "(silence)"
fi

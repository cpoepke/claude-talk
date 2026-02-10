#!/bin/bash
# speak-and-capture.sh - Speak a response via TTS, then capture next utterance
#
# Sequences TTS and capture so the mic doesn't pick up Daniel's voice:
# 1. Speak the response text (if provided via env var or arg)
# 2. Wait for TTS to finish
# 3. Start mic capture
# 4. Print transcription to stdout and exit
#
# Usage:
#   REPLY="Hello world" ./speak-and-capture.sh
#   ./speak-and-capture.sh "Hello world"
#   ./speak-and-capture.sh              # skip TTS, just capture

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPLY="${REPLY:-${1:-}}"
VOICE="${VOICE:-Daniel}"
OUTPUT_FILE="/tmp/voice_chat/utterance_$(date +%s).txt"

# Step 1: Speak response (if any)
if [[ -n "$REPLY" ]]; then
    say -v "$VOICE" "$REPLY"
    # Small pause after TTS to let mic settle
    sleep 0.3
fi

# Step 2: Capture next utterance
"$SCRIPT_DIR/capture-utterance.sh" "$OUTPUT_FILE" >/dev/null 2>&1

# Step 3: Print result
TEXT=$(cat "$OUTPUT_FILE" 2>/dev/null || echo "")
rm -f "$OUTPUT_FILE"

if [[ -n "$TEXT" && "$TEXT" != *"[Music]"* ]]; then
    echo "$TEXT"
else
    echo "(silence)"
fi

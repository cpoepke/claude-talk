#!/bin/bash
# capture-and-print.sh - Capture one utterance and print to stdout
#
# Wrapper around capture-utterance.sh that:
# 1. Captures one utterance (blocks until speech + silence detected)
# 2. Prints the transcription to stdout
# 3. Exits cleanly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_FILE="/tmp/voice_chat/utterance_$(date +%s).txt"

# Run capture (stderr goes to stderr, stdout is the transcription)
"$SCRIPT_DIR/capture-utterance.sh" "$OUTPUT_FILE" >/dev/null 2>&1

# Read and print the result to stdout
TEXT=$(cat "$OUTPUT_FILE" 2>/dev/null || echo "")

if [[ -n "$TEXT" && "$TEXT" != *"[Music]"* ]]; then
    echo "$TEXT"
else
    echo "(silence)"
fi

# Cleanup
rm -f "$OUTPUT_FILE"

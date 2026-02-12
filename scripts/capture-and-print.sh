#!/bin/bash
# capture-and-print.sh - Capture one utterance and print to stdout
#
# Wrapper around capture-utterance.sh that:
# 1. Waits if muted (polls state file, outputs "(muted)" after 55s)
# 2. Captures one utterance (blocks until speech + silence detected)
# 3. Prints the transcription to stdout
# 4. Exits cleanly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load state helpers
source "$SCRIPT_DIR/state.sh"

# Exit immediately if session has been stopped
if [[ "$(voice_state_read SESSION)" == "stopped" ]]; then
    echo "(stopped)"
    exit 0
fi

# Poll while muted (output "(muted)" before 60s Bash timeout)
MUTE_WAIT=0
while is_muted; do
    sleep 1
    MUTE_WAIT=$((MUTE_WAIT + 1))
    if [[ $MUTE_WAIT -ge 55 ]]; then
        echo "(muted)"
        exit 0
    fi
done

# Update state: listening
voice_state_write STATUS=listening

OUTPUT_FILE="/tmp/voice_chat/utterance_$(date +%s).txt"

# Run capture (stderr goes to stderr, stdout is the transcription)
"$SCRIPT_DIR/capture-utterance.sh" "$OUTPUT_FILE" >/dev/null 2>&1

# Update state: idle
voice_state_write STATUS=idle

# Read and print the result to stdout
TEXT=$(cat "$OUTPUT_FILE" 2>/dev/null || echo "")

if [[ -n "$TEXT" && "$TEXT" != *"[Music]"* ]]; then
    echo "$TEXT"
else
    echo "(silence)"
fi

# Cleanup
rm -f "$OUTPUT_FILE"

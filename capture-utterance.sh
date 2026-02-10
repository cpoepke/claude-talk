#!/bin/bash
# capture-utterance.sh - Capture one complete utterance and exit
#
# Connects to WhisperLiveKit via WebSocket, streams mic audio,
# collects real-time transcription, and exits when utterance ends.
# Triggers background task completion in Claude Code teams.
#
# Usage:
#   ./capture-utterance.sh [output_file]
#
# Environment:
#   AUDIO_DEVICE  - sounddevice device index (default: 1)
#   WLK_URL       - WLK WebSocket URL (default: ws://localhost:8090/asr)
#   MIC_GAIN      - microphone gain multiplier (default: 5.0)
#   SILENCE_SECS  - silence duration to end utterance (default: 2.0)
#   CAPTURE_MODE  - "wlk" (default) or "vad" (legacy whisper-cpp mode)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_FILE="${1:-/tmp/voice_chat/utterance.txt}"
AUDIO_DEVICE="${AUDIO_DEVICE:-1}"
WLK_URL="${WLK_URL:-ws://localhost:8090/asr}"
MIC_GAIN="${MIC_GAIN:-8.0}"
SILENCE_SECS="${SILENCE_SECS:-2.0}"
CAPTURE_MODE="${CAPTURE_MODE:-wlk}"

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT_FILE")"

if [[ "$CAPTURE_MODE" == "wlk" ]]; then
    # WhisperLiveKit mode (default) - uses /tmp/wlk-env/
    VENV_PATH="/tmp/wlk-env"
    if [[ -f "$VENV_PATH/bin/activate" ]]; then
        source "$VENV_PATH/bin/activate"
    else
        echo "ERROR: WLK venv not found at $VENV_PATH" >&2
        echo "Create it with: python3.12 -m venv $VENV_PATH && $VENV_PATH/bin/pip install 'whisperlivekit[mlx-whisper]' mlx-whisper sounddevice" >&2
        exit 1
    fi

    exec python3 "$SCRIPT_DIR/wlk-capture.py" \
        --device "$AUDIO_DEVICE" \
        --server "$WLK_URL" \
        --output "$OUTPUT_FILE" \
        --gain "$MIC_GAIN" \
        --silence "$SILENCE_SECS"
else
    # Legacy VAD + whisper-cpp mode - uses /tmp/voice_env/
    VENV_PATH="/tmp/voice_env"
    WHISPER_URL="${WHISPER_URL:-http://localhost:8178}"
    VAD_THRESHOLD="${VAD_THRESHOLD:-200}"

    if [[ -f "$VENV_PATH/bin/activate" ]]; then
        source "$VENV_PATH/bin/activate"
    else
        echo "ERROR: Voice venv not found at $VENV_PATH" >&2
        exit 1
    fi

    exec python3 "$SCRIPT_DIR/vad-capture.py" \
        --device "$AUDIO_DEVICE" \
        --server "$WHISPER_URL" \
        --output "$OUTPUT_FILE" \
        --threshold "$VAD_THRESHOLD" \
        --silence "$SILENCE_SECS"
fi

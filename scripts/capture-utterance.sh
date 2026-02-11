#!/bin/bash
# capture-utterance.sh - Capture one complete utterance and exit
#
# Connects to WhisperLiveKit via WebSocket, streams mic audio,
# collects real-time transcription, and exits when utterance ends.
#
# Usage:
#   ./capture-utterance.sh [output_file] [--tts-pid PID]
#
# Environment:
#   AUDIO_DEVICE  - sounddevice device index (default: 1)
#   WLK_URL       - WLK WebSocket URL (default: ws://localhost:8090/asr)
#   MIC_GAIN      - microphone gain multiplier (default: 8.0)
#   SILENCE_SECS  - silence duration to end utterance (default: 2.0)
#   CAPTURE_MODE  - "wlk" (default) or "vad" (legacy whisper-cpp mode)

set -euo pipefail

# Load config
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_TALK_DIR="${CLAUDE_TALK_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$CLAUDE_TALK_DIR/config/defaults.env"
[[ -f "$HOME/.claude-talk/config.env" ]] && source "$HOME/.claude-talk/config.env"

OUTPUT_FILE="${1:-/tmp/voice_chat/utterance.txt}"
shift || true

# Parse optional arguments
TTS_PID=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tts-pid)
            TTS_PID="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT_FILE")"

if [[ "$CAPTURE_MODE" == "wlk" ]]; then
    VENV_PATH="$WLK_VENV"
    if [[ -f "$VENV_PATH/bin/activate" ]]; then
        source "$VENV_PATH/bin/activate"
    else
        echo "ERROR: WLK venv not found at $VENV_PATH" >&2
        echo "Run /claude-talk:install first" >&2
        exit 1
    fi

    if [[ -n "$TTS_PID" ]]; then
        exec python3 "$SCRIPT_DIR/wlk-capture.py" \
            --device "$AUDIO_DEVICE" \
            --server "$WLK_URL" \
            --output "$OUTPUT_FILE" \
            --gain "$MIC_GAIN" \
            --silence "$SILENCE_SECS" \
            --tts-pid "$TTS_PID"
    else
        exec python3 "$SCRIPT_DIR/wlk-capture.py" \
            --device "$AUDIO_DEVICE" \
            --server "$WLK_URL" \
            --output "$OUTPUT_FILE" \
            --gain "$MIC_GAIN" \
            --silence "$SILENCE_SECS"
    fi
else
    VENV_PATH="$VAD_VENV"
    if [[ -f "$VENV_PATH/bin/activate" ]]; then
        source "$VENV_PATH/bin/activate"
    else
        echo "ERROR: VAD venv not found at $VENV_PATH" >&2
        echo "Run /claude-talk:install first" >&2
        exit 1
    fi

    exec python3 "$SCRIPT_DIR/vad-capture.py" \
        --device "$AUDIO_DEVICE" \
        --server "$WHISPER_URL" \
        --output "$OUTPUT_FILE" \
        --threshold "$VAD_THRESHOLD" \
        --silence "$SILENCE_SECS"
fi

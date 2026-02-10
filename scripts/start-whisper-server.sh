#!/bin/bash
# start-whisper-server.sh - Start the transcription server
#
# Supports two modes:
#   wlk   - WhisperLiveKit with MLX (default, real-time streaming)
#   cpp   - whisper-cpp HTTP server (legacy, batch transcription)
#
# Usage:
#   ./start-whisper-server.sh          # start WLK (foreground)
#   ./start-whisper-server.sh &        # start WLK (background)
#   ./start-whisper-server.sh cpp      # start whisper-cpp instead
#   ./start-whisper-server.sh --check  # check if running

set -euo pipefail

# Load config
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_TALK_DIR="${CLAUDE_TALK_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$CLAUDE_TALK_DIR/config/defaults.env"
[[ -f "$HOME/.claude-talk/config.env" ]] && source "$HOME/.claude-talk/config.env"

MODE="${1:-wlk}"
CPP_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"

# --- Check mode ---
if [[ "$MODE" == "--check" ]]; then
    ok=0
    if curl -s -o /dev/null -w "" "http://localhost:$WLK_PORT/" 2>/dev/null; then
        echo "WhisperLiveKit is running on port $WLK_PORT"
        ok=1
    fi
    if pgrep -f "whisper-server.*--port.*$WHISPER_PORT" >/dev/null 2>&1; then
        echo "whisper-cpp server is running on port $WHISPER_PORT"
        ok=1
    fi
    if [[ $ok -eq 0 ]]; then
        echo "No transcription server is running"
        exit 1
    fi
    exit 0
fi

# --- WhisperLiveKit mode (default) ---
if [[ "$MODE" == "wlk" ]]; then
    if [[ ! -f "$WLK_VENV/bin/activate" ]]; then
        echo "ERROR: WLK venv not found at $WLK_VENV" >&2
        echo "Run /claude-talk:voice-install first" >&2
        exit 1
    fi

    # Check if already running
    if curl -s -o /dev/null -w "" "http://localhost:$WLK_PORT/" 2>/dev/null; then
        echo "WhisperLiveKit already running on port $WLK_PORT"
        exit 0
    fi

    source "$WLK_VENV/bin/activate"

    echo "Starting WhisperLiveKit on port $WLK_PORT"
    echo "  Backend: mlx-whisper (Metal GPU)"
    echo "  Model: small.en"
    echo "  WebSocket: ws://localhost:$WLK_PORT/asr"
    echo ""

    exec wlk \
        --model small.en \
        --language en \
        --backend mlx-whisper \
        --port "$WLK_PORT" \
        --pcm-input

# --- whisper-cpp mode (legacy) ---
elif [[ "$MODE" == "cpp" ]]; then
    if ! command -v whisper-server >/dev/null 2>&1; then
        echo "ERROR: whisper-server not found. Install with: brew install whisper-cpp" >&2
        exit 1
    fi

    if [[ ! -f "$WHISPER_MODEL" ]]; then
        echo "Downloading whisper model (small.en, ~465MB)..."
        mkdir -p "$(dirname "$WHISPER_MODEL")"
        curl -L "$CPP_MODEL_URL" -o "$WHISPER_MODEL"
    fi

    if pgrep -f "whisper-server.*--port.*$WHISPER_PORT" >/dev/null 2>&1; then
        echo "whisper-cpp server already running on port $WHISPER_PORT"
        exit 0
    fi

    echo "Starting whisper-cpp on port $WHISPER_PORT (Metal GPU)"
    echo ""

    exec whisper-server \
        --model "$WHISPER_MODEL" \
        --port "$WHISPER_PORT" \
        --threads 4 \
        --language en
else
    echo "Usage: $0 [wlk|cpp|--check]" >&2
    exit 1
fi

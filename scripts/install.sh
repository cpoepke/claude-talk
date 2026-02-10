#!/bin/bash
# install.sh - Install claude-talk voice chat dependencies
#
# Creates Python venvs, installs WhisperLiveKit + audio tools,
# detects audio devices, and writes user config.
#
# Usage:
#   bash scripts/install.sh [--force]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FORCE=false

for arg in "$@"; do
    [[ "$arg" == "--force" ]] && FORCE=true
done

# Load defaults
source "$PROJECT_DIR/config/defaults.env"

echo "=== Claude Talk Installer ==="
echo "Platform: macOS (Apple Silicon) only"
echo ""

# --- Platform check ---
if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: claude-talk requires macOS. Detected: $(uname)"
    exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
    echo "WARNING: Apple Silicon (arm64) recommended for MLX acceleration."
    echo "Detected: $(uname -m). WhisperLiveKit may fall back to CPU."
fi

# --- Check for Python 3.12 ---
PYTHON=""
for p in python3.12 python3; do
    if command -v "$p" >/dev/null 2>&1; then
        ver=$("$p" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if [[ "$ver" == "3.12" ]]; then
            PYTHON="$p"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.12 is required but not found."
    echo "Install with: brew install python@3.12"
    exit 1
fi
echo "Python: $PYTHON ($($PYTHON --version))"

# --- Check optional tools ---
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "WARNING: ffmpeg not found (optional, for device listing). Install: brew install ffmpeg"
fi
if ! command -v sox >/dev/null 2>&1; then
    echo "WARNING: sox not found (optional, for audio analysis). Install: brew install sox"
fi

# --- Create directories ---
mkdir -p "$HOME/.claude-talk/models"
mkdir -p "$HOME/.claude-talk/venvs"

# --- WhisperLiveKit venv ---
echo ""
echo "--- Setting up WhisperLiveKit environment ---"
if [[ "$FORCE" == "true" ]] && [[ -d "$WLK_VENV" ]]; then
    echo "Removing existing WLK venv (--force)..."
    rm -rf "$WLK_VENV"
fi

if [[ ! -f "$WLK_VENV/bin/activate" ]]; then
    echo "Creating venv at $WLK_VENV..."
    "$PYTHON" -m venv "$WLK_VENV"
fi

echo "Installing packages (this may take a few minutes)..."
"$WLK_VENV/bin/pip" install -q --upgrade pip
"$WLK_VENV/bin/pip" install -q 'whisperlivekit[mlx-whisper]' mlx-whisper sounddevice websockets numpy
echo "WhisperLiveKit environment ready."

# --- VAD venv (lighter, for fallback) ---
echo ""
echo "--- Setting up VAD environment ---"
if [[ "$FORCE" == "true" ]] && [[ -d "$VAD_VENV" ]]; then
    echo "Removing existing VAD venv (--force)..."
    rm -rf "$VAD_VENV"
fi

if [[ ! -f "$VAD_VENV/bin/activate" ]]; then
    echo "Creating venv at $VAD_VENV..."
    "$PYTHON" -m venv "$VAD_VENV"
fi

echo "Installing packages..."
"$VAD_VENV/bin/pip" install -q --upgrade pip
"$VAD_VENV/bin/pip" install -q sounddevice numpy scipy requests
echo "VAD environment ready."

# --- Detect audio devices ---
echo ""
echo "--- Audio Devices ---"
"$WLK_VENV/bin/python3" -c "import sounddevice; print(sounddevice.query_devices())" 2>/dev/null || echo "(could not list devices)"

# --- Write user config ---
if [[ ! -f "$HOME/.claude-talk/config.env" ]] || [[ "$FORCE" == "true" ]]; then
    cat > "$HOME/.claude-talk/config.env" << CONF
# Claude Talk - User Configuration
# Uncomment and edit values to override defaults
# See $PROJECT_DIR/config/defaults.env for all options

CLAUDE_TALK_DIR="$PROJECT_DIR"

# AUDIO_DEVICE=1
# MIC_GAIN=8.0
# VOICE=Daniel
# CAPTURE_MODE=wlk
# SILENCE_SECS=2.0
CONF
    echo ""
    echo "Created config at ~/.claude-talk/config.env"
    echo "  CLAUDE_TALK_DIR=$PROJECT_DIR"
else
    # Ensure CLAUDE_TALK_DIR is set in existing config
    if ! grep -q "^CLAUDE_TALK_DIR=" "$HOME/.claude-talk/config.env" 2>/dev/null; then
        echo "" >> "$HOME/.claude-talk/config.env"
        echo "CLAUDE_TALK_DIR=\"$PROJECT_DIR\"" >> "$HOME/.claude-talk/config.env"
        echo "Added CLAUDE_TALK_DIR to existing config."
    fi
fi

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Next steps:"
echo "  1. Check audio device index above and update ~/.claude-talk/config.env if needed"
echo "  2. Start voice chat: /claude-talk:voice-start"
echo "  3. For help: /claude-talk:voice-help"

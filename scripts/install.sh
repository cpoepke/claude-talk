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
# Prefer ARM64 Homebrew Python on Apple Silicon
for p in /opt/homebrew/bin/python3.12 python3.12 python3; do
    if command -v "$p" >/dev/null 2>&1; then
        ver=$("$p" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        arch=$("$p" -c 'import platform; print(platform.machine())')
        if [[ "$ver" == "3.12" ]]; then
            PYTHON="$p"
            if [[ "$arch" == "arm64" ]]; then
                break  # Found ARM64 Python, use it
            fi
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
"$WLK_VENV/bin/pip" install -q whisperlivekit mlx-whisper sounddevice websockets numpy fastapi uvicorn pydantic
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
# BARGE_IN=true
# BARGE_IN_RATIO=2.0
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

# --- Claude Code settings ---
echo ""
echo "--- Configuring Claude Code ---"
chmod +x "$PROJECT_DIR/scripts/statusline.sh"

SETTINGS_FILE="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"

# Build the statusline command that pipes stdin to our script
STATUSLINE_CMD="cat | bash \"$PROJECT_DIR/scripts/statusline.sh\""

# Read existing settings or create empty object
if [[ -f "$SETTINGS_FILE" ]]; then
    SETTINGS=$(cat "$SETTINGS_FILE")
else
    SETTINGS='{}'
fi

# Back up existing statusline command (if any and not already ours)
EXISTING_CMD=$(echo "$SETTINGS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('statusLine',{}).get('command',''))" 2>/dev/null || echo "")
if [[ -n "$EXISTING_CMD" && "$EXISTING_CMD" != *"statusline.sh"* ]]; then
    echo "$EXISTING_CMD" > "$HOME/.claude-talk/statusline-backup.txt"
    echo "Backed up existing statusline to ~/.claude-talk/statusline-backup.txt"
fi

# Update settings with statusline and enable experimental teams feature
echo "$SETTINGS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['statusLine'] = {'type': 'command', 'command': sys.argv[1]}
if 'env' not in d:
    d['env'] = {}
d['env']['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = 'true'
json.dump(d, sys.stdout, indent=2)
" "$STATUSLINE_CMD" > "${SETTINGS_FILE}.tmp"
mv -f "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
echo "✓ Configured statusline"
echo "✓ Enabled experimental teams feature (required for voice chat)"

echo ""
echo "=== Installation complete! ==="
echo ""
echo "IMPORTANT: Restart Claude Code to enable the teams feature:"
echo "  1. Exit this session (Ctrl+D or /exit)"
echo "  2. Launch claude again"
echo ""
echo "Then:"
echo "  1. Check audio device index above and update ~/.claude-talk/config.env if needed"
echo "  2. Start voice chat: /claude-talk:start"
echo "  3. For help: /claude-talk:help"

#!/usr/bin/env bash
# Start audio server and wait for readiness
# Usage: bash scripts/lib/start-audio-server.sh
# Exits 0 on success, 1 on failure

set -euo pipefail

# Load config
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"

# Expand tilde in WLK_VENV
WLK_VENV="${WLK_VENV/#\~/$HOME}"

# Start audio server in background
(
    source "$WLK_VENV/bin/activate"
    nohup python3 "$CLAUDE_TALK_DIR/src/audio-server.py" >/dev/null 2>&1 &
)

# Wait for server to be ready (max 15 seconds)
for i in {1..15}; do
    if curl -s "http://localhost:${AUDIO_SERVER_PORT:-8150}/status" >/dev/null 2>&1; then
        echo "Audio server ready"
        exit 0
    fi
    sleep 1
done

echo "Audio server failed to start" >&2
exit 1

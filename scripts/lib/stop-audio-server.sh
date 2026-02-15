#!/usr/bin/env bash
# Stop audio server
# Usage: bash scripts/lib/stop-audio-server.sh

set -euo pipefail

# Load config for port
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/load-config.sh" 2>/dev/null || true

curl -s -X POST "http://localhost:${AUDIO_SERVER_PORT:-8150}/stop" || true

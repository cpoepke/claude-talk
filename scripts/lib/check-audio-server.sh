#!/usr/bin/env bash
# Check if audio server is running
# Usage: bash scripts/lib/check-audio-server.sh
# Exits 0 if running, 1 if not

set -euo pipefail

# Load config for port
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/load-config.sh" 2>/dev/null || true

curl -s "http://localhost:${AUDIO_SERVER_PORT:-8150}/status" >/dev/null 2>&1

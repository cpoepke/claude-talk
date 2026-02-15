#!/usr/bin/env bash
# Set voice session state
# Usage: bash scripts/lib/set-session-state.sh <active|stopped>

set -euo pipefail

STATE="${1:-active}"
echo "SESSION=$STATE" > "$HOME/.claude-talk/state"

#!/usr/bin/env bash
# Load claude-talk configuration (source this script)
# Usage: source scripts/lib/load-config.sh

# Find CLAUDE_TALK_DIR
if [ -f "$(pwd)/config/defaults.env" ]; then
    export CLAUDE_TALK_DIR="$(pwd)"
elif [ -f "$HOME/.claude-talk/config.env" ]; then
    export CLAUDE_TALK_DIR=$(grep '^CLAUDE_TALK_DIR=' "$HOME/.claude-talk/config.env" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "$(pwd)")
else
    export CLAUDE_TALK_DIR="$(pwd)"
fi

# Load defaults
if [ -f "$CLAUDE_TALK_DIR/config/defaults.env" ]; then
    set -a  # Auto-export all variables
    source "$CLAUDE_TALK_DIR/config/defaults.env"
    set +a
fi

# Load user overrides
if [ -f "$HOME/.claude-talk/config.env" ]; then
    set -a
    source "$HOME/.claude-talk/config.env"
    set +a
fi

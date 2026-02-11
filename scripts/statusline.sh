#!/bin/bash
# statusline.sh - Claude Code statusline with voice state indicator
#
# Reads JSON session data from stdin (model, workspace, etc.)
# Outputs: model + directory + git branch + voice state
#
# Voice state is read from ~/.claude-talk/state (if present and SESSION=active)

set -euo pipefail

# Read JSON from stdin
INPUT=$(cat)

# Extract model and workspace
MODEL=$(echo "$INPUT" | jq -r '.model.display_name // empty')
CWD=$(echo "$INPUT" | jq -r '.workspace.current_dir // empty')
DIR_NAME=$(basename "$CWD" 2>/dev/null || echo "")

# Git info
GIT_STATUS=""
if git -C "$CWD" rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git -C "$CWD" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [ -n "$(git -C "$CWD" --no-optional-locks status --porcelain 2>/dev/null)" ]; then
        GIT_STATUS="git:($BRANCH) ✗"
    else
        GIT_STATUS="git:($BRANCH)"
    fi
fi

# Voice state
VOICE_INDICATOR=""
STATE_FILE="$HOME/.claude-talk/state"
if [[ -f "$STATE_FILE" ]]; then
    SESSION=$(grep "^SESSION=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || echo "")
    if [[ "$SESSION" == "active" ]]; then
        STATUS=$(grep "^STATUS=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || echo "")
        MUTED=$(grep "^MUTED=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || echo "")
        if [[ "$MUTED" == "true" ]]; then
            # Red - muted
            VOICE_INDICATOR="\033[31m🚫 muted\033[0m"
        elif [[ "$STATUS" == "listening" ]]; then
            # Green - actively listening
            VOICE_INDICATOR="\033[32m🎙 listening\033[0m"
        elif [[ "$STATUS" == "speaking" ]]; then
            # Yellow - TTS playing
            VOICE_INDICATOR="\033[33m🔊 speaking\033[0m"
        else
            # Dim - idle (session active but between turns)
            VOICE_INDICATOR="\033[2m🎙 idle\033[0m"
        fi
    fi
fi

# Build output
OUTPUT=""
[[ -n "$MODEL" ]] && OUTPUT="\033[35m${MODEL}\033[0m"
[[ -n "$DIR_NAME" ]] && OUTPUT="${OUTPUT:+$OUTPUT }\033[36m${DIR_NAME}\033[0m"
[[ -n "$GIT_STATUS" ]] && OUTPUT="${OUTPUT:+$OUTPUT }\033[34m${GIT_STATUS}\033[0m"
[[ -n "$VOICE_INDICATOR" ]] && OUTPUT="${OUTPUT:+$OUTPUT }${VOICE_INDICATOR}"

printf "%b" "$OUTPUT"

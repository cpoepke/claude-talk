#!/bin/bash
# statusline.sh - Claude Code statusline with team and voice state indicator
#
# Reads JSON session data from stdin (model, workspace, team, etc.)
# Outputs: model + directory + team + git branch + voice state
#
# Voice state is read from ~/.claude-talk/state (if present and SESSION=active)

set -euo pipefail

# Read JSON from stdin
INPUT=$(cat)

# Extract model, workspace, and team
MODEL=$(echo "$INPUT" | jq -r '.model.display_name // empty' 2>/dev/null || echo "")
CWD=$(echo "$INPUT" | jq -r '.workspace.current_dir // empty' 2>/dev/null || echo "")
DIR_NAME=$(basename "$CWD" 2>/dev/null || echo "")
TEAM=$(echo "$INPUT" | jq -r '.team.name // empty' 2>/dev/null || echo "")

# Git info
GIT_STATUS=""
if [[ -n "$CWD" ]] && git -C "$CWD" rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git -C "$CWD" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    if [[ -n "$BRANCH" ]]; then
        if [ -n "$(git -C "$CWD" --no-optional-locks status --porcelain 2>/dev/null)" ]; then
            GIT_STATUS="git:($BRANCH) ✗"
        else
            GIT_STATUS="git:($BRANCH)"
        fi
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
        # Fetch live device info from audio server
        DEVICE_INFO=""
        SERVER_JSON=$(curl -s --max-time 1 http://localhost:8150/status 2>/dev/null || echo "")
        if [[ -n "$SERVER_JSON" ]]; then
            INPUT_DEV=$(echo "$SERVER_JSON" | jq -r '.input_device // empty' 2>/dev/null || echo "")
            OUTPUT_DEV=$(echo "$SERVER_JSON" | jq -r '.output_device // empty' 2>/dev/null || echo "")
            BARGE=$(echo "$SERVER_JSON" | jq -r '.barge_in // empty' 2>/dev/null || echo "")
            # Shorten common prefixes
            SHORT_IN=$(echo "$INPUT_DEV" | sed 's/MacBook Pro-//')
            SHORT_OUT=$(echo "$OUTPUT_DEV" | sed 's/MacBook Pro-//')
            [[ -n "$SHORT_IN" ]] && DEVICE_INFO="🎤 ${SHORT_IN}"
            [[ -n "$SHORT_OUT" ]] && DEVICE_INFO="${DEVICE_INFO:+$DEVICE_INFO | }🔈 ${SHORT_OUT}"
            if [[ "$BARGE" == "true" ]]; then
                DEVICE_INFO="${DEVICE_INFO:+$DEVICE_INFO | }⚡ barge-in:on"
            else
                DEVICE_INFO="${DEVICE_INFO:+$DEVICE_INFO | }barge-in:off"
            fi
        fi

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
        # Append device info with pipe separator
        [[ -n "$DEVICE_INFO" ]] && VOICE_INDICATOR="${VOICE_INDICATOR} \033[2m| ${DEVICE_INFO}\033[0m"
    fi
fi

# Build output with pipe separators
SEP=" \033[2m|\033[0m "
OUTPUT=""
[[ -n "$MODEL" ]] && OUTPUT="\033[35m${MODEL}\033[0m"
[[ -n "$DIR_NAME" ]] && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}\033[36m${DIR_NAME}\033[0m"
[[ -n "$TEAM" ]] && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}\033[33mteam:${TEAM}\033[0m"
[[ -n "$GIT_STATUS" ]] && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}\033[34m${GIT_STATUS}\033[0m"
[[ -n "$VOICE_INDICATOR" ]] && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}${VOICE_INDICATOR}"

printf "%b" "$OUTPUT"

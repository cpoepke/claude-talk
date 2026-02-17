#!/bin/bash
# statusline.sh - Claude Code statusline with voice state indicator
# Format: Model | Dir | git | [Personality] | [mic status] | ⚡interrupt:[on/off/--] | vol:[n%/--]

set -euo pipefail

INPUT=$(cat)

MODEL=$(echo "$INPUT" | jq -r '.model.display_name // empty' 2>/dev/null || echo "")
CWD=$(echo "$INPUT" | jq -r '.workspace.current_dir // empty' 2>/dev/null || echo "")
DIR_NAME=$(basename "$CWD" 2>/dev/null || echo "")
TEAM=$(echo "$INPUT" | jq -r '.team.name // empty' 2>/dev/null || echo "")
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || echo "")

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

# ── Voice state ───────────────────────────────────────────────────────────────
# Always show voice fields when SESSION=active. Use "--" for unknown values.

VOICE_BLOCK=""
STATE_FILE="$HOME/.claude-talk/state"
if [[ -f "$STATE_FILE" ]]; then
    SESSION=$(grep "^SESSION=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || echo "")
    if [[ "$SESSION" == "active" ]]; then
        STATUS=$(grep "^STATUS=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || echo "")
        MUTED=$(grep "^MUTED=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || echo "")

        # Personality (with color) — default "--"
        PERSONALITY_DISPLAY="--"
        PERSONALITY_COLOR="90"
        if [[ -n "$TMUX_PANE" ]]; then
            PERSONALITY_JSON=$(source "$HOME/.claude-talk/venvs/wlk/bin/activate" && claude-talk personality display --pane "$TMUX_PANE" --json 2>/dev/null || echo "")
            if [[ -n "$PERSONALITY_JSON" ]]; then
                PNAME=$(echo "$PERSONALITY_JSON" | jq -r '.display_name // empty' 2>/dev/null || echo "")
                PCOLOR=$(echo "$PERSONALITY_JSON" | jq -r '.color // "95"' 2>/dev/null || echo "95")
                [[ -n "$PNAME" ]] && PERSONALITY_DISPLAY="$PNAME" && PERSONALITY_COLOR="$PCOLOR"
            fi
        fi

        # Mic status (handle compound states like "speaking+listening")
        if [[ "$MUTED" == "true" ]]; then
            MIC_STATUS="\033[31m🚫 muted\033[0m"
        elif [[ "$STATUS" == *"listening"* && "$STATUS" == *"speaking"* ]]; then
            MIC_STATUS="\033[33m🔊🎙 live\033[0m"
        elif [[ "$STATUS" == *"listening"* ]]; then
            MIC_STATUS="\033[32m🎙 listening\033[0m"
        elif [[ "$STATUS" == *"speaking"* ]]; then
            MIC_STATUS="\033[33m🔊 speaking\033[0m"
        else
            MIC_STATUS="\033[2m🎙 idle\033[0m"
        fi

        # Server fields — default "--" when server unreachable
        BARGE_DISPLAY="\033[90m⚡interrupt:--\033[0m"
        VOL_DISPLAY="\033[90mvol:--\033[0m"
        SERVER_JSON=$(source "$HOME/.claude-talk/venvs/wlk/bin/activate" && claude-talk server status --json 2>/dev/null || echo "")
        if [[ -n "$SERVER_JSON" ]] && echo "$SERVER_JSON" | jq -e . >/dev/null 2>&1; then
            BARGE=$(echo "$SERVER_JSON" | jq -r 'if .barge_in == null then "" else (.barge_in | tostring) end' 2>/dev/null || echo "")
            VOLUME=$(echo "$SERVER_JSON" | jq -r '.volume // empty' 2>/dev/null || echo "")
            if [[ "$BARGE" == "true" ]]; then
                BARGE_DISPLAY="\033[33m⚡interrupt:on\033[0m"
            elif [[ "$BARGE" == "false" ]]; then
                BARGE_DISPLAY="\033[90m⚡interrupt:off\033[0m"
            fi
            [[ -n "$VOLUME" ]] && VOL_DISPLAY="\033[37mvol:${VOLUME}%\033[0m"
        fi

        SEP="\033[2m|\033[0m"
        VOICE_BLOCK="\033[${PERSONALITY_COLOR}m${PERSONALITY_DISPLAY}\033[0m ${SEP} ${MIC_STATUS} ${SEP} ${BARGE_DISPLAY} ${SEP} ${VOL_DISPLAY}"
    fi
fi

# ── Build output ───────────────────────────────────────────────────────────────
SEP=" \033[2m|\033[0m "
OUTPUT=""
[[ -n "$MODEL" ]]          && OUTPUT="\033[35m${MODEL}\033[0m"
[[ -n "$DIR_NAME" ]]       && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}\033[36m${DIR_NAME}\033[0m"
[[ -n "$TEAM" ]]           && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}\033[33mteam:${TEAM}\033[0m"
[[ -n "$GIT_STATUS" ]]     && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}\033[34m${GIT_STATUS}\033[0m"
[[ -n "$VOICE_BLOCK" ]]    && OUTPUT="${OUTPUT:+$OUTPUT${SEP}}${VOICE_BLOCK}"

printf "%b" "$OUTPUT"

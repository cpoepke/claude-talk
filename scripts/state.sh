#!/bin/bash
# state.sh - Shared voice state helpers
#
# Source this file to get functions for reading/writing the voice state file.
# State file location: ~/.claude-talk/state
#
# Usage:
#   source "$(dirname "$0")/state.sh"
#   voice_state_write SESSION=active STATUS=listening MUTED=false
#   voice_state_read STATUS    # prints "listening"
#   is_muted && echo "yes"

STATE_FILE="$HOME/.claude-talk/state"

# Write one or more KEY=VALUE pairs to the state file atomically.
# Existing keys are updated; new keys are appended.
# Usage: voice_state_write KEY1=val1 KEY2=val2 ...
voice_state_write() {
    local lockdir="${STATE_FILE}.lock"
    # Ensure directory exists
    mkdir -p "$(dirname "$STATE_FILE")"

    # Acquire lock via mkdir (atomic on all POSIX systems including macOS)
    local retries=50
    while ! mkdir "$lockdir" 2>/dev/null; do
        retries=$((retries - 1))
        if [[ $retries -le 0 ]]; then
            # Stale lock - force remove and retry once
            rm -rf "$lockdir"
            if ! mkdir "$lockdir" 2>/dev/null; then
                echo "voice_state_write: failed to acquire lock" >&2
                return 1
            fi
            break
        fi
        sleep 0.1
    done

    local tmp="${STATE_FILE}.tmp.$$"
    # Start from existing file or empty
    if [[ -f "$STATE_FILE" ]]; then
        cp "$STATE_FILE" "$tmp"
    else
        : > "$tmp"
    fi
    for pair in "$@"; do
        local key="${pair%%=*}"
        local val="${pair#*=}"
        if grep -q "^${key}=" "$tmp" 2>/dev/null; then
            local tmp2="${STATE_FILE}.tmp2.$$"
            grep -v "^${key}=" "$tmp" > "$tmp2" || true
            echo "${key}=${val}" >> "$tmp2"
            mv -f "$tmp2" "$tmp"
        else
            echo "${key}=${val}" >> "$tmp"
        fi
    done
    mv -f "$tmp" "$STATE_FILE"

    # Release lock
    rm -rf "$lockdir"
}

# Read a single value from the state file.
# Usage: voice_state_read KEY
voice_state_read() {
    local key="$1"
    if [[ -f "$STATE_FILE" ]]; then
        grep "^${key}=" "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2-
    fi
}

# Returns 0 (true) if MUTED=true in the state file.
is_muted() {
    [[ "$(voice_state_read MUTED)" == "true" ]]
}

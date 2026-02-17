#!/bin/bash
# UserPromptSubmit hook: Track current session ID for claude-talk
# Writes CLAUDE_SESSION_ID to ~/.claude-talk/current-session so that
# `claude-talk session register` can identify the current conversation.

if [ -n "$CLAUDE_SESSION_ID" ]; then
    mkdir -p ~/.claude-talk
    printf "%s" "$CLAUDE_SESSION_ID" > ~/.claude-talk/current-session
fi

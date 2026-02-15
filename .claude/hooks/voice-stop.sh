#!/bin/bash
# Stop hook: bridges audio ↔ conversation with zero Claude API overhead.
# Fires after each assistant turn. If voice session is active, speaks the
# response via TTS, captures user's next utterance, and blocks stopping
# so the transcription is injected back into the conversation.
#
# Uses server-side buffering: after getting speech, tells the audio server
# to start listening immediately (/queue-listen) so the mic is hot while
# Claude thinks. Next /speak checks the buffer first.

# Activate venv for claude-talk CLI
source "$HOME/.claude-talk/venvs/wlk/bin/activate"

INPUT=$(cat)

# Extract session ID from hook input
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
if [[ -z "$SESSION_ID" ]]; then
  exit 0
fi

# Check if this session is active (claims it if old state file says active)
if ! claude-talk session check-or-claim "$SESSION_ID" 2>/dev/null; then
  # Not our session — exit silently
  exit 0
fi

# Load session's personality and update audio server voice if needed
SESSION_INFO=$(claude-talk session get-personality "$SESSION_ID" 2>/dev/null)
if [[ -n "$SESSION_INFO" ]]; then
  SESSION_VOICE=$(echo "$SESSION_INFO" | jq -r '.voice // empty')
  if [[ -n "$SESSION_VOICE" ]]; then
    # Update audio server voice for this session
    curl -s -X POST http://localhost:8150/voice \
      -H 'Content-Type: application/json' \
      -d "$(jq -n --arg voice "$SESSION_VOICE" '{voice: $voice}')" >/dev/null 2>&1
  fi
fi

# Extract last assistant text from transcript JSONL
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path')
LAST_MSG=$(tail -r "$TRANSCRIPT" | while IFS= read -r line; do
  ROLE=$(echo "$line" | jq -r '.message.role // empty' 2>/dev/null)
  if [[ "$ROLE" == "assistant" ]]; then
    # If message contains tool_use blocks, only speak text AFTER the last tool_use
    # (preamble like "Let me read the file" shouldn't be spoken)
    HAS_TOOLS=$(echo "$line" | jq '[.message.content[] | select(.type=="tool_use")] | length' 2>/dev/null)
    if [[ "$HAS_TOOLS" -gt 0 ]]; then
      LAST_TOOL_IDX=$(echo "$line" | jq '[.message.content | to_entries[] | select(.value.type=="tool_use") | .key] | last' 2>/dev/null)
      echo "$line" | jq -r --argjson idx "$LAST_TOOL_IDX" '[.message.content[($idx+1):] | .[] | select(.type=="text") | .text] | join(" ")' 2>/dev/null
    else
      echo "$line" | jq -r '[.message.content[] | select(.type=="text") | .text] | join(" ")' 2>/dev/null
    fi
    break
  fi
done)

if [[ -z "$LAST_MSG" ]]; then
  exit 0
fi

# Speak my response and capture next utterance (with barge-in if available)
RESULT=$(curl -s -X POST http://localhost:8150/speak \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg text "$LAST_MSG" '{text: $text}')" \
  --max-time 3600)

# Audio server crashed or not responding
if [[ $? -ne 0 || -z "$RESULT" ]]; then
  jq -n '{decision: "block", reason: "Audio server not responding. The voice session may have crashed. Ask the user what to do."}'
  exit 0
fi

TEXT=$(echo "$RESULT" | jq -r '.text // empty')

# WLK connection error — don't retry, report to Claude
if [[ "$TEXT" == "(wlk_error)" ]]; then
  jq -n '{decision: "block", reason: "Whisper speech recognition is not responding. Ask the user if they want to restart the voice session."}'
  exit 0
fi

# If silence/empty, re-listen directly (don't go back through Claude which would trigger another TTS)
SILENCE_RETRIES=0
MAX_SILENCE_RETRIES=60
while [[ -z "$TEXT" || "$TEXT" == "(silence)" || "$TEXT" == "(muted)" ]]; do
  SILENCE_RETRIES=$((SILENCE_RETRIES + 1))
  if [[ $SILENCE_RETRIES -gt $MAX_SILENCE_RETRIES ]]; then
    jq -n '{decision: "block", reason: "No speech detected after extended listening. Ask the user if they are still there."}'
    exit 0
  fi
  RESULT=$(curl -s http://localhost:8150/listen --max-time 3600)
  if [[ $? -ne 0 || -z "$RESULT" ]]; then
    jq -n '{decision: "block", reason: "Audio server not responding. The voice session may have crashed. Ask the user what to do."}'
    exit 0
  fi
  TEXT=$(echo "$RESULT" | jq -r '.text // empty')
  # Check for WLK error on retry
  if [[ "$TEXT" == "(wlk_error)" ]]; then
    jq -n '{decision: "block", reason: "Whisper speech recognition is not responding. Ask the user if they want to restart the voice session."}'
    exit 0
  fi
done

# Filter garbage transcriptions (partial hallucinations, echo fragments)
# Strip bracketed noise tags and check if anything meaningful remains
CLEAN=$(echo "$TEXT" | sed -E 's/\[[^]]*\]//g; s/^[[:space:].,!?-]+//; s/[[:space:].,!?-]+$//')
WORD_COUNT=$(echo "$CLEAN" | wc -w | tr -d ' ')
if [[ $WORD_COUNT -lt 2 || ${#CLEAN} -lt 5 ]]; then
  # Too short to be real speech — treat as silence and re-listen
  RESULT=$(curl -s http://localhost:8150/listen --max-time 3600)
  TEXT=$(echo "$RESULT" | jq -r '.text // empty')
  # Re-check after retry
  CLEAN=$(echo "$TEXT" | sed -E 's/\[[^]]*\]//g; s/^[[:space:].,!?-]+//; s/[[:space:].,!?-]+$//')
  WORD_COUNT=$(echo "$CLEAN" | wc -w | tr -d ' ')
  if [[ -z "$TEXT" || "$TEXT" == "(silence)" || "$TEXT" == "(muted)" || $WORD_COUNT -lt 2 ]]; then
    RESULT=$(curl -s http://localhost:8150/listen --max-time 3600)
    TEXT=$(echo "$RESULT" | jq -r '.text // empty')
  fi
fi

# Start buffered listen for the gap while Claude is thinking
curl -s -X POST http://localhost:8150/queue-listen >/dev/null 2>&1

# Block stopping and inject user's speech
jq -n --arg reason "The user said aloud: $TEXT" '{decision: "block", reason: $reason}'

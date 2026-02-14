#!/bin/bash
# Stop hook: bridges audio ↔ conversation with zero Claude API overhead.
# Fires after each assistant turn. If voice session is active, speaks the
# response via TTS, captures user's next utterance, and blocks stopping
# so the transcription is injected back into the conversation.
#
# Uses server-side buffering: after getting speech, tells the audio server
# to start listening immediately (/queue-listen) so the mic is hot while
# Claude thinks. Next /speak checks the buffer first.

INPUT=$(cat)

# Only run if voice session is active
SESSION=$(grep "^SESSION=" "$HOME/.claude-talk/state" 2>/dev/null | cut -d= -f2)
if [[ "$SESSION" != "active" ]]; then
  exit 0
fi

# Extract last assistant text from transcript JSONL
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path')
LAST_MSG=$(tail -r "$TRANSCRIPT" | while IFS= read -r line; do
  ROLE=$(echo "$line" | jq -r '.message.role // empty' 2>/dev/null)
  if [[ "$ROLE" == "assistant" ]]; then
    echo "$line" | jq -r '[.message.content[] | select(.type=="text") | .text] | join(" ")' 2>/dev/null
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

# If silence/empty, keep listening (re-trigger the hook)
if [[ -z "$TEXT" || "$TEXT" == "(silence)" || "$TEXT" == "(muted)" ]]; then
  jq -n '{decision: "block", reason: "No speech detected. Continue waiting silently."}'
  exit 0
fi

# Start buffered listen for the gap while Claude is thinking
curl -s -X POST http://localhost:8150/queue-listen >/dev/null 2>&1

# Block stopping and inject user's speech
jq -n --arg reason "The user said aloud: $TEXT" '{decision: "block", reason: $reason}'

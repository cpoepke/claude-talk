#!/bin/bash
# TeammateIdle hook - prevents audio-mate from going idle while voice session is active

# Check if voice session is still active
STATE=$(grep "^SESSION=" ~/.claude-talk/state 2>/dev/null | cut -d= -f2)

if [[ "$STATE" == "active" ]]; then
  echo "Voice session active — keep listening." >&2
  exit 2  # Prevents idle, feeds message back to audio-mate
fi

exit 0  # Allow idle when session is stopped

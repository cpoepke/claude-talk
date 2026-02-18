"""Voice stop hook: bridges audio ↔ conversation with zero Claude API overhead.

Fires after each assistant turn. If voice session is active, speaks the
response via TTS, captures user's next utterance, and blocks stopping
so the transcription is injected back into the conversation.

Uses server-side buffering: after getting speech, tells the audio server
to start listening immediately (/queue-listen) so the mic is hot while
Claude thinks. Next /speak checks the buffer first.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from ..channels import ChannelManager
from ..config import Config
from ..db import DB
from ..routing import get_target_sessions, parse_route
from ..session import SessionStore


def run():
    """Main hook entry point. Reads JSON from stdin, outputs decision to stdout."""
    # Read hook input
    hook_input = json.load(sys.stdin)

    # Extract session ID
    session_id = hook_input.get("session_id")
    if not session_id:
        sys.exit(0)

    # Check if this session is active (claims it if old state file says active)
    db = DB()
    store = SessionStore(db)
    if not store.check_or_claim(session_id):
        # Not our session — exit silently
        sys.exit(0)

    # Poll for messages in this session's channel FIRST
    # If there are messages from other sessions, inject them instead of speaking
    manager = ChannelManager(db)
    channel_id = manager.get_or_create_channel(session_id)
    messages = manager.get_unread_messages(channel_id)

    if messages:
        # We have incoming messages - inject the first one and mark as read
        msg = messages[0]
        manager.mark_read(msg["message_id"])
        route_label = f"[{msg['route_type']}] " if msg['route_type'] == 'broadcast' else ""
        _output_decision("block", f"{route_label}Message from another session: {msg['text']}")
        return

    # Extract last assistant text from transcript JSONL
    transcript_path = Path(hook_input.get("transcript_path", ""))
    if not transcript_path.exists():
        sys.exit(0)

    last_msg = _extract_last_assistant_message(transcript_path)
    if not last_msg:
        sys.exit(0)

    # Queue message with session's voice (handled by queue-speak command)
    # The queue processor will set the voice, speak, and listen
    result = _run_cli(["server", "queue-speak", last_msg, session_id, "--timeout", "3600"])
    if not result:
        _output_decision("block", "Audio server not responding. The voice session may have crashed. Ask the user what to do.")
        return

    text = result.get("text", "")

    # WLK connection error
    if text == "(stt_error)":
        _output_decision("block", "Whisper speech recognition is not responding. Ask the user if they want to restart the voice session.")
        return

    # Silence retry loop
    silence_retries = 0
    max_silence_retries = 60
    while not text or text in ("(silence)", "(muted)"):
        silence_retries += 1
        if silence_retries > max_silence_retries:
            _output_decision("block", "No speech detected after extended listening. Ask the user if they are still there.")
            return

        result = _run_cli(["server", "listen", "--timeout", "3600"])
        if not result:
            _output_decision("block", "Audio server not responding. The voice session may have crashed. Ask the user what to do.")
            return
        text = result.get("text", "")

        if text == "(stt_error)":
            _output_decision("block", "Whisper speech recognition is not responding. Ask the user if they want to restart the voice session.")
            return

    # Filter garbage transcriptions (partial hallucinations, echo fragments)
    clean = re.sub(r'\[[^]]*\]', '', text)  # Strip bracketed noise tags
    clean = re.sub(r'^[\s.,!?-]+', '', clean)
    clean = re.sub(r'[\s.,!?-]+$', '', clean)
    word_count = len(clean.split())

    if word_count < 2 or len(clean) < 5:
        # Too short — retry
        for _ in range(2):
            result = _run_cli(["server", "listen", "--timeout", "3600"])
            if result:
                text = result.get("text", "")
                if text and text not in ("(silence)", "(muted)"):
                    clean = re.sub(r'\[[^]]*\]', '', text)
                    clean = re.sub(r'^[\s.,!?-]+', '', clean)
                    clean = re.sub(r'[\s.,!?-]+$', '', clean)
                    word_count = len(clean.split())
                    if word_count >= 2:
                        break

    # Start buffered listen for the gap while Claude is thinking
    _run_cli(["server", "queue-listen"])

    # Parse routing from transcription
    route_type, target_session_id, cleaned_text = parse_route(text)
    target_sessions = get_target_sessions(route_type, target_session_id)

    # Route message to target sessions (reuse db and manager from above)

    for target_sid in target_sessions:
        if target_sid == session_id:
            # Message for this session - inject directly
            _output_decision("block", f"The user said aloud: {cleaned_text}")
            return
        else:
            # Message for another session - send to their channel
            channel_id = manager.get_or_create_channel(target_sid)
            manager.send_message(channel_id, cleaned_text, route_type, from_session_id=None)

    # If no targets (shouldn't happen), inject to this session as fallback
    if not target_sessions:
        _output_decision("block", f"The user said aloud: {text}")


def _extract_last_assistant_message(transcript_path: Path) -> str:
    """Extract the last assistant message from transcript JSONL."""
    lines = transcript_path.read_text().strip().split("\n")
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            message = entry.get("message", {})
            if message.get("role") != "assistant":
                continue

            content = message.get("content", [])

            # If message contains tool_use blocks, only speak text AFTER the last tool_use
            tool_indices = [i for i, block in enumerate(content) if block.get("type") == "tool_use"]

            if tool_indices:
                # Get text after last tool use
                last_tool_idx = tool_indices[-1]
                text_blocks = [
                    block.get("text", "")
                    for block in content[last_tool_idx + 1:]
                    if block.get("type") == "text"
                ]
            else:
                # No tools, get all text
                text_blocks = [
                    block.get("text", "")
                    for block in content
                    if block.get("type") == "text"
                ]

            return " ".join(text_blocks).strip()
        except (json.JSONDecodeError, KeyError):
            continue

    return ""


def _output_decision(decision: str, reason: str):
    """Output hook decision as JSON."""
    print(json.dumps({"decision": decision, "reason": reason}))


def _run_cli(args: list[str]) -> dict | None:
    """Run claude-talk CLI command and return JSON result."""
    try:
        result = subprocess.run(
            ["claude-talk"] + args,
            capture_output=True,
            text=True,
            timeout=3610,  # Slightly more than max listen timeout
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
        return None
    except Exception:
        return None

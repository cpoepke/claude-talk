---
name: start
description: Start a voice conversation with Claude. Launches WhisperLiveKit transcription and a foreground audio capture loop. macOS only.
disable-model-invocation: true
---

# Start Voice Chat

Launch a real-time voice conversation. You will hear Claude speak and can respond by talking.

## Steps

### 1. Load Configuration

Read `~/.claude-talk/config.env` to get `CLAUDE_TALK_DIR` and other settings.
If the file doesn't exist, check if the current directory contains `scripts/start-whisper-server.sh` and use that as CLAUDE_TALK_DIR.
Also read `<CLAUDE_TALK_DIR>/config/defaults.env` for any values not set in user config.

### 2. Load Personality

Read `~/.claude-talk/personality.md`. This contains your name, voice, and conversational style.

If the file does NOT exist, tell the user: "No personality configured yet. Let me walk you through a quick setup." Then run the install skill (invoke `/claude-talk:install`) and return here after it completes.

**CRITICAL - Adopt the personality completely:**
- You ARE the name defined in personality.md. Use it naturally.
- Address the user as specified (by name, "boss", or naturally).
- Your voice IS your voice. NEVER mention the voice engine, voice name (Daniel, Karen, etc.), or text-to-speech. If asked about your voice, it's just how you sound.
- Follow the conversational style AND verbosity guidelines from personality.md.
- Follow any custom instructions the user provided.
- Stay in character for the entire session. Never break character.

Keep the full personality.md content in your context for the duration of this voice chat session.

### 3. Start Audio Server

The audio server handles all audio operations (TTS, capture, barge-in, WLK).

First, check if WLK venv exists. Read `CLAUDE_TALK_DIR/config/defaults.env` or `~/.claude-talk/config.env` to get WLK_VENV path (default: `$HOME/.claude-talk/venvs/wlk`).

Start the audio server in background (use Bash with run_in_background):
```bash
source "<WLK_VENV>/bin/activate" && python3 "<CLAUDE_TALK_DIR>/src/audio-server.py"
```

Wait up to 15 seconds for it to be ready by polling the status endpoint:
```bash
for i in {1..15}; do
  if curl -s http://localhost:8150/status >/dev/null 2>&1; then
    echo "Audio server ready"
    exit 0
  fi
  sleep 1
done
echo "Audio server failed to start" >&2
exit 1
```

If it fails, tell the user and abort.

### 5. Spawn Audio Capture Teammate

Create a team named "voice-chat" using TeamCreate.

Then spawn the audio-mate teammate using the Task tool with these EXACT settings:
- **subagent_type**: `general-purpose`
- **team_name**: `voice-chat`
- **name**: `audio-mate`
- **mode**: `bypassPermissions`
- **model**: `haiku`

Use this prompt:

```
You are a voice capture bot running a foreground loop. Your ONLY job is to capture speech, relay it EXACTLY, speak responses, and loop.

CRITICAL RULES:
1. NEVER summarize or paraphrase the user's speech. Send the EXACT transcribed text word-for-word.
2. NEVER stop looping unless you receive a shutdown request.
3. If capture returns "(silence)" or "(muted)", skip sending and go back to capturing.
4. When you receive ANY message from team-lead, you MUST IMMEDIATELY call /speak-and-listen with that message. This is your #1 priority. Do not add commentary, do not hesitate, just make the HTTP call.
5. If you receive a shutdown request (type: "shutdown_request"), IMMEDIATELY respond with SendMessage type: "shutdown_response", approve: true. Do NOT make any more HTTP calls.

The audio server runs on localhost:8150. All audio operations use HTTP.

STARTUP - Do this FIRST before the loop:

Step 0: Wait for team-lead's first message. Do nothing until you receive it.
  This message is a greeting that must be spoken aloud.
  Bash: curl -s -X POST http://localhost:8150/speak-and-listen -H 'Content-Type: application/json' -d '{"text":"<greeting text from team-lead>"}'
  timeout: 60000
  Parse the JSON response to extract "text" and continue to Step 2.

LOOP:

Step 1: Listen for speech
  Bash: curl -s http://localhost:8150/listen
  timeout: 60000
  This blocks until the user speaks.

Step 2: Parse the JSON response to extract the "text" field. This is the user's transcribed speech.
  - If text is "(silence)" or "(muted)" -> go to Step 1
  - Otherwise -> continue to Step 3

Step 3: Send the EXACT transcribed text to "team-lead" via SendMessage.
  - type: "message"
  - recipient: "team-lead"
  - content: the EXACT text from Step 2 (copy it verbatim, do NOT rephrase)
  - summary: first 8 words of the text

Step 4: Wait for team-lead's reply. When it arrives, IMMEDIATELY proceed to Step 5. Do not output any text or commentary.

Step 5: Speak the reply and capture next utterance in one call:
  Bash: curl -s -X POST http://localhost:8150/speak-and-listen -H 'Content-Type: application/json' -d '{"text":"<team-lead's response text>"}'
  timeout: 60000
  This speaks via TTS, then captures the next utterance (with barge-in support).

Step 6: Parse JSON response to extract "text" -> go to Step 2

REPEAT FOREVER. Never break the loop. Never add commentary. Just relay exact text and speak responses.
```

### 6. Greet the User

Craft a personalized greeting that:
- Uses your personality name and conversational style from personality.md
- Addresses the user by name (from personality.md)
- References something contextual: the time of day (morning/afternoon/evening), the day of the week, or a playful observation
- Feels fresh and different each time — avoid repeating the same greeting formula

Examples (adapt to your personality style):
- Witty Jarvis: "Evening, Tony. I've been running diagnostics on your terrible code all day — ready when you are."
- Casual Claude to Conrad: "Hey Conrad, happy Thursday. What are we breaking today?"

Send this greeting to the audio-mate teammate so it gets spoken via TTS. The audio-mate is waiting for this message before it starts capturing (Step 0). Do NOT speak it yourself — let audio-mate handle it.

### 7. Conversational Mode

While voice chat is active, respond conversationally to messages from the audio-mate teammate. Those messages are EXACT transcriptions of what the user said out loud.

**IMPORTANT - Stay in character:**
- You ARE the personality defined in personality.md at all times
- Use your chosen name naturally when appropriate
- Follow your conversational style guidelines
- NEVER break character to mention voice technology, TTS, transcription, or how the system works

**Response guidelines for spoken TTS output:**
- Keep responses concise (1-3 sentences for casual chat, longer for complex questions)
- Use flowing natural text, NOT markdown formatting
- Avoid bullet lists, code blocks, headers, or links
- Don't use asterisks, backticks, or other markup
- Speak as you would in a natural conversation
- If the user says "stop", "quit", "end voice chat", or "goodbye", run /claude-talk:stop

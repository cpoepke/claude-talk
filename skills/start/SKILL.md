---
name: start
description: Start a voice conversation with Claude. Launches WhisperLiveKit transcription and a foreground audio capture loop. macOS only.
disable-model-invocation: true
---

# Start Voice Chat

Launch a real-time voice conversation. You will hear Claude speak and can respond by talking.

## Steps

### 1. Load Configuration

Get CLAUDE_TALK_DIR (use Bash):
```bash
if [ -d scripts/lib ]; then
  echo "$(pwd)"
else
  grep CLAUDE_TALK_DIR ~/.claude-talk/config.env 2>/dev/null | cut -d= -f2 | tr -d '"'
fi
```

(Config loading is now handled by the individual scripts.)

### 2. Load Personality

**Migration check:** If `~/.claude-talk/personality.md` exists but `~/.claude-talk/personalities/` does NOT:
1. Create `~/.claude-talk/personalities/`.
2. Read `~/.claude-talk/personality.md` and extract the name from `## Identity` → `- Name: <name>`.
3. Generate a filename (lowercase, hyphens).
4. If the file lacks a `## Voice` section, read VOICE from `~/.claude-talk/config.env` and add `## Voice\n- Voice: <voice>` after `## Identity`.
5. Copy to `~/.claude-talk/personalities/<name>.md`.
6. Write the name to `~/.claude-talk/active-personality`.
**No personality at all:** If `~/.claude-talk/personality.md` does NOT exist, tell the user: "No personality configured yet. Let me walk you through a quick setup." Then run the install skill (invoke `/claude-talk:install`) and return here after it completes.

**Load:** Read `~/.claude-talk/personality.md`. If it has a `## Voice` section, extract the voice and ensure `VOICE=` in `~/.claude-talk/config.env` matches.

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

Start the audio server and wait for readiness (use Bash):
```bash
bash "$CLAUDE_TALK_DIR/scripts/lib/start-audio-server.sh"
```

If it fails, tell the user and abort.

### 5. Activate Voice Session

Set the voice session state so the Stop hook knows to activate (use Bash):
```bash
bash "$CLAUDE_TALK_DIR/scripts/lib/set-session-state.sh" active
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

Just output this greeting as plain text in your response. Do NOT call the audio server directly — the Stop hook will automatically speak it aloud via `/speak` (which includes TTS + barge-in + capture) and inject the user's first utterance back into the conversation. You don't need to do anything else — just respond naturally.

### 7. Conversational Mode

While voice chat is active, respond conversationally. The Stop hook captures user speech and injects it as the reason in a "block" decision, appearing as "The user said aloud: ..." in your context.

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

**CRITICAL - Only the final text output gets spoken via TTS.**
- Do NOT output intermediate text before tool calls (e.g., "Let me check those logs!") — the user won't hear it, it just sits silently on screen.
- If you need to use tools (read files, run commands, etc.), do the tool calls FIRST with no preceding text, then put your complete response in the final text output.
- Every text message you output should be your full, spoken response — not a teaser before work happens.

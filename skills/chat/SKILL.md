---
name: chat
description: "Quick single voice exchange — converts text to speech, captures one spoken user response, and returns the transcription. No persistent session needed. Use when the user wants a one-off voice prompt-and-response, a quick text-to-speech exchange, or a single spoken interaction without maintaining a voice chat session."
disable-model-invocation: true
---

# Quick Voice Chat

Single voice exchange without starting a full voice chat session.

## Steps

1. Check if the audio server is running (use Bash):
   ```bash
   source ~/.claude-talk/venvs/wlk/bin/activate && claude-talk server status
   ```
   If it fails, tell the user: "Audio server isn't running. Start a session with `/claude-talk:start`, or I can start the server for you."

2. Speak a prompt asking the user their question (use Bash):
   ```bash
   source ~/.claude-talk/venvs/wlk/bin/activate && claude-talk server speak "What can I help you with?"
   ```

3. Wait for the transcription to arrive as a user message. Respond conversationally.

4. Speak the response via TTS (use Bash):
   ```bash
   source ~/.claude-talk/venvs/wlk/bin/activate && claude-talk server speak "<your response>"
   ```

5. Show the exchange: "You said: `<transcription>`" / "Response: `<your response>`"

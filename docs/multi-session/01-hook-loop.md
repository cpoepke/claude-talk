# Hook Loop Approach

**Status**: ✅ Production (main branch)
**Branch**: `main`
**Implementation**: `.claude/hooks/voice-stop.sh`

## Overview

The hook loop uses Claude Code's Stop hook to create a continuous conversation loop. When the user sends a stop signal, the hook captures it, speaks Claude's response via TTS, and immediately sends another stop signal to continue the loop.

## How It Works

```
User sends message
    ↓
Claude responds
    ↓
Stop hook triggered
    ↓
TTS speaks response
    ↓
Wait for user input (audio server records)
    ↓
Send next message
    ↓
(loop continues)
```

## Implementation

### Stop Hook (`.claude/hooks/voice-stop.sh`)
```bash
#!/bin/bash
source "$HOME/.claude-talk/venvs/wlk/bin/activate"
claude-talk hook stop
```

The `claude-talk hook stop` command:
- Speaks Claude's response via TTS
- Captures user speech via audio server
- Returns the transcribed text to inject as the next message

## Characteristics

### Pros
- ⚡ **Instant latency** - synchronous, no polling
- 🎯 **Simple** - single script, easy to understand
- 🎤 **Natural interrupt** - stop speaking → next iteration
- 📦 **Self-contained** - no external dependencies

### Cons
- 🚫 **Single session only** - hook is per-session
- 🔗 **Tight coupling** - audio server must be available
- ❌ **No multi-personality** - can't run multiple personalities simultaneously

## Performance

- **Latency**: 0ms (synchronous)
- **Response time**: Limited only by TTS speed and Claude API
- **Interrupt**: Immediate (Ctrl+C stops TTS)

## Use Cases

- ✅ Single personality voice interaction
- ✅ Simple conversational loop
- ✅ Testing and development
- ❌ Multiple personalities running concurrently
- ❌ Loosely coupled architecture

## Limitations

1. **Single session**: Only one Claude conversation can run at a time
2. **Session detection**: Audio server can't distinguish between multiple sessions
3. **Scalability**: Doesn't scale to multiple personalities

## When to Use

Use this approach when:
- Running a single personality
- Simplicity is valued over scalability
- Instant response is critical
- Multi-session support is not needed

## Migration Path

To support multiple personalities, migrate to:
- [Tmux Send-Keys approach](03-tmux-send-keys.md) for instant latency
- [Inbox JSON approach](02-inbox-json.md) for loosely coupled architecture (with 1s latency tradeoff)

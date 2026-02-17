# Tmux Send-Keys Approach

**Status**: 🌿 Feature branch (fully implemented)
**Branch**: `feature/tmux-teammates`
**Implemented**: 2026-02-16

## Overview

Direct injection of transcriptions into Claude Code sessions via `tmux send-keys`. Each personality runs in a dedicated tmux pane with its own Claude session. Audio server routes transcriptions to the appropriate session based on personality detection.

## How It Works

```
Audio server detects personality
    ↓
Lookup tmux target from sessions table
    ↓
Direct injection via: tmux send-keys -t {pane} "{transcription}" Enter
    ↓
Claude receives input instantly (no polling)
    ↓
Claude responds via hook loop
    ↓
Response spoken by TTS
    ↓
(continue hook loop in that session)
```

## Architecture

### Component Overview

```
┌─────────────────┐
│  Audio Server   │
│  (port 8091)    │
└────────┬────────┘
         │ Routes transcription
         │ based on personality
         ↓
┌──────────────────────────────────┐
│   TeammateManager                │
│   - Spawns Claude per personality│
│   - Manages tmux sessions        │
│   - Tracks session → pane mapping│
└──────────────────────────────────┘
         ↓
┌────────────────────────────────┐
│  Tmux Sessions (one per personality) │
├────────────────────────────────┤
│  Pane %1: Claude (Alice)       │
│  Pane %2: Claude (Bob)         │
│  Pane %3: Claude (Charlie)     │
└────────────────────────────────┘
         ↓
Each runs hook loop independently
```

### Database Schema

Added `tmux_target` column to sessions table:

```sql
ALTER TABLE sessions ADD COLUMN tmux_target TEXT;
```

Stores: `{session}:{window}.{pane}` (e.g., `main:1.2`)

### Session Flow

1. **Claim session**: `claude-talk session claim {session_id}`
   - Auto-detects tmux session/pane from `$TMUX`
   - Stores in `sessions.tmux_target`

2. **Route transcription**: Audio server looks up tmux target for active personality
3. **Inject**: `tmux send-keys -t {target} "{text}" Enter`

## Implementation

### TeammateManager (`src/claude_talk/teammates.py`)

```python
class TeammateManager:
    def spawn_teammate(self, personality_name: str) -> dict:
        """Spawn Claude teammate in new tmux session"""

        # Create tmux session
        session_name = f"claude-{personality_name}"
        tmux.create_session(session_name, detached=True)

        # Load personality
        personality = load_personality(personality_name)

        # Spawn Claude with personality context
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "-c",  # Continue previous session or start new
        ]

        tmux.send_keys(session_name, " ".join(cmd))

        # Create session record
        session_id = f"{personality_name}-{uuid.uuid4()}"
        session.claim(
            session_id,
            personality_name,
            tmux_target=f"{session_name}:0.0"
        )

        return {
            "session_id": session_id,
            "personality": personality_name,
            "tmux_target": f"{session_name}:0.0",
        }

    def spawn_all(self):
        """Spawn teammates for all personalities"""
        personalities = list_personalities()
        return [self.spawn_teammate(p) for p in personalities]
```

### Tmux Integration (`src/claude_talk/tmux.py`)

```python
def send_keys(target: str, text: str, literal: bool = True):
    """Send keys to tmux pane"""
    if literal:
        subprocess.run([
            "tmux", "send-keys", "-t", target, "-l", text
        ])
    else:
        subprocess.run([
            "tmux", "send-keys", "-t", target, text
        ])

def get_current_target() -> str:
    """Get current tmux session:window.pane from $TMUX"""
    tmux_env = os.getenv("TMUX")
    if not tmux_env:
        return None

    # Parse /tmp/tmux-{uid}/{server},{pid},{idx}
    session = subprocess.check_output([
        "tmux", "display-message", "-p", "#S"
    ]).decode().strip()

    window = subprocess.check_output([
        "tmux", "display-message", "-p", "#I"
    ]).decode().strip()

    pane = subprocess.check_output([
        "tmux", "display-message", "-p", "#P"
    ]).decode().strip()

    return f"{session}:{window}.{pane}"
```

### Audio Server Routing (`src/audio-server.py`)

```python
def route_transcription(transcription: str, personality: str):
    """Route transcription to appropriate Claude session"""

    # Get active session for personality
    session = get_active_session_for_personality(personality)

    if not session or not session.tmux_target:
        logger.error(f"No active session for {personality}")
        return False

    # Send directly via tmux
    tmux.send_keys(session.tmux_target, transcription, literal=True)
    tmux.send_keys(session.tmux_target, "Enter", literal=False)

    return True
```

### CLI Commands

```bash
# Spawn single teammate
claude-talk teammate spawn alice

# Spawn all personalities
claude-talk teammate spawn-all

# List active teammates
claude-talk teammate list

# Kill specific teammate
claude-talk teammate kill alice

# Kill all teammates
claude-talk teammate kill-all
```

### Server Auto-Spawn

```bash
# Start audio server and auto-spawn all teammates
claude-talk server start --spawn-teammates
```

## Characteristics

### Pros
- ⚡ **Instant latency** - direct injection, no polling
- 🎭 **Multi-personality** - one Claude session per personality
- 🔍 **Session isolation** - each personality has independent context
- 🎤 **Natural interrupt** - hook loop handles it per session
- 📊 **Session tracking** - database stores routing info
- 🚀 **Scalable** - easily add more personalities

### Cons
- 🔗 **Tmux dependency** - requires tmux running
- 🎛️ **Session management** - need to spawn/kill teammates
- 📝 **Database state** - requires SQLite for routing
- 🔄 **Complexity** - more moving parts than hook loop

## Performance

- **Latency**: 0ms (synchronous send-keys)
- **Routing overhead**: Single database lookup (~1ms)
- **Scalability**: Limited only by system resources
- **Interrupt**: Immediate (Ctrl+C in each session)

## Multi-Personality Flow

### Example: Three Personalities

1. **Startup**:
   ```bash
   claude-talk teammate spawn-all
   # Spawns: alice (pane %1), bob (pane %2), charlie (pane %3)
   ```

2. **User says**: "Hey Alice, what's the weather?"
   - Audio server detects "Alice"
   - Routes to alice's tmux pane
   - Alice's Claude session receives message
   - Alice responds via her hook loop

3. **User says**: "Bob, tell me a joke"
   - Audio server detects "Bob"
   - Routes to bob's tmux pane
   - Bob's Claude session receives message
   - Bob responds via his hook loop

4. **Concurrent**: Both Alice and Bob can be active simultaneously

### Session Isolation

Each teammate has:
- ✅ Independent conversation context
- ✅ Own personality prompt
- ✅ Separate tmux pane
- ✅ Individual hook loop
- ✅ Isolated history

## Use Cases

- ✅ Multiple personalities running simultaneously
- ✅ Instant response required
- ✅ Session isolation important
- ✅ Natural conversational flow
- ✅ Tmux environment available
- ❌ Extremely resource-constrained systems

## Limitations

1. **Tmux required** - won't work without tmux
2. **Resource usage** - one Claude process per personality
3. **Session management** - manual spawn/kill (can automate)
4. **No message persistence** - unlike inbox JSON approach

## When to Use

Use this approach when:
- Running multiple personalities simultaneously
- Instant latency is critical
- Tmux is available
- Resource usage is acceptable (multiple Claude processes)
- Session isolation is valuable

## Deployment

### Development
```bash
# Terminal 1: Start audio server with auto-spawn
claude-talk server start --spawn-teammates

# Terminal 2: Attach to specific personality
tmux attach -t claude-alice
```

### Production
```bash
# Auto-start teammates on boot
systemd service or launchd plist to spawn teammates

# Monitor with
tmux ls
claude-talk teammate list
```

## Migration from Hook Loop

1. ✅ Keep existing hook loop (`.claude/hooks/voice-stop.sh`)
2. ✅ Add TeammateManager for multi-personality
3. ✅ Update audio server to route based on personality
4. ✅ Each teammate uses same hook loop mechanism
5. ✅ Backward compatible (single personality still works)

## Why This Wins

**Best of both worlds:**
- ⚡ Instant latency (like hook loop)
- 🎭 Multi-personality (like inbox JSON)
- 🎯 Simple routing (tmux send-keys)
- 🔄 Familiar hook loop per session

**Trade-off:** Requires tmux and more resources, but delivers the best user experience for multi-personality voice interaction.

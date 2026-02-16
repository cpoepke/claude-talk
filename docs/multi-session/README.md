# Multi-Session Communication Experiments

This directory documents different approaches tested for sending voice transcriptions to Claude Code sessions, particularly for supporting multiple personalities simultaneously.

## Approaches Tested

### 1. [Hook Loop Approach](01-hook-loop.md) (Current Implementation)
- **Status**: ✅ Production (main branch)
- **Latency**: Instant (synchronous)
- **Multi-session**: ❌ Single session only
- Simple Stop hook loop that cycles between user input and Claude responses

### 2. [Inbox JSON Polling](02-inbox-json.md) (Investigated)
- **Status**: 🔬 Experimental (not implemented)
- **Latency**: ~1 second (polling)
- **Multi-session**: ✅ Native support (one team per session)
- Discovered Claude Code's teammate inbox messaging system

### 3. [Tmux Send-Keys](03-tmux-send-keys.md) (Implemented)
- **Status**: 🌿 Feature branch (`feature/tmux-teammates`)
- **Latency**: Instant (direct injection)
- **Multi-session**: ✅ Full support (teammate per personality)
- Direct tmux injection with TeammateManager

## Comparison Matrix

| Feature | Hook Loop | Inbox JSON | Tmux Send-Keys |
|---------|-----------|------------|----------------|
| **Latency** | Instant | ~1s | Instant |
| **Multi-session** | ❌ | ✅ | ✅ |
| **Complexity** | Simple | Medium | Medium |
| **Coupling** | Tight | Loose | Medium |
| **Barge-in** | Natural | Complex | Natural |
| **Scalability** | Single | High | High |
| **Implementation** | Hook script | Not impl. | Full impl. |

## Recommendations

- **Single personality**: Use Hook Loop (current)
- **Multiple personalities**: Use Tmux Send-Keys (feature/tmux-teammates)
- **Loosely coupled architecture**: Consider Inbox JSON (requires tolerating 1s latency)

## Testing Timeline

- 2026-02-15: Hook loop implemented and tested
- 2026-02-16: Inbox JSON discovered and measured (~1s polling interval)
- 2026-02-16: Tmux send-keys implemented (feature/tmux-teammates branch)

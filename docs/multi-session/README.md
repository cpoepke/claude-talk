# Multi-Session Communication Architecture

This directory documents different approaches tested for sending voice transcriptions to Claude Code sessions, particularly for supporting multiple personalities simultaneously.

## Current Implementation: Tmux Send-Keys

**Status**: ✅ Production (main branch)
**Latency**: Instant (direct injection)
**Multi-session**: ✅ Full support (multiple personalities)

The audio server routes transcriptions to specific Claude sessions via `tmux send-keys`. Each session registers its tmux target (session:window.pane) during `/claude-talk:start`. See [03-tmux-send-keys.md](03-tmux-send-keys.md) for details.

## Approaches Tested

### 1. [Hook Loop Approach](01-hook-loop.md) (Legacy)
- **Status**: 🗄️ Deprecated (replaced by tmux routing)
- **Latency**: Instant (synchronous)
- **Multi-session**: ❌ Single session only
- Stop hook loop that cycled between user input and Claude responses
- **Why replaced**: Couldn't support multiple personalities simultaneously

### 2. [Inbox JSON Polling](02-inbox-json.md) (Investigated)
- **Status**: 🔬 Experimental (not implemented)
- **Latency**: ~1 second (polling)
- **Multi-session**: ✅ Native support (one team per session)
- Claude Code's teammate inbox messaging system
- **Why not used**: 1s latency unacceptable for conversational voice

### 3. [Tmux Send-Keys](03-tmux-send-keys.md) (Current)
- **Status**: ✅ Production (main branch)
- **Latency**: Instant (direct injection)
- **Multi-session**: ✅ Full support (teammate per personality)
- Direct tmux injection with session management
- **Why chosen**: Instant latency + multi-personality support

## Comparison Matrix

| Feature | Hook Loop | Inbox JSON | Tmux Send-Keys |
|---------|-----------|------------|----------------|
| **Latency** | Instant | ~1s | Instant |
| **Multi-session** | ❌ | ✅ | ✅ |
| **Complexity** | Simple | Medium | Medium |
| **Coupling** | Tight | Loose | Medium |
| **Barge-in** | Natural | Complex | Natural |
| **Scalability** | Single | High | High |
| **Status** | Deprecated | Not impl. | ✅ Production |

## Architecture Decision

**Tmux routing** is the production architecture for all voice chat sessions (single or multi-personality). The hook-based approach has been removed.

## Testing Timeline

- 2026-02-15: Hook loop implemented and tested
- 2026-02-16: Inbox JSON discovered and measured (~1s polling interval)
- 2026-02-16: Tmux send-keys implemented (feature/tmux-teammates branch)

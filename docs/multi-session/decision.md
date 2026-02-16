# Multi-Session Approach Decision

## TL;DR

**Current Architecture**: **Tmux Send-Keys** (merged to main, production)

**Why**: Instant latency + multi-personality support = best user experience

**Status**: Hook Loop approach has been deprecated and removed

## The Problem

How to send voice transcriptions to Claude Code sessions when supporting multiple personalities simultaneously?

## Requirements

1. **Multi-personality**: Support multiple personalities running at once (Alice, Bob, Charlie)
2. **Low latency**: Conversational feel requires instant response
3. **Session routing**: Audio server must route to correct personality
4. **Barge-in support**: User can interrupt Claude mid-response
5. **Scalability**: Easy to add more personalities

## Approaches Evaluated

### 1. Hook Loop (Legacy - deprecated)

**How**: Stop hook cycled between user input and Claude responses

**Pros**:
- ⚡ Instant (0ms latency)
- 🎯 Simple (single script)
- 🎤 Natural barge-in

**Cons**:
- 🚫 Single session only
- ❌ Can't support multiple personalities

**Verdict**: ✅ Perfect for single personality, ❌ doesn't meet multi-personality requirement

**Status**: 🗄️ Deprecated and removed from codebase

---

### 2. Inbox JSON Polling (Investigated)

**How**: Write to Claude's teammate inbox JSON files, polled every ~1 second

**Pros**:
- 🎭 Multi-personality native
- 🔌 Loose coupling
- 📊 Message persistence

**Cons**:
- 🐌 **~1 second latency** (measured)
- 🔄 Bidirectional polling complexity
- ❓ Harder barge-in

**Verdict**: ❌ 1 second latency breaks conversational flow (disqualifying)

---

### 3. Tmux Send-Keys (Production - main)

**How**: Direct injection via `tmux send-keys` to dedicated Claude sessions

**Pros**:
- ⚡ Instant (0ms latency)
- 🎭 Multi-personality support
- 🔍 Session isolation
- 🎤 Natural barge-in
- 🚀 Scalable

**Cons**:
- 🔗 Tmux dependency
- 📊 Session management overhead

**Verdict**: ✅ **Meets all requirements** with acceptable trade-offs

**Status**: ✅ Merged to main, production architecture

## Decision Matrix

| Requirement | Hook Loop | Inbox JSON | Tmux Send-Keys |
|-------------|-----------|------------|----------------|
| Multi-personality | ❌ | ✅ | ✅ |
| Low latency | ✅ (0ms) | ❌ (~1s) | ✅ (0ms) |
| Session routing | ❌ | ✅ | ✅ |
| Barge-in | ✅ | ⚠️ | ✅ |
| Scalability | ❌ | ✅ | ✅ |
| **Total Score** | 2/5 | 3/5 | **5/5** |

## Performance Comparison

### Latency (Lower is Better)

```
Hook Loop:       ████░░░░░░░░░░░░░░░░ 0ms ⚡
Tmux Send-Keys:  ████░░░░░░░░░░░░░░░░ 0ms ⚡
Inbox JSON:      ████████████████████ ~1000ms 🐌
```

### Complexity (Lower is Better)

```
Hook Loop:       ████░░░░░░░░░░░░░░░░ Simple
Tmux Send-Keys:  ████████████░░░░░░░░ Medium
Inbox JSON:      ████████████████░░░░ Medium-High
```

### Multi-Session Support

```
Hook Loop:       ░░░░░░░░░░░░░░░░░░░░ None
Inbox JSON:      ████████████████████ Excellent
Tmux Send-Keys:  ████████████████████ Excellent
```

## Measured Data

### Inbox JSON Polling Tests (2026-02-16)

| Test | Latency | Notes |
|------|---------|-------|
| 1 | 0.53s | First message after idle |
| 2 | 0.95s | Subsequent message |
| 3 | 0.94s | Subsequent message |
| 4 | 0.95s | Subsequent message |
| 5 | 0.97s | Subsequent message |
| **Avg** | **~0.9s** | Polling interval |

End-to-end response time: ~5s (includes Claude thinking + response generation)

### Tmux Send-Keys Performance

- Injection latency: <1ms (instant)
- Routing overhead: ~1ms (single DB lookup)
- Total overhead: Negligible

## Implementation Status

| Approach | Branch | Status | Lines of Code |
|----------|--------|--------|---------------|
| Hook Loop | None | 🗄️ Deprecated (removed) | 0 |
| Inbox JSON | None | 🔬 Investigation only | 0 |
| Tmux Send-Keys | `main` | ✅ Production | ~440 |

## Decision: Tmux Send-Keys (Implemented)

**Status**: ✅ Merged to main (2026-02-16)

**Reasoning**:
1. ✅ Meets all requirements
2. ⚡ Instant latency (critical for conversation)
3. 🎭 Full multi-personality support
4. 📦 Fully implemented and tested
5. 🗄️ Hook loop removed - unified architecture

**Trade-offs**:
- Requires tmux (acceptable - common in development environments)
- More complex than hook loop (but necessary for multi-personality)
- Higher resource usage with multiple personalities (acceptable trade-off)

## Migration Complete

Hook-based voice chat has been fully replaced with tmux routing:
- ✅ Stop hook removed
- ✅ All skills updated (start, mute, unmute, chat, config)
- ✅ Documentation updated
- ✅ README reflects new architecture

## Alternative Scenarios

### If Tmux is Not Available
Fall back to hook loop (single personality only)

### If Latency Requirements Change
If 1s latency becomes acceptable, inbox JSON provides better architectural decoupling

### If Resource Constraints Exist
Use hook loop with manual personality switching (one at a time)

## Lessons Learned

1. **Measure first**: Assumed inbox polling would be faster than 1s
2. **Test across processes**: Verified tmux teammates receive inbox messages
3. **Compare apples to apples**: Latency vs latency, not features vs features
4. **Real-world use cases**: Multi-personality requirement drove decision

## References

- [Hook Loop Documentation](01-hook-loop.md)
- [Inbox JSON Investigation](02-inbox-json.md)
- [Tmux Send-Keys Implementation](03-tmux-send-keys.md)
- Feature branch: `feature/tmux-teammates` (commit 3f60a99)

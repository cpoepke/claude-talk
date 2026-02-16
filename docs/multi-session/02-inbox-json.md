# Inbox JSON Polling Approach

**Status**: 🔬 Experimental (not implemented)
**Branch**: None (investigation only)
**Discovered**: 2026-02-16

## Overview

Claude Code's teammate system uses JSON inbox files for inter-agent messaging. External processes can write to these files to send messages to Claude sessions. Messages are delivered via polling (~1 second interval).

## How It Works

```
External process (audio server)
    ↓
Write to inbox JSON: ~/.claude/teams/{TEAM}/inboxes/team-lead.json
    ↓
Claude polls inbox (~1 second interval)
    ↓
Message marked as read: true
    ↓
Claude processes and responds
    ↓
Response written to audio-server's inbox
    ↓
Audio server polls for response
    ↓
(bidirectional polling loop)
```

## Discovery Process

### Investigation Timeline
1. Explored Claude Code teammate notification system
2. Found inbox JSON files at `~/.claude/teams/{TEAM}/inboxes/{AGENT}.json`
3. Tested external bash writing to inbox files
4. Confirmed delivery to both in-process and tmux-based teammates
5. Measured polling interval: **~1 second**

### Test Results

#### Test 1: In-Process Teammate
- Teammate spawned with `backendType: "in-process"`
- External bash wrote to inbox
- Delivery confirmed in ~1 second
- Message marked as `read: true`

#### Test 2: Tmux Teammate (Separate Process)
- Teammate spawned with `backendType: "tmux"` in pane %2
- External bash wrote to inbox
- **Delivery confirmed across processes!**
- Timeline:
  - 08:07:05 - Message written
  - 08:07:09.874 - Teammate acknowledged (~5s including processing)

#### Test 3: Polling Interval Measurement
Precise measurements of inbox polling:
- Test 1: 0.53s
- Test 2: 0.95s
- Test 3: 0.94s
- Test 4: 0.95s
- Test 5: 0.97s
- **Average: ~0.9 seconds**

## Implementation

### Inbox File Structure

Location: `~/.claude/teams/{TEAM}/inboxes/{AGENT}.json`

Format:
```json
[
  {
    "from": "sender-name",
    "text": "Message content",
    "summary": "Brief summary (first 8 words)",
    "timestamp": "2026-02-16T08:00:00.000Z",
    "read": false
  }
]
```

### Sending Messages (Bash)

```bash
INBOX="~/.claude/teams/{TEAM}/inboxes/team-lead.json"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")

jq ". + [{
  \"from\": \"audio-server\",
  \"text\": \"$TRANSCRIPTION\",
  \"summary\": \"Voice input\",
  \"timestamp\": \"$TIMESTAMP\",
  \"read\": false
}]" "$INBOX" > "$INBOX.tmp" && mv "$INBOX.tmp" "$INBOX"
```

### Receiving Responses

Audio server would need its own inbox to receive Claude's responses:
```bash
# Poll audio-server's inbox for responses
while true; do
  RESPONSE=$(jq -r '.[] | select(.read == false) | .text' \
    ~/.claude/teams/{TEAM}/inboxes/audio-server.json)

  if [ -n "$RESPONSE" ]; then
    # Mark as read and speak
    jq '(.[] | select(.read == false)).read = true' \
      ~/.claude/teams/{TEAM}/inboxes/audio-server.json > tmp && mv tmp inbox

    echo "$RESPONSE" | say
  fi

  sleep 0.5
done
```

## Characteristics

### Pros
- 🎭 **Multi-session native** - one team per personality
- 🔌 **Loose coupling** - audio server independent of Claude
- 📊 **State tracking** - all messages persisted in JSON
- 🌐 **Scalable** - easily handles multiple personalities
- ✅ **Cross-process** - works between separate processes

### Cons
- 🐌 **~1 second latency** - polling delay (not instant)
- 🔄 **Bidirectional polling** - both sides must poll
- 🎛️ **Complex routing** - need session/team management
- ❓ **Barge-in harder** - requires explicit detection
- 📝 **File I/O overhead** - constant JSON read/write

## Performance

- **Polling interval**: ~1 second
- **Delivery latency**: 0.5-1.0 seconds (measured)
- **End-to-end response**: ~5 seconds (includes Claude thinking time)
- **File watching**: None found in source code (polling only)

## Source Code Findings

### MessageBus (In-Memory)
- Location: `/usr/local/lib/node_modules/claude-flow/src/communication/message-bus.ts`
- Uses EventEmitter for in-memory messaging
- Unix domain sockets (anonymous, via socketpair)
- **Not accessible to external processes**

### No File Watching
Search of claude-flow source found:
- ❌ No `chokidar` or `fs.watch` for inbox files
- ❌ No file watching on inbox JSON
- ✅ Mechanism appears to be polling (not reactive)

### Inbox Persistence
- Inbox files are JSON arrays
- Messages marked `read: true` after processing
- Persistence happens alongside in-memory MessageBus
- External processes can only use file writing (not MessageBus)

## Multi-Session Architecture

### Team Structure
```
~/.claude/teams/
├── personality-alice/
│   ├── config.json
│   └── inboxes/
│       ├── team-lead.json    (Alice's Claude session)
│       └── audio-server.json (for responses to audio server)
├── personality-bob/
│   ├── config.json
│   └── inboxes/
│       ├── team-lead.json    (Bob's Claude session)
│       └── audio-server.json
└── personality-charlie/
    └── ...
```

### Session Routing
Audio server determines which personality to route to:
1. User says wake word or personality name
2. Audio server writes to appropriate team's inbox
3. That personality's Claude session receives message
4. Response written back to audio-server inbox

## Use Cases

- ✅ Multiple personalities running simultaneously
- ✅ Loosely coupled architecture
- ✅ Message persistence and auditing
- ✅ Cross-process communication
- ⚠️ Acceptable with 1s latency tradeoff
- ❌ Real-time conversational feel (latency too high)

## Limitations

1. **1 second latency** - not suitable for real-time conversation
2. **Polling overhead** - constant file I/O
3. **Bidirectional complexity** - both sides need inbox management
4. **No file watching** - can't reduce latency without modifying Claude Code

## When to Use

Use this approach when:
- Running multiple personalities simultaneously
- Loose coupling is critical
- 1 second latency is acceptable
- Message persistence is valuable
- Architecture is more important than responsiveness

## Why Not Used

Despite native multi-session support, **1 second latency** is too high for natural conversation. The [Tmux Send-Keys approach](03-tmux-send-keys.md) provides multi-session support with instant latency.

## Future Potential

If Claude Code added file watching (e.g., via `chokidar`), latency could drop to <100ms, making this approach competitive with tmux send-keys while maintaining loose coupling benefits.

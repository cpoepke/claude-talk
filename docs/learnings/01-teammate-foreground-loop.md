# Teammate Foreground Loop: The Only Reliable Pattern

## Problem

We needed a teammate to autonomously capture speech, relay transcriptions, speak responses, and loop - without any manual intervention from the team lead.

## What we tried

Five iterations, four failures, one breakthrough.

### audio (v1) - Background task, basic prompt

- **Approach**: Teammate runs `capture-utterance.sh` with `run_in_background=true`, goes idle, should wake on task completion.
- **Result**: FAILED. Teammate went idle and never reacted to background task completion. Required manual nudging via SendMessage every time.
- **Lesson**: Background task completion notifications don't reliably wake teammates.

### audio-2 (v2) - Background task, explicit instructions

- **Approach**: Same as v1 but with more detailed prompt about reading output and immediately starting next capture.
- **Result**: FAILED. Teammate never even started the background task after being spawned. Went idle immediately.
- **Lesson**: Even explicit "DO IT NOW" instructions don't guarantee the teammate runs the command.

### audio-3 (v3) - Background task, "mandatory" wording

- **Approach**: Very explicit prompt with "RULE 1, RULE 2" structure, "MANDATORY", "ZERO EXCEPTIONS" language.
- **Result**: FAILED. Started the capture successfully, but did not react when it completed. When nudged, admitted: "I just waited for you to give me a nudge."
- **Lesson**: Strong wording doesn't fix the underlying issue - teammates don't process background task completion events.

### audio-4 (v4) - Background task, "YOU MUST REACT" prompt

- **Approach**: Extremely forceful prompt: "YOU ARE A VOICE CAPTURE BOT", all-caps rules, "you MUST react IMMEDIATELY".
- **Result**: PARTIALLY FAILED. Started capture, but didn't react to completion. After nudge, did relay the transcription and started speak-and-capture. But the next cycle failed again - didn't detect second background task completion.
- **Lesson**: Can sometimes work for one cycle after nudging but never sustains autonomously.

### audio-5 / audio-mate (v5) - FOREGROUND loop

- **Approach**: Teammate runs capture in **foreground** (no `run_in_background`), with `timeout: 60000`. Loops: capture -> send text -> wait for reply -> speak+capture -> repeat.
- **Result**: SUCCESS! Teammate captures, sends transcription, speaks response, and loops back - all autonomously without any nudging.
- **Lesson**: **Foreground execution is the solution.** The teammate stays active during capture (using its Bash timeout), so there's no idle->wake issue.

## Summary

| Version | Approach | Started? | Reacted to completion? | Autonomous loop? |
|---------|----------|----------|----------------------|-----------------|
| v1 | Background task | Yes | No | No |
| v2 | Background task | No | N/A | No |
| v3 | Background task | Yes | No | No |
| v4 | Background task | Yes | No (once after nudge) | No |
| **v5** | **Foreground loop** | **Yes** | **N/A (foreground)** | **YES** |

## Key takeaway

**Claude Code teammates do NOT reliably process background task completion events.** This is a platform limitation, not a prompt engineering problem. No amount of forceful wording fixes it.

The solution: run blocking operations in the **foreground** with a generous timeout (60000ms). The teammate is "blocked" during capture but that's fine - it has nothing else to do. When the foreground command returns, the teammate naturally continues to the next step.

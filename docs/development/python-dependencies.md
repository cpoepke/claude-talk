# Python Dependency Hell on macOS arm64

## Problem

Getting real-time Whisper transcription working on macOS Apple Silicon required navigating a minefield of Python version and package compatibility issues.

## WhisperLive (Collabora) - BLOCKED

[whisper-live](https://github.com/collabora/WhisperLive) is a popular real-time Whisper server, but:

- `pip install whisper-live` **fails on Python 3.12** - pins `openai-whisper==20240930` which uses deprecated `pkg_resources` (removed in setuptools 72+)
- `pip install whisper-live` **fails on Python 3.13** - same issue, plus additional C extension build failures
- Newer `openai-whisper==20250625` fixes the `pkg_resources` issue, but WhisperLive hasn't updated its pinned version
- Workaround would require Python 3.10 or 3.11, or `--no-deps` with manual overrides

## WhisperLiveKit - THE SOLUTION

[WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) is a superset of WhisperLive's functionality:

- Works on **Python 3.12** (not 3.13)
- Supports MLX backend (native Apple Silicon acceleration)
- Built-in WebSocket server for streaming
- PCM input mode (raw int16 audio, no encoding overhead)

Install:
```bash
python3.12 -m venv ~/.claude-talk/venvs/wlk
~/.claude-talk/venvs/wlk/bin/pip install 'whisperlivekit[mlx-whisper]' mlx-whisper sounddevice websockets numpy
```

## Python version matrix

| Package | 3.10 | 3.11 | 3.12 | 3.13 |
|---------|------|------|------|------|
| whisper-live | Works | Works | FAILS | FAILS |
| **whisperlivekit** | Works | Works | **Works** | FAILS |
| openai-whisper | Works | Works | Broken* | FAILS |
| mlx-whisper | N/A | Works | **Works** | Partial |

*Broken due to `pkg_resources` deprecation

## Lesson

Always pin Python 3.12 for this project. The install script explicitly checks for it and refuses to continue with other versions.

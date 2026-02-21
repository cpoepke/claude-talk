"""Tests for tmux control mode client."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_talk.tmux_control import TmuxControlClient, TmuxControlError


# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeProcess:
    """Simulates an asyncio subprocess with scripted stdout output."""

    def __init__(self, lines: list[str]):
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(lines)
        self.pid = 12345
        self._terminated = False

    def terminate(self):
        self._terminated = True

    def kill(self):
        self._terminated = True

    async def wait(self):
        pass


class FakeStdin:
    def __init__(self):
        self.written: list[bytes] = []

    def write(self, data: bytes):
        self.written.append(data)

    async def drain(self):
        pass


class FakeStdout:
    def __init__(self, lines: list[str]):
        self._lines = [l.encode() + b"\n" for l in lines]
        self._index = 0

    async def readline(self) -> bytes:
        if self._index < len(self._lines):
            line = self._lines[self._index]
            self._index += 1
            return line
        # EOF — sleep to simulate process ending
        await asyncio.sleep(0.01)
        return b""


# ── Reader loop parsing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reader_parses_begin_end():
    """Test that %begin/%end blocks resolve pending futures with response data."""
    lines = [
        "%begin 1234567890 1 0",
        "session0: 1 windows",
        "%end 1234567890 1 0",
    ]
    proc = FakeProcess(lines)

    client = TmuxControlClient(idle_secs=1.0)
    client._proc = proc
    client._connected = True
    client._cmd_counter = 0

    # Pre-register a pending future for cmd_id=1
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending[1] = fut

    # Start reader and let it process lines
    reader_task = asyncio.create_task(client._reader_loop())
    result = await asyncio.wait_for(fut, timeout=2.0)
    assert result == "session0: 1 windows"

    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_reader_parses_error():
    """Test that %error blocks reject pending futures with TmuxControlError."""
    lines = [
        "%begin 1234567890 1 0",
        "session not found: nosession",
        "%error 1234567890 1 0",
    ]
    proc = FakeProcess(lines)

    client = TmuxControlClient(idle_secs=1.0)
    client._proc = proc
    client._connected = True

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending[1] = fut

    reader_task = asyncio.create_task(client._reader_loop())

    with pytest.raises(TmuxControlError, match="session not found"):
        await asyncio.wait_for(fut, timeout=2.0)

    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_reader_tracks_output_timestamps():
    """Test that %output events update pane last-output timestamps."""
    lines = [
        "%output %5 some terminal output here",
        "%output %8 more output",
    ]
    proc = FakeProcess(lines)

    client = TmuxControlClient(idle_secs=1.0)
    client._proc = proc
    client._connected = True

    reader_task = asyncio.create_task(client._reader_loop())
    # Give reader time to process
    await asyncio.sleep(0.1)

    assert "%5" in client._pane_last_output
    assert "%8" in client._pane_last_output
    assert client._pane_last_output["%5"] > 0
    assert client._pane_last_output["%8"] > 0

    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_reader_handles_multiline_response():
    """Test that multi-line response blocks are captured correctly."""
    lines = [
        "%begin 1234567890 1 0",
        "line one",
        "line two",
        "line three",
        "%end 1234567890 1 0",
    ]
    proc = FakeProcess(lines)

    client = TmuxControlClient(idle_secs=1.0)
    client._proc = proc
    client._connected = True

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending[1] = fut

    reader_task = asyncio.create_task(client._reader_loop())
    result = await asyncio.wait_for(fut, timeout=2.0)
    assert result == "line one\nline two\nline three"

    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass


# ── Idle detection ───────────────────────────────────────────────────────────


def test_is_pane_idle_no_output():
    """Pane with no recorded output is considered idle."""
    client = TmuxControlClient(idle_secs=2.0)
    assert client.is_pane_idle("%5") is True


def test_is_pane_idle_recent_output():
    """Pane with recent output is not idle."""
    client = TmuxControlClient(idle_secs=2.0)
    client._pane_last_output["%5"] = time.monotonic()
    assert client.is_pane_idle("%5") is False


def test_is_pane_idle_old_output():
    """Pane with output older than threshold is idle."""
    client = TmuxControlClient(idle_secs=2.0)
    client._pane_last_output["%5"] = time.monotonic() - 3.0
    assert client.is_pane_idle("%5") is True


def test_is_pane_idle_custom_threshold():
    """Custom quiet_secs parameter overrides instance default."""
    client = TmuxControlClient(idle_secs=10.0)
    client._pane_last_output["%5"] = time.monotonic() - 1.5
    # Default 10s would say not idle, but custom 1.0s says idle
    assert client.is_pane_idle("%5", quiet_secs=1.0) is True
    assert client.is_pane_idle("%5", quiet_secs=2.0) is False


@pytest.mark.asyncio
async def test_wait_for_idle_already_idle():
    """wait_for_idle returns immediately if pane is already idle."""
    client = TmuxControlClient(idle_secs=1.0)
    # No output recorded = idle
    result = await client.wait_for_idle("%5", timeout=1.0)
    assert result is True


@pytest.mark.asyncio
async def test_wait_for_idle_becomes_idle():
    """wait_for_idle detects when output stops."""
    client = TmuxControlClient(idle_secs=0.3)
    client._pane_last_output["%5"] = time.monotonic()

    async def age_output():
        await asyncio.sleep(0.1)
        # Simulate output stopping 0.4s ago
        client._pane_last_output["%5"] = time.monotonic() - 0.4

    asyncio.create_task(age_output())
    result = await client.wait_for_idle("%5", timeout=2.0, quiet_secs=0.3)
    assert result is True


@pytest.mark.asyncio
async def test_wait_for_idle_timeout():
    """wait_for_idle returns False when timeout expires."""
    client = TmuxControlClient(idle_secs=10.0)
    client._pane_last_output["%5"] = time.monotonic()

    # Keep updating output so it never goes idle
    stop = asyncio.Event()

    async def keep_active():
        while not stop.is_set():
            client._pane_last_output["%5"] = time.monotonic()
            await asyncio.sleep(0.05)

    task = asyncio.create_task(keep_active())
    result = await client.wait_for_idle("%5", timeout=0.5)
    assert result is False
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── send_command ─────────────────────────────────────────────────────────────


class BlockingStdout:
    """Stdout that blocks forever (never returns data or EOF)."""

    async def readline(self) -> bytes:
        await asyncio.sleep(100)
        return b""


@pytest.mark.asyncio
async def test_send_command_timeout():
    """send_command raises TmuxControlError on timeout (no response)."""
    proc = FakeProcess([])
    proc.stdout = BlockingStdout()  # never returns — simulates unresponsive tmux

    client = TmuxControlClient(idle_secs=1.0)
    client._proc = proc
    client._connected = True
    client._reader_task = asyncio.create_task(client._reader_loop())

    with pytest.raises(TmuxControlError, match="timed out"):
        await client.send_command("list-sessions", timeout=0.3)

    client._connected = False
    client._reader_task.cancel()
    try:
        await client._reader_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_send_command_not_connected():
    """send_command raises TmuxControlError when not connected."""
    client = TmuxControlClient(idle_secs=1.0)
    client._connected = False

    with pytest.raises(TmuxControlError, match="not connected"):
        await client.send_command("list-sessions")


# ── Queued send ordering ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queued_send_fifo_order():
    """Messages enqueued for the same pane are delivered in FIFO order."""
    delivered: list[str] = []

    client = TmuxControlClient(idle_secs=0.0)  # instant idle
    client._connected = True

    # Mock send_to_pane to record delivery order
    async def mock_send(target, text):
        delivered.append(text)
        return True

    client.send_to_pane = mock_send
    # Pane is idle (no output recorded)

    # Enqueue 3 messages
    tasks = [
        asyncio.create_task(client.send_queued("%5", "msg1")),
        asyncio.create_task(client.send_queued("%5", "msg2")),
        asyncio.create_task(client.send_queued("%5", "msg3")),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(r is True for r in results)
    assert delivered == ["msg1", "msg2", "msg3"]

    # Cleanup
    client._connected = False
    for task in client._drain_tasks.values():
        task.cancel()


# ── Connection lost ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connection_lost_rejects_pending():
    """Pending futures are rejected when connection is lost."""
    proc = FakeProcess([])  # EOF immediately

    client = TmuxControlClient(idle_secs=1.0)
    client._proc = proc
    client._connected = True

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending[1] = fut

    # Reader will hit EOF and disconnect
    await client._reader_loop()

    assert client._connected is False
    with pytest.raises(TmuxControlError, match="connection lost"):
        fut.result()

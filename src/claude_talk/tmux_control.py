"""Tmux control mode client for persistent, low-overhead pane communication.

Replaces subprocess-per-message with a single `tmux -CC attach` connection.
Provides idle detection via %output event monitoring so teammate messages
can wait for a quiet pane before injecting text.
"""

import asyncio
import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class TmuxControlClient:
    """Async tmux control-mode client.

    Connects via `tmux -CC attach-session` and communicates through
    stdin/stdout using the structured control-mode protocol.

    Protocol overview:
        Commands are written to stdin and produce %begin/%end or %begin/%error
        response blocks. Pane output is streamed as %output events.
    """

    def __init__(self, session_name: str | None = None, idle_secs: float = 2.0):
        self._session_name = session_name
        self._idle_secs = idle_secs
        self._proc: asyncio.subprocess.Process | None = None
        self._connected = False

        # Command tracking: command_id -> Future[str]
        self._pending: dict[int, asyncio.Future[str]] = {}
        self._cmd_counter = 0
        self._cmd_lock = asyncio.Lock()

        # Output tracking for idle detection: pane_id -> last output timestamp
        self._pane_last_output: dict[str, float] = defaultdict(float)

        # Per-pane message queues: pane_id -> Queue of (text, Future[bool])
        self._pane_queues: dict[str, asyncio.Queue] = {}
        self._drain_tasks: dict[str, asyncio.Task] = {}

        # Reader task
        self._reader_task: asyncio.Task | None = None

        # Accumulator for %begin/%end response blocks
        self._response_buf: dict[int, list[str]] = {}
        self._current_block_id: int | None = None

    async def connect(self) -> None:
        """Launch tmux in control mode and start the reader loop."""
        cmd = ["tmux", "-CC", "attach-session"]
        if self._session_name:
            cmd += ["-t", self._session_name]

        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._connected = True
        self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("tmux control mode connected (pid=%s)", self._proc.pid)

    async def _reader_loop(self) -> None:
        """Parse structured control-mode output from tmux stdout.

        Lines starting with % are control messages:
            %begin <time> <cmd_id> <flags>
            %end <time> <cmd_id> <flags>
            %error <time> <cmd_id> <flags>
            %output <pane_id> <data>
            %window-close / %pane-exited / etc.

        Lines between %begin and %end/%error are command response data.
        """
        assert self._proc and self._proc.stdout
        try:
            while self._connected:
                raw = await self._proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\n")

                if line.startswith("%begin "):
                    parts = line.split(None, 3)
                    if len(parts) >= 3:
                        try:
                            cmd_id = int(parts[2])
                            self._current_block_id = cmd_id
                            self._response_buf[cmd_id] = []
                        except ValueError:
                            pass

                elif line.startswith("%end "):
                    parts = line.split(None, 3)
                    if len(parts) >= 3:
                        try:
                            cmd_id = int(parts[2])
                        except ValueError:
                            continue
                        self._current_block_id = None
                        buf = self._response_buf.pop(cmd_id, [])
                        fut = self._pending.pop(cmd_id, None)
                        if fut and not fut.done():
                            fut.set_result("\n".join(buf))

                elif line.startswith("%error "):
                    parts = line.split(None, 3)
                    if len(parts) >= 3:
                        try:
                            cmd_id = int(parts[2])
                        except ValueError:
                            continue
                        self._current_block_id = None
                        buf = self._response_buf.pop(cmd_id, [])
                        fut = self._pending.pop(cmd_id, None)
                        if fut and not fut.done():
                            fut.set_exception(
                                TmuxControlError("\n".join(buf) or "tmux error")
                            )

                elif line.startswith("%output "):
                    # %output %<pane_id> <data>
                    rest = line[len("%output "):]
                    space_idx = rest.find(" ")
                    if space_idx > 0:
                        pane_id = rest[:space_idx]
                        self._pane_last_output[pane_id] = time.monotonic()

                elif line.startswith("%exit"):
                    logger.info("tmux control mode: server exited")
                    break

                else:
                    # Data line inside a %begin/%end block
                    if self._current_block_id is not None:
                        buf = self._response_buf.get(self._current_block_id)
                        if buf is not None:
                            buf.append(line)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("tmux control reader error: %s", e)
        finally:
            self._connected = False
            # Reject all pending futures
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(TmuxControlError("connection lost"))
            self._pending.clear()

    async def send_command(self, cmd: str, timeout: float = 10.0) -> str:
        """Send a tmux command and await the structured response.

        Returns the response text between %begin and %end.
        Raises TmuxControlError on %error or timeout.
        """
        if not self._connected or not self._proc or not self._proc.stdin:
            raise TmuxControlError("not connected")

        async with self._cmd_lock:
            self._cmd_counter += 1
            cmd_id = self._cmd_counter

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[cmd_id] = fut

        try:
            self._proc.stdin.write((cmd + "\n").encode())
            await self._proc.stdin.drain()
        except Exception as e:
            self._pending.pop(cmd_id, None)
            raise TmuxControlError(f"write failed: {e}") from e

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(cmd_id, None)
            raise TmuxControlError(f"command timed out: {cmd!r}")

    async def send_to_pane(self, target: str, text: str) -> bool:
        """Send text to a pane via control mode (no subprocess).

        Sends text in literal mode then Enter, equivalent to:
            tmux send-keys -t <target> -l <text>
            tmux send-keys -t <target> Enter
        """
        try:
            await self.send_command(f"send-keys -t {target} -l {_escape_for_control(text)}")
            await self.send_command(f"send-keys -t {target} Enter")
            return True
        except TmuxControlError as e:
            logger.error("send_to_pane(%s) failed: %s", target, e)
            return False

    def is_pane_idle(self, pane_id: str, quiet_secs: float | None = None) -> bool:
        """Check if a pane has been quiet for at least quiet_secs."""
        threshold = quiet_secs if quiet_secs is not None else self._idle_secs
        last = self._pane_last_output.get(pane_id, 0.0)
        if last == 0.0:
            # Never seen output — treat as idle (pane may have been quiet since attach)
            return True
        return (time.monotonic() - last) >= threshold

    async def wait_for_idle(self, pane_id: str, timeout: float = 30.0,
                            quiet_secs: float | None = None) -> bool:
        """Poll until the pane is idle or timeout expires.

        Returns True if idle detected, False on timeout.
        """
        deadline = time.monotonic() + timeout
        poll_interval = 0.25
        while time.monotonic() < deadline:
            if self.is_pane_idle(pane_id, quiet_secs):
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def send_queued(self, target: str, text: str) -> bool:
        """Enqueue a message for delivery when the target pane is idle.

        Messages are delivered FIFO per pane. Each pane has its own
        drain task that waits for idle before sending the next message.
        """
        if target not in self._pane_queues:
            self._pane_queues[target] = asyncio.Queue()

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        await self._pane_queues[target].put((text, fut))

        # Ensure drain task is running for this pane
        if target not in self._drain_tasks or self._drain_tasks[target].done():
            self._drain_tasks[target] = asyncio.create_task(
                self._drain_queue(target)
            )

        return await fut

    async def _drain_queue(self, target: str) -> None:
        """Drain the message queue for a pane, waiting for idle between sends."""
        queue = self._pane_queues.get(target)
        if not queue:
            return

        while not queue.empty() or self._connected:
            try:
                text, fut = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                if queue.empty():
                    break
                continue

            try:
                idle = await self.wait_for_idle(target)
                if not idle:
                    logger.warning("pane %s not idle after timeout, sending anyway", target)

                ok = await self.send_to_pane(target, text)
                if not fut.done():
                    fut.set_result(ok)
            except Exception as e:
                if not fut.done():
                    fut.set_result(False)
                logger.error("drain_queue(%s) error: %s", target, e)

    @property
    def connected(self) -> bool:
        return self._connected

    async def disconnect(self) -> None:
        """Detach from tmux and clean up."""
        if not self._connected:
            return

        self._connected = False

        # Cancel drain tasks
        for task in self._drain_tasks.values():
            task.cancel()
        if self._drain_tasks:
            await asyncio.gather(*self._drain_tasks.values(), return_exceptions=True)
        self._drain_tasks.clear()

        # Send detach and terminate
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(b"detach\n")
                await self._proc.stdin.drain()
            except Exception:
                pass

        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        logger.info("tmux control mode disconnected")


class TmuxControlError(Exception):
    """Error from tmux control mode protocol."""


def _escape_for_control(text: str) -> str:
    """Escape text for tmux send-keys -l in control mode.

    Control mode commands are newline-delimited, so we need to ensure
    the text doesn't contain raw newlines. Tmux send-keys -l handles
    most special chars, but newlines would break the protocol.
    """
    return text.replace("\n", " ")

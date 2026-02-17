#!/usr/bin/env python3
"""
Audio Server for Claude Talk

Replaces shell scripts + agent with a dedicated HTTP server that handles:
- TTS playback (macOS `say`)
- Speech capture via WhisperLiveKit
- Barge-in detection (Speex AEC + BlackHole)
- State management
- WLK subprocess lifecycle

API:
  POST /speak               - TTS + capture in one call (with barge-in)
  GET  /listen              - Block until user speaks, return transcription
  GET  /status              - Current state (idle/listening/speaking)
  GET  /devices             - List audio devices and active input
  POST /mute                - Mute mic
  POST /unmute              - Unmute mic
  POST /stop                - Graceful shutdown
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
import uvicorn
import websockets
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Claude Talk modules
sys.path.insert(0, str(Path(__file__).parent))
from claude_talk.db import DB
from claude_talk.session import SessionStore
from claude_talk.tmux import send_to_session


# ============================================================================
# Speex Acoustic Echo Cancellation
# ============================================================================


class SpeexAEC:
    """Wrapper around libspeexdsp for acoustic echo cancellation."""

    def __init__(self, frame_size: int = 256, filter_length: int = 2048, sample_rate: int = 16000):
        import ctypes
        # Find libspeexdsp
        lib_paths = [
            Path.home() / ".claude-talk" / "lib" / "libspeexdsp.dylib",
            Path("/opt/homebrew/lib/libspeexdsp.dylib"),
            Path("/usr/local/lib/libspeexdsp.dylib"),
        ]
        self._lib = None
        for p in lib_paths:
            if p.exists():
                self._lib = ctypes.CDLL(str(p))
                break
        if self._lib is None:
            raise RuntimeError("libspeexdsp not found. Install with: brew install speexdsp")

        self._ctypes = ctypes
        self._frame_size = frame_size

        # Bind functions
        self._lib.speex_echo_state_init.restype = ctypes.c_void_p
        self._lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.speex_echo_cancellation.restype = None
        self._lib.speex_echo_cancellation.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16),
            ctypes.POINTER(ctypes.c_int16),
        ]
        self._lib.speex_echo_ctl.restype = ctypes.c_int
        self._lib.speex_echo_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self._lib.speex_echo_state_destroy.restype = None
        self._lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]

        self._state = self._lib.speex_echo_state_init(frame_size, filter_length)
        rate = ctypes.c_int(sample_rate)
        SPEEX_ECHO_SET_SAMPLING_RATE = 24
        self._lib.speex_echo_ctl(self._state, SPEEX_ECHO_SET_SAMPLING_RATE, ctypes.byref(rate))

    def cancel(self, mic: np.ndarray, ref: np.ndarray) -> np.ndarray:
        """Process one frame: subtract echo of ref from mic, return cleaned audio."""
        ct = self._ctypes
        out = np.zeros(self._frame_size, dtype=np.int16)
        self._lib.speex_echo_cancellation(
            self._state,
            mic.ctypes.data_as(ct.POINTER(ct.c_int16)),
            ref.ctypes.data_as(ct.POINTER(ct.c_int16)),
            out.ctypes.data_as(ct.POINTER(ct.c_int16)),
        )
        return out

    def destroy(self):
        if self._state:
            self._lib.speex_echo_state_destroy(self._state)
            self._state = None

    def __del__(self):
        self.destroy()


# ============================================================================
# Event Logger
# ============================================================================


class EventLogger:
    """Logs timestamped events to file for latency analysis"""

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        # Append mode, create if doesn't exist
        self.file = open(self.log_file, "a", buffering=1)  # Line buffered
        self.log_event("SERVER_START", {"pid": os.getpid()})

    def log_event(self, event: str, data: dict[str, Any] | None = None):
        """Write event with timestamp to log file"""
        timestamp = datetime.now().isoformat()
        entry = {"timestamp": timestamp, "event": event}
        if data:
            entry.update(data)
        self.file.write(json.dumps(entry) + "\n")

    def close(self):
        self.log_event("SERVER_STOP")
        self.file.close()


# ============================================================================
# Configuration
# ============================================================================


from claude_talk.config import Config


# ============================================================================
# State Management
# ============================================================================


class StateManager:
    """Manages ~/.claude-talk/state file (single writer, no locking needed)"""

    def __init__(self):
        self.state_file = Path.home() / ".claude-talk/state"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, str] = {}
        self._load()

    def _load(self):
        """Load state from file"""
        if not self.state_file.exists():
            return
        for line in self.state_file.read_text().splitlines():
            line = line.strip()
            if "=" in line:
                key, _, val = line.partition("=")
                self.state[key.strip()] = val.strip()

    def _save(self):
        """Write state to file atomically"""
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text("\n".join(f"{k}={v}" for k, v in self.state.items()) + "\n")
        tmp.replace(self.state_file)

    def set(self, **kwargs: str):
        """Update state values and write to disk"""
        self.state.update(kwargs)
        self._save()

    def get(self, key: str, default: str = "") -> str:
        return self.state.get(key, default)


# ============================================================================
# WLK Subprocess Manager
# ============================================================================


class WLKManager:
    """Manages WhisperLiveKit subprocess with auto-restart"""

    def __init__(self, config: Config):
        self.config = config
        self.port = config.get_int("WLK_PORT", 8090)
        self.venv_path = Path(config.get("WLK_VENV"))
        self.process: subprocess.Popen | None = None
        self.stop_requested = False

    async def start(self):
        """Start WLK in background with auto-restart loop"""
        if not (self.venv_path / "bin/activate").exists():
            print(f"ERROR: WLK venv not found at {self.venv_path}", file=sys.stderr)
            return

        # Check if already running
        if await self._is_running():
            print(f"WLK already running on port {self.port}")
            return

        # Run in background task
        asyncio.create_task(self._run_wlk())

    async def _run_wlk(self):
        """Auto-restart loop for WLK"""
        wlk_bin = self.venv_path / "bin/wlk"
        while not self.stop_requested:
            print(f"[WLK] starting on port {self.port}...", file=sys.stderr, flush=True)
            self.process = subprocess.Popen(
                [
                    str(wlk_bin),
                    "--model",
                    "small.en",
                    "--language",
                    "en",
                    "--backend",
                    "mlx-whisper",
                    "--port",
                    str(self.port),
                    "--pcm-input",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            # Wait for process to exit
            while self.process and self.process.poll() is None:
                await asyncio.sleep(0.5)
                if self.stop_requested:
                    self.process.terminate()
                    await asyncio.sleep(1)
                    if self.process.poll() is None:
                        self.process.kill()
                    return

            # Drain stderr for crash diagnostics
            exit_code = self.process.returncode if self.process else None
            print(f"[WLK] process exited with code {exit_code} at {time.strftime('%Y-%m-%d %H:%M:%S')}", file=sys.stderr, flush=True)
            if self.process and self.process.stderr:
                try:
                    err = self.process.stderr.read().decode(errors="replace")
                    if err.strip():
                        print(f"[WLK] stderr output (last 20 lines):", file=sys.stderr, flush=True)
                        for line in err.strip().splitlines()[-20:]:
                            print(f"[WLK]   {line}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[WLK] failed to read stderr: {e}", file=sys.stderr, flush=True)

            if self.stop_requested:
                return

            print(f"[WLK] restarting in 2s...", file=sys.stderr, flush=True)
            await asyncio.sleep(2)

    async def _is_running(self) -> bool:
        """Check if WLK is responding on its port"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", self.port), timeout=1.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError):
            return False

    async def stop(self):
        """Stop WLK subprocess"""
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            await asyncio.sleep(1)
            if self.process.poll() is None:
                self.process.kill()


# ============================================================================
# Audio Engine
# ============================================================================


def detect_blackhole_device() -> int | None:
    """Auto-detect BlackHole 2ch input device index."""
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if "BlackHole 2ch" in dev["name"] and dev["max_input_channels"] > 0:
            return i
    return None


def auto_detect_input_device() -> int:
    """Use the macOS system default input device (set in System Settings > Sound)."""
    default_input = sd.default.device[0]
    if default_input is not None and default_input >= 0:
        dev = sd.query_devices(int(default_input))
        print(f"  System default input: [{int(default_input)}] {dev['name']}")
        return int(default_input)
    raise RuntimeError("No default input audio device configured in System Settings")


class AudioEngine:
    """Handles mic capture, TTS, barge-in, and WLK transcription"""

    def __init__(self, config: Config, state: StateManager, event_logger: EventLogger):
        self.config = config
        self.state = state
        self.logger = event_logger

        # Audio settings — auto-detect unless explicitly configured
        device_cfg = config.get("AUDIO_DEVICE", "auto")
        self._auto_device = device_cfg.lower() == "auto" or device_cfg == ""
        if self._auto_device:
            self.device_index = auto_detect_input_device()
        else:
            self.device_index = int(device_cfg)
            print(f"  Using configured mic device: [{self.device_index}] {sd.query_devices(self.device_index)['name']}")
        self.sample_rate = 16000
        self.gain = config.get_float("MIC_GAIN", 8.0)
        self.silence_timeout = config.get_float("SILENCE_SECS", 2.0)
        self.max_duration = 60.0

        # Barge-in settings
        self.barge_in_enabled = config.get_bool("BARGE_IN", True)
        blackhole_cfg = config.get("BLACKHOLE_DEVICE", "")
        if blackhole_cfg:
            self.blackhole_device = int(blackhole_cfg)
        else:
            self.blackhole_device = detect_blackhole_device()
        if self.blackhole_device is None:
            self.barge_in_enabled = False
        self.barge_in_ratio = config.get_float("BARGE_IN_RATIO", 0.5)

        # TTS settings
        self.voice = config.get("VOICE", "Daniel")

        # WLK settings
        self.wlk_url = config.get("WLK_URL", "ws://localhost:8090/asr")

        # Persistent resources
        self.mic_stream: sd.InputStream | None = None
        self.ref_stream: sd.InputStream | None = None
        self.lock = asyncio.Lock()  # Serialize capture operations

        # Acoustic Echo Cancellation (Speex)
        self.aec = None
        if self.barge_in_enabled and self.blackhole_device is not None:
            try:
                self.aec = SpeexAEC(frame_size=320, filter_length=8000, sample_rate=16000)
                print(f"  Speex AEC: enabled (frame=320, filter=8000)")
            except Exception as e:
                print(f"  Speex AEC: unavailable ({e})", file=sys.stderr)

        # TTS enforcer: track current say PID to prevent overlapping TTS
        self._tts_pid: int | None = None
        # Track when TTS last finished for post-TTS protection in all capture paths
        self._tts_finished_at: float = 0.0

        # Buffered listen: pre-captured text from /queue-listen
        self._buffered_text: str | None = None
        self._buffer_task: asyncio.Task | None = None

        print(f"AudioEngine initialized:")
        print(f"  Mic device: {self.device_index}, gain: {self.gain}")
        print(f"  TTS voice: {self.voice}")
        print(f"  Barge-in: {self.barge_in_enabled}", end="")
        if self.barge_in_enabled:
            print(f" (BlackHole device: {self.blackhole_device})")
        else:
            print(" (disabled)")

    def _is_muted(self) -> bool:
        return self.state.get("MUTED", "false").lower() == "true"

    async def speak(self, text: str) -> int | None:
        """
        Speak text via macOS `say`. Returns PID if successful, None if failed.
        Kills any previous TTS process to prevent overlap.
        """
        # TTS enforcer: kill previous say process if still running
        if self._tts_pid is not None:
            try:
                os.kill(self._tts_pid, signal.SIGTERM)
                print(f"[TTS] killed previous say (pid={self._tts_pid})", file=sys.stderr, flush=True)
            except ProcessLookupError:
                pass
            self._tts_pid = None

        self.state.set(STATUS="speaking")
        self.logger.log_event("TTS_START", {"text": text, "voice": self.voice})
        try:
            proc = await asyncio.create_subprocess_exec(
                "say",
                "-v",
                self.voice,
                text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._tts_pid = proc.pid
            return proc.pid
        except Exception as e:
            print(f"TTS failed: {e}", file=sys.stderr)
            return None

    async def listen(self) -> str:
        """
        Capture one utterance. Returns transcribed text or "(muted)"/"(silence)".
        """
        async with self.lock:
            if self._is_muted():
                return "(muted)"

            self.state.set(STATUS="listening")
            try:
                text = await self._capture_utterance()
                return text if text else "(silence)"
            finally:
                self.state.set(STATUS="idle")

    async def queue_listen(self):
        """Start capturing in background. Result stored in _buffered_text."""
        await self._cancel_buffer()
        self._buffered_text = None
        self._buffer_task = asyncio.create_task(self._run_buffered_listen())

    async def _run_buffered_listen(self):
        """Background capture task — stores result in _buffered_text."""
        try:
            async with self.lock:
                if self._is_muted():
                    self._buffered_text = "(muted)"
                    return
                self.state.set(STATUS="listening")
                self.logger.log_event("BUFFER_LISTEN_START")
                try:
                    text = await self._capture_utterance()
                    self._buffered_text = text if text else "(silence)"
                    self.logger.log_event("BUFFER_LISTEN_END", {"text": self._buffered_text})
                finally:
                    self.state.set(STATUS="idle")
        except asyncio.CancelledError:
            self.logger.log_event("BUFFER_LISTEN_CANCELLED")

    async def _cancel_buffer(self):
        """Cancel any running buffer task."""
        if self._buffer_task and not self._buffer_task.done():
            self._buffer_task.cancel()
            try:
                await self._buffer_task
            except asyncio.CancelledError:
                pass
            self._buffer_task = None

    def drain_buffer(self) -> str | None:
        """Return buffered text if available, clearing it."""
        if self._buffered_text is not None:
            text = self._buffered_text
            self._buffered_text = None
            self._buffer_task = None
            return text
        if self._buffer_task and self._buffer_task.done():
            self._buffer_task = None
        return None

    async def speak_and_listen(self, text: str) -> str:
        """
        Speak text, then capture utterance (with barge-in if enabled).
        Checks buffer first — if user already spoke during the gap, just speak and return that.
        """
        buffered = self.drain_buffer()
        if buffered and buffered not in ("(silence)", "(muted)"):
            self.logger.log_event("BUFFER_HIT", {"buffered_text": buffered})
            # User already spoke — just do TTS, no capture needed
            pid = await self.speak(text)
            if pid:
                while True:
                    try:
                        os.kill(pid, 0)
                        await asyncio.sleep(0.1)
                    except ProcessLookupError:
                        break
            self.state.set(STATUS="idle")
            return buffered

        # Cancel any stale buffer task before acquiring lock
        await self._cancel_buffer()

        async with self.lock:
            if self._is_muted():
                # Still speak, but don't capture
                pid = await self.speak(text)
                if pid:
                    # Wait for TTS to finish
                    while True:
                        try:
                            os.kill(pid, 0)
                            await asyncio.sleep(0.1)
                        except ProcessLookupError:
                            break
                return "(muted)"

            # Start TTS
            tts_pid = await self.speak(text)
            if not tts_pid:
                return "(silence)"

            # Capture with barge-in
            self.state.set(STATUS="speaking+listening")
            try:
                return await self._capture_utterance(tts_pid=tts_pid, tts_text=text)
            finally:
                self.state.set(STATUS="idle")

    async def _capture_utterance(self, tts_pid: int = 0, tts_text: str = "") -> str:
        """
        Core capture logic: streams mic to WLK, handles barge-in, returns text.
        """
        # Health check: wait for WLK to be ready before connecting
        wlk_port = self.config.get_int("WLK_PORT", 8090)
        for attempt in range(10):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("localhost", wlk_port), timeout=2.0
                )
                writer.close()
                await writer.wait_closed()
                if attempt > 0:
                    print(f"[WLK] ready after {attempt + 1} attempts", file=sys.stderr, flush=True)
                break
            except (asyncio.TimeoutError, OSError) as e:
                print(f"[WLK] health check attempt {attempt + 1}/10 failed: {e}", file=sys.stderr, flush=True)
                if attempt == 9:
                    print(f"[WLK] not reachable after 10 attempts, giving up", file=sys.stderr, flush=True)
                    return "(wlk_error)"
                await asyncio.sleep(1.0)

        # Resilience: retry connection with exponential backoff
        ws = None
        max_retries = 3
        for retry in range(max_retries):
            try:
                retry_timeout = min(5.0 * (2 ** retry), 15.0)  # 5s, 10s, 15s
                ws = await asyncio.wait_for(
                    websockets.connect(self.wlk_url), timeout=retry_timeout
                )
                print(f"[WLK] websocket connected", file=sys.stderr, flush=True)
                break
            except (asyncio.TimeoutError, OSError) as e:
                if retry < max_retries - 1:
                    backoff = 0.5 * (2 ** retry)  # 0.5s, 1s, 2s
                    print(f"[WLK] websocket connect attempt {retry + 1}/{max_retries} failed: {e}, retrying in {backoff}s", file=sys.stderr, flush=True)
                    await asyncio.sleep(backoff)
                else:
                    print(f"[WLK] websocket connect failed after {max_retries} attempts: {e}", file=sys.stderr, flush=True)
                    return "(wlk_error)"

        if ws is None:
            print(f"[WLK] websocket connection failed, no valid connection established", file=sys.stderr, flush=True)
            return "(wlk_error)"

        text_result = ""
        last_text_change = 0.0
        got_text = False
        frame_size = int(self.sample_rate * 0.02)  # 20ms chunks (320 samples, matches AEC frame)

        # TTS monitoring
        tts_active = tts_pid > 0
        tts_done_event = asyncio.Event()
        if not tts_active:
            tts_done_event.set()

        # Re-query system default input if in auto mode (user may have switched)
        if self._auto_device:
            new_default = sd.default.device[0]
            if new_default is not None and int(new_default) != self.device_index:
                dev = sd.query_devices(int(new_default))
                print(f"  Input device changed: [{int(new_default)}] {dev['name']}")
                self.device_index = int(new_default)

        # Barge-in state
        barge_in_enabled = tts_active and self.barge_in_enabled and self.blackhole_device is not None
        barge_in_triggered = False

        loop = asyncio.get_event_loop()
        audio_queue: asyncio.Queue = asyncio.Queue()
        barge_ref_queue: asyncio.Queue = asyncio.Queue()  # ref frames for barge-in detection
        send_ref_queue: asyncio.Queue = asyncio.Queue()   # ref frames for AEC in send path
        done_event = asyncio.Event()

        def audio_callback(indata, frames, time_info, status):
            boosted = np.clip(indata.astype(np.float64) * self.gain, -32768, 32767).astype(np.int16)
            loop.call_soon_threadsafe(audio_queue.put_nowait, boosted)

        def ref_callback(indata, frames, time_info, status):
            frame = indata.copy()
            loop.call_soon_threadsafe(barge_ref_queue.put_nowait, frame)
            loop.call_soon_threadsafe(send_ref_queue.put_nowait, frame)

        # Mic stream
        mic_stream = sd.InputStream(
            device=self.device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_size,
            callback=audio_callback,
        )

        # Reference stream (BlackHole) - only if barge-in enabled
        ref_stream = None
        if barge_in_enabled:
            ref_stream = sd.InputStream(
                device=self.blackhole_device,
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=frame_size,
                callback=ref_callback,
            )

        async def tts_monitor():
            """Poll TTS process until it exits"""
            if not tts_active:
                return
            while not done_event.is_set():
                try:
                    os.kill(tts_pid, 0)
                except ProcessLookupError:
                    self.logger.log_event("TTS_STOPPED_NATURAL", {"pid": tts_pid})
                    self._tts_finished_at = time.monotonic()
                    tts_done_event.set()
                    return
                await asyncio.sleep(0.05)

        async def barge_in_monitor():
            """Adaptive barge-in: calibrates mic baseline during TTS, detects speech above it.
            Buffers all mic frames and replays them to WLK after barge-in so no speech is lost."""
            nonlocal barge_in_triggered
            if not barge_in_enabled:
                return

            await asyncio.sleep(0.5)
            if tts_done_event.is_set():
                return

            # Geigel double-talk detection: compare raw mic/reference ratio
            # Echo = ~5-12% of reference, real speech = 40%+ (see docs/barge-in-setup.md)
            buffered_mic_frames: list[np.ndarray] = []
            spike_count = 0
            frame_count = 0
            nonsplke_run = 0  # consecutive non-spike frames (for slow decay)
            ratio_threshold = self.barge_in_ratio  # from config (default 0.15)

            # Dynamic calibration: measure echo bleed during first N frames
            calibration_frames = 15  # ~750ms at 50ms/frame
            calibration_ratios: list[float] = []
            calibration_mic_rms_values: list[float] = []
            min_speech_rms = 500  # default until calibrated
            calibrated = False

            while not done_event.is_set() and not tts_done_event.is_set():
                mic_frame = None
                while not audio_queue.empty():
                    mic_frame = audio_queue.get_nowait()

                if mic_frame is None:
                    await asyncio.sleep(0.05)
                    continue

                # Get raw mic RMS BEFORE AEC for barge-in detection
                raw_mic_rms = float(np.sqrt(np.mean(mic_frame.astype(np.float64) ** 2)))

                # Get reference RMS (TTS output via BlackHole)
                ref_frame = None
                while not barge_ref_queue.empty():
                    ref_frame = barge_ref_queue.get_nowait()
                ref_rms = 0.0
                if ref_frame is not None:
                    ref_rms = float(np.sqrt(np.mean(ref_frame.astype(np.float64) ** 2)))

                # Apply AEC for the buffered frames (used later for WLK send)
                if self.aec is not None and ref_frame is not None:
                    try:
                        mic_frame = self.aec.cancel(mic_frame.flatten(), ref_frame.flatten())
                        mic_frame = mic_frame.reshape(-1, 1)
                    except Exception:
                        pass

                buffered_mic_frames.append(mic_frame)
                frame_count += 1

                # Skip first few frames for stabilization
                if frame_count <= 5:
                    await asyncio.sleep(0.05)
                    continue

                # Dynamic calibration phase: collect echo bleed measurements
                if not calibrated and frame_count <= 5 + calibration_frames:
                    if ref_rms > 100:  # Only calibrate when TTS is playing
                        calibration_ratios.append(raw_mic_rms / ref_rms)
                        calibration_mic_rms_values.append(raw_mic_rms)
                    if frame_count == 5 + calibration_frames:
                        calibrated = True
                        if calibration_ratios:
                            avg_echo_ratio = sum(calibration_ratios) / len(calibration_ratios)
                            max_echo_rms = max(calibration_mic_rms_values)
                            # Set ratio threshold to 2x observed echo ratio (with floor)
                            ratio_threshold = max(ratio_threshold, avg_echo_ratio * 2.0)
                            # Set min speech RMS to 2x observed max echo bleed (with floor)
                            min_speech_rms = max(500, max_echo_rms * 2.0)
                            print(f"[BARGE-IN] Calibrated: echo_ratio={avg_echo_ratio:.2f} max_echo_rms={max_echo_rms:.0f} → ratio_thr={ratio_threshold:.2f} min_speech={min_speech_rms:.0f}", file=sys.stderr, flush=True)
                        else:
                            print(f"[BARGE-IN] Calibration: no ref frames, using defaults ratio_thr={ratio_threshold} min_speech={min_speech_rms}", file=sys.stderr, flush=True)
                    await asyncio.sleep(0.05)
                    continue

                # Geigel ratio detection: mic/reference
                # Require both: ratio exceeds threshold AND mic RMS is loud enough to be speech
                if ref_rms > 100:  # Only detect when TTS is actively playing
                    ratio = raw_mic_rms / ref_rms
                    if frame_count % 10 == 0:
                        print(f"[BARGE-IN] mic={raw_mic_rms:.0f} ref={ref_rms:.0f} ratio={ratio:.2f} thr={ratio_threshold} spk={spike_count}", file=sys.stderr, flush=True)
                    if ratio > ratio_threshold and raw_mic_rms > min_speech_rms:
                        spike_count += 1
                        nonsplke_run = 0
                        if spike_count >= 2:
                            print(f"[BARGE-IN] spike! ratio={ratio:.2f} spikes={spike_count}", file=sys.stderr, flush=True)
                    else:
                        # Slow decay: only decrement after 3 consecutive non-spike frames
                        # (20ms frames = 5x more frames than 100ms, so decay must be slower)
                        nonsplke_run += 1
                        if nonsplke_run >= 3:
                            spike_count = max(0, spike_count - 1)
                            nonsplke_run = 0
                else:
                    # TTS pausing — slow decay
                    nonsplke_run += 1
                    if nonsplke_run >= 3:
                        spike_count = max(0, spike_count - 1)
                        nonsplke_run = 0

                if spike_count >= 3:
                    self.logger.log_event("BARGE_IN_DETECTED", {"mic_rms": raw_mic_rms})
                    print(f"BARGE-IN! mic_rms={raw_mic_rms:.0f} (buffered {len(buffered_mic_frames)} frames for replay)", file=sys.stderr)
                    barge_in_triggered = True
                    try:
                        os.kill(tts_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    tts_done_event.set()
                    # Only replay frames from the trigger point onward
                    # Earlier frames are contaminated with TTS bleed
                    replay_start = max(0, len(buffered_mic_frames) - 3)
                    for frame in buffered_mic_frames[replay_start:]:
                        audio_queue.put_nowait(frame)
                    while not barge_ref_queue.empty():
                        barge_ref_queue.get_nowait()
                    while not send_ref_queue.empty():
                        send_ref_queue.get_nowait()
                    return

                await asyncio.sleep(0.05)

        async def send_audio():
            """Send mic audio to WLK"""
            await tts_done_event.wait()
            self.logger.log_event("CAPTURE_START")
            print(f"[DEBUG] TTS done, starting audio send", file=sys.stderr, flush=True)
            if tts_active and not barge_in_triggered:
                # Wait for TTS audio to actually stop playing (not just process exit)
                # Monitor ref stream RMS — when it drops to near-zero, speakers are silent
                if self.blackhole_device is not None:
                    silent_frames = 0
                    for _ in range(100):  # Max ~5s wait
                        await asyncio.sleep(0.05)
                        ref_frame = None
                        while not send_ref_queue.empty():
                            ref_frame = send_ref_queue.get_nowait()
                        if ref_frame is not None:
                            rms = float(np.sqrt(np.mean(ref_frame.astype(np.float64) ** 2)))
                            if rms < 50:
                                silent_frames += 1
                            else:
                                silent_frames = 0
                            if silent_frames >= 10:  # ~500ms of silence on ref
                                break
                        else:
                            silent_frames += 1
                            if silent_frames >= 10:
                                break
                    print(f"[DEBUG] Ref stream silent", file=sys.stderr, flush=True)
                    # Extra delay: speakers have hardware buffers that play after BlackHole goes silent
                    # Plus room reverb tail. Mic still picks up residual audio.
                    await asyncio.sleep(1.5)
                    print(f"[DEBUG] Post-silence delay done, flushing mic buffer", file=sys.stderr, flush=True)
                else:
                    await asyncio.sleep(3.0)
                # Flush any remaining contaminated frames
                while not audio_queue.empty():
                    audio_queue.get_nowait()
                while not send_ref_queue.empty():
                    send_ref_queue.get_nowait()
            if not barge_in_enabled:
                mic_stream.start()

            frame_count = 0
            send_failed = False
            # Post-TTS energy gate: suppress bleed frames after TTS
            # Applies to ALL captures within 5s of TTS finishing (including /listen retries)
            # With 8x mic gain, TTS bleed through speakers→mic is 500-900 RMS
            # Real speech with gain is typically 2000+ RMS
            time_since_tts = time.monotonic() - self._tts_finished_at if self._tts_finished_at > 0 else 999
            remaining_gate = max(0, 3.0 - time_since_tts)
            energy_gate_rms = 1000 if (tts_active or remaining_gate > 0) else 0
            gate_until = time.monotonic() + (3.0 if tts_active else remaining_gate)
            gate_consecutive = 0  # require 3+ consecutive loud frames to pass
            if remaining_gate > 0 and not tts_active:
                print(f"[GATE] Applying post-TTS gate to /listen call ({remaining_gate:.1f}s remaining)", file=sys.stderr, flush=True)
            try:
                while not done_event.is_set() and not send_failed:
                    try:
                        data = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                        # Apply AEC to clean residual echo from mic frames
                        if self.aec is not None and not send_ref_queue.empty():
                            ref_frame = None
                            while not send_ref_queue.empty():
                                ref_frame = send_ref_queue.get_nowait()
                            if ref_frame is not None:
                                try:
                                    data = self.aec.cancel(data.flatten(), ref_frame.flatten())
                                    data = data.reshape(-1, 1)
                                except Exception:
                                    pass
                        # Energy gate: suppress residual TTS bleed after flush
                        # Requires 3 consecutive loud frames to prevent isolated noise spikes
                        if time.monotonic() < gate_until:
                            frame_rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                            if frame_count % 100 == 0:
                                print(f"[GATE] rms={frame_rms:.0f} gate={energy_gate_rms} remaining={gate_until - time.monotonic():.1f}s", file=sys.stderr, flush=True)
                            if frame_rms >= energy_gate_rms:
                                gate_consecutive += 1
                                if gate_consecutive < 3:
                                    continue  # Not enough consecutive loud frames yet
                                # Sustained loud audio — disable gate for rest of session
                                gate_until = 0
                                print(f"[GATE] speech detected (rms={frame_rms:.0f}), gate disabled", file=sys.stderr, flush=True)
                            else:
                                gate_consecutive = 0
                                continue
                        # Resilience: wrap send in exception handler and add rate limiting
                        try:
                            await ws.send(data.tobytes())
                            frame_count += 1
                            # Rate limiting: prevent overwhelming WLK with rapid frame bursts
                            if frame_count % 50 == 0:
                                await asyncio.sleep(0.01)
                            if frame_count % 100 == 0:
                                print(f"[DEBUG] Sent {frame_count} frames to WLK", file=sys.stderr, flush=True)
                        except websockets.exceptions.ConnectionClosed as e:
                            print(f"[WLK] send failed, connection closed: code={e.code} reason='{e.reason}'", file=sys.stderr, flush=True)
                            send_failed = True
                            done_event.set()
                        except Exception as e:
                            print(f"[WLK] send failed with unexpected error: {e}", file=sys.stderr, flush=True)
                            send_failed = True
                            done_event.set()
                    except asyncio.TimeoutError:
                        continue
            finally:
                print(f"[DEBUG] Audio send complete, sent {frame_count} frames total", file=sys.stderr, flush=True)
                if not barge_in_enabled:
                    mic_stream.stop()

        async def recv_transcription():
            """Receive and accumulate transcription from WLK"""
            nonlocal text_result, last_text_change, got_text
            # Don't start unresponsive timer until we're actually sending audio
            await tts_done_event.wait()
            idle_since = time.monotonic()
            msg_count = 0

            while not done_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    idle_since = time.monotonic()
                    msg_count += 1
                except asyncio.TimeoutError:
                    # Resilience: 3s timeout for WLK failure detection,
                    # but only AFTER first speech has been received.
                    # Before speech: wait up to max_duration for user to start speaking.
                    if got_text and time.monotonic() - idle_since > 3.0:
                        print("[WLK] unresponsive for 3s after speech, ending capture", file=sys.stderr, flush=True)
                        done_event.set()
                        return
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"[WLK] connection closed during recv: code={e.code} reason='{e.reason}'", file=sys.stderr, flush=True)
                    if got_text and text_result:
                        print(f"[WLK] preserving partial transcription: '{text_result}'", file=sys.stderr, flush=True)
                    done_event.set()
                    return

                d = json.loads(msg)
                lines_text = " ".join(l.get("text", "") for l in d.get("lines", [])).strip()
                buffer_text = d.get("buffer_transcription", "").strip()
                combined = (lines_text + " " + buffer_text).strip()

                # Filter hallucinations (exact and partial matches)
                import re
                combined = re.sub(r'\[(?:Music|INAUDIBLE|BLANK_AUDIO|BLANK[^\]]*)\]?', '', combined, flags=re.IGNORECASE)
                combined = combined.strip()

                if combined and combined != text_result:
                    text_result = combined
                    last_text_change = time.monotonic()
                    print(f"[DEBUG] WLK transcription: '{combined}'", file=sys.stderr, flush=True)
                    if not got_text:
                        got_text = True
                        self.logger.log_event("FIRST_TRANSCRIPTION", {"text": combined})
                        print("[DEBUG] First text received", file=sys.stderr, flush=True)
                    else:
                        self.logger.log_event("TRANSCRIPTION_UPDATE", {"text": combined})

        async def monitor():
            """Check for end-of-utterance"""
            await tts_done_event.wait()
            capture_start = time.monotonic()
            # After barge-in, user is mid-thought — give them more silence leeway
            effective_timeout = self.silence_timeout * 2 if barge_in_triggered else self.silence_timeout

            while not done_event.is_set():
                await asyncio.sleep(0.3)
                now = time.monotonic()

                if now - capture_start > self.max_duration:
                    done_event.set()
                    return

                if got_text and last_text_change > 0:
                    idle_time = now - last_text_change
                    if idle_time >= effective_timeout and len(text_result) >= 2:
                        self.logger.log_event("CAPTURE_END", {
                            "text": text_result,
                            "silence_duration": idle_time,
                        })
                        done_event.set()
                        return

        # Start streams
        if barge_in_enabled:
            mic_stream.start()
            ref_stream.start()

        try:
            async with ws:
                tasks = [
                    asyncio.create_task(tts_monitor()),
                    asyncio.create_task(barge_in_monitor()),
                    asyncio.create_task(send_audio()),
                    asyncio.create_task(recv_transcription()),
                    asyncio.create_task(monitor()),
                ]
                await done_event.wait()
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Record TTS finish time for post-TTS protection in subsequent /listen calls
            if tts_active:
                self._tts_finished_at = time.monotonic()
                # Also kill say if still running (e.g. capture ended before TTS finished)
                if self._tts_pid:
                    try:
                        os.kill(self._tts_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            if barge_in_enabled:
                mic_stream.stop()
                mic_stream.close()
                if ref_stream:
                    ref_stream.stop()
                    ref_stream.close()
            elif mic_stream.active:
                mic_stream.stop()
                mic_stream.close()

        # Echo filter: strip TTS bleed from transcription
        if tts_text and text_result:
            text_result = self._strip_tts_echo(text_result, tts_text)

        return text_result

    @staticmethod
    def _strip_tts_echo(transcription: str, tts_text: str) -> str:
        """Remove fragments of TTS text that bled into the transcription.
        Handles partial matches — echo may start mid-sentence of TTS text."""
        tts_words = tts_text.lower().split()
        trans_words = transcription.lower().split()

        if len(trans_words) < 3 or len(tts_words) < 3:
            return transcription

        # Find the longest run of consecutive TTS words at the start of transcription
        # The echo might start from any word in the TTS text (mic may miss first words)
        best_match_len = 0  # number of transcription words matched

        for tts_start in range(len(tts_words)):
            match_len = 0
            for j in range(min(len(trans_words) - match_len, len(tts_words) - tts_start)):
                tw = trans_words[match_len].rstrip(".,!?;:-—'\"")
                sw = tts_words[tts_start + j].rstrip(".,!?;:-—'\"")
                if tw == sw:
                    match_len += 1
                else:
                    break
            if match_len > best_match_len:
                best_match_len = match_len

        if best_match_len >= 3:
            # Strip matched echo words, keep the rest
            remaining_words = transcription.split()[best_match_len:]
            remaining = " ".join(remaining_words).strip(" .,!?-—")
            if remaining:
                print(f"[ECHO-FILTER] stripped {best_match_len} TTS echo words, kept: '{remaining}'", file=sys.stderr, flush=True)
                return remaining
            else:
                print(f"[ECHO-FILTER] entire transcription was TTS echo", file=sys.stderr, flush=True)
                return "(silence)"

        # Fuzzy check: if >50% of transcription words appear in TTS text, likely echo
        if len(trans_words) >= 4:
            tts_word_set = set(w.rstrip(".,!?;:-—'\"") for w in tts_words)
            match_count = sum(1 for w in trans_words if w.rstrip(".,!?;:-—'\"") in tts_word_set)
            match_ratio = match_count / len(trans_words)
            if match_ratio > 0.5:
                print(f"[ECHO-FILTER] fuzzy match {match_ratio:.0%} ({match_count}/{len(trans_words)} words), treating as echo", file=sys.stderr, flush=True)
                return "(silence)"

        return transcription


# ============================================================================
# FastAPI Server
# ============================================================================


class SpeakRequest(BaseModel):
    text: str
    voice: str | None = None  # Optional: override server voice for this request


class QueueSpeakRequest(BaseModel):
    text: str
    voice: str
    session_id: str


class StatusResponse(BaseModel):
    state: str
    muted: bool
    input_device: str = ""
    input_device_index: int = -1
    output_device: str = ""
    output_device_index: int = -1
    barge_in: bool = False
    blackhole_device: int | None = None
    auto_device: bool = False
    voice: str = ""
    volume: int = 50


class TextResponse(BaseModel):
    text: str


# Global instances
config = Config()
state = StateManager()
log_file = Path.home() / ".claude-talk/audio-server.log"
event_logger = EventLogger(log_file)
audio_engine = AudioEngine(config, state, event_logger)
wlk_manager = WLKManager(config)

# Session management for tmux routing
db = DB()
session_store = SessionStore(db)


def send_transcription_to_claude(text: str) -> None:
    """Send transcription to Claude session(s) via tmux, using name-based routing."""
    if not text or text == "(silence)":
        return

    from claude_talk.routing import parse_route, get_target_sessions

    route_type, target_session_id, cleaned_text = parse_route(text)
    session_ids = get_target_sessions(route_type, target_session_id)

    if not session_ids:
        print(f"[TMUX] No target sessions found (route: {route_type})", file=sys.stderr)
        return

    routed_text = f"The user said aloud: {cleaned_text}"
    for sid in session_ids:
        tmux_target = session_store.get_tmux_target(sid)
        if not tmux_target:
            print(f"[TMUX] No tmux target for session {sid[:8]}", file=sys.stderr)
            continue
        if send_to_session(tmux_target, routed_text):
            print(f"[TMUX] {route_type} -> {tmux_target}: {cleaned_text}", file=sys.stderr)
        else:
            print(f"[TMUX] Failed to send to {tmux_target}", file=sys.stderr)

# Message queue for multi-session voice handling (initialized in lifespan)
message_queue = None
queue_processor_task = None


async def process_message_queue():
    """Background task that processes queued TTS messages sequentially."""
    global message_queue
    event_logger.log_event("QUEUE_PROCESSOR_START")

    while True:
        try:
            # Get next message from queue (blocks until available)
            msg = await message_queue.get()

            if msg is None:  # Shutdown signal
                event_logger.log_event("QUEUE_PROCESSOR_STOP")
                break

            text, voice, session_id = msg["text"], msg["voice"], msg["session_id"]
            event_logger.log_event("QUEUE_PROCESS_START", {
                "session_id": session_id,
                "voice": voice,
                "text": text[:50]
            })

            # Set voice for this message
            original_voice = audio_engine.voice
            audio_engine.voice = voice

            # Speak and listen with barge-in
            try:
                response = await audio_engine.speak_and_listen(text)
                event_logger.log_event("QUEUE_PROCESS_END", {
                    "session_id": session_id,
                    "response": response[:50] if response else ""
                })

                # Store response for the session to retrieve
                # Use a marker to indicate response is ready (even if empty)
                response_value = response if response else "(silence)"
                state.set(**{f"RESPONSE_{session_id}": response_value, f"READY_{session_id}": "true"})

            finally:
                # Restore original voice
                audio_engine.voice = original_voice

            message_queue.task_done()

        except asyncio.CancelledError:
            event_logger.log_event("QUEUE_PROCESSOR_CANCELLED")
            break
        except Exception as e:
            event_logger.log_event("QUEUE_PROCESSOR_ERROR", {"error": str(e)})
            message_queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown"""
    global queue_processor_task, message_queue

    # Initialize message queue in the event loop
    message_queue = asyncio.Queue()

    state.set(SESSION="active", STATUS="idle", MUTED="false")
    await wlk_manager.start()
    # Wait for WLK to be ready
    for _ in range(30):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", config.get_int("WLK_PORT", 8090)),
                timeout=1.0,
            )
            writer.close()
            await writer.wait_closed()
            print("WLK ready")
            break
        except (asyncio.TimeoutError, OSError):
            await asyncio.sleep(1)

    # Start message queue processor
    queue_processor_task = asyncio.create_task(process_message_queue())
    print("Message queue processor started")

    yield

    # Stop queue processor
    if queue_processor_task:
        await message_queue.put(None)  # Shutdown signal
        try:
            await asyncio.wait_for(queue_processor_task, timeout=5.0)
        except asyncio.TimeoutError:
            queue_processor_task.cancel()

    await wlk_manager.stop()
    state.set(SESSION="stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/status")
async def get_status() -> StatusResponse:
    """Get current server state with device and barge-in info"""
    import sounddevice as sd
    input_dev = sd.query_devices(audio_engine.device_index)
    default_out = sd.default.device[1]
    output_dev = sd.query_devices(int(default_out)) if default_out is not None else {}

    # Get current volume
    volume_info = await get_volume()

    return StatusResponse(
        state=state.get("STATUS", "idle"),
        muted=state.get("MUTED", "false") == "true",
        input_device=input_dev.get("name", "unknown"),
        input_device_index=audio_engine.device_index,
        output_device=output_dev.get("name", "unknown"),
        output_device_index=int(default_out) if default_out is not None else -1,
        barge_in=audio_engine.barge_in_enabled,
        blackhole_device=audio_engine.blackhole_device,
        auto_device=audio_engine._auto_device,
        voice=audio_engine.voice,
        volume=volume_info["volume"],
    )


@app.get("/listen")
async def listen() -> TextResponse:
    """Block until user speaks, return transcription"""
    event_logger.log_event("API_LISTEN_START")
    text = await audio_engine.listen()
    event_logger.log_event("API_LISTEN_END", {"text": text})

    # Send transcription to Claude via tmux
    try:
        print(f"[DEBUG] About to route: '{text}'", file=sys.stderr, flush=True)
        send_transcription_to_claude(text)
        print(f"[DEBUG] Routing complete", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[ERROR] Routing failed: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()

    return TextResponse(text=text)


@app.post("/queue-listen")
async def queue_listen() -> dict[str, str]:
    """Start listening in background. Result buffered for next /speak."""
    event_logger.log_event("API_QUEUE_LISTEN")
    await audio_engine.queue_listen()
    return {"status": "ok"}


@app.post("/speak")
async def speak(req: SpeakRequest) -> TextResponse:
    """Speak text via TTS, then capture user's response (with barge-in if available).
    BLOCKING: waits for user speech and returns transcription. Use /tts for async."""
    event_logger.log_event("API_SPEAK_START", {"text": req.text})
    text = await audio_engine.speak_and_listen(req.text)
    event_logger.log_event("API_SPEAK_END", {"text": text})

    # Send transcription to Claude via tmux
    try:
        send_transcription_to_claude(text)
    except Exception as e:
        print(f"[ERROR] Routing failed: {e}", file=sys.stderr, flush=True)

    return TextResponse(text=text)


@app.post("/tts")
async def tts(req: SpeakRequest):
    """Fire-and-forget TTS: speak text, then capture and route user response in background.
    Returns immediately without waiting for user speech.
    Optional voice field overrides the server's default voice for this utterance."""
    original_voice = audio_engine.voice
    if req.voice:
        audio_engine.voice = req.voice

    async def _speak_and_route(voice_to_restore: str):
        try:
            event_logger.log_event("TTS_START", {"text": req.text, "voice": audio_engine.voice})
            text = await audio_engine.speak_and_listen(req.text)
            event_logger.log_event("TTS_END", {"text": text})
            send_transcription_to_claude(text)
        except Exception as e:
            print(f"[TTS] Error: {e}", file=sys.stderr, flush=True)
        finally:
            audio_engine.voice = voice_to_restore

    asyncio.create_task(_speak_and_route(original_voice))
    return {"status": "speaking"}


@app.post("/queue-speak")
async def queue_speak(req: QueueSpeakRequest) -> dict:
    """Queue a TTS message with specific voice for sequential playback"""
    print(f"[DEBUG] queue_speak called: text={req.text[:20]}, voice={req.voice}, session={req.session_id[:8]}", file=sys.stderr, flush=True)
    try:
        print(f"[DEBUG] message_queue is None: {message_queue is None}", file=sys.stderr, flush=True)
        if message_queue is None:
            raise HTTPException(status_code=503, detail="Message queue not initialized")

        event_logger.log_event("API_QUEUE_SPEAK", {
            "session_id": req.session_id,
            "voice": req.voice,
            "text": req.text[:50]
        })
        await message_queue.put({
            "text": req.text,
            "voice": req.voice,
            "session_id": req.session_id
        })
        return {"status": "queued", "queue_size": message_queue.qsize()}
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR in queue_speak: {e}", file=sys.stderr, flush=True)
        raise


@app.get("/queue-response/{session_id}")
async def get_queue_response(session_id: str) -> TextResponse:
    """Get and clear the response for a session (blocks until available)"""
    try:
        # Poll for response with timeout
        ready_key = f"READY_{session_id}"
        response_key = f"RESPONSE_{session_id}"

        for _ in range(3600):  # 1 hour timeout (1 second intervals)
            # Check if response is ready (queue processor sets READY flag)
            if state.get(ready_key) == "true":
                response = state.get(response_key) or "(silence)"
                # Clear both keys
                state.set(**{ready_key: "", response_key: ""})
                return TextResponse(text=response)
            await asyncio.sleep(1)
        return TextResponse(text="(timeout)")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR in get_queue_response: {e}", file=sys.stderr, flush=True)
        raise


@app.get("/queue-status")
async def get_queue_status() -> dict:
    """Get current message queue status"""
    return {
        "queue_size": message_queue.qsize() if message_queue else 0,
        "processor_running": queue_processor_task is not None and not queue_processor_task.done()
    }


@app.get("/devices")
async def get_devices() -> dict:
    """List audio devices with active input/output info"""
    devices = sd.query_devices()
    device_list = []
    for i, dev in enumerate(devices):
        device_list.append({
            "index": i,
            "name": dev["name"],
            "input_channels": dev["max_input_channels"],
            "output_channels": dev["max_output_channels"],
        })
    default_in, default_out = sd.default.device
    return {
        "devices": device_list,
        "active_input": audio_engine.device_index,
        "active_input_name": devices[audio_engine.device_index]["name"],
        "default_input": int(default_in) if default_in is not None else None,
        "default_output": int(default_out) if default_out is not None else None,
    }


@app.post("/mute")
async def mute() -> dict[str, str]:
    """Mute microphone"""
    state.set(MUTED="true")
    return {"status": "muted"}


@app.post("/unmute")
async def unmute() -> dict[str, str]:
    """Unmute microphone"""
    state.set(MUTED="false")
    return {"status": "unmuted"}


@app.post("/voice")
async def set_voice(req: dict):
    """Change TTS voice at runtime"""
    voice = req.get("voice")
    if not voice:
        return {"error": "voice is required"}, 400
    audio_engine.voice = voice
    return {"voice": audio_engine.voice}


@app.get("/volume")
async def get_volume() -> dict[str, int]:
    """Get current system output volume (0-100)"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", "output volume of (get volume settings)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        volume = int(stdout.decode().strip())
        return {"volume": volume}
    except Exception:
        return {"volume": 50}  # fallback


@app.post("/volume/up")
async def volume_up() -> dict[str, int]:
    """Increase system volume by 10%"""
    current = await get_volume()
    new_volume = min(100, current["volume"] + 10)
    try:
        await asyncio.create_subprocess_exec(
            "osascript", "-e", f"set volume output volume {new_volume}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return {"volume": new_volume}
    except Exception:
        return current


@app.post("/volume/down")
async def volume_down() -> dict[str, int]:
    """Decrease system volume by 10%"""
    current = await get_volume()
    new_volume = max(0, current["volume"] - 10)
    try:
        await asyncio.create_subprocess_exec(
            "osascript", "-e", f"set volume output volume {new_volume}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return {"volume": new_volume}
    except Exception:
        return current


@app.post("/stop")
async def stop():
    """Graceful shutdown"""
    await wlk_manager.stop()
    state.set(SESSION="stopped")
    # Give time for response to be sent
    asyncio.create_task(_delayed_exit())
    return {"status": "shutting down"}


async def _delayed_exit():
    await asyncio.sleep(1)
    os._exit(0)


# ============================================================================
# Main
# ============================================================================


def main():
    import socket as _socket
    socket_path = Path.home() / ".claude-talk/audio-server.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    # Create and bind socket ourselves so we can chmod before accepting connections
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.bind(str(socket_path))
    socket_path.chmod(0o600)  # Owner-only before any client can connect

    print(f"Starting audio server on {socket_path}")
    uvicorn.run(app, fd=sock.fileno(), log_level="warning")


if __name__ == "__main__":
    main()

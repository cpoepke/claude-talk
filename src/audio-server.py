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


class Config:
    """Loads config from defaults.env + ~/.claude-talk/config.env"""

    def __init__(self):
        self.values: dict[str, str] = {}
        self._load_env_file(Path(__file__).parent.parent / "config/defaults.env")
        user_config = Path.home() / ".claude-talk/config.env"
        if user_config.exists():
            self._load_env_file(user_config)

    def _load_env_file(self, path: Path):
        """Parse shell-style KEY=VALUE lines"""
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            # Remove quotes
            val = val.strip().strip('"').strip("'")
            self.values[key.strip()] = val

        # Second pass: expand variables now that all are loaded
        for key in list(self.values.keys()):
            original = self.values[key]
            # Expand $HOME and ${VAR} using both os.environ and self.values
            expanded = original
            for var_key, var_val in self.values.items():
                expanded = expanded.replace(f"${{{var_key}}}", var_val)
                expanded = expanded.replace(f"${var_key}", var_val)
            expanded = os.path.expandvars(expanded)
            self.values[key] = expanded

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except ValueError:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key, str(default)))
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key, "").lower()
        if val in ("true", "1", "yes"):
            return True
        if val in ("false", "0", "no"):
            return False
        return default


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
        self.barge_in_ratio = config.get_float("BARGE_IN_RATIO", 0.4)

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
                self.aec = SpeexAEC(frame_size=1600, filter_length=4800, sample_rate=16000)
                print(f"  Speex AEC: enabled (frame=1600, filter=4800)")
            except Exception as e:
                print(f"  Speex AEC: unavailable ({e})", file=sys.stderr)

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
        """
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

        try:
            ws = await asyncio.wait_for(
                websockets.connect(self.wlk_url), timeout=10.0
            )
            print(f"[WLK] websocket connected", file=sys.stderr, flush=True)
        except (asyncio.TimeoutError, OSError) as e:
            print(f"[WLK] websocket connect failed: {e}", file=sys.stderr, flush=True)
            return "(wlk_error)"

        text_result = ""
        last_text_change = 0.0
        got_text = False
        frame_size = int(self.sample_rate * 0.1)  # 100ms chunks

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
        ref_queue: asyncio.Queue = asyncio.Queue()
        done_event = asyncio.Event()

        def audio_callback(indata, frames, time_info, status):
            boosted = np.clip(indata.astype(np.float64) * self.gain, -32768, 32767).astype(np.int16)
            loop.call_soon_threadsafe(audio_queue.put_nowait, boosted)

        def ref_callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(ref_queue.put_nowait, indata.copy())

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

            # Unified calibration + detection loop
            CALIBRATION_FRAMES = 8  # ~0.8s at 100ms/frame
            baseline_rms: list[float] = []
            buffered_mic_frames: list[np.ndarray] = []
            spike_count = 0
            frame_count = 0
            threshold = 0.0

            while not done_event.is_set() and not tts_done_event.is_set():
                mic_frame = None
                while not audio_queue.empty():
                    mic_frame = audio_queue.get_nowait()

                if mic_frame is None:
                    await asyncio.sleep(0.05)
                    continue

                # Apply AEC if available: cancel TTS echo from mic signal
                if self.aec is not None:
                    ref_frame = None
                    while not ref_queue.empty():
                        ref_frame = ref_queue.get_nowait()
                    if ref_frame is not None:
                        try:
                            mic_frame = self.aec.cancel(mic_frame.flatten(), ref_frame.flatten())
                            mic_frame = mic_frame.reshape(-1, 1)
                        except Exception:
                            pass

                buffered_mic_frames.append(mic_frame)
                mic_rms = float(np.sqrt(np.mean(mic_frame.astype(np.float64) ** 2)))
                frame_count += 1

                # Calibration: measure mic RMS during TTS (speaker bleed baseline)
                if frame_count <= CALIBRATION_FRAMES:
                    baseline_rms.append(mic_rms)
                    if frame_count == CALIBRATION_FRAMES:
                        baseline = sum(baseline_rms) / len(baseline_rms)
                        # With AEC: residual is low (~50-180), speech adds ~200-500 on top
                        # Without AEC: raw bleed is high (~300-800), speech adds ~500-1000
                        if self.aec is not None:
                            threshold = max(baseline * 3.0, 400)
                        else:
                            threshold = max(baseline * 2.5, 1200)
                        print(f"[BARGE-IN] calibrated: baseline={baseline:.0f} threshold={threshold:.0f}", file=sys.stderr, flush=True)
                    await asyncio.sleep(0.05)
                    continue

                # Detection — log every 5th frame for tuning visibility
                if frame_count % 5 == 0:
                    print(f"[BARGE-IN] rms={mic_rms:.0f} thr={threshold:.0f} spk={spike_count}", file=sys.stderr, flush=True)
                if mic_rms > threshold:
                    spike_count += 1
                    print(f"[BARGE-IN] spike! mic_rms={mic_rms:.0f} threshold={threshold:.0f} spikes={spike_count}", file=sys.stderr, flush=True)
                else:
                    spike_count = max(0, spike_count - 1)

                if spike_count >= 4:
                    self.logger.log_event("BARGE_IN_DETECTED", {"mic_rms": mic_rms})
                    print(f"BARGE-IN! mic_rms={mic_rms:.0f} (buffered {len(buffered_mic_frames)} frames for replay)", file=sys.stderr)
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
                    while not ref_queue.empty():
                        ref_queue.get_nowait()
                    return

                await asyncio.sleep(0.05)

        async def send_audio():
            """Send mic audio to WLK"""
            await tts_done_event.wait()
            self.logger.log_event("CAPTURE_START")
            print(f"[DEBUG] TTS done, starting audio send", file=sys.stderr, flush=True)
            if tts_active and not barge_in_triggered:
                # Wait for TTS echo/reverb to decay, then flush contaminated frames
                # With AEC active we need less flush time
                flush_delay = 0.5 if self.aec is not None else 1.5
                await asyncio.sleep(flush_delay)
                while not audio_queue.empty():
                    audio_queue.get_nowait()
                while not ref_queue.empty():
                    ref_queue.get_nowait()
            if not barge_in_enabled:
                mic_stream.start()

            frame_count = 0
            try:
                while not done_event.is_set():
                    try:
                        data = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                        # Apply AEC to clean residual echo from mic frames
                        if self.aec is not None and not ref_queue.empty():
                            ref_frame = None
                            while not ref_queue.empty():
                                ref_frame = ref_queue.get_nowait()
                            if ref_frame is not None:
                                try:
                                    data = self.aec.cancel(data.flatten(), ref_frame.flatten())
                                    data = data.reshape(-1, 1)
                                except Exception:
                                    pass
                        await ws.send(data.tobytes())
                        frame_count += 1
                        if frame_count % 10 == 0:
                            print(f"[DEBUG] Sent {frame_count} frames to WLK", file=sys.stderr, flush=True)
                    except asyncio.TimeoutError:
                        continue
            finally:
                print(f"[DEBUG] Audio send complete, sent {frame_count} frames total", file=sys.stderr, flush=True)
                if not barge_in_enabled:
                    mic_stream.stop()

        async def recv_transcription():
            """Receive and accumulate transcription from WLK"""
            nonlocal text_result, last_text_change, got_text
            idle_since = time.monotonic()
            msg_count = 0

            while not done_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    idle_since = time.monotonic()
                    msg_count += 1
                except asyncio.TimeoutError:
                    if time.monotonic() - idle_since > 10.0:
                        print("[WLK] unresponsive for 10s, ending capture", file=sys.stderr, flush=True)
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


class TextResponse(BaseModel):
    text: str


# Global instances
config = Config()
state = StateManager()
log_file = Path.home() / ".claude-talk/audio-server.log"
event_logger = EventLogger(log_file)
audio_engine = AudioEngine(config, state, event_logger)
wlk_manager = WLKManager(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown"""
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
    yield
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
    )


@app.get("/listen")
async def listen() -> TextResponse:
    """Block until user speaks, return transcription"""
    event_logger.log_event("API_LISTEN_START")
    text = await audio_engine.listen()
    event_logger.log_event("API_LISTEN_END", {"text": text})
    return TextResponse(text=text)


@app.post("/queue-listen")
async def queue_listen() -> dict[str, str]:
    """Start listening in background. Result buffered for next /speak."""
    event_logger.log_event("API_QUEUE_LISTEN")
    await audio_engine.queue_listen()
    return {"status": "ok"}


@app.post("/speak")
async def speak(req: SpeakRequest) -> TextResponse:
    """Speak text via TTS, then capture user's response (with barge-in if available)"""
    event_logger.log_event("API_SPEAK_START", {"text": req.text})
    text = await audio_engine.speak_and_listen(req.text)
    event_logger.log_event("API_SPEAK_END", {"text": text})
    return TextResponse(text=text)


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
    port = config.get_int("AUDIO_SERVER_PORT", 8150)
    print(f"Starting audio server on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

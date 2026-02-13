#!/usr/bin/env python3
"""
Audio Server for Claude Talk

Replaces shell scripts + agent with a dedicated HTTP server that handles:
- TTS playback (macOS `say`)
- Speech capture via WhisperLiveKit
- Barge-in detection (Geigel DTD with BlackHole)
- State management
- WLK subprocess lifecycle

API:
  GET  /listen              - Block until user speaks, return transcription
  POST /speak-and-listen    - TTS + capture in one call
  POST /speak               - TTS only (no capture)
  GET  /status              - Current state (idle/listening/speaking)
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
            print(f"Starting WLK on port {self.port}...")
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
                stderr=subprocess.DEVNULL,
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

            if self.stop_requested:
                return

            print(f"WLK crashed at {time.strftime('%Y-%m-%d %H:%M:%S')}. Restarting in 2s...")
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


class AudioEngine:
    """Handles mic capture, TTS, barge-in, and WLK transcription"""

    def __init__(self, config: Config, state: StateManager, event_logger: EventLogger):
        self.config = config
        self.state = state
        self.logger = event_logger

        # Audio settings
        self.device_index = config.get_int("AUDIO_DEVICE", 1)
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

    async def speak_and_listen(self, text: str) -> str:
        """
        Speak text, then capture utterance (with barge-in if enabled).
        """
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
                return await self._capture_utterance(tts_pid=tts_pid)
            finally:
                self.state.set(STATUS="idle")

    async def _capture_utterance(self, tts_pid: int = 0) -> str:
        """
        Core capture logic: streams mic to WLK, handles barge-in, returns text.
        """
        try:
            ws = await asyncio.wait_for(
                websockets.connect(self.wlk_url), timeout=10.0
            )
        except (asyncio.TimeoutError, OSError) as e:
            print(f"Failed to connect to WLK: {e}", file=sys.stderr)
            return ""

        text_result = ""
        last_text_change = 0.0
        got_text = False
        frame_size = int(self.sample_rate * 0.1)  # 100ms chunks

        # TTS monitoring
        tts_active = tts_pid > 0
        tts_done_event = asyncio.Event()
        if not tts_active:
            tts_done_event.set()

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
            """Geigel double-talk detection"""
            nonlocal barge_in_triggered
            if not barge_in_enabled:
                return

            await asyncio.sleep(0.8)  # Grace period
            if tts_done_event.is_set():
                return

            spike_count = 0
            while not done_event.is_set() and not tts_done_event.is_set():
                mic_frame = None
                while not audio_queue.empty():
                    mic_frame = audio_queue.get_nowait()

                ref_frame = None
                while not ref_queue.empty():
                    ref_frame = ref_queue.get_nowait()

                if mic_frame is None or ref_frame is None:
                    await asyncio.sleep(0.05)
                    continue

                mic_rms = float(np.sqrt(np.mean(mic_frame.astype(np.float64) ** 2)))
                ref_rms = float(np.sqrt(np.mean(ref_frame.astype(np.float64) ** 2)))
                ratio = mic_rms / max(ref_rms, 1)

                if ref_rms > 50 and ratio > self.barge_in_ratio:
                    spike_count += 1
                elif ref_rms <= 50 and mic_rms > 500:
                    spike_count += 1
                else:
                    spike_count = max(0, spike_count - 1)

                if spike_count >= 3:
                    self.logger.log_event("BARGE_IN_DETECTED", {
                        "mic_rms": mic_rms,
                        "ref_rms": ref_rms,
                        "ratio": ratio,
                    })
                    print(f"BARGE-IN! mic={mic_rms:.0f} ref={ref_rms:.0f} ratio={ratio:.2f}", file=sys.stderr)
                    barge_in_triggered = True
                    try:
                        os.kill(tts_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    tts_done_event.set()
                    # Drain stale frames
                    while not audio_queue.empty():
                        audio_queue.get_nowait()
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
                await asyncio.sleep(0.5)  # Buffer drain delay
            if barge_in_enabled and not barge_in_triggered:
                while not audio_queue.empty():
                    audio_queue.get_nowait()
            if not barge_in_enabled:
                mic_stream.start()

            frame_count = 0
            try:
                while not done_event.is_set():
                    try:
                        data = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
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
                    if time.monotonic() - idle_since > 30.0:
                        print("[DEBUG] WLK unresponsive for 30s", file=sys.stderr, flush=True)
                        done_event.set()
                        return
                    continue
                except websockets.exceptions.ConnectionClosed:
                    print("[DEBUG] WLK connection closed", file=sys.stderr, flush=True)
                    done_event.set()
                    return

                d = json.loads(msg)
                lines_text = " ".join(l.get("text", "") for l in d.get("lines", [])).strip()
                buffer_text = d.get("buffer_transcription", "").strip()
                combined = (lines_text + " " + buffer_text).strip()

                # Filter hallucinations
                for noise in ["[Music]", "[INAUDIBLE]", "[BLANK_AUDIO]"]:
                    combined = combined.replace(noise, "")
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

            while not done_event.is_set():
                await asyncio.sleep(0.3)
                now = time.monotonic()

                if now - capture_start > self.max_duration:
                    done_event.set()
                    return

                if got_text and last_text_change > 0:
                    idle_time = now - last_text_change
                    if idle_time >= self.silence_timeout and len(text_result) >= 2:
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

        return text_result


# ============================================================================
# FastAPI Server
# ============================================================================


class SpeakRequest(BaseModel):
    text: str


class StatusResponse(BaseModel):
    state: str
    muted: bool


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
    """Get current server state"""
    return StatusResponse(
        state=state.get("STATUS", "idle"), muted=state.get("MUTED", "false") == "true"
    )


@app.get("/listen")
async def listen() -> TextResponse:
    """Block until user speaks, return transcription"""
    event_logger.log_event("API_LISTEN_START")
    text = await audio_engine.listen()
    event_logger.log_event("API_LISTEN_END", {"text": text})
    return TextResponse(text=text)


@app.post("/speak")
async def speak(req: SpeakRequest) -> dict[str, str]:
    """Speak text via TTS (no capture)"""
    event_logger.log_event("API_SPEAK_START", {"text": req.text})
    pid = await audio_engine.speak(req.text)
    if pid:
        # Wait for TTS to finish
        while True:
            try:
                os.kill(pid, 0)
                await asyncio.sleep(0.1)
            except ProcessLookupError:
                break
        state.set(STATUS="idle")
    event_logger.log_event("API_SPEAK_END")
    return {"status": "ok"}


@app.post("/speak-and-listen")
async def speak_and_listen(req: SpeakRequest) -> TextResponse:
    """Speak text, then capture utterance (with barge-in)"""
    event_logger.log_event("API_SPEAK_AND_LISTEN_START", {"text": req.text})
    text = await audio_engine.speak_and_listen(req.text)
    event_logger.log_event("API_SPEAK_AND_LISTEN_END", {"text": text})
    return TextResponse(text=text)


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

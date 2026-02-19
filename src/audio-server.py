#!/usr/bin/env python3
"""
Audio Server for Claude Talk

Raw asyncio Unix socket server for local IPC. JSON-lines protocol.

Commands:
  status              - Current state (idle/listening/speaking)
  speak               - Fire-and-forget TTS with background capture + continuous listen
  voice               - Change TTS voice
  volume              - Get system volume
  volume_up           - Increase volume by 10%
  volume_down         - Decrease volume by 10%
  mute                - Mute mic
  unmute              - Unmute mic
  devices             - List audio devices
  session_connect     - Persistent session connection (ref counting)
  stop                - Graceful shutdown
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

# Claude Talk modules
sys.path.insert(0, str(Path(__file__).parent))
from claude_talk.db import DB
from claude_talk.session import SessionStore
from claude_talk.tmux import send_to_session
from claude_talk.tts import KokoroTTS

# Known Whisper hallucinations from YouTube training data
_WHISPER_HALLUCINATION_BLOCKLIST = frozenset({
    "thanks for watching",
    "thank you for watching",
    "thanks for listening",
    "thank you for listening",
    "please subscribe",
    "subscribe",
    "like and subscribe",
    "please like and subscribe",
    "see you next time",
    "see you in the next video",
    "see you in the next one",
    "bye bye",
    "goodbye",
    "thank you",
    "thanks",
    "you",
})


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
        os.chmod(self.log_file, 0o600)  # Restrict log to owner-only
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
# whisper.cpp STT Engine (via pywhispercpp)
# ============================================================================


class WhisperEngine:
    """In-process whisper.cpp model via pywhispercpp. No subprocess, no WebSocket."""

    def __init__(self, config: Config):
        self.config = config
        self.model_name = config.get("WHISPER_MODEL", "base.en")
        self._model = None
        self._model_lock = asyncio.Lock()  # one transcribe at a time
        self._ready = False

    async def start(self):
        """Load whisper model in executor thread (~0.5-2s)."""
        self.initial_prompt = self._build_personality_prompt()
        loop = asyncio.get_running_loop()
        self._model = await loop.run_in_executor(None, self._load_model)
        self._ready = True
        print(f"[WHISPER] model ready ({self.model_name})")

    def _load_model(self):
        from pywhispercpp.model import Model
        return Model(self.model_name, language="en",
                     initial_prompt=self.initial_prompt, suppress_blank=True)

    async def transcribe(self, pcm_float32: np.ndarray) -> str:
        """Transcribe a float32 PCM array. Returns joined text from all segments."""
        segments = []
        def on_segment(seg):
            segments.append(seg.text)
        loop = asyncio.get_running_loop()
        async with self._model_lock:
            await loop.run_in_executor(None, lambda: self._model.transcribe(
                pcm_float32, new_segment_callback=on_segment))
        return " ".join(segments).strip()

    def _build_personality_prompt(self) -> str:
        """Build a prompt with personality names so Whisper recognizes them."""
        names = []
        personalities_dir = Path.home() / ".claude-talk/personalities"
        if personalities_dir.exists():
            for f in personalities_dir.glob("*.md"):
                content = f.read_text()
                for line in content.splitlines():
                    if line.strip().startswith("- Name:"):
                        name = line.split(":", 1)[1].strip()
                        names.append(name)
                        break
        if names:
            prompt = "Personalities: " + ", ".join(names) + "."
            print(f"[WHISPER] init prompt: {prompt}")
            return prompt
        return ""

    def is_ready(self) -> bool:
        return self._ready and self._model is not None

    async def stop(self):
        """Release the model."""
        self._model = None
        self._ready = False


# ============================================================================
# Voice Activity Detection (webrtcvad)
# ============================================================================


class VoiceActivityDetector:
    """webrtcvad-based voice activity detection on 20ms frames at 16kHz."""

    def __init__(self, aggressiveness: int = 2, silence_frames: int = 50, sample_rate: int = 16000):
        import webrtcvad
        self.vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate
        self.silence_frames = silence_frames
        self.frame_duration_ms = 20
        self.frame_size = int(sample_rate * self.frame_duration_ms / 1000)  # 320 at 16kHz
        self.max_frames = 1500  # 30s safety cap

        self._speech_frames: list[np.ndarray] = []
        self._silent_count = 0
        self._speech_started = False
        self._frame_count = 0
        # Lookback buffer: preserve 100ms of leading audio (5 frames at 20ms)
        self._lookback: list[np.ndarray] = []
        self._lookback_size = 5

    def process_frame(self, frame_int16: np.ndarray) -> tuple[bool, np.ndarray | None]:
        """Process one 20ms frame. Returns (done, float32_utterance_array).
        done=True with array when silence boundary hit after speech.
        done=True with None on max_frames safety cap (no speech detected).
        done=False otherwise."""
        self._frame_count += 1

        # Convert to bytes for webrtcvad (expects 16-bit PCM)
        frame_bytes = frame_int16.flatten()[:self.frame_size].astype(np.int16).tobytes()

        try:
            is_speech = self.vad.is_speech(frame_bytes, self.sample_rate)
        except Exception:
            is_speech = False

        if not self._speech_started:
            # Pre-speech: maintain lookback buffer
            self._lookback.append(frame_int16.flatten().copy())
            if len(self._lookback) > self._lookback_size:
                self._lookback.pop(0)

            if is_speech:
                self._speech_started = True
                # Prepend lookback buffer to preserve leading consonants
                # Current frame is already the last item in lookback, so no double-append
                for lb_frame in self._lookback:
                    self._speech_frames.append(lb_frame)
                self._silent_count = 0
                self._lookback.clear()
        else:
            # During speech
            self._speech_frames.append(frame_int16.flatten().copy())

            if is_speech:
                self._silent_count = 0
            else:
                self._silent_count += 1

            if self._silent_count >= self.silence_frames:
                # Utterance complete
                utterance = np.concatenate(self._speech_frames).astype(np.float32) / 32768.0
                self.reset()
                return True, utterance

        # Safety cap
        if self._frame_count >= self.max_frames:
            if self._speech_frames:
                utterance = np.concatenate(self._speech_frames).astype(np.float32) / 32768.0
                self.reset()
                return True, utterance
            self.reset()
            return True, None

        return False, None

    def get_partial(self) -> np.ndarray | None:
        """Return accumulated speech as float32, or None if no speech collected."""
        if self._speech_started and self._speech_frames:
            return np.concatenate(self._speech_frames).astype(np.float32) / 32768.0
        return None

    def reset(self):
        self._speech_frames.clear()
        self._silent_count = 0
        self._speech_started = False
        self._frame_count = 0
        self._lookback.clear()


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
    """Handles mic capture, TTS, interrupt, and whisper.cpp transcription"""

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

        # Interrupt settings
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

        # Kokoro TTS engine
        self.kokoro: KokoroTTS | None = None
        self._tts_stop_event = asyncio.Event()
        self._tts_playback_done = asyncio.Event()
        self._playback_stream: sd.OutputStream | None = None
        self._tts_active = False  # replaces _tts_pid tracking

        # Persistent resources
        self.mic_stream: sd.InputStream | None = None
        self.ref_stream: sd.InputStream | None = None
        self.lock = asyncio.Lock()  # Serialize capture operations
        # Listener pause/resume: TTS sets _listener_pause to pause the global listener
        self._listener_pause = asyncio.Event()   # set = listener should pause
        self._listener_paused = asyncio.Event()  # set = listener has actually paused
        self._listener_resume = asyncio.Event()  # set = listener can resume
        self._listener_resume.set()  # start in resumed state

        # Acoustic Echo Cancellation (Speex)
        self.aec = None
        if self.barge_in_enabled and self.blackhole_device is not None:
            try:
                self.aec = SpeexAEC(frame_size=320, filter_length=8000, sample_rate=16000)
                print(f"  Speex AEC: enabled (frame=320, filter=8000)")
            except Exception as e:
                print(f"  Speex AEC: unavailable ({e})", file=sys.stderr)

        # Track when TTS last finished for post-TTS protection in all capture paths
        self._tts_finished_at: float = 0.0
        # Track last TTS text for echo filtering in continuous listen
        self._last_tts_text: str = ""
        # Rescued partial audio when capture is cancelled mid-speech for TTS
        self._rescued_audio: np.ndarray | None = None

        print(f"AudioEngine initialized:")
        print(f"  Mic device: {self.device_index}, gain: {self.gain}")
        print(f"  TTS voice: {self.voice}")
        print(f"  Interrupt: {self.barge_in_enabled}", end="")
        if self.barge_in_enabled:
            print(f" (BlackHole device: {self.blackhole_device})")
        else:
            print(" (disabled)")

    def _is_muted(self) -> bool:
        return self.state.get("MUTED", "false").lower() == "true"

    # macOS say voice -> Kokoro voice ID static map
    MACOS_TO_KOKORO = {
        "Daniel": "bm_daniel", "Daniel (Enhanced)": "bm_daniel",
        "Fiona": "bf_emma", "Fiona (Enhanced)": "bf_emma",
        "Zoe": "af_bella", "Zoe (Premium)": "af_bella",
        "Evan": "am_adam", "Evan (Enhanced)": "am_adam",
        "Moira": "bf_alice", "Moira (Enhanced)": "bf_alice",
        "Karen": "af_nova", "Karen (Premium)": "af_nova",
        "Zarvox": "am_echo",
        "Rishi": "bm_george", "Rishi (Enhanced)": "bm_george",
        "Samantha": "af_heart", "Samantha (Enhanced)": "af_heart",
    }

    def _resolve_kokoro_voice(self, say_voice: str) -> str:
        """Resolve a macOS say voice name to a Kokoro voice ID."""
        return self.MACOS_TO_KOKORO.get(say_voice, self.config.get("KOKORO_VOICE", KokoroTTS.DEFAULT_VOICE))

    async def initialize_tts(self):
        """Load Kokoro TTS model at startup."""
        model = self.config.get("KOKORO_MODEL", KokoroTTS.DEFAULT_MODEL)
        self.kokoro = KokoroTTS(model_name=model)
        await self.kokoro.initialize()
        print(f"  Kokoro TTS: loaded ({model})")

    async def _play_audio(self, audio: np.ndarray, sample_rate: int):
        """Play audio through sounddevice OutputStream with stop support."""
        if len(audio) == 0:
            self._tts_playback_done.set()
            return

        loop = asyncio.get_running_loop()
        pos = 0
        chunk_size = 1024  # samples per callback

        def callback(outdata, frames, time_info, status):
            nonlocal pos
            if self._tts_stop_event.is_set():
                raise sd.CallbackStop()
            end = pos + frames
            if end <= len(audio):
                outdata[:, 0] = audio[pos:end]
            else:
                # Fill partial + silence
                remaining = len(audio) - pos
                if remaining > 0:
                    outdata[:remaining, 0] = audio[pos:]
                outdata[remaining:, 0] = 0.0
                raise sd.CallbackStop()
            pos = end

        def finished():
            loop.call_soon_threadsafe(self._tts_playback_done.set)

        self._playback_stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype='float32',
            blocksize=chunk_size,
            callback=callback,
            finished_callback=finished,
            device=None,  # system default -> Multi-Output -> BlackHole
        )
        self._playback_stream.start()

    def _stop_current_tts(self):
        """Stop current TTS generation and playback."""
        self._tts_stop_event.set()
        if self.kokoro:
            self.kokoro.stop()
        if self._playback_stream is not None:
            try:
                self._playback_stream.stop()
                self._playback_stream.close()
            except Exception:
                pass
            self._playback_stream = None
        self._tts_active = False

    async def speak(self, text: str, voice: str | None = None) -> int | None:
        """
        Speak text via Kokoro TTS. Returns 1 (sentinel) if successful, None if failed.
        Stops any previous TTS to prevent overlap.
        Voice param: can be macOS voice name (resolved via map), Kokoro voice ID, or
        personality kokoro_voice field.
        """
        use_voice = voice or self.voice
        # TTS enforcer: stop previous TTS if still active
        if self._tts_active:
            self._stop_current_tts()
            print(f"[TTS] stopped previous TTS", file=sys.stderr, flush=True)

        if not self.kokoro or not self.kokoro.is_available():
            print(f"[TTS] Kokoro not available", file=sys.stderr, flush=True)
            return None

        # Resolve voice: if it looks like a Kokoro ID (contains underscore), use directly
        # Otherwise treat as macOS voice name and resolve via map
        if "_" in use_voice and use_voice.split("_")[0] in ("af", "am", "bf", "bm", "jf", "jm", "zf", "zm", "ef", "em", "ff", "hf", "hm", "if", "im", "pf", "pm"):
            kokoro_voice = use_voice
        else:
            kokoro_voice = self._resolve_kokoro_voice(use_voice)

        speed = self.config.get_float("KOKORO_SPEED", 1.0)

        self.state.set(STATUS="speaking")
        self._last_tts_text = text
        self.logger.log_event("TTS_START", {"text": text, "voice": kokoro_voice})

        try:
            # Reset stop/done events
            self._tts_stop_event.clear()
            self._tts_playback_done.clear()
            self._tts_active = True

            # Generate audio (runs in thread pool)
            audio, sample_rate = await self.kokoro.generate(text, kokoro_voice, speed)

            if self._tts_stop_event.is_set():
                self._tts_active = False
                return None

            if len(audio) == 0:
                print(f"[TTS] Kokoro produced empty audio", file=sys.stderr, flush=True)
                self._tts_active = False
                return None

            # Start playback
            await self._play_audio(audio, sample_rate)
            return 1  # sentinel: TTS is active (callers check tts_pid > 0)
        except Exception as e:
            print(f"TTS failed: {e}", file=sys.stderr)
            self._tts_active = False
            return None

    async def speak_say(self, text: str, voice: str | None = None) -> int | None:
        """Speak text via macOS 'say' command. Returns PID if successful, None if failed."""
        use_voice = voice or self.voice
        if self._tts_active:
            self._stop_current_tts()
            print(f"[TTS] stopped previous TTS", file=sys.stderr, flush=True)

        self.state.set(STATUS="speaking")
        self._last_tts_text = text
        self.logger.log_event("TTS_START", {"text": text, "voice": use_voice, "engine": "say"})

        try:
            self._tts_stop_event.clear()
            self._tts_playback_done.clear()
            self._tts_active = True

            # Validate voice name to prevent unexpected arguments
            import re as _re
            if not _re.match(r'^[a-zA-Z0-9 ()\-_.]+$', use_voice):
                print(f"[TTS] Invalid voice name rejected: {use_voice!r}", file=sys.stderr)
                self._tts_active = False
                return None

            proc = await asyncio.create_subprocess_exec(
                "say", "-v", use_voice, text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            pid = proc.pid

            async def _wait_say():
                await proc.wait()
                self._tts_active = False
                self._tts_finished_at = time.monotonic()
                self._tts_playback_done.set()

            asyncio.create_task(_wait_say())
            return pid
        except Exception as e:
            print(f"TTS (say) failed: {e}", file=sys.stderr)
            self._tts_active = False
            return None

    async def _capture_utterance(self, tts_pid: int = 0, tts_text: str = "", tts_only: bool = False) -> str:
        """
        Core capture logic: reads mic, runs VAD, transcribes via whisper.cpp.
        If tts_only=True: exits with "(silence)" when TTS finishes naturally (no barge-in).
        """
        # Check whisper engine readiness
        if not whisper_engine.is_ready():
            print(f"[WHISPER] engine not ready, attempting start", file=sys.stderr, flush=True)
            try:
                await whisper_engine.start()
            except Exception as e:
                print(f"[WHISPER] failed to start: {e}", file=sys.stderr, flush=True)
                return "(stt_error)"

        text_result = ""
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

        # Interrupt state
        barge_in_enabled = tts_active and self.barge_in_enabled and self.blackhole_device is not None
        barge_in_triggered = False

        loop = asyncio.get_running_loop()
        audio_queue: asyncio.Queue = asyncio.Queue()
        barge_ref_queue: asyncio.Queue = asyncio.Queue()  # ref frames for interrupt detection
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

        # Reference stream (BlackHole) - only if interrupt enabled
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
            """Monitor TTS playback until it completes"""
            if not tts_active:
                return
            while not done_event.is_set():
                if self._tts_playback_done.is_set():
                    self.logger.log_event("TTS_STOPPED_NATURAL")
                    self._tts_finished_at = time.monotonic()
                    self._tts_active = False
                    tts_done_event.set()
                    if tts_only and not barge_in_triggered:
                        # TTS finished naturally, no barge-in — exit immediately
                        done_event.set()
                    return
                await asyncio.sleep(0.05)

        async def barge_in_monitor():
            """Adaptive interrupt: calibrates mic baseline during TTS, detects speech above it.
            Buffers all mic frames and replays them after interrupt so no speech is lost."""
            nonlocal barge_in_triggered
            if not barge_in_enabled:
                return

            await asyncio.sleep(0.5)
            if tts_done_event.is_set():
                return

            # Geigel double-talk detection: compare raw mic/reference ratio
            # Echo = ~5-12% of reference, real speech = 40%+ (see docs/interrupt-setup.md)
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

                # Get raw mic RMS BEFORE AEC for interrupt detection
                raw_mic_rms = float(np.sqrt(np.mean(mic_frame.astype(np.float64) ** 2)))

                # Get reference RMS (TTS output via BlackHole)
                ref_frame = None
                while not barge_ref_queue.empty():
                    ref_frame = barge_ref_queue.get_nowait()
                ref_rms = 0.0
                if ref_frame is not None:
                    ref_rms = float(np.sqrt(np.mean(ref_frame.astype(np.float64) ** 2)))

                # Apply AEC for the buffered frames (used later for transcription)
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
                    self.logger.log_event("INTERRUPT_DETECTED", {"mic_rms": raw_mic_rms})
                    print(f"BARGE-IN! mic_rms={raw_mic_rms:.0f} (buffered {len(buffered_mic_frames)} frames for replay)", file=sys.stderr)
                    barge_in_triggered = True
                    self._stop_current_tts()
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

        async def audio_capture_and_transcribe():
            """Capture mic audio, run VAD, transcribe complete utterances via whisper.cpp."""
            nonlocal text_result
            await tts_done_event.wait()
            self.logger.log_event("CAPTURE_START")
            print(f"[DEBUG] TTS done, starting audio capture", file=sys.stderr, flush=True)
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
            # Post-TTS energy gate: suppress bleed frames after TTS
            # Dynamic baseline: calibrate from first 25 frames (~0.5s), then gate at 3x ambient
            # This adapts to any mic gain, room acoustics, or speaker volume
            GATE_DURATION = 4.0  # seconds after TTS to enforce energy gate
            GATE_CALIBRATION_FRAMES = 25  # ~0.5s at 20ms/frame
            GATE_MULTIPLIER = 3.0  # threshold = ambient_rms * multiplier
            GATE_RMS_FLOOR = 500   # minimum threshold regardless of calibration
            time_since_tts = time.monotonic() - self._tts_finished_at if self._tts_finished_at > 0 else 999
            remaining_gate = max(0, GATE_DURATION - time_since_tts)
            energy_gate_rms = GATE_RMS_FLOOR if (tts_active or remaining_gate > 0) else 0
            gate_until = time.monotonic() + (GATE_DURATION if tts_active else remaining_gate)
            gate_consecutive = 0  # require 3+ consecutive loud frames to pass
            gate_calibration: list[float] = []  # RMS values for dynamic baseline
            gate_calibrated = not (tts_active or remaining_gate > 0)  # skip calibration if no gate
            if remaining_gate > 0 and not tts_active:
                print(f"[GATE] Applying post-TTS gate to /listen call ({remaining_gate:.1f}s remaining)", file=sys.stderr, flush=True)

            # Create VAD for this capture session
            vad_aggressiveness = self.config.get_int("VAD_AGGRESSIVENESS", 2)
            vad_silence_frames = self.config.get_int("VAD_SILENCE_FRAMES", 50)
            vad = VoiceActivityDetector(
                aggressiveness=vad_aggressiveness,
                silence_frames=vad_silence_frames,
                sample_rate=self.sample_rate,
            )

            try:
                while not done_event.is_set():
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
                        # Phase 1: calibrate ambient RMS from first N frames
                        # Phase 2: gate using dynamic threshold (3x ambient)
                        if time.monotonic() < gate_until:
                            frame_rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                            # Calibration phase: collect baseline frames
                            if not gate_calibrated:
                                gate_calibration.append(frame_rms)
                                if len(gate_calibration) >= GATE_CALIBRATION_FRAMES:
                                    ambient_rms = sum(gate_calibration) / len(gate_calibration)
                                    energy_gate_rms = max(ambient_rms * GATE_MULTIPLIER, GATE_RMS_FLOOR)
                                    gate_calibrated = True
                                    print(f"[GATE] calibrated: ambient={ambient_rms:.0f} threshold={energy_gate_rms:.0f}", file=sys.stderr, flush=True)
                                frame_count += 1
                                continue  # always suppress during calibration
                            if frame_count % 100 == 0:
                                print(f"[GATE] rms={frame_rms:.0f} gate={energy_gate_rms:.0f} remaining={gate_until - time.monotonic():.1f}s", file=sys.stderr, flush=True)
                            if frame_rms >= energy_gate_rms:
                                gate_consecutive += 1
                                if gate_consecutive < 3:
                                    frame_count += 1
                                    continue  # Not enough consecutive loud frames yet
                                # Sustained loud audio — disable gate for rest of session
                                gate_until = 0
                                print(f"[GATE] speech detected (rms={frame_rms:.0f} > {energy_gate_rms:.0f}), gate disabled", file=sys.stderr, flush=True)
                            else:
                                gate_consecutive = 0
                                frame_count += 1
                                continue

                        # Feed frame to VAD
                        frame_count += 1
                        vad_done, utterance = vad.process_frame(data.flatten()[:vad.frame_size])

                        if vad_done:
                            if utterance is None:
                                # Safety cap hit with no speech
                                print(f"[VAD] max frames reached, no speech detected", file=sys.stderr, flush=True)
                                continue

                            # Transcribe the utterance
                            print(f"[VAD] utterance detected ({len(utterance)/self.sample_rate:.1f}s, {len(utterance)} samples)", file=sys.stderr, flush=True)
                            try:
                                transcribed = await whisper_engine.transcribe(utterance)
                            except Exception as e:
                                print(f"[WHISPER] transcribe error: {e}", file=sys.stderr, flush=True)
                                continue

                            # Filter hallucinations — Whisper produces bracketed/parenthesized
                            # sound annotations on noise/silence. Catch ALL of them generically.
                            transcribed = re.sub(r'\[[^\]]{1,30}\]', '', transcribed)  # [anything up to 30 chars]
                            transcribed = re.sub(r'\([^\)]{1,30}\)', '', transcribed)  # (anything up to 30 chars)
                            transcribed = re.sub(r'\bINAUDIBLE\b', '', transcribed, flags=re.IGNORECASE)
                            transcribed = transcribed.strip()
                            # Drop if only punctuation/whitespace remains
                            if re.fullmatch(r'[\s\.\,\!\?\-]*', transcribed):
                                transcribed = ""
                            # Blocklist: common Whisper hallucinations from YouTube training data
                            if transcribed:
                                _lower = transcribed.lower().strip().rstrip(".,!?")
                                if _lower in _WHISPER_HALLUCINATION_BLOCKLIST:
                                    print(f"[WHISPER] blocked hallucination: '{transcribed}'", file=sys.stderr, flush=True)
                                    transcribed = ""

                            if transcribed and len(transcribed) >= 2:
                                text_result = transcribed
                                self.logger.log_event("TRANSCRIPTION", {"text": transcribed})
                                print(f"[WHISPER] transcription: '{transcribed}'", file=sys.stderr, flush=True)
                                done_event.set()
                                return

                        if frame_count % 100 == 0:
                            print(f"[DEBUG] Processed {frame_count} frames", file=sys.stderr, flush=True)

                    except asyncio.TimeoutError:
                        continue
            except asyncio.CancelledError:
                # Rescue partial speech: if VAD has buffered speech frames, save them
                # so the global listener can transcribe them after TTS finishes
                partial = vad.get_partial()
                if partial is not None and len(partial) / self.sample_rate >= 0.3:
                    self._rescued_audio = partial
                    print(f"[VAD] rescued partial utterance ({len(partial)/self.sample_rate:.1f}s)", file=sys.stderr, flush=True)
                raise
            finally:
                print(f"[DEBUG] Audio capture complete, processed {frame_count} frames total", file=sys.stderr, flush=True)
                if not barge_in_enabled and mic_stream.active:
                    mic_stream.stop()

        # Start streams
        if barge_in_enabled:
            mic_stream.start()
            ref_stream.start()

        try:
            tasks = [
                asyncio.create_task(tts_monitor()),
                asyncio.create_task(barge_in_monitor()),
                asyncio.create_task(audio_capture_and_transcribe()),
            ]
            await done_event.wait()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Record TTS finish time for post-TTS protection in subsequent /listen calls
            if tts_active:
                self._tts_finished_at = time.monotonic()
                # Stop TTS if still active (e.g. capture ended before TTS finished)
                if self._tts_active:
                    self._stop_current_tts()
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
            if not remaining:
                print(f"[ECHO-FILTER] entire transcription was TTS echo", file=sys.stderr, flush=True)
                return "(silence)"
            # Continue to fuzzy check on remaining text (echo may extend beyond exact match)
            print(f"[ECHO-FILTER] stripped {best_match_len} TTS echo words, checking remainder: '{remaining[:60]}'", file=sys.stderr, flush=True)
            transcription = remaining
            trans_words = transcription.lower().split()

        # Fuzzy check: if >30% of transcription words appear in TTS text, likely echo
        # (lowered from 50% because Whisper garbles echo significantly)
        if len(trans_words) >= 4:
            tts_word_set = set(w.rstrip(".,!?;:-—'\"") for w in tts_words)
            match_count = sum(1 for w in trans_words if w.rstrip(".,!?;:-—'\"") in tts_word_set)
            match_ratio = match_count / len(trans_words)
            if match_ratio > 0.3:
                print(f"[ECHO-FILTER] fuzzy match {match_ratio:.0%} ({match_count}/{len(trans_words)} words), treating as echo", file=sys.stderr, flush=True)
                return "(silence)"

        return transcription


# ============================================================================
# Socket Server
# ============================================================================


# Global instances
config = Config()
state = StateManager()
log_file = Path.home() / ".claude-talk/audio-server.log"
event_logger = EventLogger(log_file)
audio_engine = AudioEngine(config, state, event_logger)
whisper_engine = WhisperEngine(config)

# Session management for tmux routing
db = DB()
session_store = SessionStore(db)

# Message queue (initialized in server_main)

# Session ref counting for auto-shutdown
_session_connections: set[asyncio.StreamWriter] = set()
_auto_shutdown_task: asyncio.Task | None = None


def send_transcription_to_claude(text: str) -> None:
    """Send transcription to Claude session(s) via tmux, using name-based routing."""
    if not text or text in ("(silence)", "(muted)", "(stt_error)"):
        return

    from claude_talk.routing import parse_route, get_target_sessions

    route_type, target_session_id, cleaned_text = parse_route(text)
    session_ids = get_target_sessions(route_type, target_session_id)
    print(f"[ROUTE] type={route_type} target={target_session_id and target_session_id[:8]} sessions={[s[:8] for s in session_ids]}", file=sys.stderr, flush=True)

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


_listener_capture_task: asyncio.Task | None = None


async def _global_listener():
    """Single global capture loop. Runs WITHOUT the lock so TTS can interrupt.
    When TTS needs to speak, it sets audio_engine._listener_pause, which causes
    us to cancel any active capture and wait until TTS is done."""
    global _listener_capture_task
    while True:
        try:
            # Wait if TTS has paused us
            if audio_engine._listener_pause.is_set():
                audio_engine.state.set(STATUS="idle")
                print(f"[LISTENER] paused for TTS", file=sys.stderr, flush=True)
                audio_engine._listener_paused.set()  # signal that we've actually stopped
                await audio_engine._listener_resume.wait()
                audio_engine._listener_paused.clear()
                # Post-TTS settling: let room reverb and speaker buffers fully drain
                # Reset _tts_finished_at so energy gate in _capture_utterance gets full window
                # (the barge-in capture already consumed most of the original gate time)
                await asyncio.sleep(1.0)
                audio_engine._tts_finished_at = time.monotonic()
                print(f"[LISTENER] resumed after TTS (gate reset, 1.0s settle)", file=sys.stderr, flush=True)

            audio_engine.state.set(STATUS="listening")
            _listener_capture_task = asyncio.create_task(audio_engine._capture_utterance())
            try:
                text = await _listener_capture_task
            except asyncio.CancelledError:
                print(f"[LISTENER] capture cancelled for TTS", file=sys.stderr, flush=True)
                # Rescue partial speech that was buffered when TTS interrupted
                rescued = audio_engine._rescued_audio
                audio_engine._rescued_audio = None
                if rescued is not None:
                    try:
                        transcribed = await whisper_engine.transcribe(rescued)
                        transcribed = re.sub(r'\[[^\]]{1,30}\]', '', transcribed)
                        transcribed = re.sub(r'\([^\)]{1,30}\)', '', transcribed)
                        transcribed = re.sub(r'\bINAUDIBLE\b', '', transcribed, flags=re.IGNORECASE)
                        transcribed = transcribed.strip()
                        if re.fullmatch(r'[\s\.\,\!\?\-]*', transcribed):
                            transcribed = ""
                        if transcribed:
                            _lower = transcribed.lower().strip().rstrip(".,!?")
                            if _lower in _WHISPER_HALLUCINATION_BLOCKLIST:
                                print(f"[WHISPER] blocked rescued hallucination: '{transcribed}'", file=sys.stderr, flush=True)
                                transcribed = ""
                        if transcribed and len(transcribed) >= 2 and len(transcribed.strip().split()) >= 2:
                            audio_engine.logger.log_event("TRANSCRIPTION", {"text": transcribed, "rescued": True})
                            print(f"[LISTENER] rescued transcription: '{transcribed}'", file=sys.stderr, flush=True)
                            send_transcription_to_claude(transcribed)
                        elif transcribed:
                            print(f"[LISTENER] dropping short rescued utterance: '{transcribed}'", file=sys.stderr, flush=True)
                    except Exception as e:
                        print(f"[LISTENER] rescued transcription error: {e}", file=sys.stderr, flush=True)
                continue
            finally:
                _listener_capture_task = None
            if not text or text in ("(silence)", "(muted)", "(stt_error)"):
                if text == "(stt_error)":
                    await asyncio.sleep(2)
                continue
            if len(text.strip()) < 3 or len(text.strip().split()) < 2:
                print(f"[LISTENER] dropping short utterance: '{text.strip()}'", file=sys.stderr, flush=True)
                continue
            # Echo filter: TTS bleed may reach global listener after TTS releases lock
            echo_text = audio_engine._last_tts_text
            if echo_text and audio_engine._tts_finished_at > 0:
                since_tts = time.monotonic() - audio_engine._tts_finished_at
                if since_tts < 15.0:
                    filtered = AudioEngine._strip_tts_echo(text, echo_text)
                    print(f"[ECHO-FILTER] since_tts={since_tts:.1f}s input='{text[:50]}' output='{filtered[:50]}'", file=sys.stderr, flush=True)
                    if not filtered or filtered == "(silence)":
                        continue
                    text = filtered
            print(f"[LISTENER] routing: '{text[:60]}'", file=sys.stderr, flush=True)
            send_transcription_to_claude(text)
        except Exception as e:
            import traceback
            print(f"[LISTENER] Error (retrying): {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            await asyncio.sleep(2)


# ── Volume helpers ────────────────────────────────────────────────────────────


async def _get_volume() -> dict[str, int]:
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
        return {"volume": 50}


async def _set_volume(level: int) -> dict[str, int]:
    level = max(0, min(100, int(level)))  # Defense-in-depth: clamp before interpolation
    try:
        await asyncio.create_subprocess_exec(
            "osascript", "-e", f"set volume output volume {level}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return {"volume": level}
    except Exception:
        return await _get_volume()


# ── Command handlers ──────────────────────────────────────────────────────────


async def handle_status(params: dict) -> dict:
    import sounddevice as sd
    input_dev = sd.query_devices(audio_engine.device_index)
    default_out = sd.default.device[1]
    output_dev = sd.query_devices(int(default_out)) if default_out is not None else {}
    volume_info = await _get_volume()
    return {
        "ok": True,
        "state": state.get("STATUS", "idle"),
        "muted": state.get("MUTED", "false") == "true",
        "input_device": input_dev.get("name", "unknown"),
        "input_device_index": audio_engine.device_index,
        "output_device": output_dev.get("name", "unknown"),
        "output_device_index": int(default_out) if default_out is not None else -1,
        "barge_in": audio_engine.barge_in_enabled,
        "blackhole_device": audio_engine.blackhole_device,
        "auto_device": audio_engine._auto_device,
        "voice": audio_engine.voice,
        "tts_engine": "kokoro",
        "tts_available": audio_engine.kokoro is not None and audio_engine.kokoro.is_available(),
        "stt_engine": "whisper.cpp",
        "stt_model": whisper_engine.model_name,
        "stt_available": whisper_engine.is_ready(),
        "vad_aggressiveness": config.get_int("VAD_AGGRESSIVENESS", 2),
        "volume": volume_info["volume"],
    }


async def handle_speak(params: dict) -> dict:
    """Fire-and-forget TTS with barge-in support. Pauses global listener during TTS.
    If user interrupts (barge-in): captures interrupted speech and routes it.
    If TTS finishes naturally: resumes global listener for next capture."""
    text = params.get("text", "")
    if not text:
        return {"ok": False, "error": "text is required"}
    voice = params.get("voice")  # passed through to speak(), no shared state mutation
    engine = params.get("engine", "kokoro")  # "kokoro" (default) or "say" (macOS)

    async def _do_tts():
        global _listener_capture_task
        try:
            # Pause global listener: signal pause, cancel active capture, wait for stop
            audio_engine._listener_pause.set()
            audio_engine._listener_resume.clear()
            if _listener_capture_task and not _listener_capture_task.done():
                _listener_capture_task.cancel()
            # Wait for listener to actually pause (with timeout)
            try:
                await asyncio.wait_for(audio_engine._listener_paused.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                print(f"[TTS] Warning: listener didn't pause in time, proceeding", file=sys.stderr, flush=True)

            # Route to the right TTS engine
            _speak = audio_engine.speak_say if engine == "say" else audio_engine.speak

            try:
                if audio_engine._is_muted():
                    tts_pid = await _speak(text, voice=voice)
                    if tts_pid:
                        await audio_engine._tts_playback_done.wait()
                    return

                tts_pid = await _speak(text, voice=voice)
                if not tts_pid:
                    return

                audio_engine.state.set(STATUS="speaking+listening")
                try:
                    result = await audio_engine._capture_utterance(
                        tts_pid=tts_pid, tts_text=text, tts_only=True
                    )
                    if result and result not in ("(silence)", "(muted)", "(stt_error)"):
                        # Barge-in happened — route the interrupted speech
                        send_transcription_to_claude(result)
                finally:
                    audio_engine.state.set(STATUS="idle")
            finally:
                # Resume global listener
                audio_engine._listener_pause.clear()
                audio_engine._listener_resume.set()
        except Exception as e:
            import traceback
            print(f"[TTS] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            # Ensure listener resumes even on error
            audio_engine._listener_pause.clear()
            audio_engine._listener_resume.set()

    asyncio.create_task(_do_tts())
    return {"ok": True, "status": "speaking"}


async def handle_voice(params: dict) -> dict:
    voice = params.get("voice", "")
    if not voice:
        return {"ok": False, "error": "voice is required"}
    audio_engine.voice = voice
    return {"ok": True, "voice": audio_engine.voice}


async def handle_volume(params: dict) -> dict:
    v = await _get_volume()
    return {"ok": True, **v}


async def handle_set_volume(params: dict) -> dict:
    level = params.get("level")
    if level is None:
        return {"ok": False, "error": "level is required (0-100)"}
    level = max(0, min(100, int(level)))
    result = await _set_volume(level)
    state.set(VOLUME=str(result["volume"]))
    return {"ok": True, **result}


async def handle_volume_up(params: dict) -> dict:
    current = await _get_volume()
    new_vol = min(100, current["volume"] + 10)
    result = await _set_volume(new_vol)
    state.set(VOLUME=str(result["volume"]))
    return {"ok": True, **result}


async def handle_volume_down(params: dict) -> dict:
    current = await _get_volume()
    new_vol = max(0, current["volume"] - 10)
    result = await _set_volume(new_vol)
    state.set(VOLUME=str(result["volume"]))
    return {"ok": True, **result}


async def handle_mute(params: dict) -> dict:
    state.set(MUTED="true")
    return {"ok": True, "status": "muted"}


async def handle_unmute(params: dict) -> dict:
    state.set(MUTED="false")
    return {"ok": True, "status": "unmuted"}


async def handle_devices(params: dict) -> dict:
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
        "ok": True,
        "devices": device_list,
        "active_input": audio_engine.device_index,
        "active_input_name": devices[audio_engine.device_index]["name"],
        "default_input": int(default_in) if default_in is not None else None,
        "default_output": int(default_out) if default_out is not None else None,
    }


async def handle_stop(params: dict) -> dict:
    await whisper_engine.stop()
    state.set(SESSION="stopped")
    asyncio.create_task(_delayed_exit())
    return {"ok": True, "status": "shutting down"}


async def _delayed_exit():
    await asyncio.sleep(1)
    os._exit(0)


# Command dispatch table
COMMANDS: dict[str, Any] = {
    "status": handle_status,
    "speak": handle_speak,
    "voice": handle_voice,
    "volume": handle_volume,
    "set_volume": handle_set_volume,
    "volume_up": handle_volume_up,
    "volume_down": handle_volume_down,
    "mute": handle_mute,
    "unmute": handle_unmute,
    "devices": handle_devices,
    "stop": handle_stop,
}


# ── Session ref counting ─────────────────────────────────────────────────────


async def _handle_session_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, params: dict):
    """Persistent session connection. Stays open until client disconnects."""
    global _auto_shutdown_task

    session_id = params.get("session_id", "unknown")
    _session_connections.add(writer)
    print(f"[SESSION] connected: {session_id[:8]}... (total: {len(_session_connections)})", file=sys.stderr, flush=True)

    # Cancel pending auto-shutdown
    if _auto_shutdown_task and not _auto_shutdown_task.done():
        _auto_shutdown_task.cancel()
        _auto_shutdown_task = None
        print(f"[SESSION] auto-shutdown cancelled", file=sys.stderr, flush=True)

    # Restart whisper engine if it was stopped (e.g. after auto-shutdown)
    if not whisper_engine.is_ready():
        print(f"[SESSION] restarting whisper engine for new session", file=sys.stderr, flush=True)
        await whisper_engine.start()

    # Send ack
    writer.write(json.dumps({"ok": True, "status": "connected"}).encode() + b"\n")
    await writer.drain()

    # Hold connection open — read until EOF
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
    except (asyncio.CancelledError, ConnectionError):
        pass
    finally:
        _session_connections.discard(writer)
        print(f"[SESSION] disconnected: {session_id[:8]}... (remaining: {len(_session_connections)})", file=sys.stderr, flush=True)

        if not _session_connections:
            print(f"[SESSION] no sessions left, scheduling auto-shutdown in 5s", file=sys.stderr, flush=True)
            _auto_shutdown_task = asyncio.create_task(_auto_shutdown())


async def _auto_shutdown():
    """Auto-shutdown after grace period when all sessions disconnect.
    Stops whisper engine but keeps server process alive for reconnection."""
    await asyncio.sleep(5)
    if not _session_connections:
        print(f"[SESSION] no sessions for 5s, stopping whisper engine (server stays alive)", file=sys.stderr, flush=True)
        await whisper_engine.stop()
        state.set(SESSION="stopped")


# ── Client handler ────────────────────────────────────────────────────────────


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single client connection. Reads one JSON-line, dispatches, responds."""
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not line:
            return

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            writer.write(json.dumps({"ok": False, "error": "invalid JSON"}).encode() + b"\n")
            await writer.drain()
            return

        cmd = msg.get("cmd", "")
        params = {k: v for k, v in msg.items() if k != "cmd"}

        # Session connect is special — persistent connection
        if cmd == "session_connect":
            await _handle_session_connect(reader, writer, params)
            return

        handler = COMMANDS.get(cmd)
        if not handler:
            writer.write(json.dumps({"ok": False, "error": f"unknown command: {cmd}"}).encode() + b"\n")
            await writer.drain()
            return

        result = await handler(params)
        writer.write(json.dumps(result).encode() + b"\n")
        await writer.drain()

    except asyncio.TimeoutError:
        pass
    except Exception as e:
        try:
            writer.write(json.dumps({"ok": False, "error": str(e)}).encode() + b"\n")
            await writer.drain()
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ============================================================================
# Main
# ============================================================================


async def server_main():
    """Async main: start whisper.cpp STT and Unix socket server."""
    import socket as _socket

    socket_path = Path.home() / ".claude-talk/audio-server.sock"
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    state.set(SESSION="active", STATUS="idle", MUTED="false")

    # Start whisper.cpp STT engine (in-process, no port to poll)
    await whisper_engine.start()

    # Initialize Kokoro TTS
    await audio_engine.initialize_tts()

    # Create Unix socket with restrictive permissions
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.bind(str(socket_path))
    socket_path.chmod(0o600)
    sock.setblocking(False)

    server = await asyncio.start_unix_server(handle_client, sock=sock)
    print(f"Audio server listening on {socket_path}")

    # Start global listener — always-on mic capture, yields to speak via lock
    listener_task = asyncio.create_task(_global_listener())
    print("Global listener started")

    try:
        await server.serve_forever()
    finally:
        listener_task.cancel()
        server.close()
        await whisper_engine.stop()
        state.set(SESSION="stopped")
        event_logger.close()
        if socket_path.exists():
            socket_path.unlink()


def main():
    asyncio.run(server_main())


if __name__ == "__main__":
    main()

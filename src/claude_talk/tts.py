"""Kokoro TTS engine using MLX-Audio for neural text-to-speech."""

import threading
from typing import Any

import numpy as np


class KokoroTTS:
    """MLX-Audio Kokoro neural TTS engine. Singleton model, thread-safe."""

    SAMPLE_RATE = 24000
    DEFAULT_MODEL = "mlx-community/Kokoro-82M-bf16"
    DEFAULT_VOICE = "bm_daniel"

    # Language code derived from first character of voice ID
    LANG_CODES = {
        "a": "a", "b": "b", "j": "j", "z": "z",
        "e": "e", "f": "f", "h": "h", "i": "i", "p": "p",
    }

    # All 54 Kokoro voices with metadata
    VOICES = {
        # American Female
        "af_alloy": ("American", "Female"),
        "af_aoede": ("American", "Female"),
        "af_bella": ("American", "Female"),
        "af_heart": ("American", "Female"),
        "af_jessica": ("American", "Female"),
        "af_kore": ("American", "Female"),
        "af_nicole": ("American", "Female"),
        "af_nova": ("American", "Female"),
        "af_river": ("American", "Female"),
        "af_sarah": ("American", "Female"),
        "af_sky": ("American", "Female"),
        # American Male
        "am_adam": ("American", "Male"),
        "am_echo": ("American", "Male"),
        "am_eric": ("American", "Male"),
        "am_fenrir": ("American", "Male"),
        "am_liam": ("American", "Male"),
        "am_michael": ("American", "Male"),
        "am_onyx": ("American", "Male"),
        "am_puck": ("American", "Male"),
        # British Female
        "bf_alice": ("British", "Female"),
        "bf_emma": ("British", "Female"),
        "bf_isabella": ("British", "Female"),
        "bf_lily": ("British", "Female"),
        # British Male
        "bm_daniel": ("British", "Male"),
        "bm_fable": ("British", "Male"),
        "bm_george": ("British", "Male"),
        "bm_lewis": ("British", "Male"),
        # Japanese Female
        "jf_alpha": ("Japanese", "Female"),
        "jf_gongitsune": ("Japanese", "Female"),
        "jf_nezumi": ("Japanese", "Female"),
        "jf_tebukuro": ("Japanese", "Female"),
        # Japanese Male
        "jm_kumo": ("Japanese", "Male"),
        # Chinese Female
        "zf_xiaobei": ("Chinese", "Female"),
        "zf_xiaoni": ("Chinese", "Female"),
        "zf_xiaoxiao": ("Chinese", "Female"),
        "zf_xiaoyi": ("Chinese", "Female"),
        # Chinese Male
        "zm_yunjian": ("Chinese", "Male"),
        "zm_yunxi": ("Chinese", "Male"),
        "zm_yunxia": ("Chinese", "Male"),
        "zm_yunyang": ("Chinese", "Male"),
        # Spanish Female
        "ef_dora": ("Spanish", "Female"),
        # Spanish Male
        "em_alex": ("Spanish", "Male"),
        "em_santa": ("Spanish", "Male"),
        # French Female
        "ff_siwis": ("French", "Female"),
        # Hindi Female
        "hf_alpha": ("Hindi", "Female"),
        "hf_beta": ("Hindi", "Female"),
        # Hindi Male
        "hm_omega": ("Hindi", "Male"),
        "hm_psi": ("Hindi", "Male"),
        # Italian Female
        "if_sara": ("Italian", "Female"),
        # Italian Male
        "im_nicola": ("Italian", "Male"),
        # Portuguese Female
        "pf_dora": ("Portuguese", "Female"),
        # Portuguese Male
        "pm_alex": ("Portuguese", "Male"),
        "pm_santa": ("Portuguese", "Male"),
    }

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model: Any = None
        self._load_lock = threading.Lock()
        self._stop_requested = False

    async def initialize(self):
        """Load model in executor thread (non-blocking)."""
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_model)

    def _load_model(self):
        """Load the Kokoro model (thread-safe singleton)."""
        with self._load_lock:
            if self._model is not None:
                return
            from mlx_audio.tts.utils import load_model
            self._model = load_model(self.model_name)

    def _get_lang_code(self, voice: str) -> str:
        """Derive language code from voice ID prefix."""
        if voice and len(voice) >= 1:
            return self.LANG_CODES.get(voice[0], "a")
        return "a"

    def generate_sync(self, text: str, voice: str | None = None, speed: float = 1.0) -> np.ndarray:
        """Generate audio synchronously. Returns float32 numpy array.

        Iterates generation chunks and checks _stop_requested between them.
        """
        if self._model is None:
            raise RuntimeError("Kokoro model not loaded. Call initialize() first.")

        use_voice = voice or self.DEFAULT_VOICE
        lang_code = self._get_lang_code(use_voice)
        self._stop_requested = False

        chunks = []
        for result in self._model.generate(
            text=text, voice=use_voice, lang_code=lang_code, speed=speed
        ):
            if self._stop_requested:
                break
            audio = np.array(result.audio).flatten().astype(np.float32)
            chunks.append(audio)

        if not chunks:
            return np.array([], dtype=np.float32)

        return np.concatenate(chunks)

    async def generate(self, text: str, voice: str | None = None, speed: float = 1.0) -> tuple[np.ndarray, int]:
        """Async wrapper around generate_sync. Returns (audio_array, sample_rate)."""
        import asyncio
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(
            None, self.generate_sync, text, voice, speed
        )
        return audio, self.SAMPLE_RATE

    def stop(self):
        """Request generation to stop at next chunk boundary."""
        self._stop_requested = True

    def is_available(self) -> bool:
        """Check if the model is loaded and ready."""
        return self._model is not None

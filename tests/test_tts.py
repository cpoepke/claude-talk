"""Tests for Kokoro TTS engine."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from claude_talk.tts import KokoroTTS


# ── Voice metadata coverage ────────────────────────────────────────────────


# All 9 personality Kokoro voices must exist in the VOICES dict
PERSONALITY_VOICES = [
    "bm_daniel",   # claude
    "bf_emma",      # bonnie
    "af_bella",     # crystal
    "am_adam",      # hank
    "bf_alice",     # maeve
    "af_nova",      # sheila
    "af_heart",     # tash
    "am_echo",      # vex
    "bm_george",    # vikram
]


def test_all_personality_voices_in_kokoro_map():
    """Every personality's Kokoro voice must be a valid Kokoro voice ID."""
    for voice_id in PERSONALITY_VOICES:
        assert voice_id in KokoroTTS.VOICES, f"{voice_id} not in KokoroTTS.VOICES"


def test_personality_voices_unique():
    """Each personality should have a distinct Kokoro voice."""
    assert len(PERSONALITY_VOICES) == len(set(PERSONALITY_VOICES))


# ── Language code derivation ───────────────────────────────────────────────


class TestLangCodeDerivation:
    def setup_method(self):
        self.tts = KokoroTTS.__new__(KokoroTTS)

    def test_british_male(self):
        assert self.tts._get_lang_code("bm_daniel") == "b"

    def test_american_female(self):
        assert self.tts._get_lang_code("af_heart") == "a"

    def test_american_male(self):
        assert self.tts._get_lang_code("am_echo") == "a"

    def test_british_female(self):
        assert self.tts._get_lang_code("bf_emma") == "b"

    def test_japanese(self):
        assert self.tts._get_lang_code("jf_alpha") == "j"

    def test_chinese(self):
        assert self.tts._get_lang_code("zf_xiaobei") == "z"

    def test_spanish(self):
        assert self.tts._get_lang_code("ef_dora") == "e"

    def test_french(self):
        assert self.tts._get_lang_code("ff_siwis") == "f"

    def test_hindi(self):
        assert self.tts._get_lang_code("hf_alpha") == "h"

    def test_italian(self):
        assert self.tts._get_lang_code("if_sara") == "i"

    def test_portuguese(self):
        assert self.tts._get_lang_code("pf_dora") == "p"

    def test_empty_voice_defaults_to_a(self):
        assert self.tts._get_lang_code("") == "a"

    def test_none_voice_defaults_to_a(self):
        assert self.tts._get_lang_code(None) == "a"

    def test_unknown_prefix_defaults_to_a(self):
        assert self.tts._get_lang_code("xf_unknown") == "a"


# ── Voice resolution (from audio-server.py) ────────────────────────────────


# Import the map that will be used in audio-server.py
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


def test_all_macos_voices_map_to_valid_kokoro():
    """Every macOS voice in the map must resolve to a valid Kokoro voice."""
    for macos_voice, kokoro_voice in MACOS_TO_KOKORO.items():
        assert kokoro_voice in KokoroTTS.VOICES, (
            f"macOS '{macos_voice}' -> '{kokoro_voice}' not in KokoroTTS.VOICES"
        )


def test_resolve_enhanced_variants():
    """Enhanced/Premium variants should map to the same Kokoro voice as base."""
    assert MACOS_TO_KOKORO["Daniel"] == MACOS_TO_KOKORO["Daniel (Enhanced)"]
    assert MACOS_TO_KOKORO["Karen"] == MACOS_TO_KOKORO["Karen (Premium)"]
    assert MACOS_TO_KOKORO["Moira"] == MACOS_TO_KOKORO["Moira (Enhanced)"]


def test_all_personality_macos_voices_covered():
    """Every macOS voice used by a personality must be in the resolution map."""
    personality_macos_voices = [
        "Daniel (Enhanced)",   # claude
        "Fiona (Enhanced)",    # bonnie
        "Zoe (Premium)",       # crystal
        "Evan (Enhanced)",     # hank
        "Moira (Enhanced)",    # maeve
        "Karen (Premium)",     # sheila, tash
        "Zarvox",              # vex
        "Rishi (Enhanced)",    # vikram
    ]
    for voice in personality_macos_voices:
        assert voice in MACOS_TO_KOKORO, f"Personality voice '{voice}' not in MACOS_TO_KOKORO"


# ── KokoroTTS class behavior (mocked) ─────────────────────────────────────


def test_is_available_before_init():
    """Model should not be available before initialization."""
    tts = KokoroTTS()
    assert tts.is_available() is False


def test_is_available_after_load():
    """Model should be available after loading."""
    tts = KokoroTTS()
    tts._model = MagicMock()
    assert tts.is_available() is True


def test_stop_sets_flag():
    """stop() should set _stop_requested flag."""
    tts = KokoroTTS()
    assert tts._stop_requested is False
    tts.stop()
    assert tts._stop_requested is True


def test_generate_sync_raises_without_model():
    """generate_sync should raise if model not loaded."""
    tts = KokoroTTS()
    with pytest.raises(RuntimeError, match="not loaded"):
        tts.generate_sync("hello")


def _make_result(audio_array):
    """Create a mock result object like mlx-audio's generate() yields."""
    r = MagicMock()
    r.audio = audio_array
    r.sample_rate = 24000
    return r


def test_generate_sync_concatenates_chunks():
    """generate_sync should concatenate all chunks from model.generate."""
    tts = KokoroTTS()
    chunk1 = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    chunk2 = np.array([0.4, 0.5], dtype=np.float32)
    mock_model = MagicMock()
    mock_model.generate.return_value = iter([_make_result(chunk1), _make_result(chunk2)])
    tts._model = mock_model

    result = tts.generate_sync("hello", voice="bm_daniel")

    assert result.dtype == np.float32
    np.testing.assert_array_almost_equal(result, [0.1, 0.2, 0.3, 0.4, 0.5])
    mock_model.generate.assert_called_once_with(
        text="hello", voice="bm_daniel", lang_code="b", speed=1.0
    )


def test_generate_sync_stops_on_flag():
    """generate_sync should stop when _stop_requested is set."""
    tts = KokoroTTS()
    chunk1 = np.array([0.1, 0.2], dtype=np.float32)
    chunk2 = np.array([0.3, 0.4], dtype=np.float32)

    call_count = 0

    def stop_after_first(results):
        nonlocal call_count
        for r in results:
            call_count += 1
            yield r
            if call_count == 1:
                tts._stop_requested = True

    mock_model = MagicMock()
    mock_model.generate.return_value = stop_after_first([_make_result(chunk1), _make_result(chunk2)])
    tts._model = mock_model

    result = tts.generate_sync("hello")
    np.testing.assert_array_almost_equal(result, [0.1, 0.2])


def test_generate_sync_empty_output():
    """generate_sync should return empty array if model produces nothing."""
    tts = KokoroTTS()
    mock_model = MagicMock()
    mock_model.generate.return_value = iter([])
    tts._model = mock_model

    result = tts.generate_sync("hello")
    assert len(result) == 0
    assert result.dtype == np.float32


def test_generate_sync_uses_default_voice():
    """generate_sync should use DEFAULT_VOICE if none provided."""
    tts = KokoroTTS()
    mock_model = MagicMock()
    mock_model.generate.return_value = iter([_make_result(np.array([0.1], dtype=np.float32))])
    tts._model = mock_model

    tts.generate_sync("hello")
    mock_model.generate.assert_called_once_with(
        text="hello", voice="bm_daniel", lang_code="b", speed=1.0
    )


def test_generate_sync_custom_speed():
    """generate_sync should pass speed parameter to model."""
    tts = KokoroTTS()
    mock_model = MagicMock()
    mock_model.generate.return_value = iter([_make_result(np.array([0.1], dtype=np.float32))])
    tts._model = mock_model

    tts.generate_sync("hello", voice="af_heart", speed=1.5)
    mock_model.generate.assert_called_once_with(
        text="hello", voice="af_heart", lang_code="a", speed=1.5
    )


def test_default_model_name():
    """Default model should be the bf16 Kokoro model."""
    tts = KokoroTTS()
    assert tts.model_name == "mlx-community/Kokoro-82M-bf16"


def test_custom_model_name():
    """Custom model name should be stored."""
    tts = KokoroTTS(model_name="custom/model")
    assert tts.model_name == "custom/model"


def test_sample_rate():
    """Sample rate should be 24kHz for Kokoro."""
    assert KokoroTTS.SAMPLE_RATE == 24000


def test_voices_dict_not_empty():
    """VOICES dict should contain entries."""
    assert len(KokoroTTS.VOICES) > 50

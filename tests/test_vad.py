"""Tests for VoiceActivityDetector.

Since VoiceActivityDetector lives inside audio-server.py which imports heavy
dependencies (sounddevice, etc.), we re-implement the class logic in a
standalone test module for isolated unit testing.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── Standalone VAD class (mirrors audio-server.py implementation) ────────────


class VoiceActivityDetector:
    """Test copy of VoiceActivityDetector from audio-server.py."""

    def __init__(self, aggressiveness=2, silence_frames=50, sample_rate=16000, _mock_vad=None):
        if _mock_vad is not None:
            self.vad = _mock_vad
        else:
            import webrtcvad
            self.vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate
        self.silence_frames = silence_frames
        self.frame_duration_ms = 20
        self.frame_size = int(sample_rate * self.frame_duration_ms / 1000)
        self.max_frames = 1500

        self._speech_frames: list[np.ndarray] = []
        self._silent_count = 0
        self._speech_started = False
        self._frame_count = 0
        self._lookback: list[np.ndarray] = []
        self._lookback_size = 5

    def process_frame(self, frame_int16: np.ndarray) -> tuple[bool, np.ndarray | None]:
        self._frame_count += 1
        frame_bytes = frame_int16.flatten()[:self.frame_size].astype(np.int16).tobytes()
        try:
            is_speech = self.vad.is_speech(frame_bytes, self.sample_rate)
        except Exception:
            is_speech = False

        if not self._speech_started:
            self._lookback.append(frame_int16.flatten().copy())
            if len(self._lookback) > self._lookback_size:
                self._lookback.pop(0)
            if is_speech:
                self._speech_started = True
                for lb_frame in self._lookback:
                    self._speech_frames.append(lb_frame)
                self._speech_frames.append(frame_int16.flatten().copy())
                self._silent_count = 0
                self._lookback.clear()
        else:
            self._speech_frames.append(frame_int16.flatten().copy())
            if is_speech:
                self._silent_count = 0
            else:
                self._silent_count += 1
            if self._silent_count >= self.silence_frames:
                utterance = np.concatenate(self._speech_frames).astype(np.float32) / 32768.0
                self.reset()
                return True, utterance

        if self._frame_count >= self.max_frames:
            if self._speech_frames:
                utterance = np.concatenate(self._speech_frames).astype(np.float32) / 32768.0
                self.reset()
                return True, utterance
            self.reset()
            return True, None

        return False, None

    def reset(self):
        self._speech_frames.clear()
        self._silent_count = 0
        self._speech_started = False
        self._frame_count = 0
        self._lookback.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_vad(aggressiveness=2, silence_frames=5, speech_return=False):
    """Create a VoiceActivityDetector with a mocked webrtcvad backend."""
    mock_vad_instance = MagicMock()
    mock_vad_instance.is_speech.return_value = speech_return

    vad = VoiceActivityDetector(
        aggressiveness=aggressiveness,
        silence_frames=silence_frames,
        sample_rate=16000,
        _mock_vad=mock_vad_instance,
    )
    return vad, mock_vad_instance


def _make_frame(value=0, size=320):
    """Create a 320-sample int16 frame filled with a constant value."""
    return np.full(size, value, dtype=np.int16)


def _make_speech_frame(size=320):
    """Create a frame that looks like speech (high amplitude)."""
    return np.full(size, 5000, dtype=np.int16)


# ============================================================================
# Tests
# ============================================================================


class TestVADConstruction:
    """Test VAD initialization."""

    def test_creates_with_defaults(self):
        vad, _ = _make_vad()
        assert vad.sample_rate == 16000
        assert vad.frame_size == 320
        assert vad.silence_frames == 5
        assert vad.max_frames == 1500

    def test_frame_size_at_16khz(self):
        vad, _ = _make_vad()
        # 20ms at 16kHz = 320 samples
        assert vad.frame_size == 320

    def test_initial_state_clean(self):
        vad, _ = _make_vad()
        assert vad._speech_started is False
        assert vad._frame_count == 0
        assert len(vad._speech_frames) == 0
        assert len(vad._lookback) == 0


class TestVADSilence:
    """Test VAD behavior with pure silence (no speech detected)."""

    def test_silence_returns_false(self):
        """Pure silence frames should not trigger an utterance."""
        vad, mock = _make_vad(silence_frames=5)
        mock.is_speech.return_value = False

        for _ in range(100):
            done, utterance = vad.process_frame(_make_frame(0))
            if done:
                # Should only happen at max_frames with no speech
                assert utterance is None
                return
            assert utterance is None

    def test_silence_no_speech_frames_accumulated(self):
        """Silence should not accumulate speech frames."""
        vad, mock = _make_vad()
        mock.is_speech.return_value = False

        for _ in range(10):
            vad.process_frame(_make_frame(0))

        assert len(vad._speech_frames) == 0
        assert vad._speech_started is False


class TestVADSpeechDetection:
    """Test VAD speech boundary detection."""

    def test_speech_then_silence_produces_utterance(self):
        """Speech followed by enough silence should produce a float32 utterance."""
        vad, mock = _make_vad(silence_frames=3)

        # 5 speech frames
        mock.is_speech.return_value = True
        for _ in range(5):
            done, utterance = vad.process_frame(_make_speech_frame())
            assert done is False  # Not enough silence yet

        # 3 silence frames (= silence_frames threshold)
        mock.is_speech.return_value = False
        for i in range(3):
            done, utterance = vad.process_frame(_make_frame(0))
            if i < 2:
                assert done is False
            else:
                assert done is True
                assert utterance is not None
                assert utterance.dtype == np.float32
                return

        pytest.fail("Expected utterance after silence threshold")

    def test_utterance_is_float32_normalized(self):
        """Utterance should be float32 normalized to [-1, 1]."""
        vad, mock = _make_vad(silence_frames=2)

        # Speech frame with known value
        mock.is_speech.return_value = True
        vad.process_frame(np.full(320, 16384, dtype=np.int16))

        # Silence to trigger
        mock.is_speech.return_value = False
        vad.process_frame(_make_frame(0))
        done, utterance = vad.process_frame(_make_frame(0))

        assert done is True
        assert utterance is not None
        assert utterance.dtype == np.float32
        # 16384 / 32768.0 = 0.5
        assert np.any(np.isclose(utterance, 0.5, atol=0.01))

    def test_intermittent_speech_does_not_trigger(self):
        """Speech interrupted by brief silence (< threshold) should continue accumulating."""
        vad, mock = _make_vad(silence_frames=5)

        # Speech
        mock.is_speech.return_value = True
        for _ in range(5):
            vad.process_frame(_make_speech_frame())

        # Brief silence (2 frames, < threshold of 5)
        mock.is_speech.return_value = False
        for _ in range(2):
            done, _ = vad.process_frame(_make_frame(0))
            assert done is False

        # More speech
        mock.is_speech.return_value = True
        for _ in range(3):
            done, _ = vad.process_frame(_make_speech_frame())
            assert done is False

        # Silent count should have been reset
        assert vad._silent_count == 0


class TestVADLookback:
    """Test lookback buffer preserves leading audio."""

    def test_lookback_prepended_to_utterance(self):
        """Lookback frames should be prepended to speech when speech starts."""
        vad, mock = _make_vad(silence_frames=2)

        # Feed silence frames first (build lookback buffer)
        mock.is_speech.return_value = False
        for i in range(3):
            vad.process_frame(_make_frame(i + 1))  # fill with 1, 2, 3

        assert len(vad._lookback) == 3

        # Now speech starts. The process_frame logic:
        # 1. Appends current frame to lookback (now 4 items)
        # 2. is_speech=True -> copies all 4 lookback frames to speech_frames
        # 3. Also appends the current frame again to speech_frames
        # Result: 5 speech_frames = 4 lookback + 1 current
        mock.is_speech.return_value = True
        vad.process_frame(_make_speech_frame())

        # Lookback should have been consumed
        assert len(vad._lookback) == 0
        # Speech frames: 4 from lookback (3 silence + 1 speech) + 1 current = 5
        assert len(vad._speech_frames) == 5

    def test_lookback_capped_at_size(self):
        """Lookback buffer should not exceed _lookback_size."""
        vad, mock = _make_vad()
        mock.is_speech.return_value = False

        for _ in range(20):
            vad.process_frame(_make_frame(0))

        assert len(vad._lookback) <= vad._lookback_size


class TestVADMaxFrames:
    """Test safety cap behavior."""

    def test_max_frames_with_speech_returns_utterance(self):
        """Max frames cap should return accumulated speech as utterance."""
        vad, mock = _make_vad(silence_frames=9999)  # Never trigger silence
        vad.max_frames = 10  # Low cap for testing

        # All speech, never silence
        mock.is_speech.return_value = True
        for i in range(10):
            done, utterance = vad.process_frame(_make_speech_frame())
            if done:
                assert utterance is not None
                assert utterance.dtype == np.float32
                assert len(utterance) > 0
                return

        pytest.fail("Expected max_frames to trigger")

    def test_max_frames_without_speech_returns_none(self):
        """Max frames cap with no speech should return None."""
        vad, mock = _make_vad()
        vad.max_frames = 10
        mock.is_speech.return_value = False

        for i in range(10):
            done, utterance = vad.process_frame(_make_frame(0))
            if done:
                assert utterance is None
                return

        pytest.fail("Expected max_frames to trigger")


class TestVADReset:
    """Test reset clears state."""

    def test_reset_clears_all_state(self):
        vad, mock = _make_vad(silence_frames=999)
        mock.is_speech.return_value = True

        # Accumulate some state
        for _ in range(5):
            vad.process_frame(_make_speech_frame())

        assert vad._speech_started is True
        assert vad._frame_count == 5
        assert len(vad._speech_frames) > 0

        vad.reset()

        assert vad._speech_started is False
        assert vad._frame_count == 0
        assert len(vad._speech_frames) == 0
        assert vad._silent_count == 0
        assert len(vad._lookback) == 0

    def test_reusable_after_reset(self):
        """VAD should work correctly after reset."""
        vad, mock = _make_vad(silence_frames=2)

        # First utterance
        mock.is_speech.return_value = True
        for _ in range(3):
            vad.process_frame(_make_speech_frame())
        mock.is_speech.return_value = False
        for _ in range(2):
            done, utt = vad.process_frame(_make_frame(0))
        assert done is True
        assert utt is not None

        # VAD auto-resets after utterance - should work for second utterance
        mock.is_speech.return_value = True
        for _ in range(3):
            vad.process_frame(_make_speech_frame())
        mock.is_speech.return_value = False
        for _ in range(2):
            done, utt = vad.process_frame(_make_frame(0))
        assert done is True
        assert utt is not None


class TestVADExceptionHandling:
    """Test VAD handles webrtcvad errors gracefully."""

    def test_is_speech_exception_treated_as_no_speech(self):
        """If webrtcvad.is_speech raises, treat frame as non-speech."""
        vad, mock = _make_vad(silence_frames=3)
        mock.is_speech.side_effect = Exception("webrtcvad error")

        # Should not raise, just treat as silence
        for _ in range(10):
            done, utterance = vad.process_frame(_make_frame(0))
            assert done is False or utterance is None

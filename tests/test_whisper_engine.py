"""Tests for WhisperEngine.

Since WhisperEngine lives inside audio-server.py which imports heavy
dependencies, we re-implement the class logic in a standalone test copy
for isolated unit testing.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── Standalone WhisperEngine (mirrors audio-server.py implementation) ────────


class WhisperEngine:
    """Test copy of WhisperEngine from audio-server.py."""

    def __init__(self, config):
        self.config = config
        self.model_name = config.get("WHISPER_MODEL", "base.en")
        self._model = None
        self._model_lock = None
        self._ready = False

    async def start(self):
        self.initial_prompt = self._build_personality_prompt()
        self._model_lock = asyncio.Lock()
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(None, self._load_model)
        self._ready = True

    def _load_model(self):
        from pywhispercpp.model import Model
        return Model(self.model_name, language="en",
                     initial_prompt=self.initial_prompt, suppress_blank=True)

    async def transcribe(self, pcm_float32: np.ndarray) -> str:
        segments = []
        def on_segment(seg):
            segments.append(seg.text)
        loop = asyncio.get_event_loop()
        async with self._model_lock:
            await loop.run_in_executor(None, lambda: self._model.transcribe(
                pcm_float32, new_segment_callback=on_segment))
        return " ".join(segments).strip()

    def _build_personality_prompt(self) -> str:
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
            return prompt
        return ""

    def is_ready(self) -> bool:
        return self._ready and self._model is not None

    async def stop(self):
        self._model = None
        self._ready = False


# ── Mock config helper ───────────────────────────────────────────────────────


class MockConfig:
    """Minimal Config mock for testing."""
    def __init__(self, data=None):
        self._data = data or {}

    def get(self, key, default=""):
        return self._data.get(key, default)

    def get_int(self, key, default=0):
        return int(self._data.get(key, default))


# ============================================================================
# Tests
# ============================================================================


class TestWhisperEngineConstruction:
    """Test WhisperEngine initialization."""

    def test_default_model_name(self):
        engine = WhisperEngine(MockConfig())
        assert engine.model_name == "base.en"

    def test_custom_model_name(self):
        engine = WhisperEngine(MockConfig({"WHISPER_MODEL": "small.en"}))
        assert engine.model_name == "small.en"

    def test_not_ready_before_start(self):
        engine = WhisperEngine(MockConfig())
        assert engine.is_ready() is False

    def test_model_is_none_before_start(self):
        engine = WhisperEngine(MockConfig())
        assert engine._model is None

    def test_model_lock_is_none_before_start(self):
        engine = WhisperEngine(MockConfig())
        assert engine._model_lock is None


class TestWhisperEngineStart:
    """Test WhisperEngine startup."""

    @pytest.mark.asyncio
    async def test_start_loads_model(self, tmp_path):
        engine = WhisperEngine(MockConfig())
        mock_model = MagicMock()

        mock_model_class = MagicMock(return_value=mock_model)
        mock_pywhispercpp = MagicMock()
        mock_pywhispercpp.model.Model = mock_model_class

        with patch.dict("sys.modules", {
            "pywhispercpp": mock_pywhispercpp,
            "pywhispercpp.model": mock_pywhispercpp.model,
        }), patch("pathlib.Path.home", return_value=tmp_path):
            await engine.start()

        assert engine.is_ready() is True
        assert engine._model is not None
        mock_model_class.assert_called_once_with(
            "base.en", language="en", initial_prompt="", suppress_blank=True
        )

    @pytest.mark.asyncio
    async def test_start_creates_model_lock(self, tmp_path):
        engine = WhisperEngine(MockConfig())
        mock_model_class = MagicMock(return_value=MagicMock())
        mock_pywhispercpp = MagicMock()
        mock_pywhispercpp.model.Model = mock_model_class

        with patch.dict("sys.modules", {
            "pywhispercpp": mock_pywhispercpp,
            "pywhispercpp.model": mock_pywhispercpp.model,
        }), patch("pathlib.Path.home", return_value=tmp_path):
            await engine.start()

        assert engine._model_lock is not None
        assert isinstance(engine._model_lock, asyncio.Lock)


class TestWhisperEngineStop:
    """Test WhisperEngine shutdown."""

    @pytest.mark.asyncio
    async def test_stop_clears_model(self):
        engine = WhisperEngine(MockConfig())
        engine._model = MagicMock()
        engine._ready = True

        await engine.stop()

        assert engine._model is None
        assert engine._ready is False
        assert engine.is_ready() is False

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        """Stopping an already-stopped engine should not raise."""
        engine = WhisperEngine(MockConfig())
        await engine.stop()
        await engine.stop()
        assert engine.is_ready() is False


class TestWhisperEngineTranscribe:
    """Test WhisperEngine transcription."""

    @pytest.mark.asyncio
    async def test_transcribe_returns_joined_segments(self):
        engine = WhisperEngine(MockConfig())
        engine._model_lock = asyncio.Lock()

        # Mock model with transcribe that calls the callback
        mock_model = MagicMock()

        def fake_transcribe(pcm, new_segment_callback=None):
            seg1 = MagicMock()
            seg1.text = "hello"
            seg2 = MagicMock()
            seg2.text = "world"
            if new_segment_callback:
                new_segment_callback(seg1)
                new_segment_callback(seg2)

        mock_model.transcribe.side_effect = fake_transcribe
        engine._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        result = await engine.transcribe(audio)

        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_transcribe_empty_audio_returns_empty(self):
        engine = WhisperEngine(MockConfig())
        engine._model_lock = asyncio.Lock()

        mock_model = MagicMock()

        def fake_transcribe(pcm, new_segment_callback=None):
            pass  # No segments

        mock_model.transcribe.side_effect = fake_transcribe
        engine._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        result = await engine.transcribe(audio)

        assert result == ""

    @pytest.mark.asyncio
    async def test_transcribe_strips_whitespace(self):
        engine = WhisperEngine(MockConfig())
        engine._model_lock = asyncio.Lock()

        mock_model = MagicMock()

        def fake_transcribe(pcm, new_segment_callback=None):
            seg = MagicMock()
            seg.text = "  hello  "
            if new_segment_callback:
                new_segment_callback(seg)

        mock_model.transcribe.side_effect = fake_transcribe
        engine._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        result = await engine.transcribe(audio)

        assert result == "hello"


class TestWhisperEnginePersonalityPrompt:
    """Test personality prompt building."""

    def test_no_personalities_dir_returns_empty(self, tmp_path):
        engine = WhisperEngine(MockConfig())
        # Patch Path.home to use tmp_path where no personalities dir exists
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = engine._build_personality_prompt()
        assert result == ""

    def test_builds_prompt_from_personality_files(self, tmp_path):
        engine = WhisperEngine(MockConfig())
        personalities_dir = tmp_path / ".claude-talk" / "personalities"
        personalities_dir.mkdir(parents=True)

        # Create personality files
        (personalities_dir / "claude.md").write_text(
            "## Identity\n- Name: Claude\n- Style: witty\n"
        )
        (personalities_dir / "bonnie.md").write_text(
            "## Identity\n- Name: Bonnie\n- Style: warm\n"
        )

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = engine._build_personality_prompt()

        assert "Personalities:" in result
        assert "Claude" in result
        assert "Bonnie" in result
        assert result.endswith(".")

    def test_ignores_files_without_name_field(self, tmp_path):
        engine = WhisperEngine(MockConfig())
        personalities_dir = tmp_path / ".claude-talk" / "personalities"
        personalities_dir.mkdir(parents=True)

        (personalities_dir / "bad.md").write_text("## Identity\nNo name field here\n")
        (personalities_dir / "good.md").write_text("## Identity\n- Name: Claude\n")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = engine._build_personality_prompt()

        assert "Claude" in result
        # "bad" personality should not appear
        assert result.count(",") == 0  # Only one name, no comma


class TestWhisperEngineIsReady:
    """Test is_ready state tracking."""

    def test_not_ready_with_no_model(self):
        engine = WhisperEngine(MockConfig())
        engine._ready = True
        engine._model = None
        assert engine.is_ready() is False

    def test_not_ready_with_ready_false(self):
        engine = WhisperEngine(MockConfig())
        engine._ready = False
        engine._model = MagicMock()
        assert engine.is_ready() is False

    def test_ready_with_both(self):
        engine = WhisperEngine(MockConfig())
        engine._ready = True
        engine._model = MagicMock()
        assert engine.is_ready() is True

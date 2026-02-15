"""Tests for config loading."""

from pathlib import Path

from claude_talk.config import Config


def test_load_defaults(tmp_path):
    env_file = tmp_path / "config" / "defaults.env"
    env_file.parent.mkdir()
    env_file.write_text("FOO=bar\nBAZ=123\n")
    config = Config(project_dir=tmp_path)
    assert config.get("FOO") == "bar"
    assert config.get_int("BAZ") == 123


def test_comments_and_blanks(tmp_path):
    env_file = tmp_path / "config" / "defaults.env"
    env_file.parent.mkdir()
    env_file.write_text("# comment\n\nKEY=value\n")
    config = Config(project_dir=tmp_path)
    assert config.get("KEY") == "value"
    assert config.get("missing", "default") == "default"


def test_quoted_values(tmp_path):
    env_file = tmp_path / "config" / "defaults.env"
    env_file.parent.mkdir()
    env_file.write_text('VOICE="Daniel (Enhanced)"\nNAME=\'Claude\'\n')
    config = Config(project_dir=tmp_path)
    assert config.get("VOICE") == "Daniel (Enhanced)"
    assert config.get("NAME") == "Claude"


def test_variable_expansion(tmp_path):
    env_file = tmp_path / "config" / "defaults.env"
    env_file.parent.mkdir()
    env_file.write_text("PORT=8090\nURL=ws://localhost:${PORT}/asr\n")
    config = Config(project_dir=tmp_path)
    assert config.get("URL") == "ws://localhost:8090/asr"


def test_get_float(tmp_path):
    env_file = tmp_path / "config" / "defaults.env"
    env_file.parent.mkdir()
    env_file.write_text("GAIN=8.0\nBAD=abc\n")
    config = Config(project_dir=tmp_path)
    assert config.get_float("GAIN") == 8.0
    assert config.get_float("BAD", 1.0) == 1.0


def test_get_bool(tmp_path):
    env_file = tmp_path / "config" / "defaults.env"
    env_file.parent.mkdir()
    env_file.write_text("ON=true\nOFF=false\nYES=1\n")
    config = Config(project_dir=tmp_path)
    assert config.get_bool("ON") is True
    assert config.get_bool("OFF") is False
    assert config.get_bool("YES") is True
    assert config.get_bool("MISSING", True) is True

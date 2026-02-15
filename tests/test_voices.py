"""Tests for macOS voice listing."""

from unittest.mock import patch

from claude_talk.voices import _parse_voices, list_enhanced_voices


def test_parse_voices():
    output = (
        "Daniel (Enhanced)    en_GB  # Hello, my name is Daniel.\n"
        "Karen                en_AU  # Hello, my name is Karen.\n"
        "Zarvox               en_US  # That does not compute.\n"
        "Samantha (Enhanced)  en_US  # Hello, my name is Samantha.\n"
    )
    voices = _parse_voices(output)
    assert len(voices) == 4
    assert voices[0]["name"] == "Daniel (Enhanced)"
    assert voices[0]["enhanced"] is True
    assert voices[0]["lang"] == "en_GB"
    assert voices[1]["name"] == "Karen"
    assert voices[1]["enhanced"] is False
    assert voices[3]["name"] == "Samantha (Enhanced)"
    assert voices[3]["enhanced"] is True


def test_list_enhanced_voices():
    output = (
        "Daniel (Enhanced)    en_GB  # Hello\n"
        "Karen                en_AU  # Hello\n"
        "Moira (Premium)      en_IE  # Hello\n"
    )
    with patch("claude_talk.voices.subprocess.check_output", return_value=output):
        enhanced = list_enhanced_voices()
    assert len(enhanced) == 2
    names = {v["name"] for v in enhanced}
    assert names == {"Daniel (Enhanced)", "Moira (Premium)"}

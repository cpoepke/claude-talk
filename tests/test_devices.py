"""Tests for audio device listing."""

from unittest.mock import MagicMock, patch


def test_list_devices():
    mock_devices = [
        {"name": "Built-in Mic", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
    ]
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = mock_devices

    with patch.dict("sys.modules", {"sounddevice": mock_sd}):
        from claude_talk.devices import list_devices
        devs = list_devices()

    assert len(devs) == 3
    assert devs[0]["name"] == "Built-in Mic"
    assert devs[0]["input_channels"] == 1
    assert devs[2]["name"] == "BlackHole 2ch"


def test_get_defaults():
    mock_sd = MagicMock()
    mock_sd.default.device = (0, 1)

    with patch.dict("sys.modules", {"sounddevice": mock_sd}):
        from claude_talk.devices import get_defaults
        din, dout = get_defaults()

    assert din == 0
    assert dout == 1

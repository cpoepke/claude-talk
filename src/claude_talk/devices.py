"""Audio device listing via sounddevice."""


def list_devices() -> list[dict]:
    """List all audio devices."""
    import sounddevice as sd
    devices = sd.query_devices()
    result = []
    for i, dev in enumerate(devices):
        result.append({
            "index": i,
            "name": dev["name"],
            "input_channels": dev["max_input_channels"],
            "output_channels": dev["max_output_channels"],
        })
    return result


def get_defaults() -> tuple[int | None, int | None]:
    """Return (default_input_index, default_output_index)."""
    import sounddevice as sd
    din, dout = sd.default.device
    return (
        int(din) if din is not None else None,
        int(dout) if dout is not None else None,
    )

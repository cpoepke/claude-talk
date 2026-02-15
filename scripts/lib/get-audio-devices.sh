#!/usr/bin/env bash
# List audio devices using Python sounddevice
# Usage: bash scripts/lib/get-audio-devices.sh

set -euo pipefail

# Load config to get WLK_VENV
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/load-config.sh"
WLK_VENV="${WLK_VENV/#\~/$HOME}"

(
    source "$WLK_VENV/bin/activate"
    python3 -c "
import sounddevice as sd
devices = sd.query_devices()
din, dout = sd.default.device
print('Audio Devices:')
for i, d in enumerate(devices):
    flags = []
    if d['max_input_channels'] > 0: flags.append(f\"{d['max_input_channels']}in\")
    if d['max_output_channels'] > 0: flags.append(f\"{d['max_output_channels']}out\")
    marker = ''
    if i == din: marker += ' ← default input'
    if i == dout: marker += ' ← default output'
    print(f'  [{i}] {d[\"name\"]} ({', '.join(flags)}){marker}')
"
)

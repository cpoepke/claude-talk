#!/usr/bin/env python3
"""
Voice Activity Detection + Whisper transcription capture.

Listens on the microphone, detects speech using energy-based VAD,
captures the utterance, sends it to whisper-cpp server for transcription,
and prints the result to stdout before exiting.

Usage:
    python3 vad-capture.py [--device DEVICE_INDEX] [--server URL] [--output FILE]

Designed to be run as a background task in Claude Code teams:
each invocation captures ONE utterance and exits, triggering a
task-completion notification that wakes the teammate.
"""

import argparse
import io
import os
import sys
import wave

import numpy as np
import requests
import sounddevice as sd


def rms(audio_chunk: np.ndarray) -> float:
    """Root mean square energy of an audio chunk."""
    return float(np.sqrt(np.mean(audio_chunk.astype(np.float64) ** 2)))


def capture_utterance(
    device_index: int = 1,
    sample_rate: int = 16000,
    channels: int = 1,
    block_duration_ms: int = 100,
    speech_threshold: float = 200.0,
    silence_duration: float = 1.8,
    min_speech_duration: float = 0.3,
    max_speech_duration: float = 30.0,
    pre_speech_buffer_s: float = 0.3,
) -> np.ndarray | None:
    """
    Capture a single utterance from the microphone.

    Waits for speech to start (energy above threshold), then records
    until silence is detected (energy below threshold for silence_duration seconds).

    Returns the audio as a numpy array, or None if nothing was captured.
    """
    block_size = int(sample_rate * block_duration_ms / 1000)
    silence_blocks = int(silence_duration * 1000 / block_duration_ms)
    min_speech_blocks = int(min_speech_duration * 1000 / block_duration_ms)
    max_blocks = int(max_speech_duration * 1000 / block_duration_ms)
    pre_buffer_blocks = int(pre_speech_buffer_s * 1000 / block_duration_ms)

    recording = False
    audio_blocks: list[np.ndarray] = []
    pre_buffer: list[np.ndarray] = []
    silent_count = 0
    speech_count = 0

    print("Listening for speech...", file=sys.stderr, flush=True)

    with sd.InputStream(
        device=device_index,
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        blocksize=block_size,
    ) as stream:
        while True:
            data, overflowed = stream.read(block_size)
            energy = rms(data)

            if not recording:
                # Keep a rolling pre-buffer so we don't clip the start of speech
                pre_buffer.append(data.copy())
                if len(pre_buffer) > pre_buffer_blocks:
                    pre_buffer.pop(0)

                if energy > speech_threshold:
                    recording = True
                    silent_count = 0
                    speech_count = 1
                    # Include pre-buffer to capture the very start of speech
                    audio_blocks = list(pre_buffer)
                    audio_blocks.append(data.copy())
                    print("Speech detected, recording...", file=sys.stderr, flush=True)
            else:
                audio_blocks.append(data.copy())
                speech_count += 1

                if energy > speech_threshold:
                    silent_count = 0
                else:
                    silent_count += 1

                # End of utterance: enough silence after speech
                if silent_count >= silence_blocks and speech_count >= min_speech_blocks:
                    print("End of speech detected.", file=sys.stderr, flush=True)
                    break

                # Safety: max duration reached
                if speech_count >= max_blocks:
                    print("Max duration reached.", file=sys.stderr, flush=True)
                    break

    if not audio_blocks:
        return None

    return np.concatenate(audio_blocks)


def audio_to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Convert numpy int16 audio to WAV bytes in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def transcribe_with_server(
    wav_bytes: bytes,
    server_url: str = "http://localhost:8178",
) -> str:
    """Send WAV audio to whisper-cpp server and return transcription."""
    resp = requests.post(
        f"{server_url}/inference",
        files={"file": ("audio.wav", wav_bytes, "audio/wav")},
        data={"response_format": "json", "temperature": "0.0"},
        timeout=30,
    )
    resp.raise_for_status()

    result = resp.json()
    # whisper-cpp server returns {"text": "..."}
    if isinstance(result, dict) and "text" in result:
        return result["text"].strip()
    # Some versions return a list of segments
    if isinstance(result, list):
        return " ".join(seg.get("text", "") for seg in result).strip()
    return str(result).strip()


def transcribe_with_cli(
    wav_bytes: bytes,
    model_path: str = "/tmp/ggml-small.en.bin",
) -> str:
    """Fallback: write WAV to temp file and use whisper-cpp CLI."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["whisper-cpp", "-m", model_path, "-f", tmp_path, "--no-timestamps", "-t", "4"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()
    finally:
        os.unlink(tmp_path)


def main():
    parser = argparse.ArgumentParser(description="Capture one utterance and transcribe it")
    parser.add_argument("--device", type=int, default=1, help="Audio device index (default: 1)")
    parser.add_argument("--server", type=str, default="http://localhost:8178", help="Whisper server URL")
    parser.add_argument("--output", type=str, default="/tmp/voice_chat/utterance.txt", help="Output file for transcription")
    parser.add_argument("--threshold", type=float, default=200.0, help="Speech energy threshold in raw int16 RMS (default: 200, ambient ~50)")
    parser.add_argument("--silence", type=float, default=1.8, help="Silence duration to end utterance (default: 1.8s)")
    parser.add_argument("--use-cli", action="store_true", help="Use whisper-cpp CLI instead of server")
    args = parser.parse_args()

    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    # Capture utterance
    audio = capture_utterance(
        device_index=args.device,
        speech_threshold=args.threshold,
        silence_duration=args.silence,
    )

    if audio is None or len(audio) < 4800:  # Less than 0.3s at 16kHz
        print("No speech captured.", file=sys.stderr)
        # Write empty file so the caller knows we ran but got nothing
        with open(args.output, "w") as f:
            f.write("")
        sys.exit(0)

    # Convert to WAV
    wav_bytes = audio_to_wav_bytes(audio)
    duration = len(audio) / 16000
    print(f"Captured {duration:.1f}s of audio ({len(wav_bytes)} bytes)", file=sys.stderr, flush=True)

    # Transcribe
    try:
        if args.use_cli:
            text = transcribe_with_cli(wav_bytes)
        else:
            text = transcribe_with_server(wav_bytes, args.server)
    except Exception as e:
        print(f"Server transcription failed ({e}), falling back to CLI...", file=sys.stderr, flush=True)
        try:
            text = transcribe_with_cli(wav_bytes)
        except Exception as e2:
            print(f"CLI transcription also failed: {e2}", file=sys.stderr)
            sys.exit(1)

    # Filter hallucinations on near-silence
    max_amplitude = float(np.max(np.abs(audio)))
    if max_amplitude < 650 and len(text) > 0:  # ~0.02 * 32768
        print(f"Low amplitude ({max_amplitude:.0f}/32768), likely hallucination. Discarding.", file=sys.stderr)
        text = ""

    # Write result
    with open(args.output, "w") as f:
        f.write(text)

    # Also print to stdout for direct use
    if text:
        print(text)
    else:
        print("(silence)", file=sys.stderr)


if __name__ == "__main__":
    main()

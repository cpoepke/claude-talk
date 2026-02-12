#!/usr/bin/env python3
"""
WhisperLiveKit WebSocket capture - streams mic audio to WLK server,
collects real-time transcription, detects end-of-utterance, and exits.

When --tts-pid is provided, waits for TTS to finish (monitors PID)
before sending audio to WLK. Mic stream stays warm so capture begins
instantly when TTS ends - zero gap.

When --reference-device is provided (BlackHole), enables Geigel
barge-in: compares mic power vs clean TTS reference to detect when
the user speaks over TTS. Kills TTS and begins capture immediately.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
import time

import numpy as np
import sounddevice as sd


def detect_blackhole_device() -> int | None:
    """Auto-detect BlackHole 2ch input device index."""
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if "BlackHole 2ch" in dev["name"] and dev["max_input_channels"] > 0:
            return i
    return None


async def capture_utterance(
    server_url: str = "ws://localhost:8090/asr",
    device_index: int = 1,
    sample_rate: int = 16000,
    gain: float = 8.0,
    silence_timeout: float = 2.0,
    min_text_length: int = 2,
    max_duration: float = 60.0,
    tts_pid: int = 0,
    reference_device: int = -1,
    barge_in_ratio: float = 0.4,
    barge_in_grace: float = 0.8,
    barge_in_consecutive: int = 3,
) -> str:
    """
    Stream mic to WLK, collect transcription, return when utterance ends.

    If tts_pid > 0, waits for the TTS process to exit before sending
    audio to WLK. Mic stays warm so there's zero gap when TTS ends.

    If reference_device >= 0, enables Geigel barge-in detection:
    opens a second stream on BlackHole to get clean TTS reference,
    compares mic RMS vs reference RMS to detect user speech.
    """
    import websockets

    text_result = ""
    last_text_change = 0.0
    start_time = time.monotonic()
    got_text = False
    frame_size = int(sample_rate * 0.1)  # 100ms chunks for WLK

    # TTS monitoring state
    tts_active = tts_pid > 0
    tts_done_event = asyncio.Event()

    if not tts_active:
        tts_done_event.set()

    # Barge-in state
    barge_in_enabled = tts_active and reference_device >= 0
    barge_in_triggered = False

    async with websockets.connect(server_url) as ws:
        if tts_active:
            if barge_in_enabled:
                print(
                    f"TTS playing (PID {tts_pid}), barge-in via ref device {reference_device}...",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                print(
                    f"TTS playing (PID {tts_pid}), waiting to finish...",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            print("Listening for speech...", file=sys.stderr, flush=True)

        loop = asyncio.get_event_loop()
        audio_queue: asyncio.Queue = asyncio.Queue()
        ref_queue: asyncio.Queue = asyncio.Queue()
        done_event = asyncio.Event()

        def audio_callback(indata, frames, time_info, status):
            boosted = np.clip(
                indata.astype(np.float64) * gain, -32768, 32767
            ).astype(np.int16)
            loop.call_soon_threadsafe(audio_queue.put_nowait, boosted)

        def ref_callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(ref_queue.put_nowait, indata.copy())

        # Mic stream
        mic_stream = sd.InputStream(
            device=device_index,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_size,
            callback=audio_callback,
        )

        # Reference stream (BlackHole) - only if barge-in enabled
        ref_stream = None
        if barge_in_enabled:
            ref_stream = sd.InputStream(
                device=reference_device,
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=frame_size,
                callback=ref_callback,
            )

        async def tts_monitor():
            """Poll TTS process until it exits, then signal capture to begin."""
            if not tts_active:
                return

            while not done_event.is_set():
                try:
                    os.kill(tts_pid, 0)
                except ProcessLookupError:
                    print(
                        "TTS finished, capturing...",
                        file=sys.stderr,
                        flush=True,
                    )
                    tts_done_event.set()
                    return
                await asyncio.sleep(0.05)

        async def barge_in_monitor():
            """Geigel DTD: detect user speech by comparing mic vs reference."""
            nonlocal barge_in_triggered

            if not barge_in_enabled:
                return

            # Grace period: let TTS audio stabilize
            await asyncio.sleep(barge_in_grace)

            if tts_done_event.is_set():
                return

            print("Barge-in monitor active.", file=sys.stderr, flush=True)

            spike_count = 0

            while not done_event.is_set() and not tts_done_event.is_set():
                # Drain queues, keep latest frame from each
                mic_frame = None
                while not audio_queue.empty():
                    mic_frame = audio_queue.get_nowait()

                ref_frame = None
                while not ref_queue.empty():
                    ref_frame = ref_queue.get_nowait()

                if mic_frame is None or ref_frame is None:
                    await asyncio.sleep(0.05)
                    continue

                # Compute RMS power
                mic_rms = float(np.sqrt(np.mean(mic_frame.astype(np.float64) ** 2)))
                ref_rms = float(np.sqrt(np.mean(ref_frame.astype(np.float64) ** 2)))

                # Geigel condition: mic echo is ~5-12% of BlackHole ref.
                # User speech pushes mic to 50-100% of ref.
                # Trigger when mic/ref ratio exceeds threshold (default 0.4).
                # This catches user speech while ignoring echo-only frames.
                ratio = mic_rms / max(ref_rms, 1)

                if ref_rms > 50 and ratio > barge_in_ratio:
                    spike_count += 1
                elif ref_rms <= 50 and mic_rms > 500:
                    # TTS pause but mic has energy = user speaking
                    spike_count += 1
                else:
                    spike_count = max(0, spike_count - 1)

                if spike_count >= barge_in_consecutive:
                    print(
                        f"BARGE-IN! mic={mic_rms:.0f} ref={ref_rms:.0f} ratio={ratio:.2f}",
                        file=sys.stderr,
                        flush=True,
                    )
                    barge_in_triggered = True

                    # Kill TTS
                    try:
                        os.kill(tts_pid, signal.SIGTERM)
                        print(f"Killed TTS (PID {tts_pid})", file=sys.stderr, flush=True)
                    except ProcessLookupError:
                        pass

                    tts_done_event.set()

                    # Drain stale frames
                    while not audio_queue.empty():
                        audio_queue.get_nowait()
                    while not ref_queue.empty():
                        ref_queue.get_nowait()

                    return

                await asyncio.sleep(0.05)

        async def send_audio():
            await tts_done_event.wait()

            # Extra delay: macOS `say` may exit before audio buffer finishes
            if tts_active and not barge_in_triggered:
                await asyncio.sleep(0.5)

            # Drain echo frames accumulated during TTS
            if barge_in_enabled and not barge_in_triggered:
                while not audio_queue.empty():
                    audio_queue.get_nowait()

            # Open mic if not already open for barge-in
            if not barge_in_enabled:
                mic_stream.start()

            try:
                while not done_event.is_set():
                    try:
                        data = await asyncio.wait_for(
                            audio_queue.get(), timeout=0.5
                        )
                        await ws.send(data.tobytes())
                    except asyncio.TimeoutError:
                        continue
            finally:
                if not barge_in_enabled:
                    mic_stream.stop()

        async def recv_transcription():
            nonlocal text_result, last_text_change, got_text

            while not done_event.is_set():
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                d = json.loads(msg)
                lines_text = " ".join(
                    l.get("text", "") for l in d.get("lines", [])
                ).strip()
                buffer_text = d.get("buffer_transcription", "").strip()
                combined = (lines_text + " " + buffer_text).strip()

                # Filter whisper hallucinations
                if any(
                    h in combined
                    for h in ["[Music]", "[INAUDIBLE]", "[BLANK_AUDIO]"]
                ):
                    combined = (
                        combined.replace("[Music]", "")
                        .replace("[INAUDIBLE]", "")
                        .replace("[BLANK_AUDIO]", "")
                        .strip()
                    )

                if combined and combined != text_result:
                    text_result = combined
                    last_text_change = time.monotonic()
                    if not got_text:
                        got_text = True
                        print(
                            "Speech detected, transcribing...",
                            file=sys.stderr,
                            flush=True,
                        )

        async def monitor():
            """Check for utterance completion."""
            nonlocal text_result

            await tts_done_event.wait()
            capture_start = time.monotonic()

            while not done_event.is_set():
                await asyncio.sleep(0.3)
                now = time.monotonic()

                if now - capture_start > max_duration:
                    print("Max duration reached.", file=sys.stderr, flush=True)
                    done_event.set()
                    return

                if got_text and last_text_change > 0:
                    idle_time = now - last_text_change
                    if (
                        idle_time >= silence_timeout
                        and len(text_result) >= min_text_length
                    ):
                        print(
                            "End of utterance detected.",
                            file=sys.stderr,
                            flush=True,
                        )
                        done_event.set()
                        return

        # Start streams for barge-in (mic + ref both needed during TTS)
        if barge_in_enabled:
            mic_stream.start()
            ref_stream.start()

        try:
            tasks = [
                asyncio.create_task(tts_monitor()),
                asyncio.create_task(barge_in_monitor()),
                asyncio.create_task(send_audio()),
                asyncio.create_task(recv_transcription()),
                asyncio.create_task(monitor()),
            ]

            await done_event.wait()

            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if barge_in_enabled:
                mic_stream.stop()
                mic_stream.close()
                if ref_stream:
                    ref_stream.stop()
                    ref_stream.close()

    return text_result


def main():
    parser = argparse.ArgumentParser(
        description="Capture one utterance via WhisperLiveKit WebSocket"
    )
    parser.add_argument(
        "--server", default="ws://localhost:8090/asr", help="WLK WebSocket URL"
    )
    parser.add_argument("--device", type=int, default=1, help="Audio device index")
    parser.add_argument(
        "--gain", type=float, default=8.0, help="Mic gain multiplier"
    )
    parser.add_argument(
        "--output", default="/tmp/voice_chat/utterance.txt", help="Output file"
    )
    parser.add_argument(
        "--silence", type=float, default=2.0, help="Silence timeout (s)"
    )
    parser.add_argument(
        "--max-duration", type=float, default=60.0, help="Max recording duration (s)"
    )
    parser.add_argument(
        "--tts-pid",
        type=int,
        default=0,
        help="PID of TTS process to wait for (0 = disabled)",
    )
    parser.add_argument(
        "--reference-device",
        type=int,
        default=-1,
        help="BlackHole device index for barge-in (-1 = auto-detect, -2 = disabled)",
    )
    parser.add_argument(
        "--barge-in-ratio",
        type=float,
        default=0.4,
        help="Geigel threshold: mic/ref ratio above this triggers barge-in (echo ~0.1, speech ~0.5+)",
    )
    parser.add_argument(
        "--barge-in-grace",
        type=float,
        default=0.8,
        help="Grace period (s) before barge-in detection activates",
    )
    parser.add_argument(
        "--barge-in-consecutive",
        type=int,
        default=3,
        help="Consecutive spike frames needed to trigger barge-in",
    )
    args = parser.parse_args()

    # Auto-detect BlackHole
    ref_device = args.reference_device
    if ref_device == -1:
        detected = detect_blackhole_device()
        if detected is not None:
            ref_device = detected
            print(
                f"Auto-detected BlackHole 2ch at device {ref_device}",
                file=sys.stderr,
                flush=True,
            )
        else:
            ref_device = -2
            print(
                "BlackHole not found, barge-in disabled.",
                file=sys.stderr,
                flush=True,
            )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    text = asyncio.run(
        capture_utterance(
            server_url=args.server,
            device_index=args.device,
            gain=args.gain,
            silence_timeout=args.silence,
            max_duration=args.max_duration,
            tts_pid=args.tts_pid,
            reference_device=ref_device if ref_device >= 0 else -1,
            barge_in_ratio=args.barge_in_ratio,
            barge_in_grace=args.barge_in_grace,
            barge_in_consecutive=args.barge_in_consecutive,
        )
    )

    with open(args.output, "w") as f:
        f.write(text)

    if text:
        print(text)
    else:
        print("(silence)", file=sys.stderr)


if __name__ == "__main__":
    main()

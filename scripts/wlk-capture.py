#!/usr/bin/env python3
"""
WhisperLiveKit WebSocket capture - streams mic audio to WLK server,
collects real-time transcription, detects end-of-utterance, and exits.

Designed to be run as a background task in Claude Code teams:
each invocation captures ONE utterance and exits.
"""

import argparse
import asyncio
import json
import os
import sys
import time

import numpy as np
import sounddevice as sd


async def capture_utterance(
    server_url: str = "ws://localhost:8090/asr",
    device_index: int = 1,
    sample_rate: int = 16000,
    gain: float = 8.0,
    silence_timeout: float = 2.0,
    min_text_length: int = 2,
    max_duration: float = 60.0,
) -> str:
    """
    Stream mic to WLK, collect transcription, return when utterance ends.

    Utterance end is detected when:
    - We have received some transcription text (min_text_length chars)
    - The text hasn't changed for silence_timeout seconds
    """
    import websockets

    text_result = ""
    last_text_change = 0.0
    start_time = time.monotonic()
    got_text = False

    async with websockets.connect(server_url) as ws:
        print("Listening for speech...", file=sys.stderr, flush=True)

        loop = asyncio.get_event_loop()
        audio_queue: asyncio.Queue = asyncio.Queue()
        done_event = asyncio.Event()

        def audio_callback(indata, frames, time_info, status):
            boosted = np.clip(
                indata.astype(np.float64) * gain, -32768, 32767
            ).astype(np.int16)
            loop.call_soon_threadsafe(audio_queue.put_nowait, boosted)

        stream = sd.InputStream(
            device=device_index,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=int(sample_rate * 0.1),  # 100ms chunks
            callback=audio_callback,
        )

        async def send_audio():
            with stream:
                while not done_event.is_set():
                    try:
                        data = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                        await ws.send(data.tobytes())
                    except asyncio.TimeoutError:
                        continue

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
                if any(h in combined for h in ["[Music]", "[INAUDIBLE]", "[BLANK_AUDIO]"]):
                    combined = combined.replace("[Music]", "").replace("[INAUDIBLE]", "").replace("[BLANK_AUDIO]", "").strip()

                if combined and combined != text_result:
                    text_result = combined
                    last_text_change = time.monotonic()
                    if not got_text:
                        got_text = True
                        print("Speech detected, transcribing...", file=sys.stderr, flush=True)

        async def monitor():
            """Check for utterance completion."""
            nonlocal text_result
            while not done_event.is_set():
                await asyncio.sleep(0.3)
                now = time.monotonic()

                # Max duration safety
                if now - start_time > max_duration:
                    print("Max duration reached.", file=sys.stderr, flush=True)
                    done_event.set()
                    return

                # Utterance complete: got text and it's been stable
                if got_text and last_text_change > 0:
                    idle_time = now - last_text_change
                    if idle_time >= silence_timeout and len(text_result) >= min_text_length:
                        print("End of utterance detected.", file=sys.stderr, flush=True)
                        done_event.set()
                        return

        tasks = [
            asyncio.create_task(send_audio()),
            asyncio.create_task(recv_transcription()),
            asyncio.create_task(monitor()),
        ]

        # Wait for monitor to signal done
        await done_event.wait()

        # Give tasks a moment to clean up
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    return text_result


def main():
    parser = argparse.ArgumentParser(
        description="Capture one utterance via WhisperLiveKit WebSocket"
    )
    parser.add_argument("--server", default="ws://localhost:8090/asr", help="WLK WebSocket URL")
    parser.add_argument("--device", type=int, default=1, help="Audio device index")
    parser.add_argument("--gain", type=float, default=8.0, help="Mic gain multiplier (default: 8.0)")
    parser.add_argument("--output", default="/tmp/voice_chat/utterance.txt", help="Output file")
    parser.add_argument("--silence", type=float, default=2.0, help="Silence timeout to end utterance (s)")
    parser.add_argument("--max-duration", type=float, default=60.0, help="Max recording duration (s)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    text = asyncio.run(capture_utterance(
        server_url=args.server,
        device_index=args.device,
        gain=args.gain,
        silence_timeout=args.silence,
        max_duration=args.max_duration,
    ))

    # Write result
    with open(args.output, "w") as f:
        f.write(text)

    if text:
        print(text)
    else:
        print("(silence)", file=sys.stderr)


if __name__ == "__main__":
    main()

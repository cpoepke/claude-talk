#!/usr/bin/env python3
"""
Voice Cloning A/B Experiment for claude-talk

Generates comparison samples for 5 personalities that need accent work.
Kokoro lacks Irish, Scottish, Australian, and Indian English accents,
so we test CSM-1B and Qwen3-TTS voice cloning using macOS reference voices.

Usage:
    ~/.claude-talk/venvs/wlk/bin/python3 experiments/voice-cloning/generate.py

Output structure per personality:
    reference-<voice>.wav        macOS say reference
    01-kokoro-<voice>.wav        Kokoro baseline (no accent)
    02-csm1b-<voice>-clone.wav   CSM-1B clone attempt
    03-qwen3-<voice>-clone.wav   Qwen3-TTS clone attempt
"""

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

TEST_PHRASE_TEMPLATE = "Hello, I'm {name}. Let me tell you something interesting about the world today."

KOKORO_MODEL = "mlx-community/Kokoro-82M-bf16"
CSM_MODEL = "mlx-community/csm-1b"
QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"

# Whisper model for transcribing reference audio (needed by voice cloning)
STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"


@dataclass
class Personality:
    name: str               # e.g. "Bonnie"
    folder: str             # e.g. "bonnie"
    accent: str             # e.g. "Scottish"
    macos_voice: str        # e.g. "Fiona"
    kokoro_voice: str       # e.g. "bf_emma"
    kokoro_lang: str        # Kokoro lang_code
    results: dict = field(default_factory=dict)  # variant -> {path, latency, status}


PERSONALITIES = [
    Personality("Bonnie",  "bonnie",  "Scottish",       "Fiona", "bf_emma",   "b"),
    Personality("Maeve",   "maeve",   "Irish",          "Moira", "bf_alice",  "b"),
    Personality("Sheila",  "sheila",  "Australian",     "Karen", "af_nova",   "a"),
    Personality("Tash",    "tash",    "Australian",     "Karen", "af_heart",  "a"),
    Personality("Vikram",  "vikram",  "Indian English", "Rishi", "bm_george", "b"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str, level: str = "INFO") -> None:
    print(f"[{level}] {msg}", flush=True)


def timed(func):
    """Decorator that returns (result, elapsed_seconds)."""
    def wrapper(*args, **kwargs):
        t0 = time.time()
        result = func(*args, **kwargs)
        return result, time.time() - t0
    return wrapper


def check_macos_voice(voice_name: str) -> bool:
    """Check if a macOS say voice is available."""
    try:
        result = subprocess.run(
            ["say", "-v", "?"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            # Lines look like: "Fiona (Enhanced)    en_GB_U_SD@sd=gbsct # Hello!"
            if line.strip().startswith(voice_name):
                return True
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Step 1: Generate macOS reference WAVs
# ---------------------------------------------------------------------------

@timed
def generate_reference_wav(personality: Personality) -> Optional[str]:
    """Generate a reference WAV using macOS say command."""
    out_dir = SCRIPT_DIR / personality.folder
    out_dir.mkdir(parents=True, exist_ok=True)

    voice = personality.macos_voice
    out_path = out_dir / f"reference-{voice.lower()}.wav"

    if not check_macos_voice(voice):
        log(f"macOS voice '{voice}' not installed - skipping reference for {personality.name}", "WARN")
        return None

    phrase = TEST_PHRASE_TEMPLATE.format(name=personality.name)
    cmd = ["say", "-v", voice, "-o", str(out_path), "--data-format=LEF32@24000", phrase]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        log(f"Reference WAV: {out_path.name} ({out_path.stat().st_size} bytes)")
        return str(out_path)
    except subprocess.CalledProcessError as e:
        log(f"say command failed for {voice}: {e.stderr}", "ERROR")
        return None


# ---------------------------------------------------------------------------
# Step 2: Kokoro baseline
# ---------------------------------------------------------------------------

@timed
def generate_kokoro(personality: Personality, kokoro_model=None) -> Optional[str]:
    """Generate Kokoro baseline WAV (no accent cloning, just the fallback voice)."""
    from mlx_audio.tts.utils import load_model
    import numpy as np
    from mlx_audio.audio_io import write as audio_write

    out_dir = SCRIPT_DIR / personality.folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"01-kokoro-{personality.kokoro_voice}.wav"

    phrase = TEST_PHRASE_TEMPLATE.format(name=personality.name)

    try:
        if kokoro_model is None:
            kokoro_model = load_model(KOKORO_MODEL)

        audio_chunks = []
        sample_rate = None

        for result in kokoro_model.generate(
            text=phrase,
            voice=personality.kokoro_voice,
            speed=1.0,
            lang_code=personality.kokoro_lang,
        ):
            audio_chunks.append(np.array(result.audio))
            sample_rate = result.sample_rate

        if not audio_chunks:
            log(f"Kokoro produced no audio for {personality.name}", "ERROR")
            return None

        audio = np.concatenate(audio_chunks, axis=0)
        audio_write(str(out_path), audio, sample_rate, format="wav")
        log(f"Kokoro WAV: {out_path.name} ({out_path.stat().st_size} bytes)")
        return str(out_path)

    except Exception as e:
        log(f"Kokoro generation failed for {personality.name}: {e}", "ERROR")
        return None


# ---------------------------------------------------------------------------
# Step 3: CSM-1B voice cloning
# ---------------------------------------------------------------------------

@timed
def generate_csm_clone(personality: Personality, ref_wav: str, csm_model=None) -> Optional[str]:
    """Generate CSM-1B voice clone using the macOS reference WAV."""
    from mlx_audio.tts.utils import load_model
    from mlx_audio.utils import load_audio
    import numpy as np
    from mlx_audio.audio_io import write as audio_write

    out_dir = SCRIPT_DIR / personality.folder
    out_path = out_dir / f"02-csm1b-{personality.macos_voice.lower()}-clone.wav"

    phrase = TEST_PHRASE_TEMPLATE.format(name=personality.name)
    ref_text = TEST_PHRASE_TEMPLATE.format(name=personality.name)

    try:
        if csm_model is None:
            log("Loading CSM-1B model (this may download ~2GB on first run)...")
            csm_model = load_model(CSM_MODEL)

        # Load reference audio at model's sample rate
        ref_audio = load_audio(ref_wav, sample_rate=csm_model.sample_rate)

        audio_chunks = []
        sample_rate = None

        for result in csm_model.generate(
            text=phrase,
            ref_audio=ref_audio,
            ref_text=ref_text,
        ):
            audio_chunks.append(np.array(result.audio))
            sample_rate = result.sample_rate

        if not audio_chunks:
            log(f"CSM-1B produced no audio for {personality.name}", "ERROR")
            return None

        audio = np.concatenate(audio_chunks, axis=0)
        audio_write(str(out_path), audio, sample_rate, format="wav")
        log(f"CSM-1B WAV: {out_path.name} ({out_path.stat().st_size} bytes)")
        return str(out_path)

    except Exception as e:
        log(f"CSM-1B clone failed for {personality.name}: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Step 4: Qwen3-TTS voice cloning
# ---------------------------------------------------------------------------

@timed
def generate_qwen3_clone(personality: Personality, ref_wav: str, qwen_model=None) -> Optional[str]:
    """Generate Qwen3-TTS voice clone using the macOS reference WAV."""
    from mlx_audio.tts.utils import load_model
    from mlx_audio.utils import load_audio
    import numpy as np
    from mlx_audio.audio_io import write as audio_write

    out_dir = SCRIPT_DIR / personality.folder
    out_path = out_dir / f"03-qwen3-{personality.macos_voice.lower()}-clone.wav"

    phrase = TEST_PHRASE_TEMPLATE.format(name=personality.name)
    ref_text = TEST_PHRASE_TEMPLATE.format(name=personality.name)

    try:
        if qwen_model is None:
            log("Loading Qwen3-TTS model (this may download ~1.5GB on first run)...")
            qwen_model = load_model(QWEN3_MODEL)

        # Load reference audio at model's sample rate
        ref_audio = load_audio(ref_wav, sample_rate=qwen_model.sample_rate)

        results = list(qwen_model.generate(
            text=phrase,
            ref_audio=ref_audio,
            ref_text=ref_text,
        ))

        if not results:
            log(f"Qwen3-TTS produced no audio for {personality.name}", "ERROR")
            return None

        audio_chunks = [np.array(r.audio) for r in results]
        audio = np.concatenate(audio_chunks, axis=0)
        sample_rate = results[0].sample_rate
        audio_write(str(out_path), audio, sample_rate, format="wav")
        log(f"Qwen3-TTS WAV: {out_path.name} ({out_path.stat().st_size} bytes)")
        return str(out_path)

    except Exception as e:
        log(f"Qwen3-TTS clone failed for {personality.name}: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(personalities: list) -> str:
    """Print and return a markdown summary table."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("VOICE CLONING EXPERIMENT - RESULTS SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    # Header
    lines.append(f"{'Personality':<12} {'Variant':<28} {'Latency':>10} {'Status':<10} {'File'}")
    lines.append("-" * 90)

    for p in personalities:
        for variant, info in sorted(p.results.items()):
            latency_str = f"{info['latency']:.1f}s" if info['latency'] else "N/A"
            status = info['status']
            fname = Path(info['path']).name if info['path'] else "N/A"
            lines.append(f"{p.name:<12} {variant:<28} {latency_str:>10} {status:<10} {fname}")
        lines.append("")

    summary = "\n".join(lines)
    print(summary)
    return summary


def write_latency_data(personalities: list) -> None:
    """Write latency data to a file for README consumption."""
    out_path = SCRIPT_DIR / "latency.txt"
    with open(out_path, "w") as f:
        f.write("personality,variant,latency_s,status,file\n")
        for p in personalities:
            for variant, info in sorted(p.results.items()):
                latency = f"{info['latency']:.2f}" if info['latency'] else ""
                fname = Path(info['path']).name if info['path'] else ""
                f.write(f"{p.name},{variant},{latency},{info['status']},{fname}\n")
    log(f"Latency data written to {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import mlx.core as mx

    log("Voice Cloning A/B Experiment for claude-talk")
    log(f"Output directory: {SCRIPT_DIR}")
    log("")

    # -----------------------------------------------------------------------
    # Phase 1: macOS reference WAVs
    # -----------------------------------------------------------------------
    log("=== Phase 1: Generating macOS reference WAVs ===")
    ref_wavs = {}  # personality.name -> path

    for p in PERSONALITIES:
        path, elapsed = generate_reference_wav(p)
        ref_wavs[p.name] = path
        p.results["00-reference"] = {
            "path": path,
            "latency": elapsed,
            "status": "OK" if path else "SKIPPED",
        }

    # -----------------------------------------------------------------------
    # Phase 2: Kokoro baselines (load model once, reuse)
    # -----------------------------------------------------------------------
    log("")
    log("=== Phase 2: Generating Kokoro baselines ===")

    kokoro_model = None
    try:
        from mlx_audio.tts.utils import load_model
        log("Loading Kokoro model...")
        kokoro_model = load_model(KOKORO_MODEL)
        log("Kokoro model loaded.")
    except Exception as e:
        log(f"Failed to load Kokoro model: {e}", "ERROR")

    for p in PERSONALITIES:
        if kokoro_model is None:
            p.results["01-kokoro"] = {"path": None, "latency": None, "status": "MODEL_FAIL"}
            continue
        path, elapsed = generate_kokoro(p, kokoro_model=kokoro_model)
        p.results["01-kokoro"] = {
            "path": path,
            "latency": elapsed,
            "status": "OK" if path else "FAILED",
        }

    # Free Kokoro model memory before loading cloning models
    del kokoro_model
    mx.clear_cache()

    # -----------------------------------------------------------------------
    # Phase 3: CSM-1B voice cloning
    # -----------------------------------------------------------------------
    log("")
    log("=== Phase 3: CSM-1B voice cloning ===")

    csm_model = None
    try:
        from mlx_audio.tts.utils import load_model
        log("Loading CSM-1B model (may download on first run)...")
        csm_model = load_model(CSM_MODEL)
        log("CSM-1B model loaded.")
    except Exception as e:
        log(f"Failed to load CSM-1B model: {e}", "ERROR")
        log("CSM-1B will be skipped for all personalities.", "WARN")

    for p in PERSONALITIES:
        ref_path = ref_wavs.get(p.name)
        if csm_model is None:
            p.results["02-csm1b"] = {"path": None, "latency": None, "status": "MODEL_FAIL"}
            continue
        if ref_path is None:
            p.results["02-csm1b"] = {"path": None, "latency": None, "status": "NO_REF"}
            continue

        path, elapsed = generate_csm_clone(p, ref_path, csm_model=csm_model)
        p.results["02-csm1b"] = {
            "path": path,
            "latency": elapsed,
            "status": "OK" if path else "FAILED",
        }

    # Free CSM model memory
    del csm_model
    mx.clear_cache()

    # -----------------------------------------------------------------------
    # Phase 4: Qwen3-TTS voice cloning
    # -----------------------------------------------------------------------
    log("")
    log("=== Phase 4: Qwen3-TTS voice cloning ===")

    qwen_model = None
    try:
        from mlx_audio.tts.utils import load_model
        log("Loading Qwen3-TTS model (may download on first run)...")
        qwen_model = load_model(QWEN3_MODEL)
        log("Qwen3-TTS model loaded.")
    except Exception as e:
        log(f"Failed to load Qwen3-TTS model: {e}", "ERROR")
        log("Qwen3-TTS will be skipped for all personalities.", "WARN")

    for p in PERSONALITIES:
        ref_path = ref_wavs.get(p.name)
        if qwen_model is None:
            p.results["03-qwen3"] = {"path": None, "latency": None, "status": "MODEL_FAIL"}
            continue
        if ref_path is None:
            p.results["03-qwen3"] = {"path": None, "latency": None, "status": "NO_REF"}
            continue

        path, elapsed = generate_qwen3_clone(p, ref_path, qwen_model=qwen_model)
        p.results["03-qwen3"] = {
            "path": path,
            "latency": elapsed,
            "status": "OK" if path else "FAILED",
        }

    del qwen_model
    mx.clear_cache()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print_summary(PERSONALITIES)
    write_latency_data(PERSONALITIES)
    log("Done. Listen to the WAVs and update README.md with your picks!")


if __name__ == "__main__":
    main()

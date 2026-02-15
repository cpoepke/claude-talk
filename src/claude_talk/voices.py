"""macOS voice listing and checking."""

import subprocess


def list_voices() -> list[dict]:
    """Parse `say -v '?'` output into structured list."""
    try:
        output = subprocess.check_output(["say", "-v", "?"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return _parse_voices(output)


def list_enhanced_voices() -> list[dict]:
    """Return only Enhanced/Premium voices."""
    return [v for v in list_voices() if v.get("enhanced")]


def _parse_voices(output: str) -> list[dict]:
    """Parse say -v '?' output lines."""
    voices = []
    for line in output.strip().splitlines():
        # Format: "Name                lang  # sample text"
        parts = line.split("#", 1)
        name_lang = parts[0].strip()
        sample = parts[1].strip() if len(parts) > 1 else ""

        # Split name from language code — language is the last whitespace-separated token
        tokens = name_lang.rsplit(None, 1)
        if len(tokens) == 2:
            name, lang = tokens
        else:
            name = name_lang
            lang = ""

        enhanced = "(Enhanced)" in name or "(Premium)" in name
        voices.append({
            "name": name.strip(),
            "lang": lang.strip(),
            "sample": sample,
            "enhanced": enhanced,
        })
    return voices

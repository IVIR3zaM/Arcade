"""Text-to-speech via Piper (the Phase 8 TTS choice; fast, has EN + DE voices).

We shell out to the `piper` CLI, which is the most stable interface across
piper-tts releases: text on stdin, a WAV file out. One voice model per language,
baked into the image.
"""

import os
import subprocess
import tempfile

# Voice models fetched into the cached volume on first run (see entrypoint.sh).
_VOICES_DIR = os.environ.get("VOICES_DIR", "/models/voices")
_VOICES = {
    "en": f"{_VOICES_DIR}/en_US-kristin-medium.onnx",
    "de": f"{_VOICES_DIR}/de_DE-eva_k-x_low.onnx",
    "fa": f"{_VOICES_DIR}/fa_IR-amir-medium.onnx",
}


def synthesize(text: str, language: str = "en") -> bytes:
    """Render `text` to spoken WAV bytes in the given language."""
    model = _VOICES.get(language, _VOICES["en"])
    with tempfile.NamedTemporaryFile(suffix=".wav") as out:
        subprocess.run(
            ["piper", "--model", model, "--output_file", out.name],
            input=text.encode("utf-8"),
            check=True,
            capture_output=True,
        )
        out.seek(0)
        return out.read()

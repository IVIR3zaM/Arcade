"""Text-to-speech via Piper (the Phase 8 TTS choice; fast, EN + DE voices).

The voice model is loaded ONCE and kept resident in this process — exactly like
the LLM. Previously every reply shelled out to the `piper` CLI, which respawns a
process and reloads the ONNX voice each time; on the throttled Pi-class CPU that
fixed overhead was a big slice of the 2-4s we measured per reply. Now the first
reply loads the voice and every reply after is a fast in-process inference. The
CLI path is kept as a safety-net fallback if the Python API isn't available.
"""

import io
import os
import subprocess
import tempfile
import wave

# Voice models fetched into the cached volume on first run (see entrypoint.sh).
_VOICES_DIR = os.environ.get("VOICES_DIR", "/models/voices")
_VOICES = {
    # 'low' tier: noticeably faster to synthesize than 'medium', still clear.
    "en": f"{_VOICES_DIR}/en_US-lessac-low.onnx",
    "de": f"{_VOICES_DIR}/de_DE-eva_k-x_low.onnx",
}

_loaded: dict = {}  # model path -> PiperVoice, kept resident across replies

# Cache synthesized WAVs, keyed by (language, text). Many replies are fixed lines
# — "Sorry, I didn't catch that" (every mishear), goodbyes, "English it is!" — so
# their second use (this session or the next, since the cache lives as long as the
# process) is instant. Bounded so a long session can't grow it without limit.
_CACHE_MAX = 128
_cache: "dict[tuple[str, str], bytes]" = {}


def _voice(language: str):
    """Load (once) and return the resident PiperVoice for a language."""
    path = _VOICES.get(language, _VOICES["en"])
    if path not in _loaded:
        from piper import PiperVoice  # imported lazily so tests never need piper

        _loaded[path] = PiperVoice.load(path)
    return _loaded[path]


def _synthesize_resident(text: str, language: str) -> bytes:
    """Synthesize with the in-RAM voice (fast path)."""
    voice = _voice(language)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        # piper-tts renamed this across versions; support both.
        if hasattr(voice, "synthesize_wav"):
            voice.synthesize_wav(text, wav_file)
        else:
            voice.synthesize(text, wav_file)
    return buf.getvalue()


def _synthesize_cli(text: str, language: str) -> bytes:
    """Fallback: the piper CLI (slower — reloads the model each call)."""
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


def synthesize(text: str, language: str = "en") -> bytes:
    """Render `text` to spoken WAV bytes in the given language (cached by text)."""
    key = (language, text)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    try:
        audio = _synthesize_resident(text, language)
    except Exception:
        audio = _synthesize_cli(text, language)
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))  # evict oldest (insertion order)
    _cache[key] = audio
    return audio


def warmup() -> None:
    """Preload both voices (best-effort) so the FIRST reply doesn't stall on a
    cold model load. Called at app startup, inside the serving process."""
    for lang in ("de", "en"):
        try:
            _synthesize_resident("ok", lang)
        except Exception:
            pass

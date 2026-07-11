"""Speech-to-text via faster-whisper (the whisper.cpp family, CPU int8).

Mirrors Phase 8's STT choice while staying easy to install in the image. The
model is loaded once and reused. Kept behind one small function so the pure logic
never depends on it.
"""

import os

from faster_whisper import WhisperModel

# 'base' is multilingual (EN + DE) and small enough to feel Pi-like on CPU.
_MODEL_NAME = os.environ.get("WHISPER_MODEL", "base")
# Pin transcription threads to the CPU quota, exactly as the LLM does. Otherwise
# faster-whisper sees ALL host cores and spawns that many threads, which then
# fight the container's CFS throttle instead of mirroring the Pi's 4 cores.
_CPU_THREADS = int(os.environ.get("COMPANION_NUM_THREAD", "4"))

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            _MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=_CPU_THREADS
        )
    return _model


def transcribe(
    wav_path: str, language: str | None = None, initial_prompt: str | None = None
) -> tuple[str, str, float]:
    """Transcribe a WAV file. Returns (text, detected_language, probability).

    `language=None` lets whisper AUTO-DETECT the spoken language — essential for
    a bilingual cabinet: forcing 'de' makes whisper mangle English speech into
    German gibberish instead of transcribing it. `initial_prompt` biases decoding
    toward the arcade's real game + people names so it stops mishearing them
    (e.g. "Pong" instead of "Point").
    """
    segments, info = _get_model().transcribe(
        wav_path, language=language, initial_prompt=initial_prompt, beam_size=1
    )
    text = "".join(segment.text for segment in segments).strip()
    return text, info.language, info.language_probability

"""Speech-to-text via faster-whisper (the whisper.cpp family, CPU int8).

Mirrors Phase 8's STT choice while staying easy to install in the image. The
model is loaded once and reused. Kept behind one small function so the pure logic
never depends on it.
"""

import os

from faster_whisper import WhisperModel

# 'tiny' (multilingual: EN + DE) — ~2x faster than 'base' on a Pi-class CPU. The
# name/game initial_prompt bias offsets much of the accuracy loss. Override with
# WHISPER_MODEL=base for higher accuracy at more latency.
_MODEL_NAME = os.environ.get("WHISPER_MODEL", "tiny")
# Pin transcription threads to the CPU quota, exactly as the LLM does. Otherwise
# faster-whisper sees ALL host cores and spawns that many threads, which then
# fight the container's CFS throttle instead of mirroring the Pi's 4 cores.
_CPU_THREADS = int(os.environ.get("COMPANION_NUM_THREAD", "4"))

# The cabinet speaks these two, and ONLY these two, are allowed as transcription
# languages. Free auto-detect across all ~99 whisper languages was the worst
# latency spike we saw: on foreign or garbled speech it would lock onto Arabic
# or Polish and burn 6-9s decoding hallucinated text. We clamp to EN/DE.
_SUPPORTED = ("en", "de")

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            _MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=_CPU_THREADS
        )
    return _model


def _load_audio(wav_path: str):
    """Decode the WAV once so detection and transcription can share it."""
    try:
        from faster_whisper.audio import decode_audio

        return decode_audio(wav_path, sampling_rate=16000)
    except Exception:
        return None  # fall back to the file path + auto-detect


def _detect_en_or_de(model: WhisperModel, audio) -> str:
    """Pick EN or DE — never a third language — from a cheap detection pass.

    This is the key latency fix: we decide the language BEFORE decoding, so a
    non-EN/DE utterance is decoded as the more-likely of the two (fast, ~1.8s)
    instead of whisper wandering off into Arabic/Polish (6-9s of garbage)."""
    try:
        _lang, _prob, all_probs = model.detect_language(audio)
        probs = dict(all_probs)
        return "en" if probs.get("en", 0.0) >= probs.get("de", 0.0) else "de"
    except Exception:
        return "de"  # cabinet default; keeps working if the API differs


def transcribe(
    wav_path: str, language: str | None = None, initial_prompt: str | None = None
) -> tuple[str, str, float]:
    """Transcribe a WAV file. Returns (text, language, probability).

    The language is LOCKED to EN or DE (see `_SUPPORTED`): we run a cheap
    detection, clamp it to the better of the two, then decode in that language.
    Forcing a single language mangles the other, so we can't just pin 'de' — but
    clamping to the two we support keeps English working while eliminating the
    slow, garbage decodes free auto-detect produced on foreign speech.
    `initial_prompt` biases decoding toward the arcade's game + people names.
    """
    model = _get_model()
    audio = _load_audio(wav_path)
    if language is None:
        language = _detect_en_or_de(model, audio) if audio is not None else None
    segments, info = model.transcribe(
        audio if audio is not None else wav_path,
        language=language,
        initial_prompt=initial_prompt,
        beam_size=1,
    )
    text = "".join(segment.text for segment in segments).strip()
    return text, info.language, info.language_probability

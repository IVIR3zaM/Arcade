# The "Pi box": ONE container that mirrors the cabinet's Raspberry Pi 5 (8GB).
# Everything the on-device companion needs runs here and shares a single budget —
# the local LLM (Ollama), whisper STT, Piper TTS, the deterministic brief, and the
# HTTP API — exactly like the Pi runs them all on one board. docker-compose caps
# this container at 4 CPUs / 8GB so the pieces contend for the same pool the Pi
# gives them.
#
# OS: python:3.12-slim-bookworm is Debian 12 Bookworm arm64 — the same base as
# Raspberry Pi OS (Bookworm) — and runs natively as linux/arm64 on Apple Silicon,
# the Pi's architecture.
#
# HONEST CAVEAT: CPU *count* and RAM match the Pi, but an Apple-Silicon core is
# ~2-3x a Pi 5 core in clock/IPC, and Docker can't slow a core to Pi speed. So
# latency/tokens-per-second here are an OPTIMISTIC upper bound; real performance
# is the Phase 8.9 hardware checkpoint. This box is for the *experience*.
#
# The AI models (Ollama LLM, whisper, Piper voices) are NOT baked in — they're
# fetched on first run into a cached volume (see entrypoint.sh), the same way the
# Ollama model is pulled. That keeps this image build small, portable, and free of
# any single model host, and defers the one-time download to your own network.
FROM python:3.12-slim-bookworm

# curl to fetch voices at runtime + install Ollama (whose installer unpacks a zstd
# archive); ffmpeg is faster-whisper's audio backend; espeak-ng data backs Piper's
# phonemization.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl zstd ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Ollama, installed into the image (arm64 binary, like the Pi). It runs as a local
# server inside this same container — no second container, one shared budget.
RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /app
COPY brain/requirements-brain.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY brain/ ./brain/
COPY brain/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
# Starts Ollama, fetches the model + whisper + voices (cached), then serves the API.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

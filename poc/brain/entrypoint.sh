#!/usr/bin/env bash
# Boot the whole Pi box in one process tree: Ollama's local server, then a one-time
# fetch of the AI models (LLM + whisper + Piper voices) into the cached volume, then
# the brain API. Everything shares this container's 4-core / 8GB budget, like the Pi.
#
# The model fetches need network the first time (Ollama registry + Hugging Face);
# after that they're served from the mounted volume and startup is fast.
set -euo pipefail

MODEL="${COMPANION_MODEL:-qwen2.5:3b}"
VOICES_DIR="${VOICES_DIR:-/models/voices}"
VOICES_BASE="${VOICES_BASE_URL:-https://huggingface.co/rhasspy/piper-voices/resolve/main}"

echo "[pi-box] starting Ollama..."
ollama serve &

echo "[pi-box] waiting for Ollama..."
until ollama list >/dev/null 2>&1; do sleep 1; done

# Idempotent: after the first pull the model is cached in the mounted volume.
echo "[pi-box] ensuring LLM '$MODEL' (first run downloads ~2GB)..."
ollama pull "$MODEL"

# Piper voices (EN default + DE). Downloaded once into the cached volume.
echo "[pi-box] ensuring Piper voices in $VOICES_DIR..."
mkdir -p "$VOICES_DIR"
fetch_voice() {
    local rel="$1" name="$2"
    if [ ! -s "$VOICES_DIR/$name" ]; then
        curl -fL -o "$VOICES_DIR/$name" "$VOICES_BASE/$rel/$name"
        curl -fL -o "$VOICES_DIR/$name.json" "$VOICES_BASE/$rel/$name.json"
    fi
}
fetch_voice "en/en_US/kristin/medium" "en_US-kristin-medium.onnx"
fetch_voice "de/de_DE/eva_k/x_low" "de_DE-eva_k-x_low.onnx"
fetch_voice "fa/fa_IR/amir/medium" "fa_IR-amir-medium.onnx"

# Warm the whisper model into the cache (HF_HOME points into the volume) so the
# first transcription doesn't stall.
echo "[pi-box] ensuring whisper model..."
python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL:-base}', device='cpu', compute_type='int8')"

# Pre-load the LLM into RAM (keep_alive -1 keeps it resident) so the FIRST person
# who walks up doesn't wait ~10s for a cold model load.
echo "[pi-box] warming up the LLM ($MODEL)..."
curl -s http://localhost:11434/api/generate \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"hi\",\"stream\":false,\"keep_alive\":-1}" >/dev/null || true

echo "[pi-box] starting the brain API on :8000"
exec uvicorn brain.app:app --host 0.0.0.0 --port 8000

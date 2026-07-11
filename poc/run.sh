#!/usr/bin/env bash
# One command to try the arcade AI companion on your MacBook.
#
#   ./run.sh
#
# It brings up the single Pi-like container (Ollama + whisper + Piper + brain, all
# sharing a throttled CPU / 8GB budget sized to approximate the Pi), then sets up a
# tiny host-side venv for the mic/speaker CLI and hands you the scenario picker.
set -euo pipefail

cd "$(dirname "$0")"

BRAIN_URL="${BRAIN_URL:-http://localhost:8080}"

echo "==> Building and starting the Pi box (Ollama + brain in one container)..."
docker compose up -d --build

echo "==> Waiting for the Pi box to be ready."
echo "    (first run pulls the model ~2GB inside the container — this can take a while)"
until curl -sf "$BRAIN_URL/health" >/dev/null 2>&1; do sleep 3; done

echo "==> Setting up the host mic/speaker CLI..."
# Kept OUTSIDE the repo so it doesn't pollute the tree (cairn verify would scan a
# venv living under poc/). Override with POC_VENV if you like.
VENV="${POC_VENV:-$HOME/.cache/arcade-poc-venv}"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r host/requirements-host.txt

echo "==> Ready. Starting the companion."
echo
BRAIN_URL="$BRAIN_URL" python3 host/companion.py

echo
echo "The Pi box is still running. Stop it with:  docker compose -f $(pwd)/docker-compose.yml down"

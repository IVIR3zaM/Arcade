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
echo "    Live: elapsed time · container RAM (used / limit, % of the 8GB cap) · current step"

start=$(date +%s)
stats="starting…"
phase=""
i=0
until curl -sf "$BRAIN_URL/health" >/dev/null 2>&1; do
  elapsed=$(( $(date +%s) - start ))
  # The docker calls are ~1-2s each, so refresh RAM + phase every ~4th tick and
  # keep the seconds counter ticking every second in between.
  if (( i % 4 == 0 )); then
    cid="$(docker compose ps -q pi-box 2>/dev/null || true)"
    if [ -n "$cid" ]; then
      stats="$(docker stats --no-stream --format '{{.MemUsage}} ({{.MemPerc}} of cap)' "$cid" 2>/dev/null || echo 'n/a')"
    fi
    phase="$(docker compose logs --tail 30 pi-box 2>/dev/null | grep -aoE '\[pi-box\].*' | tail -1 || true)"
    phase="${phase#*] }"          # drop the "[pi-box] " tag
    phase="${phase:0:64}"          # keep the status line from wrapping
  fi
  printf '\r    ⏳ %3ds · RAM %s · %s\033[K' "$elapsed" "$stats" "${phase:-booting…}"
  sleep 1
  i=$(( i + 1 ))
done
printf '\r    ✓ Pi box ready in %ds · RAM %s\033[K\n' "$(( $(date +%s) - start ))" "$stats"

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

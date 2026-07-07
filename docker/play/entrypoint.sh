#!/bin/sh
# Bring up a headless X desktop that is viewable over VNC, then run the given
# command inside it. This lets a Mac host actually SEE RetroArch running in the
# Linux container (connect a VNC viewer to localhost:5900). Dev/test only.
set -e

: "${DISPLAY:=:99}"
export DISPLAY

# Virtual framebuffer — a real X server with no physical monitor.
Xvfb "$DISPLAY" -screen 0 1280x720x24 &

# Wait for the X server to accept connections before starting anything on it.
for _ in $(seq 1 50); do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done

# A light window manager so windows get borders/focus, and the VNC server.
fluxbox >/dev/null 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -nopw -rfbport 5900 -bg -quiet

exec "$@"

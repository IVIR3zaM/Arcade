# Arcade

A home-built retro arcade cabinet for the kids. Wood cabinet, a Raspberry Pi 5
inside, one screen, a two-player joystick/button panel, and a dead-simple
gallery of games. Kids see cover art, pick a game with the stick or a gamepad,
and play. No menus. No file managers. No drama.

## What it does

- Boots straight into a fullscreen **gallery**: a grid of game cover art, each
  with its title and a small console label (Atari, Sega, NES, SNES, N64, PS1).
- Kids navigate with the arcade stick or a Bluetooth gamepad and press a button
  to launch.
- The selected game runs in the right emulator. When they quit, they land back
  in the gallery.
- Games are added over the network from a MacBook via a small **REST API** —
  upload the ROM, the cover art, and the metadata, and it shows up in the
  gallery. No Samba, no SD-card shuffling.

## Hardware

| Part | Choice |
| --- | --- |
| Computer | Raspberry Pi 5, 4GB |
| OS | Raspberry Pi OS 64-bit **Lite** (no desktop) |
| Storage | USB SSD (boot from USB, not SD card) |
| Display | Samsung 27" 1080p, single monitor over HDMI |
| Controls | Two-player arcade joystick + buttons via USB zero-delay encoder |
| Optional controls | Bluetooth gamepad |
| Audio | HDMI audio (monitor speakers) or a small amp — TBD during the build |

## Software stack

- **Emulation layer**
  - **RetroArch** with cores for Atari, Sega, and Nintendo systems
    (NES/SNES/N64).
  - **DuckStation** for PlayStation 1.
  - Both are launched as separate processes by the launcher — the launcher does
    not embed them.
- **Launcher (the app we're building)** — Python + Pygame. The fullscreen
  gallery/frontend. Reads game metadata from SQLite, draws the grid, handles
  controller input, and shells out to the right emulator.
- **Game library API** — FastAPI service exposing REST endpoints to add, list,
  and remove games (ROM + cover art + metadata). Writes to the same SQLite
  database and file storage the launcher reads from.
- **SQLite** — single database file holding game metadata (title, console,
  cover art path, ROM path, emulator/core to use).
- **Temperature watchdog** — a standalone systemd service that reads CPU temp
  (`vcgencmd`), and if the Pi overheats, gracefully kills the running emulator
  and shuts the Pi down. Runs independently of the launcher so it protects the
  hardware even if the launcher has crashed or hung.
- **Tailscale** — for SSH access from the MacBook. Starlink puts us behind
  CGNAT, so Tailscale is how we reach the Pi remotely.

### Experimental (not part of the core build)

- **Box64 + Wine** to try one specific old Windows game (**Hard Truck 2**) as a
  one-off. Kept isolated from the main system. It only gets added to the gallery
  if it actually runs acceptably on the Pi. If it doesn't, we drop it and move
  on — it is not allowed to complicate the rest of the system.

## Scope (read this before adding "just one more thing")

This is a **single-monitor, one-emulator-at-a-time** build. We explicitly
considered and **rejected** a dual-monitor, multi-mode (mirror/split/
independent) setup with a GPIO rotary switch. Do not design around that. One
screen, one game running at a time, keep it simple.

## How it's built (iteratively)

We build this in phases, playable-first: a **CLI proof-of-concept** comes first
(prove a game launches), then a **SQLite library**, then the **temperature
watchdog** and **REST API**, and the **Pygame gallery GUI last**. See
[ITERATIONS.md](ITERATIONS.md) for the ordered task list and
[PROMPT.md](PROMPT.md) for how an AI agent should work through it.

## Repository layout

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full breakdown. In short:

```
launcher/     Pygame gallery frontend
api/          FastAPI game-library service
shared/       Code both use (SQLite access, models, paths)
hardware/     Hardware-dependent adapters (vcgencmd, GPIO if ever needed)
watchdog/     Temperature-monitoring systemd service
tests/        Tests — run these off-device
data/         SQLite DB + ROMs + cover art (git-ignored, lives on the SSD)
```

## Getting started

> The build is early. These steps describe the intended setup and will be
> filled in with exact commands as the code lands.

### 1. Develop and test on the MacBook first

Most of the software can be built and tested **without a Pi**. The M1 Mac and
the Pi are both ARM64, so we run the actual Raspberry Pi OS 64-bit in a VM.

- **UTM (QEMU ARM64 VM)** running real Raspberry Pi OS 64-bit is the main dev
  target. Install the stack there, run the launcher and the API, exercise the
  full flow.
- **Plain Python on the Mac / in Docker** is enough for the hardware-independent
  parts: the API, the SQLite schema, game metadata, and the launcher's UI logic.
  Hardware-dependent pieces (temperature reads, any GPIO, real display/gamepad
  behavior) are stubbed with mocks here — see [AGENTS.md](AGENTS.md) and
  [ARCHITECTURE.md](ARCHITECTURE.md).

Typical local loop:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# run the tests (no hardware needed)
pytest

# run the API locally
uvicorn api.main:app --reload

# run the launcher against fake/mock hardware
ARCADE_ENV=dev python -m launcher
```

### 2. What can only be verified on real hardware

These cannot be trusted in a VM and must be checked on an actual Pi:

- GPIO reads (if any are ever added)
- Real display behavior at 1080p over HDMI
- Real USB gamepad / zero-delay encoder behavior
- Real emulator performance (frame rates, audio sync, especially N64/PS1)
- CPU temperature behavior under sustained load, and the watchdog acting on it

### 3. Deploy to the Pi

1. Flash Raspberry Pi OS 64-bit Lite to the USB SSD, set the Pi to boot from
   USB.
2. Install RetroArch (+ cores) and DuckStation.
3. Install Tailscale and join the tailnet for remote SSH from the MacBook.
4. Deploy the launcher, API, and watchdog; install the watchdog and launcher as
   systemd services.
5. Copy the game library (ROMs + cover art + SQLite DB) onto the SSD, or add
   games over the API.
6. Boot — the Pi should come straight up into the gallery.

Exact commands and service files will be documented here as they're written.

## License

Licensed under the **Apache License 2.0** — see [LICENSE](LICENSE).

Copyright 2026 Reza Maghoul.

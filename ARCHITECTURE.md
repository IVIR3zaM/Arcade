# Architecture

This describes how the Arcade software fits together, and — importantly — where
the line sits between code that needs real Pi hardware and code that doesn't, so
almost everything can be built and tested in UTM or Docker before touching the
cabinet.

Read [AGENTS.md](AGENTS.md) for how we write the code. This document is about
_what_ the pieces are and how they talk.

## Big picture

There are four independent programs plus a shared core:

1. **Launcher** (Pygame) — the fullscreen gallery the kids see and use.
2. **Library API** (FastAPI) — how games get added/listed/removed over the
   network from the MacBook.
3. **Temperature watchdog** (systemd service) — protects the hardware, runs on
   its own.
4. **Emulators** (RetroArch, DuckStation) — external processes the launcher
   starts.

They are deliberately decoupled. The launcher and the API never call each other
directly — they communicate only through the **SQLite database** and the
**file storage** on disk. The watchdog talks to nobody; it reads temperature and
acts on the OS/processes directly. This keeps each piece simple and separately
testable.

```
   MacBook                          Raspberry Pi 5
 ┌─────────┐   HTTP (Tailscale)   ┌───────────────────────────────────┐
 │ browser │ ───────────────────▶ │  FastAPI Library API              │
 │ / curl  │                      │   writes ROMs + art + metadata    │
 └─────────┘                      └───────────────┬───────────────────┘
                                                  │ writes
                                    ┌─────────────▼─────────────┐
                                    │  SQLite DB  +  file store │
                                    └─────────────▲─────────────┘
                                                  │ reads
                                  ┌───────────────┴───────────────┐
                                  │  Pygame Launcher (gallery)    │
                                  │   draws grid, reads controls  │
                                  │   launches emulator process   │
                                  └───────────────┬───────────────┘
                                                  │ subprocess
                              ┌───────────────────▼───────────────────┐
                              │  RetroArch (cores)  /  DuckStation     │
                              └────────────────────────────────────────┘

   Independent, always running:
                              ┌────────────────────────────────────────┐
                              │  Temperature Watchdog (systemd)         │
                              │   reads vcgencmd → kills emu / shutdown  │
                              └────────────────────────────────────────┘
```

## Components

### Launcher (`launcher/`)

Python + Pygame. Responsibilities, and nothing more:

- On start, read the list of games from SQLite via the shared data layer.
- Draw the gallery: a grid of cover art, each cell showing the title and a small
  console label.
- Read controller input (arcade stick / buttons via the USB encoder, or a
  Bluetooth gamepad) to move the selection and launch.
- On launch, look up the game's emulator/core + ROM path, build the command, and
  run the emulator as a subprocess. Block until it exits, then redraw the
  gallery.

The launcher is a normal loop: read input → update selection → draw. It does not
manage the library (that's the API's job) and does not embed the emulators.

**Hardware-dependent parts of the launcher** (real display, real controller
USB/Bluetooth behavior) are reached through small adapters so the pure UI logic
— selection movement, which game maps to which command, gallery paging — can be
unit-tested with no display and a fake input source.

### Library API (`api/`)

FastAPI. This is the only way games enter or leave the library, replacing Samba
and manual file copying. Endpoints (initial set — add only what's actually
needed):

- `GET /games` — list all games (metadata).
- `POST /games` — add a game: upload ROM + cover art, plus metadata (title,
  console, which emulator/core). The API stores the files under the file store
  and inserts a row in SQLite.
- `DELETE /games/{id}` — remove a game: delete its row and its files.

The API is entirely hardware-independent. It runs and is fully testable on the
Mac or in Docker with a temp directory and a temp SQLite file.

### Shared core (`shared/`)

Code both the launcher and the API depend on, so the two never drift:

- **Data access** — open the SQLite DB, and the small set of functions to
  list/insert/delete games. One place that knows the schema.
- **Models** — a plain `Game` representation (e.g. a dataclass) passed around
  instead of raw rows/dicts.
- **Paths** — where the DB, ROMs, and cover art live. Single source of truth,
  overridable in tests so nothing writes to the real store.

Keeping this shared avoids two copies of the schema and two ideas of where files
live. This is a real, present-day dedup — not a speculative abstraction.

### Emulator invocation layer (`shared/` or `launcher/`)

A small, pure function that takes a `Game` and returns the command to run:

```
game (console + core + rom path)  ->  ["retroarch", "-L", core, rom]
game (PS1)                        ->  ["duckstation", ..., rom]
```

Because it returns a command (a list of strings) rather than immediately
executing, it is trivially unit-testable: assert the right command for each
console/core without launching anything. A separate, thin "run this command and
wait" function does the actual subprocess call — that thin part is the only
piece that needs a real emulator present, and it's stubbed in tests.

### Temperature watchdog (`watchdog/`)

A standalone script installed as a **systemd service**, independent of the
launcher on purpose — it must protect the Pi even if the launcher has crashed.

Loop: read CPU temp → if over the threshold, gracefully terminate any running
emulator and shut the Pi down.

- **Reading the temperature is hardware-dependent** (`vcgencmd measure_temp`).
  That read sits behind a single function/interface. In tests and in UTM we
  inject a fake temperature source and can drive the "too hot → shut down" logic
  with no real sensor. The decision logic itself is pure and fully testable.

### Emulators (external)

RetroArch (with cores for Atari/Sega/Nintendo) and DuckStation (PS1). Installed
on the Pi, launched by the launcher as subprocesses. Not part of our codebase;
we only build commands for them.

### Experimental: Box64 + Wine (isolated)

Trying one Windows game (Hard Truck 2) via Box64 + Wine is kept **isolated** and
out of the core architecture. If it ends up working acceptably, it appears in the
gallery as just another `Game` whose emulator command happens to be the Box64/
Wine invocation — i.e. it reuses the existing invocation layer and nothing
special is added to the launcher. If it doesn't work, it's dropped with zero
impact on the rest of the system.

## SQLite schema

One table to start. Add columns/tables only when a real feature needs them.

```sql
CREATE TABLE games (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    console     TEXT    NOT NULL,   -- 'Atari', 'Sega', 'NES', 'SNES', 'N64', 'PS1'
    emulator    TEXT    NOT NULL,   -- 'retroarch' | 'duckstation'
    core        TEXT,               -- RetroArch core name; NULL for DuckStation
    rom_path    TEXT    NOT NULL,   -- path under the file store
    cover_path  TEXT    NOT NULL    -- path under the file store
);
```

- `console` drives the small label under the cover art.
- `emulator` + `core` are what the invocation layer uses to build the command.
- `rom_path` / `cover_path` point into the file store (below), not arbitrary
  absolute paths from the uploader.

## File storage layout

Lives on the USB SSD, git-ignored. The API writes here; the launcher reads here.

```
data/
  arcade.db            SQLite database
  roms/                uploaded ROM files
  covers/              uploaded cover art
```

The `shared/` paths module is the one place that knows these locations, and
tests point it at a temp directory.

## Data flow: from "uploaded" to "playable"

1. From the MacBook (over Tailscale), a `POST /games` sends the ROM file, the
   cover image, and the metadata (title, console, emulator, core).
2. The API saves the ROM into `data/roms/`, the cover into `data/covers/`, and
   inserts a `games` row via the shared data layer, storing the two paths.
3. Next time the launcher reads the game list (on start, or on refresh), the new
   row is there. It draws the new cover + title + console label in the grid.
4. A kid selects it and presses the button.
5. The launcher loads that `Game`, the invocation layer turns it into a command
   (`retroarch -L <core> <rom>` or the DuckStation equivalent), and the run
   function launches the emulator as a subprocess.
6. The emulator runs fullscreen on the single HDMI display. On exit, control
   returns to the launcher loop and the gallery reappears.

Throughout, the watchdog is independently sampling CPU temp and will kill the
emulator and shut down if the Pi overheats — regardless of what the launcher is
doing.

## Hardware-dependent vs. hardware-independent

This split is the point of the whole design: keep the hardware-touching surface
tiny and behind swappable functions, so the bulk of the system is testable in
UTM/Docker/plain Python.

**Hardware-independent (test anywhere — Mac, Docker, CI):**

- The FastAPI service and all its endpoints.
- The SQLite schema and the shared data-access functions.
- The `Game` model and metadata handling.
- The emulator invocation layer (building the command list).
- Launcher UI logic: selection movement, paging, mapping a selection to a game
  and command.
- The watchdog's decision logic (given a temperature, decide whether to act).

**Hardware-dependent (verify on a real Pi):**

- Reading CPU temperature (`vcgencmd`).
- GPIO reads — none are currently needed; if any are ever added, they go behind
  the same kind of adapter.
- Real display behavior at 1080p over HDMI.
- Real USB zero-delay encoder and Bluetooth gamepad input.
- Real emulator performance and audio sync (especially N64 and PS1).
- Actually terminating the emulator process and shutting the Pi down.

**How the split is enforced in code:** each hardware-dependent piece is a small
function or interface (e.g. a "read temperature" function, a "run this command"
function, an input source). Tests and the UTM/dev environment inject a fake;
the Pi uses the real one. The mechanism is just a constructor argument or a
simple conditional keyed off an env flag (e.g. `ARCADE_ENV`) — **not** a plugin
framework. See [AGENTS.md](AGENTS.md).

## Deployment shape on the Pi

- `launcher` — systemd service (or an autostart) that runs on boot and brings up
  the gallery fullscreen.
- `api` — a service (uvicorn) reachable over Tailscale for library management.
- `watchdog` — its own systemd service, started at boot, independent of the
  launcher.
- `data/` — on the USB SSD.

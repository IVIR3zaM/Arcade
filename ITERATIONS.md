# Iterations

The plan for getting Arcade from nothing to a fully working cabinet, built
**iteratively**. The order is deliberate: get something playable as fast as
possible (a CLI proof-of-concept), then grow outward. The pretty GUI gallery and
the network API come **later** — they are not needed to prove a kid can launch a
game.

Guiding rule: **each phase ends with something that actually works and is
tested.** Don't start a later phase until the current one runs. Follow
[AGENTS.md](AGENTS.md) throughout — TDD, KISS/YAGNI, keep the stack.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done.

---

## Phase 0 — Project skeleton

Just enough to hold code and run tests. No features yet.

- [x] `[x]` Create the repo layout: `launcher/`, `api/`, `shared/`,
  `watchdog/`, `tests/`, `data/` (git-ignored).
- [x] `[x]` Add `.gitignore` (`.venv/`, `__pycache__/`, `data/`, `*.db`).
- [x] `[x]` Add `requirements.txt` (start empty; add deps only when a phase
  needs them).
- [x] `[x]` Set up `pytest` and confirm an empty test suite runs green.
- [x] `[x]` Add a `Makefile` or a couple of scripts: `test`, `run-cli`.

**Done when:** `pytest` runs (with zero or one trivial test) on the Mac.

---

## Phase 1 — CLI proof-of-concept (make it playable)

The fastest path to "a game launches." No GUI, no API, no network. A text list
in the terminal, pick a number, the emulator starts. This proves the hard part:
that we can drive RetroArch/DuckStation correctly.

- [x] `[x]` `shared/models.py`: a `Game` dataclass (title, console, emulator,
  core, rom_path, cover_path). *Test first.*
- [x] `[x]` Emulator invocation layer: pure function `build_command(game) ->
  list[str]` for RetroArch (`retroarch -L <core> <rom>`) and DuckStation.
  *Test first — assert exact command per console/core; no launching.*
- [x] `[x]` `run_game(command)`: thin subprocess wrapper that runs and waits.
  Kept separate from `build_command` so the pure part stays testable; the
  subprocess call is stubbed in tests.
- [x] `[x]` A hardcoded/seeded in-memory list of a few `Game`s to start (no DB
  yet — YAGNI).
- [ ] `[ ]` CLI entrypoint (`python -m launcher.cli`): print numbered list of
  games with console labels, read a number from stdin, launch it, return to the
  list on exit.
- [ ] `[ ]` Verify end-to-end **in UTM** with real RetroArch + a test ROM: pick
  a game, it launches, quit returns to the list.
- [ ] `[ ]` Verify **on real Pi hardware**: one game per system boots and is
  playable at acceptable performance (this is the first real-hardware checkpoint;
  N64/PS1 are the risky ones).

**Done when:** on the Pi, you can run one command, pick a game from a text menu,
and play it, for at least one title per console.

---

## Phase 2 — SQLite-backed library

Replace the hardcoded game list with a real database, still driven from the CLI.

- [ ] `[ ]` Define the `games` table (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- [ ] `[ ]` `shared/paths.py`: single source of truth for DB / roms / covers
  locations, overridable in tests.
- [ ] `[ ]` `shared/db.py`: `list_games()`, `add_game(...)`, `remove_game(id)`.
  *Test first, against a temp SQLite file.*
- [ ] `[ ]` Point the CLI at `list_games()` instead of the hardcoded list.
- [ ] `[ ]` A tiny seed/import script to load existing ROMs + metadata into the
  DB (manual for now — the API comes in Phase 4).
- [ ] `[ ]` Verify the CLI still launches games, now reading from SQLite.

**Done when:** the CLI plays games listed from the SQLite database.

---

## Phase 3 — Temperature watchdog

The hardware-protection service. Doesn't depend on the GUI, so it can land early
and run independently.

- [ ] `[ ]` Pure logic: `should_shut_down(temp_c, threshold_c)`. *Test first.*
- [ ] `[ ]` `parse_temp(output)` for `vcgencmd measure_temp`. *Test first with
  sample strings.*
- [ ] `[ ]` `read_temp_c()`: the one hardware-touching function (calls
  `vcgencmd`).
- [ ] `[ ]` `watchdog_tick(read_temp=..., threshold_c=...)`: inject the reader;
  on overheat, terminate the running emulator, then shut down. *Test with a fake
  reader.*
- [ ] `[ ]` systemd unit for the watchdog; enable on boot.
- [ ] `[ ]` Verify **on real Pi**: under sustained load, temp is read correctly,
  and a forced/simulated overheat triggers emulator kill + shutdown.

**Done when:** the watchdog runs as a service on the Pi and demonstrably acts on
overheating, independent of the launcher.

---

## Phase 4 — Library API

Now make adding games easy over the network, replacing manual DB/file work.

- [ ] `[ ]` `GET /games` — list. *Test first (FastAPI TestClient, temp DB).*
- [ ] `[ ]` `POST /games` — upload ROM + cover + metadata; store files under the
  file store, insert row. *Test first.*
- [ ] `[ ]` `DELETE /games/{id}` — remove row + files. *Test first.*
- [ ] `[ ]` Reuse `shared/db.py` and `shared/paths.py` — no second copy of the
  schema or path logic.
- [ ] `[ ]` Run the API under uvicorn; confirm it's reachable from the MacBook
  over Tailscale.
- [ ] `[ ]` End-to-end: `POST` a game from the Mac → it appears in the CLI list
  on the Pi → it launches.

**Done when:** you can add a game from the MacBook and immediately play it on the
Pi, no manual file copying.

---

## Phase 5 — Pygame gallery GUI

The kid-facing experience. Only now, once everything underneath works.

- [ ] `[ ]` Pure UI logic first (no display): selection movement, grid paging,
  mapping a selection to a `Game`. *Test first with a fake input source.*
- [ ] `[ ]` Render the gallery: grid of cover art, title, small console label.
- [ ] `[ ]` Controller input adapter: arcade stick/buttons via USB encoder;
  behind a small interface so UI logic tests use a fake.
- [ ] `[ ]` Launch on select (reuse `build_command` + `run_game`), return to the
  gallery on exit.
- [ ] `[ ]` Fullscreen at 1080p; make it boot straight into the gallery
  (systemd/autostart).
- [ ] `[ ]` Optional: Bluetooth gamepad support.
- [ ] `[ ]` Verify **on real Pi**: real display, real stick + real gamepad,
  smooth navigation, launch and return.

**Done when:** the Pi boots into the gallery and a kid can pick a game by cover
art with the stick/gamepad and play — the core project goal.

---

## Phase 6 — Polish & the experiment

Everything that's genuinely optional. Do only what's wanted.

- [ ] `[ ]` `DELETE`/edit games from a simple admin path (API already supports
  it; add UI only if actually needed).
- [ ] `[ ]` Cover-art fallback for games without art.
- [ ] `[ ]` **Experimental:** try Hard Truck 2 via Box64 + Wine, isolated. If it
  runs acceptably, add it as a normal `Game` whose command is the Box64/Wine
  invocation — no special-casing in the launcher. If not, drop it.
- [ ] `[ ]` Any real-hardware performance tuning that surfaced along the way.

**Done when:** the cabinet does everything wanted and the experiment is either in
(as a normal gallery entry) or cleanly dropped.

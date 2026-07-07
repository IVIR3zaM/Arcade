# Iterations

The plan for getting Arcade from nothing to a fully working cabinet, built
**iteratively**. The order is deliberate: get something playable as fast as
possible (a CLI proof-of-concept), then grow outward. The pretty GUI gallery and
the network API come **later** — they are not needed to prove a kid can launch a
game.

We don't harely on the Raspberry Pi yet, so every phase is proven **locally in a
Docker container** that mirrors the Pi's Linux/arm64 userland (same Debian base,
same `apt` packages, same `retroarch`). Docker is the local stand-in until the
last stages — it was chosen by the user for exactly this, and is a dev/test
tool, **not** part of what ships on the Pi. Anything that genuinely needs the
physical device — a real display, the arcade stick/gamepad, actual overheat
shutdown, systemd-on-boot, Tailscale reachability from the MacBook — is
**deferred to Phase 7**, the real-hardware bring-up, done once the Pi is in hand.

Guiding rule: **each phase ends with something that actually works and is
tested** — locally in Docker for now. Don't start a later phase until the current
one runs. Follow [AGENTS.md](AGENTS.md) throughout — TDD, KISS/YAGNI, keep the
stack.

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
- [x] `[x]` **Docker local environment** (user-approved): a `Dockerfile` on a
  Debian + Python base that installs the app, and a `make` target (or compose
  service) that builds the image and runs the test suite inside it. This is the
  local stand-in for the Pi until the hardware arrives.

**Done when:** `pytest` runs green both on the Mac and **inside the Docker
container**.

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
- [x] `[x]` CLI entrypoint (`python -m launcher.cli`): print numbered list of
  games with console labels, read a number from stdin, launch it, return to the
  list on exit.
  - [x] `format_menu(games)`: pure numbered-menu string with console labels.
  - [x] `parse_selection(text, count)`: map input to a game index (validate).
  - [x] `run(...)`: interactive loop (inject I/O + launch) — print menu, read
    choice, launch, repeat until `q`.
  - [x] `__main__`: wire `run` to `SEED_GAMES`, real stdin, and `run_game`.
- [ ] `[ ]` Verify end-to-end **in Docker**: run `python -m launcher.cli` in the
  container, pick a game, confirm the launch command is invoked and the loop
  returns to the menu (and `q` exits). RetroArch needs a display, so run it
  **headless** — a null/dummy video driver, or a stub `retroarch`/`duckstation`
  on `PATH` that records its args — to prove the loop without a real window.

**Done when:** in the Docker container, one command → pick a game from a text
menu → the emulator command fires (headless) → the loop returns to the menu, for
at least one title per console. *(Actual on-screen playability on the Pi is a
Phase 7 checkpoint.)*

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
- [ ] `[ ]` Verify **in Docker** that the CLI still launches games, now reading
  from SQLite.

**Done when:** the CLI (in the container) plays games listed from the SQLite
database.

---

## Phase 3 — Temperature watchdog

The hardware-protection service. Doesn't depend on the GUI, so it can land early
and run independently. The *logic* is fully testable in Docker with fakes; the
real sensor, the systemd service, and a real overheat are Phase 7.

- [ ] `[ ]` Pure logic: `should_shut_down(temp_c, threshold_c)`. *Test first.*
- [ ] `[ ]` `parse_temp(output)` for `vcgencmd measure_temp`. *Test first with
  sample strings.*
- [ ] `[ ]` `read_temp_c()`: the one hardware-touching function (calls
  `vcgencmd`). Mocked in Docker/tests; exercised for real in Phase 7.
- [ ] `[ ]` `watchdog_tick(read_temp=..., threshold_c=...)`: inject the reader;
  on overheat, terminate the running emulator, then shut down. *Test with a fake
  reader.*
- [ ] `[ ]` Verify **in Docker**: run `watchdog_tick` with an injected fake
  reader that crosses the threshold; assert it terminates a fake emulator
  process and calls a fake shutdown — no real `vcgencmd`/`shutdown`.

**Done when:** the watchdog logic and tick behavior are verified in Docker with
fakes. *(Running as a real systemd service and acting on a real overheat is a
Phase 7 checkpoint.)*

---

## Phase 4 — Library API

Now make adding games easy over the network, replacing manual DB/file work.

- [ ] `[ ]` `GET /games` — list. *Test first (FastAPI TestClient, temp DB).*
- [ ] `[ ]` `POST /games` — upload ROM + cover + metadata; store files under the
  file store, insert row. *Test first.*
- [ ] `[ ]` `DELETE /games/{id}` — remove row + files. *Test first.*
- [ ] `[ ]` Reuse `shared/db.py` and `shared/paths.py` — no second copy of the
  schema or path logic.
- [ ] `[ ]` Run the API under uvicorn **in the container**; confirm it's
  reachable from the host over a mapped port.
- [ ] `[ ]` End-to-end **in Docker**: `POST` a game to the API → it appears in
  the CLI list (shared DB/volume) → it launches (headless).

**Done when:** from the host you can `POST` a game to the containerized API and
immediately see and launch it via the CLI in the container. *(Doing this
MacBook→Pi over Tailscale is a Phase 7 checkpoint.)*

---

## Phase 5 — Pygame gallery GUI

The kid-facing experience. Only now, once everything underneath works. The pure
UI logic is testable headless in Docker; the actual rendering, controller input,
fullscreen, and boot-into-gallery need a real display + stick and are Phase 7.

- [ ] `[ ]` Pure UI logic first (no display): selection movement, grid paging,
  mapping a selection to a `Game`. *Test first with a fake input source, headless
  in Docker.*
- [ ] `[ ]` Render the gallery: grid of cover art, title, small console label.
  *(Needs a display — verify on hardware in Phase 7.)*
- [ ] `[ ]` Controller input adapter: arcade stick/buttons via USB encoder;
  behind a small interface so UI logic tests use a fake. *(Real input verified in
  Phase 7.)*
- [ ] `[ ]` Launch on select (reuse `build_command` + `run_game`), return to the
  gallery on exit.

**Done when:** the UI logic (navigation, paging, selection→`Game`) is fully
tested headless in Docker. *(The kid-facing "boots into the gallery, pick by
cover art with the stick, play" experience is the Phase 7 goal.)*

---

## Phase 6 — Polish & the experiment

Everything that's genuinely optional. Do only what's wanted.

- [ ] `[ ]` `DELETE`/edit games from a simple admin path (API already supports
  it; add UI only if actually needed).
- [ ] `[ ]` Cover-art fallback for games without art.
- [ ] `[ ]` **Experimental:** try Hard Truck 2 via Box64 + Wine, isolated. If it
  runs acceptably, add it as a normal `Game` whose command is the Box64/Wine
  invocation — no special-casing in the launcher. If not, drop it. *(Real
  performance judged on hardware in Phase 7.)*

**Done when:** the optional local pieces that are wanted are in and tested in
Docker; the experiment is either wired in (as a normal `Game`) or cleanly
dropped.

---

## Phase 7 — Real hardware bring-up (needs the physical Pi)

The deferred hardware checkpoints, collected here to run **once the Raspberry Pi
is in hand**. Nothing here blocks local progress; it's the final validation that
what we built in Docker also works on the real cabinet.

- [ ] `[ ]` **CLI:** on the Pi, one game per system boots and is playable at
  acceptable performance (this is the first real-hardware checkpoint; N64/PS1 are
  the risky ones).
- [ ] `[ ]` **Watchdog:** systemd unit enabled on boot; under sustained load the
  temp is read correctly; a forced/simulated overheat triggers emulator kill +
  shutdown, independent of the launcher.
- [ ] `[ ]` **API:** reachable from the MacBook over Tailscale; end-to-end `POST`
  a game from the Mac → it appears in the CLI list on the Pi → it launches, no
  manual file copying.
- [ ] `[ ]` **Gallery:** real display, fullscreen at 1080p; real arcade stick +
  real gamepad, smooth navigation, launch and return; boots straight into the
  gallery (systemd/autostart). Optional: Bluetooth gamepad support.
- [ ] `[ ]` Any real-hardware performance tuning that surfaced along the way; the
  Box64/Wine experiment judged on real hardware.

**Done when:** the Pi boots into the gallery and a kid can pick a game by cover
art with the stick/gamepad and play — the core project goal.

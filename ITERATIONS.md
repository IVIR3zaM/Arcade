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

**Phases 0–7 are the arcade** — that's the whole core project. **Phase 8 is a
separate, optional, on-device AI companion** (voice + camera) built on top of the
finished arcade; it is all-local (no cloud) and strictly additive. Don't start it
until the arcade works, and never let it become a dependency of the arcade.

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
- [x] `[x]` Verify end-to-end **in Docker**: run `python -m launcher.cli` in the
  container, pick a game, confirm the launch command is invoked and the loop
  returns to the menu (and `q` exits). RetroArch needs a display, so run it
  **headless** — a null/dummy video driver, or a stub `retroarch`/`duckstation`
  on `PATH` that records its args — to prove the loop without a real window.
- [~] `[~]` **Real-emulator local dev environment (VNC)** — a full local dev
  environment, not a PoC: it should mirror the Pi's emulator stack as closely as
  possible so games run for real and can be watched from the Mac over VNC and
  driven by the CLI. Known limitations are expected (software GL, no GPU, and
  copyrighted BIOS/ROMs must be supplied by the user, not baked in). Still a
  dev/test stand-in — not the image that ships on the Pi.
  - [x] `Dockerfile.play` + `make docker-play`: real RetroArch (v1.14) on a
    headless X server (Xvfb) exposed over VNC (x11vnc) with fluxbox and software
    GL. Verified the desktop serves on `localhost:5900` and RetroArch initializes
    GL on the headless display.
  - [~] Add a libretro Atari 2600 core (Stella — not packaged in Debian, fetched
    from the libretro buildbot) plus a free/homebrew ROM into the image.
    - [x] Fetch the Stella-based `stella2014` core (only Atari 2600 core built for
      arm64) from the libretro buildbot into `/usr/lib/libretro/` in
      `Dockerfile.play`, keyed off `uname -m` so it works on arm64 and x86_64.
    - [x] Add a free/homebrew Atari 2600 ROM into the image (2048-2600 by
      chesterbr, MIT-licensed, at `/roms/atari2600/2048.bin`).
  - [~] Install a **PS1 emulator** matching the launcher's PS1 path
    (`build_command` runs standalone `duckstation <rom>`). Decision (user-approved):
    keep DuckStation — it ships an official arm64 AppImage with a native AArch64
    JIT, so no launcher change / libretro fallback is needed.
    - [x] Fetch the official `DuckStation-arm64.AppImage` in `Dockerfile.play`
      (keyed off `uname -m`), `--appimage-extract` it (no FUSE in containers), and
      expose the extracted `AppRun` as `duckstation` on `PATH`. Verified in the
      built image.
    - [~] Provide a PS1 BIOS the user supplies (copyrighted — mounted, never baked
      in) plus homebrew/free PS1 content for a smoke test.
      - [x] Mount the user-supplied BIOS read-only into DuckStation via
        `make docker-play` (`bios/ps1/`, overridable with `PS1_BIOS_DIR`); contents
        git-ignored, never baked in. Documented in `README.md` + `bios/ps1/README.md`.
      - [ ] Add homebrew/free PS1 content into the image for the smoke test.
  - [ ] Point the CLI library at the real ROM path(s) and launch a game per
    console (Atari 2600 via RetroArch, PS1 via DuckStation) from
    `python -m launcher.cli`, watched over VNC.

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

---

## Phase 8 — Local AI companion (all on-device, no cloud)

A voice + camera assistant layer built **on top of the finished arcade** (Phases
0–7). It recognizes who is at the cabinet, greets them **by name in their
language (English or German, English default)**, knows their play history and how
much time they have today, suggests a game, tells them **which joystick to use**,
and logs every session. It includes a **guest / party mode** with consented,
locally-stored, deletable profiles.

**This phase is strictly additive and opt-in.** The arcade must keep working with
none of it. It is built the same way as everything else — **iteratively, TDD,
testable off-device with fakes** (fake camera, mic, LLM); the real sensors are
Phase-7-style hardware checkpoints collected in **8.9**.

**Everything is on-device. Nothing ever leaves the Pi — no cloud.** This is the
core constraint that keeps the whole thing GDPR-simple (household, local-only),
and it is deliberate: we evaluated and **rejected** any cloud LLM / offload path.

### Hardware this phase adds (all optional to the arcade)

- Pi 5 **8GB** (already provisioned in the core build).
- **Raspberry Pi AI HAT+ (Hailo-8L)** — runs face detection + face embeddings on
  the accelerator; only tiny vectors come back to the Pi CPU, so recognition
  barely touches the CPU and leaves it free for speech + the LLM.
- **Camera Module 3.**
- **USB speakerphone** (mic + speaker with echo cancellation) — *not* a Bluetooth
  mic.
- **Active cooling** — sustained LLM inference is a new 100%-CPU heat source on a
  Pi that already runs hot; the temperature watchdog (Phase 3) still guards it.

### The golden rule (design constraint for the whole phase)

**Deterministic code owns the facts; the LLM owns only language.** SQLite +
plain Python decide *what is true* (who is present, play history, trends, time
budgets, turn order). The local LLM only turns a compact structured summary into
a friendly spoken sentence in EN/DE. A small on-device model cannot be trusted to
reason over raw logs or schedule turns — so it never does.

- **Vision:** Hailo face detect + ArcFace embeddings; the Pi does a trivial
  nearest-neighbour match against local profiles. Handles multiple faces at once.
- **STT:** `whisper.cpp` (multilingual, EN + DE).
- **TTS:** Piper (fast, has EN + DE voices).
- **LLM:** a small 4-bit model (Qwen2.5-3B / Gemma-3-4B) via Ollama/llama.cpp,
  used only as the narrator over a structured "brief".

### Privacy constraints (hard rules, tested)

- All data local; nothing leaves the Pi.
- Face embeddings and names stored **only** locally.
- Guest profiles are **opt-in**, naming is optional, **deletable any time**, and
  **auto-expire** unless the guest asks to keep them.
- Conversations and sessions are logged locally, per profile.

### 8.1 — Profiles & session logging (pure data, no hardware)

- [ ] `[ ]` `profiles` table: id, name, language pref (EN/DE), is_guest, consent,
  created_at, expires_at (nullable). *Test first, temp SQLite.*
- [ ] `[ ]` `sessions` table: profile_id, game_id, started, ended, duration,
  co_players. *Test first.*
- [ ] `[ ]` Pure analytics over history: `favorite_game`, `recent_trend(window)`
  (e.g. "sports → shooter"), `prefers_multiplayer`, `favorite_partner`,
  `time_budget_remaining(profile, today)`. *Test first with a fake history.*

**Done when:** given a fake history, the analytics functions return the correct
facts, tested off-device.

### 8.2 — Recognition adapter (mockable)

- [ ] `[ ]` `VisionSource` interface: `present_faces() -> list[embedding]`
  (real impl = camera + Hailo; tests use a fake).
- [ ] `[ ]` Pure `match(embeddings, profiles, threshold) -> [profile | UNKNOWN]`
  — known within threshold → match, far → guest. *Test first with fake vectors,
  including several faces at once.*

**Done when:** the matcher correctly classifies known vs. unknown from fake
embeddings, off-device.

### 8.3 — The "brief" (deterministic context builder)

- [ ] `[ ]` `build_brief(present_profiles, histories, budgets, now) -> dict` — the
  structured summary handed to the LLM (name, language, budget_left, top_game,
  trend, partner_present, is_guest, which joystick/side …). Pure. *Test first.*

**Done when:** given fake state, `build_brief` returns exactly the expected
structured summary. This is the only object the LLM is allowed to see.

### 8.4 — Voice I/O (mockable)

- [ ] `[ ]` STT adapter (whisper.cpp) and TTS adapter (Piper) behind interfaces;
  tests use text stubs (no audio).
- [ ] `[ ]` Language selection: per-profile preference, English default, German
  for German profiles. *Test first.*

**Done when:** a fake STT transcript flows through to a TTS utterance, verified
off-device with stubs.

### 8.5 — Local LLM narrator

- [ ] `[ ]` Ollama client wrapper: system prompt = persona; input = the brief;
  output = a short EN/DE utterance.
- [ ] `[ ]` Enforce the golden rule: the narrator may only phrase the brief's
  facts — it never invents history, budgets, or turn order. *Test with a mocked
  model asserting the prompt carries only the brief; optional live smoke test.*

**Done when:** given a brief + a stubbed model, the narrator produces a greeting
and the prompt contains only the brief's facts.

### 8.6 — Interaction flow / orchestration

- [ ] `[ ]` State machine: idle → face detected → identify → **known:** greet by
  name, state time budget, suggest a game, say which joystick to use → **unknown:**
  offer guest play + optional consented profile → hand off to the existing
  launcher → on return, log the session → wrap up. *Test the transitions with all
  fakes.*
- [ ] `[ ]` The assistant is **idle during gameplay** — the emulator owns the Pi;
  vision + LLM are paused (time-multiplex). Make this explicit and tested.

**Done when:** the full flow runs off-device with fakes (vision, STT/TTS, LLM,
launcher), producing correct transitions and session logs.

### 8.7 — Guest & party mode

- [ ] `[ ]` New face → guest; play allowed immediately; afterwards the assistant
  asks (voice) whether to save a **named, consented** profile — stored locally,
  deletable, auto-expiring.
- [ ] `[ ]` **Party mode:** many guests, ephemeral profiles auto-created; log who
  played what, for how long, and with whom.
- [ ] `[ ]` "Making the rounds": a **deterministic turn scheduler** (fair queue)
  that the assistant *voices* — plus kids' time-limit rules enforced. The
  intelligence is the scheduler; the LLM only announces it. *Test with a party
  simulation of several fake guests.*

**Done when:** a party simulation with several fake guests produces correct
per-guest logs, a fair turn order, and consented/deletable profiles — all
off-device.

### 8.8 — GUI integration (the speaking side + the gallery)

- [ ] `[ ]` The Pygame gallery gains a companion side: show who is recognized, the
  assistant's spoken line as text, and the suggested game highlighted. Pure UI
  logic tested headless; actual rendering is a hardware checkpoint (8.9).

**Done when:** the companion UI logic (recognized user → highlighted suggestion +
transcript panel) is tested headless.

### 8.9 — Real-hardware bring-up (needs the AI HAT + camera + speakerphone)

- [ ] `[ ]` AI HAT+ installed; the camera recognizes the family at the cabinet in
  real lighting; unknown faces fall through to a spoken "are you X, or a guest?"
  rather than mislogging.
- [ ] `[ ]` Whisper + Piper real latency is acceptable; LLM tok/s is acceptable
  for **terse** replies.
- [ ] `[ ]` Thermals OK under LLM + idle with active cooling; the assistant is
  genuinely idle during gameplay (no frame-rate hit to the emulator); the
  watchdog still protects the Pi.
- [ ] `[ ]` End-to-end: walk up → greeted by name in the right language → get a
  game suggestion + joystick hint → play → session logged. Nothing leaves the Pi.

**Done when:** at the real cabinet, a known person is greeted by name in their
language, gets a suggestion and a joystick hint, plays, and the session is logged
— entirely on-device.

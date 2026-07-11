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

Second guiding rule: **the cabinet is fully functional with no internet, and
never downloads anything at boot or at runtime.** Every dependency — packages,
emulator cores, AI models, voices — is installed once at **provisioning/image-
build time**. Fetch-on-first-run is acceptable only in dev conveniences (the
Docker stand-ins, the PoC), never on the Pi.

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
language (English default; German is the backup for kids who can't speak English
yet)**, knows their play history and how much time they have today, suggests a
game, tells them **which joystick to use**, and logs every session. It includes a
**guest / party mode** with consented, locally-stored, deletable profiles.

**This phase is strictly additive and opt-in.** The arcade must keep working with
none of it. It is built the same way as everything else — **iteratively, TDD,
testable off-device with fakes** (fake camera, mic, LLM); the real sensors are
Phase-7-style hardware checkpoints collected in **8.9**.

**Everything is on-device. Nothing ever leaves the Pi — no cloud.** This is the
core constraint that keeps the whole thing GDPR-simple (household, local-only),
and it is deliberate: we evaluated and **rejected** any cloud LLM / offload path.

**And nothing ever comes down to the Pi either: fully offline, no downloads at
boot or runtime.** The LLM weights, whisper model, and Piper voices are all
installed at provisioning time (baked into the image or copied once during
setup). The PoC's first-run fetch from the Ollama registry / Hugging Face was a
dev convenience only — the production companion must start and run with the
network cable unplugged.

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

### 8.0 — Experience PoC ✅ (done) — and the lessons that now bind this phase

- [x] `[x]` A throwaway PoC (`poc/`) proved the full experience end-to-end on a
  Pi-approximating throttled container: continuous listening (VAD, no
  push-to-talk), wake word, greeting, fuzzy game launch, joystick assignment,
  profiles/memory in SQLite, guest onboarding, admin privacy scheduling, EN/DE —
  at **~2–4 s for a typical turn**.

**The PoC code is throwaway and stays in `poc/`.** It grew by iteration into
shallow, monolithic modules (a 1,400-line `agent.py`); none of it is ported. The
production companion is a **clean rewrite** with a simpler, layered structure
(see 8.3/8.6): a pure conversation engine with no I/O, thin adapters (audio,
vision, model, hardware) at the edges, and one orchestrator. What we keep are
the findings below — each one was paid for in latency or a live misbehavior, and
the sub-phases reference them.

**What a 3B model on a Pi-class CPU can and can't do**

1. It **cannot** be an autonomous many-tools agent: given one big prompt with a
   dozen tools it under-calls them, goes silent, and fills arguments with junk
   (`create_profile(name="me")`, `name="unspecified"`). Split honestly, it works:
   the model **only classifies intent** (schema-constrained JSON — it physically
   can't answer in prose or invent an intent) and **only phrases the open-ended
   moments** (a greeting that weaves in remembered detail, free-form context
   answers). Everything else — execution, access control, argument sanity — is
   deterministic code. *Yes for understanding; no for anything you can't afford
   it getting wrong.*
2. A typical turn must cost **at most one model call**. Routine outcomes
   (launched, stopped, remembered, denied, …) get hand-written EN/DE templates —
   zero model calls. Templating replies halved latency with no felt loss.
3. The perf disciplines, each measured: pin `num_thread` to the real core count
   (unpinned, Ollama fights the CPU quota — ~4× slower); keep the model resident
   (`keep_alive -1`); keep the intent **system prompt constant** so llama.cpp
   reuses its prefill cache (all few-shot lives there; only the short user line
   is processed per turn) and **prime that cache at boot**; keep `num_ctx` /
   `num_predict` small. Fewer model calls beats faster model calls.

**Language — hard decisions, already made**

4. The cabinet speaks **English and German, and only those**. Persian was tried
   and **dropped** — whisper-tiny mangles it and there is no usable voice; any
   other language gets an honest "I can speak English and German", never a fake
   "switch".
5. **Never free auto-detect.** Letting whisper pick from ~99 languages was the
   worst latency spike seen: garbled speech locked onto Arabic/Polish and burned
   6–9 s decoding hallucinated text. Run a cheap detection pass, **clamp to the
   better of EN vs DE**, then decode. Once the language is settled, **lock it**
   and skip detection entirely (~0.5 s saved per turn).
6. The reply language only flips on **genuine spoken content** (≥2 real words) —
   never on the wake phrase alone ("Hey Arc" reads as English to whisper) or a
   one-word "okay". Explicit requests ("speak English" / "sprich Deutsch") are
   matched **in code**, not by the model, and persist to the profile.
7. **Default is English** (a deliberate reversal of the PoC's German default);
   known profiles get their saved language.

**Latency & perceived responsiveness**

8. STT: whisper **tiny** int8, `beam_size=1`, threads pinned like the LLM, and an
   `initial_prompt` biasing decoding toward the wake phrase, the game titles, and
   the known people's names — that bias buys back most of tiny's accuracy loss.
9. TTS: keep the Piper voices **resident in-process** (the CLI respawn +
   ONNX reload per reply was a big fixed cost), **warm them up at startup**, and
   **cache synthesized audio by (language, text)** — templated lines are then
   instant on reuse.
10. **Time every step and stream progress** (step began / step finished events):
    a 3-second silent gap feels broken; the same gap with a visible "processing"
    state doesn't. This instrumentation feeds the status bar (8.8).

**The conversation — code owns the flow**

11. High-frequency turns are matched **in code, fuzzily, at zero model calls**,
    because whisper mishears everything: wake word ("Hey Ark/Arg/Hallo Arc"),
    goodbye ("Tschüss" → "Schüsse"), acceptance ("let's go for that"), cancel,
    joystick sides ("Ride"/"Wright" = right), stop-the-game ("Kilo's the game"),
    language requests, and letter-by-letter spelled names ("K-I-A-N").
12. **Attention state machine:** *engaged* after a greeting or wake word — every
    utterance handled; *idle* after ~45 s of silence or while a game runs —
    everything transcribed but ignored unless it starts with the wake phrase, so
    players talking to each other never trigger the companion. Mid-game it
    answers one woken request and goes right back to ignoring chatter — and it
    **says so** ("Say 'Hey Arc' when you need me"); going silent unannounced
    reads as a bug. The mic is closed while the companion speaks.
13. Filter whisper's silence hallucinations ("Thanks for watching",
    "Untertitelung des ZDF") before they reach the engine.
14. **Pending-question state:** when the companion asked something ("what's your
    name?", "which joystick?", "restart on the left?", "is that you?", "close
    the game first?"), the next utterance is interpreted as the answer in code —
    no model call, and an unclear reply doesn't withdraw the question.
15. **Suggestion memory:** track the last offer and every rejection; never
    re-offer a declined game; accepting an offer **launches** it (not
    re-recommends it); saying a game's full title IS choosing it, even when the
    model labels the turn as browsing.
16. **Possibility map:** which intents are legal depends on cabinet state — a
    running game owns the screen and joysticks, so launching another game,
    remapping a joystick, screen-off, and privacy changes are impossible until
    it's closed, and the companion asks first. The map both steers the model
    (only doable intents are offered) and is enforced in code (the model
    reaching past it is coerced to "unclear").
17. **Never trust the model with names or permissions.** Names are extracted in
    code from explicit cues only, guarded against pronouns, stopwords, and
    schema-placeholder junk — when unsure, ask. Access control (admin gating,
    who may delete whose profile) lives only in code; a duplicate name triggers
    an "is that you?" merge flow instead of overwriting.

### The golden rule (design constraint for the whole phase)

**Deterministic code owns the facts and the flow; the LLM owns only
understanding and open-ended wording.** SQLite + plain Python decide *what is
true* (who is present, play history, budgets, turn order) and *what happens*
(execution, access control, state). The model's whole job is: (a) one
schema-constrained intent classification per non-trivial turn, and (b) phrasing
the few genuinely open-ended replies. Validated by the PoC (8.0.1).

- **Vision:** Hailo face detect + ArcFace embeddings; the Pi does a trivial
  nearest-neighbour match against local profiles. Handles multiple faces at
  once — and its output (who is on which side) feeds the status bar (8.8), not
  the LLM.
- **STT:** whisper-family, `tiny` int8 (faster-whisper proved out; whisper.cpp
  acceptable if it fits the Pi image better), **clamped to EN/DE** (8.0.5).
- **TTS:** Piper, resident + cached (8.0.9), with **two matched male voices**
  (8.4).
- **LLM:** Qwen2.5-3B 4-bit via Ollama, resident, intent + open phrasing only
  (validated in the PoC; 7B remains a quality/latency knob).

### Privacy constraints (hard rules, tested)

- All data local; nothing leaves the Pi.
- Face embeddings and names stored **only** locally.
- Guest profiles are **opt-in**, naming is optional, **deletable any time**, and
  **auto-expire** unless the guest asks to keep them.
- Conversations and sessions are logged locally, per profile.

### 8.1 — Profiles & session logging (pure data, no hardware)

- [ ] `[ ]` `profiles` table: id, name, language pref (EN/DE, **default en**),
  is_guest, is_admin, consent, created_at, expires_at (nullable). *Test first,
  temp SQLite.*
- [ ] `[ ]` `notes` (remembered facts): profile_id, note, created_at — the
  "remember I only play after 5pm" store the PoC proved people actually use.
  *Test first.*
- [ ] `[ ]` `sessions` table: profile_id, game_id, started, ended, duration,
  co_players, joystick side. *Test first.*
- [ ] `[ ]` Pure analytics over history: `favorite_game`, `recent_trend(window)`,
  `prefers_multiplayer`, `favorite_partner`,
  `time_budget_remaining(profile, today)`, `time_played_today(profile)` — the
  last two also drive the status bar (8.8). *Test first with a fake history.*

**Done when:** given a fake history, the analytics functions return the correct
facts, tested off-device.

### 8.2 — Recognition adapter (mockable)

- [ ] `[ ]` `VisionSource` interface: `present_faces() -> list[(embedding,
  position)]` (real impl = camera + Hailo; tests use a fake). Position matters:
  left/right in frame maps players to joystick sides for the status bar.
- [ ] `[ ]` Pure `match(embeddings, profiles, threshold) -> [profile | UNKNOWN]`
  — known within threshold → match, far → guest. *Test first with fake vectors,
  including several faces at once.*
- [ ] `[ ]` Presence snapshot: `who_is_where() -> [(profile|guest, side)]` —
  deterministic, from vision alone (8.0's rule: the LLM never decides who is
  present). This is the single source for greetings AND the top status bar.

**Done when:** the matcher classifies known vs. unknown from fake embeddings and
the presence snapshot maps people to sides, off-device.

### 8.3 — Conversation engine (pure, replaces the PoC's agent)

The clean rewrite of what the PoC proved, structured as three pure layers with
**no I/O, no audio, no HTTP** — fully testable with a stubbed model:

- [ ] `[ ]` **Intent layer:** the intent list + JSON schema for constrained
  decoding; the possibility map (8.0.16) deciding which intents are offered and
  legal per state; the constant few-shot system prompt (EN+DE examples).
  *Test: state → allowed intents; out-of-map intent coerced.*
- [ ] `[ ]` **Code-match layer:** the zero-model fast paths (8.0.11) — wake word,
  goodbye, acceptance, cancel, sides, stop, language requests, spelled names —
  plus the name guards (8.0.17) and pending-question resolution (8.0.14). Each
  is a small pure function with the PoC's misheard variants as test cases.
- [ ] `[ ]` **Execute + phrase layer:** deterministic execution with all access
  control; suggestion memory (8.0.15); EN/DE templates for every routine
  outcome, model phrasing only for greeting-with-memory and context answers.
  *Test the full turn pipeline with a stubbed model: transcript in → (reply
  text, actions, state changes) out.*

**Done when:** every conversational behavior the PoC demonstrated passes as a
unit test against the new engine with a stubbed model — including the misheard
inputs — and no module does I/O.

### 8.4 — Voice I/O (mockable)

- [ ] `[ ]` STT adapter (whisper tiny int8): EN/DE clamp, settle-then-lock,
  vocabulary-biasing prompt, junk filter (8.0.5/8/13). Behind an interface;
  tests use text stubs.
- [ ] `[ ]` TTS adapter (Piper): resident voices, startup warmup, synthesis
  cache (8.0.9). Behind an interface; tests use stubs. Whisper model and both
  voices load from **local paths installed at provisioning time** — the adapters
  have no download path at all; a missing model file is a hard, clear error.
- [ ] `[ ]` **Voice pair selection: two MALE voices, one EN one DE, chosen to
  sound as close to the same person as possible** — switching language must not
  feel like a speaker swap (the PoC's `en_US-lessac` + `de_DE-eva_k` pair was a
  male/female clash). Start with `en_US-ryan` + `de_DE-thorsten`; A/B a few
  pairs by ear (same sentence, alternating languages) and pick the closest
  timbre/pace at the `low`/`medium` tier the Pi can afford.
- [ ] `[ ]` VAD mic loop: continuous capture, adaptive noise floor, utterance
  segmentation (start on voice, end on ~0.8 s silence), mic closed while the
  companion speaks. Pure segmentation logic tested with synthetic frames.
- [ ] `[ ]` Language selection: per-profile preference, **English default**,
  flip only on genuine spoken content (8.0.6/7). *Test first.*

**Done when:** a fake transcript flows through to a TTS utterance with the
right language, verified off-device with stubs — and the voice pair is chosen
and documented.

### 8.5 — Local LLM adapter

- [ ] `[ ]` Ollama client wrapper exposing exactly two calls: `classify(text,
  allowed_intents) -> intent dict` (schema-constrained) and `phrase(instruction,
  facts, language) -> str`. Nothing else reaches the model.
- [ ] `[ ]` Bake in the perf disciplines (8.0.3): `num_thread` pinned,
  `keep_alive -1`, constant system prompt, boot-time prefill priming, small
  `num_ctx`/`num_predict`. Config, not code, sets the model tag.
- [ ] `[ ]` Model weights are **pre-pulled at provisioning time** (part of the
  image/setup, alongside the whisper model and Piper voices); startup only
  verifies they're present and loads them — it never pulls. *Test: startup with
  a fake registry that would fail any pull still comes up green.*
- [ ] `[ ]` Enforce the golden rule at the boundary: the phrase call receives
  only the engine's facts dict — never raw history, never tool schemas. *Test
  with a mocked transport asserting the exact prompts; optional live smoke test.*

**Done when:** given stubbed transport, both calls produce correct prompts and
parse responses; the prompt provably contains only what the engine passed.

### 8.6 — Orchestration (the one impure layer)

- [ ] `[ ]` Session state machine wiring vision + engine + voice: idle → face
  detected → monitor on → greet (templated unless remembered detail, 8.0.2) →
  **known:** name, time budget, suggestion, joystick hint → **unknown:** guest
  play + optional consented profile → hand off to the launcher → on return, log
  the session. *Test transitions with all fakes.*
- [ ] `[ ]` Attention states engaged/idle with the PoC's rules (8.0.12): wake
  word to re-engage, timeout back to idle, one-request-then-idle mid-game with
  the spoken idle hint. *Tested with fakes.*
- [ ] `[ ]` Monitor management: on at walk-up, off by voice, off after idle
  timeout with no game; "Hey Arc" with nobody in frame → invite over, stay dark.
- [ ] `[ ]` The assistant is **idle during gameplay** — the emulator owns the
  Pi; vision + LLM are paused (time-multiplex). Explicit and tested.
- [ ] `[ ]` Per-turn step timing with streamed begin/end events (8.0.10) — the
  data source for the status bar's listening/processing state.

**Done when:** the full flow runs off-device with fakes (vision, STT/TTS, LLM,
launcher), producing correct transitions, session logs, and timing events.

### 8.7 — Guest & party mode

- [ ] `[ ]` New face → guest; play allowed immediately; afterwards the assistant
  asks (voice) whether to save a **named, consented** profile — name captured
  via the guarded code paths (ask → next utterance is the name → pronoun/
  stopword/spelled-name handling → duplicate-name merge flow, 8.0.17), stored
  locally, deletable, auto-expiring.
- [ ] `[ ]` **Party mode:** many guests, ephemeral profiles auto-created; log who
  played what, for how long, and with whom.
- [ ] `[ ]` "Making the rounds": a **deterministic turn scheduler** (fair queue)
  that the assistant *voices* — plus kids' time-limit rules enforced. The
  intelligence is the scheduler; the LLM only announces it. *Test with a party
  simulation of several fake guests.*

**Done when:** a party simulation with several fake guests produces correct
per-guest logs, a fair turn order, and consented/deletable profiles — all
off-device.

### 8.8 — Cabinet HUD (two always-on bars in the gallery)

The companion's face in the GUI is two persistent bars around the gallery, both
pure-logic-first (tested headless), rendered by Pygame:

- [ ] `[ ]` **Bottom conversation bar** (always visible): the companion's state
  as a live indicator — *listening / processing (which step) / speaking* — fed
  by the timing events (8.6); the last thing the user said (transcript, dimmed
  when it was ignored chatter); and the companion's last reply. Pure
  `ConversationBarState` reducer over engine/timing events. *Test first.*
- [ ] `[ ]` **Top system bar** (always visible): CPU usage, CPU temperature, RAM
  usage; cabinet status — which game is running, how long it's been played,
  time remaining for the current player's daily budget (8.1 analytics); and
  **which profiles are playing on which sides — from the vision presence
  snapshot (8.2), never the LLM**. Pure `SystemBarState` builder over a stats
  sampler interface (real impl reads `vcgencmd`/`/proc`; tests use fakes).
  *Test first.*
- [ ] `[ ]` Gallery integration: suggested game highlighted on greeting; bars
  keep updating while browsing. Rendering itself is a hardware checkpoint (8.9).

**Done when:** both bar states are computed correctly from fake events/stats,
tested headless, and the gallery renders them (visually verified in the Docker
VNC environment, on-cabinet in 8.9).

### 8.9 — Real-hardware bring-up (needs the AI HAT + camera + speakerphone)

- [ ] `[ ]` AI HAT+ installed; the camera recognizes the family at the cabinet in
  real lighting; unknown faces fall through to a spoken "are you X, or a guest?"
  rather than mislogging; side detection (who is left/right) matches reality.
- [ ] `[ ]` Whisper + Piper real latency is acceptable; LLM tok/s is acceptable
  for **terse** replies; the PoC's ~2–4 s typical turn holds on the real Pi
  (the Docker throttle was an optimistic bound — memory bandwidth is lower).
- [ ] `[ ]` The matched voice pair sounds right on the real speaker — same-person
  feel across an EN↔DE switch; re-pick the pair if the cabinet speaker changes
  the verdict.
- [ ] `[ ]` Thermals OK under LLM + idle with active cooling; the assistant is
  genuinely idle during gameplay (no frame-rate hit to the emulator); the
  watchdog still protects the Pi; the top bar's CPU/temp/RAM read the real
  sensors.
- [ ] `[ ]` **Offline test:** power the Pi up with **no network at all** (cable
  unplugged, Wi-Fi off) — it boots into the gallery and the full companion
  experience works: recognition, greeting, STT/TTS, LLM, game launch, logging.
  No boot-time download, no degraded mode, no startup delay waiting on a
  network timeout.
- [ ] `[ ]` End-to-end: walk up → greeted by name in the right language → get a
  game suggestion + joystick hint → play (bars live the whole time) → session
  logged. Nothing leaves the Pi.

**Done when:** at the real cabinet, a known person is greeted by name in their
language, gets a suggestion and a joystick hint, plays with both bars live, and
the session is logged — entirely on-device.

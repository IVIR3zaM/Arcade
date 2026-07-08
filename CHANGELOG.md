# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Conventional Commits](https://www.conventionalcommits.org/)
for commit messages.

New work always goes under **[Unreleased]**, grouped by type (`Added`,
`Changed`, `Fixed`, `Removed`). When we cut a release, move those entries into a
new dated version section.

## [Unreleased]

### Added

- `poc/`: a throwaway **Phase 8 experience PoC** that tests whether a small
  on-device LLM can be the arcade's **tool-calling manager** — run `poc/run.sh`
  on the Mac, pick a scenario, and talk to the cabinet by voice. A **single**
  container mirrors the cabinet's Pi 5 (8GB): Debian 12 Bookworm arm64 (what
  Raspberry Pi OS is), capped at **4 cores / 8GB shared**, running the whole
  pipeline in one box — **faster-whisper** STT (biased to the real names),
  **Ollama** (`qwen2.5:3b` default, `COMPANION_MODEL`-overridable) in a
  tool-calling loop, **Piper** TTS. The LLM drives everything through an MCP-style
  tool surface it must call — `get_player`, `list_games`, `recommend_game`,
  `launch_game`/`close_game`, `assign_joystick`, `create_profile`/`delete_profile`,
  `remember`, `get_context`, `set_privacy_schedule` — and **every tool call is
  printed in the CLI** so you can see what it did. Tools **enforce truth** (e.g.
  `launch_game` fuzzy-matches a misheard "Point" back to "Pong" and refuses
  unknown games; privacy changes are admin-gated), so the model orchestrates but
  can't invent facts. Profiles, learned per-person memory ("only plays after
  5pm"), and admin privacy schedules persist in a **real SQLite** DB in a volume
  (survives restarts); Pi hardware (temp, mic/camera state) is mocked behind small
  functions. The AI models are fetched on first run into cached volumes, keeping
  the image build small. The MacBook's mic + speakers stand in for the Pi's
  speakerphone (Docker Desktop can't reach host audio). Documented caveats: this
  matches the Pi's core count/RAM/OS/arch but not per-core clock speed (latency is
  an optimistic upper bound; real perf is Phase 8.9), and a 3B model under-calls
  tools on harder requests — a stronger model (`qwen2.5:7b` / `llama3.1:8b`) is a
  drop-in. Deterministic core (tools, store, agent loop, privacy-window logic,
  analytics) is unit-tested with no model/audio/network (`cd poc && python3 -m
  pytest tests`). Separate from the real dev env and entirely optional; documented
  in `poc/README.md`.
- `make docker-play`: the copyrighted PS1 BIOS is now supplied by the user and
  mounted read-only into DuckStation instead of being baked into the image. Drop
  it in `bios/ps1/` (overridable via `PS1_BIOS_DIR`); the directory's contents are
  git-ignored (a `bios/ps1/README.md` explains it). Documented in `README.md`.
  (Homebrew/free PS1 content + the actual smoke test land in follow-up steps.)
- `Dockerfile.play`: the PS1 emulator DuckStation is now installed. Its official
  arm64 AppImage is fetched at build time (keyed off `uname -m`; recent
  DuckStation is CC-BY-NC-ND so the binary is never committed), `--appimage-extract`-ed
  (no FUSE in containers), and exposed as `duckstation` on `PATH` — matching the
  launcher's standalone `duckstation <rom>` command with no launcher change. DuckStation's
  native AArch64 JIT matches the Pi's arch. (PS1 BIOS/ROM smoke test + CLI wiring
  land in follow-up steps.)
- `Dockerfile.play`: a free, homebrew Atari 2600 ROM — 2048-2600 by chesterbr,
  MIT-licensed (so it's genuinely redistributable inside the image) — is now
  fetched at build time to `/roms/atari2600/2048.bin`, matching the launcher's
  `/roms/<console>/` `rom_path` convention. Gives the real-emulator env something
  to actually launch. (CLI wiring to this path lands in a follow-up step.)
- `Dockerfile.play`: the Atari 2600 Stella core (`stella2014`, the only 2600 core
  the libretro buildbot builds for arm64) is now fetched into `/usr/lib/libretro/`
  at build time, keyed off `uname -m` so it resolves the right buildbot arch dir
  (`aarch64`/`x86_64`). Adds `curl`/`unzip` to the image for the fetch. (Free ROM +
  CLI wiring land in follow-up steps.)
- Real-emulator dev environment: `Dockerfile.play` + `make docker-play` build an
  image with RetroArch actually installed on a headless X server (Xvfb) exposed
  over VNC (x11vnc + fluxbox, software GL), so a game can be launched and watched
  from the Mac host at `localhost:5900`. Dev/test stand-in only — not shipped on
  the Pi. (Atari 2600 core + free ROM + CLI wiring land in follow-up steps.)

### Changed

- Planned **Phase 8 — local AI companion** in `ITERATIONS.md`: an optional,
  strictly-additive, **all on-device (no cloud)** voice + camera assistant built
  on top of the finished arcade. It recognizes who is at the cabinet, greets them
  by name in English/German, knows their play history and time budget, suggests a
  game and which joystick to use, logs sessions, and has a consented, deletable
  guest/party mode. Built the same way as everything else (TDD, testable
  off-device with fakes; real sensors are the Phase-8 hardware bring-up). Core
  design constraint: **deterministic code owns the facts, the LLM only phrases
  them**, and nothing ever leaves the Pi.
- Bumped the core-build Pi to **8GB** in `README.md` (headroom for the Phase 8
  companion) and documented the companion's optional add-on hardware (AI HAT+,
  Camera Module 3, USB speakerphone, active cooling) plus a scope note that it
  does not change the one-screen, one-game-at-a-time build.
- Reframed the real-emulator Docker work in `ITERATIONS.md` as a full local dev
  environment (not a PoC) that mirrors the Pi's emulator stack, and planned the
  missing **PS1 emulator** (standalone DuckStation, with an arm64/BIOS caveat and
  a `libretro-beetle-psx` fallback) alongside the Atari 2600 core.
- Documented Docker as the **primary local dev environment (not a PoC)** across
  `README.md`, `AGENTS.md`, and `ARCHITECTURE.md`: added a Docker/VNC section and
  the `make docker-test`/`make docker-play` targets to the README, an
  "environment is Docker" note to AGENTS, and demoted UTM to an optional
  alternative so the next agent treats Docker as the real dev target.
- End-to-end CLI test (`tests/test_cli_e2e.py`) that spawns `python -m
  launcher.cli` against a stub emulator on `PATH`, proving the launch → return to
  menu → `q` exit loop headlessly (verified inside the Docker container).
- Initial project documentation: `README.md`, `ARCHITECTURE.md`, `AGENTS.md`,
  `ITERATIONS.md` (iterative, CLI-first plan), and `PROMPT.md` (agent operating
  instructions).
- Apache License 2.0 (`LICENSE`).
- This changelog.
- Repo layout: `launcher/`, `api/`, `shared/`, `watchdog/`, `tests/` Python
  packages, plus a git-ignored `data/` directory.
- Empty `requirements.txt` placeholder; dependencies added per phase as needed.
- `pytest` configured via `pyproject.toml` (`testpaths = ["tests"]`) with a
  passing smoke test (`tests/test_smoke.py`).
- `Makefile` with `test` (runs `cairn verify`) and `run-cli` (runs the launcher
  CLI) targets.
- Cairn as the repo quality gate: `cairn.yaml`, git hooks (`.cairn/hooks/`), and
  a GitHub Actions workflow (`.github/workflows/cairn.yml`) — `cairn verify`
  runs format/lint/test the same way locally and in CI.
- `requirements-dev.txt` pinning the dev tools Cairn shells out to (`pytest`,
  `ruff`).
- Local Docker environment (Phase 0): a `Dockerfile` on `python:3.12-slim-bookworm`
  (Debian) that installs deps and copies the app, a `.dockerignore`, and a
  `make docker-test` target that builds the image and runs the test suite inside
  it — the Pi stand-in until the hardware arrives.
- `shared/models.py`: `Game` dataclass (title, console, emulator, core,
  rom_path, cover_path) with a covering test.
- `launcher/emulator.py`: pure `build_command(game)` that builds the RetroArch
  (`retroarch -L <core> <rom>`) or DuckStation launch command without running
  it, with tests asserting the exact command per emulator.
- `launcher/emulator.py`: `run_game(command)`, a thin subprocess wrapper that
  runs the launch command and waits, kept separate from `build_command` and
  stubbed in tests.
- `launcher/library.py`: `SEED_GAMES`, a small hardcoded in-memory list of
  `Game`s (N64/Genesis/PS1) to drive the CLI before a real database exists.
- `launcher/cli.py`: `format_menu(games)`, a pure function rendering games as a
  numbered menu with console labels (first slice of the CLI entrypoint).
- `launcher/cli.py`: `parse_selection(text, count)`, a pure function mapping a
  1-based menu choice to a 0-based index and returning `None` for out-of-range
  or non-numeric input.
- `launcher/cli.py`: `run(games, read_line, launch, write)`, the interactive
  loop that prints the menu, launches the chosen game, and repeats until the
  user quits with `q`; I/O and launching are injected so it is testable.
- `launcher/cli.py`: `launch_game(game)`, `main()`, and a `__main__` block —
  `python -m launcher.cli` now shows the seeded games, reads a choice from
  stdin, and launches it via `build_command` + `run_game`.

### Changed

- `.gitignore` now excludes `.venv/`, `__pycache__/`, `data/`, and `*.db`.

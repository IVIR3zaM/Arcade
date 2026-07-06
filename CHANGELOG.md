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

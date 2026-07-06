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

### Known issues

- `cairn verify`'s format step false-fails against ruff 0.15.20: ruff prints
  "N files already formatted" to stdout on success (exit 0), which Cairn reads
  as pending changes. Lint and test pass. Fix belongs in the Cairn repo.

### Changed

- `.gitignore` now excludes `.venv/`, `__pycache__/`, `data/`, and `*.db`.

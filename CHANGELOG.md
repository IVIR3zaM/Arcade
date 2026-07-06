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

### Changed

- `.gitignore` now excludes `.venv/`, `__pycache__/`, `data/`, and `*.db`.

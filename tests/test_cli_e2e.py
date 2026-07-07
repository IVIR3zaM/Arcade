import os
import subprocess
import sys
from pathlib import Path

from launcher.library import SEED_GAMES

# A tiny stub that stands in for the real emulator: it records the args it was
# called with, so the loop can be proven headless (no display, no RetroArch).
STUB = """#!/bin/sh
echo "$0 $@" >> "$RECORD_FILE"
"""


def _write_stub(directory: Path, name: str) -> None:
    path = directory / name
    path.write_text(STUB)
    path.chmod(0o755)


def test_cli_launches_game_then_returns_to_menu_and_quits(tmp_path):
    record_file = tmp_path / "record.txt"
    _write_stub(tmp_path, "retroarch")
    _write_stub(tmp_path, "duckstation")

    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "RECORD_FILE": str(record_file),
    }

    # Pick the first game, then quit — proving launch + return-to-menu + q-exit.
    result = subprocess.run(
        [sys.executable, "-m", "launcher.cli"],
        input="1\nq\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert result.returncode == 0
    # The menu is printed once before the choice and again after the game exits.
    first = SEED_GAMES[0]
    assert result.stdout.count(f"1. {first.title} ({first.console})") == 2
    # The stubbed emulator was actually invoked with the built command.
    recorded = record_file.read_text()
    assert first.rom_path in recorded
    assert first.core in recorded

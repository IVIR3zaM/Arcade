from launcher import emulator
from launcher.emulator import build_command, run_game
from shared.models import Game


def _game(emulator, core):
    return Game(
        title="Test Game",
        console="N64",
        emulator=emulator,
        core=core,
        rom_path="/roms/game.rom",
        cover_path="/covers/game.png",
    )


def test_build_command_for_retroarch():
    game = _game("retroarch", "mupen64plus_next")

    assert build_command(game) == [
        "retroarch",
        "-L",
        "mupen64plus_next",
        "/roms/game.rom",
    ]


def test_build_command_for_duckstation():
    game = _game("duckstation", None)

    assert build_command(game) == ["duckstation", "/roms/game.rom"]


def test_run_game_runs_command_and_waits(monkeypatch):
    calls = []
    monkeypatch.setattr(emulator.subprocess, "run", lambda cmd: calls.append(cmd))

    run_game(["retroarch", "-L", "core", "/roms/game.rom"])

    assert calls == [["retroarch", "-L", "core", "/roms/game.rom"]]

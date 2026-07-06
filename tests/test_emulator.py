from launcher.emulator import build_command
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

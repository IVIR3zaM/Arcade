from launcher.cli import format_menu
from shared.models import Game


def _game(title, console):
    return Game(
        title=title,
        console=console,
        emulator="retroarch",
        core="core",
        rom_path="/roms/game.rom",
        cover_path="/covers/game.png",
    )


def test_format_menu_numbers_games_with_console_labels():
    games = [_game("Super Mario 64", "N64"), _game("Sonic", "Genesis")]

    assert format_menu(games) == "1. Super Mario 64 (N64)\n2. Sonic (Genesis)"

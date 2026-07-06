from launcher.cli import format_menu, parse_selection, run
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


def test_parse_selection_maps_number_to_zero_based_index():
    assert parse_selection("1", 2) == 0
    assert parse_selection("2", 2) == 1


def test_parse_selection_tolerates_surrounding_whitespace():
    assert parse_selection(" 1 ", 2) == 0


def test_parse_selection_rejects_out_of_range():
    assert parse_selection("0", 2) is None
    assert parse_selection("3", 2) is None


def test_parse_selection_rejects_non_numeric():
    assert parse_selection("abc", 2) is None
    assert parse_selection("", 2) is None


def test_run_launches_selected_game_then_repeats_until_quit():
    games = [_game("Super Mario 64", "N64"), _game("Sonic", "Genesis")]
    inputs = iter(["2", "q"])
    launched = []

    run(games, read_line=lambda: next(inputs), launch=launched.append)

    assert launched == [games[1]]


def test_run_reprompts_on_invalid_selection():
    games = [_game("Super Mario 64", "N64")]
    inputs = iter(["5", "1", "q"])
    launched = []

    run(games, read_line=lambda: next(inputs), launch=launched.append)

    assert launched == [games[0]]

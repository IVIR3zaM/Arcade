from launcher.library import SEED_GAMES
from shared.models import Game


def test_seed_games_is_a_nonempty_list_of_games():
    assert len(SEED_GAMES) > 0
    assert all(isinstance(game, Game) for game in SEED_GAMES)


def test_seed_games_have_titles_and_rom_paths():
    for game in SEED_GAMES:
        assert game.title
        assert game.rom_path

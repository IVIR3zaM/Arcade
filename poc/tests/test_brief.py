"""Tests for the deterministic core — analytics, the game suggester, and the
brief. These are pure functions (no model, no audio, no network), so they run
anywhere with just pytest.

Run from the poc/ directory:  python3 -m pytest tests -q
"""

from brain.brief import (
    favorite_game,
    favorite_partner,
    prefers_multiplayer,
    recent_trend,
    suggest_game,
)
from brain.models import GameInfo, Profile, SessionRecord

LEO = Profile(id="leo", name="Leo", language="en")
MIA = Profile(id="mia", name="Mia", language="de")
GUEST = Profile(id="guest-1", name=None, language="en", is_guest=True)

GAMES = [
    GameInfo("Track & Field", "Atari", "sports", 1, quick=False),
    GameInfo("Tetris", "NES", "puzzle", 1, quick=True),
    GameInfo("Street Fighter II", "SNES", "fighting", 2, quick=False),
]

LEO_HISTORY = [
    SessionRecord("Track & Field", "sports", 20),
    SessionRecord("Track & Field", "sports", 25),
    SessionRecord("River Raid", "shooter", 30),
    SessionRecord("Contra", "shooter", 25, co_players=["Mia"]),
]


def test_favorite_game_is_most_played():
    assert favorite_game(LEO_HISTORY) == "Track & Field"


def test_favorite_game_none_without_history():
    assert favorite_game([]) is None


def test_recent_trend_detects_genre_shift():
    assert recent_trend(LEO_HISTORY, window=4) == "sports → shooter"


def test_recent_trend_none_when_stable():
    stable = [SessionRecord("Tetris", "puzzle", 10)] * 3
    assert recent_trend(stable) is None


def test_prefers_multiplayer_threshold():
    solo = [SessionRecord("Tetris", "puzzle", 10)]
    assert prefers_multiplayer(solo) is False
    mixed = [
        SessionRecord("Pong", "sports", 10, co_players=["Mia"]),
        SessionRecord("Contra", "shooter", 10, co_players=["Mia"]),
    ]
    assert prefers_multiplayer(mixed) is True


def test_favorite_partner():
    assert favorite_partner(LEO_HISTORY) == "Mia"


def test_suggest_favorite_when_time_is_plentiful():
    game = suggest_game([LEO], {"leo": LEO_HISTORY}, {"leo": 45}, GAMES)
    assert game.title == "Track & Field"


def test_suggest_quick_game_when_time_is_low():
    game = suggest_game([LEO], {"leo": LEO_HISTORY}, {"leo": 10}, GAMES)
    assert game.quick is True


def test_suggest_nothing_when_time_is_up():
    assert suggest_game([LEO], {"leo": LEO_HISTORY}, {"leo": 0}, GAMES) is None


def test_suggest_multiplayer_for_two_players():
    game = suggest_game([LEO, MIA], {}, {"leo": 45, "mia": 30}, GAMES)
    assert game.max_players >= 2


def test_guest_gets_a_quick_game():
    game = suggest_game([GUEST], {}, {}, GAMES)
    assert game.quick is True

"""The deterministic analytics the tools serve to the LLM manager.

These functions decide *what is true* over a person's play history — favorite
game, genre trend, whether they like multiplayer, their usual partner, and the
game suggestion. The LLM reads them through tools (get_player, recommend_game)
and only phrases them; it never computes them. Pure and fully unit-testable.
"""

from collections import Counter

from .models import GameInfo, Profile, SessionRecord

# Below this many minutes left, suggest a short ("quick") game instead of a favorite.
LOW_BUDGET_MIN = 15


def favorite_game(history: list[SessionRecord]) -> str | None:
    """The most-played game title, or None with no history."""
    if not history:
        return None
    counts = Counter(s.game_title for s in history)
    return counts.most_common(1)[0][0]


def recent_trend(history: list[SessionRecord], window: int = 3) -> str | None:
    """A genre shift across the last `window` sessions, e.g. 'sports → shooter'.

    None when there's no clear shift (too little history, or same genre).
    """
    recent = history[-window:]
    if len(recent) < 2:
        return None
    first, last = recent[0].genre, recent[-1].genre
    if first == last:
        return None
    return f"{first} → {last}"


def prefers_multiplayer(history: list[SessionRecord]) -> bool:
    """True if at least half of past sessions had a co-player."""
    if not history:
        return False
    with_others = sum(1 for s in history if s.co_players)
    return with_others * 2 >= len(history)


def favorite_partner(history: list[SessionRecord]) -> str | None:
    """The person this player has played with most, or None."""
    partners = Counter(name for s in history for name in s.co_players)
    if not partners:
        return None
    return partners.most_common(1)[0][0]


def suggest_game(
    present: list[Profile],
    histories: dict[str, list[SessionRecord]],
    budgets: dict[str, int],
    games: list[GameInfo],
) -> GameInfo | None:
    """Pick a game deterministically. None means "don't suggest" (time's up)."""
    multiplayer_games = [g for g in games if g.max_players >= 2]

    # Two or more players → a game everyone can play together.
    if len(present) >= 2:
        return multiplayer_games[0] if multiplayer_games else games[0]

    player = present[0]

    # Guest with no history → an easy, quick pick-up game.
    if player.is_guest:
        quick = [g for g in games if g.quick]
        return quick[0] if quick else games[0]

    budget = budgets.get(player.id, 0)
    if budget <= 0:
        return None  # time's up — nothing to suggest

    if budget < LOW_BUDGET_MIN:
        quick = [g for g in games if g.quick]
        return quick[0] if quick else games[0]

    # Enough time → their favorite, if it's still in the library.
    fav = favorite_game(histories.get(player.id, []))
    for g in games:
        if g.title == fav:
            return g
    return games[0]

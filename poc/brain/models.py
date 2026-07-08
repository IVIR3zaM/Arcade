"""Plain data the PoC passes around.

Kept local to the PoC on purpose — the real `shared.Game` is deliberately tiny
and we don't bolt companion-only fields (genre, player count) onto it. This is a
throwaway experience test, not production data.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameInfo:
    """A game the companion can suggest. Superset of `shared.Game` for the PoC."""

    title: str
    console: str
    genre: str  # 'sports' | 'shooter' | 'puzzle' | 'racing' | 'fighting' | 'platformer'
    max_players: int
    quick: bool  # true = a short session, good when time is almost up


@dataclass(frozen=True)
class Profile:
    """A person the AI HAT might recognize at the cabinet."""

    id: str
    name: str | None  # None for an unnamed guest
    language: str  # 'en' (default) | 'de'
    is_guest: bool = False


@dataclass(frozen=True)
class SessionRecord:
    """One past play session, used by the analytics functions."""

    game_title: str
    genre: str
    duration_min: int
    co_players: list[str] = field(default_factory=list)

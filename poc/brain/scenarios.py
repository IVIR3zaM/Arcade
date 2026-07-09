"""The mock world the PoC runs against.

Profiles (and the memory the assistant learns about people, privacy schedules,
etc.) live in the SQLite store now. This module holds the things that don't
change at runtime: the game catalog, a bit of demo play-history + today's screen
-time budgets used for analytics, and the hand-picked scenarios you choose from
the CLI — each of which tells the fake AI HAT who is standing at the cabinet.
"""

from .models import GameInfo, SessionRecord

# The mock game library, tagged with what the tools need (player count, "quick"
# for short slots).
GAMES: list[GameInfo] = [
    GameInfo("Track & Field", "Atari", "sports", 1, quick=False),
    GameInfo("River Raid", "Atari", "shooter", 1, quick=False),
    GameInfo("Pong", "Atari", "sports", 2, quick=True),
    GameInfo("Tetris", "NES", "puzzle", 1, quick=True),
    GameInfo("Contra", "NES", "shooter", 2, quick=False),
    GameInfo("Super Mario World", "SNES", "platformer", 1, quick=False),
    GameInfo("Street Fighter II", "SNES", "fighting", 2, quick=False),
    GameInfo("Mario Kart 64", "N64", "racing", 2, quick=True),
]

# Demo play history + remaining screen time today, keyed by lowercased name. The
# analytics functions read these; new people the assistant creates have neither.
HISTORIES: dict[str, list[SessionRecord]] = {
    "leo": [
        SessionRecord("Track & Field", "sports", 20),
        SessionRecord("Track & Field", "sports", 25),
        SessionRecord("Pong", "sports", 10, co_players=["Mia"]),
        SessionRecord("River Raid", "shooter", 30),
        SessionRecord("Contra", "shooter", 25, co_players=["Mia"]),
    ],
    "mia": [
        SessionRecord("Tetris", "puzzle", 15),
        SessionRecord("Super Mario World", "platformer", 20),
        SessionRecord("Pong", "sports", 10, co_players=["Leo"]),
    ],
}

BUDGETS: dict[str, int] = {
    "leo": 45,
    "mia": 10,
}

# What the camera "sees" for each scenario: known names, or "unknown" for a new
# face (a guest). Pick one from the CLI.
SCENARIOS: dict[str, dict] = {
    "leo-solo": {
        "description": "Leo (English) walks up alone — loves sports, drifting to shooters.",
        "present": ["Leo"],
    },
    "mia-solo": {
        "description": "Mia (German) walks up alone — only 10 min of screen time left.",
        "present": ["Mia"],
    },
    "leo-and-mia": {
        "description": "Leo and Mia arrive together — two players.",
        "present": ["Leo", "Mia"],
    },
    "guest": {
        "description": "An unrecognized face — the assistant can offer to save a profile.",
        "present": ["unknown"],
    },
    "reza-admin": {
        "description": "Reza (admin) walks up — can set privacy schedules (mic/camera off).",
        "present": ["Reza"],
    },
    "nobody-home": {
        "description": "Nobody in front of the cabinet — it listens quietly; say "
        "'Hey Arc' from across the room and it invites you over.",
        "present": [],
    },
}

"""The arcade's actions — the deterministic executor behind the manager.

Each is a real action against the SQLite store, the game catalog, or the (mocked)
Pi hardware. `agent.execute_intent` calls these by name (run_tool) after the model
classifies intent; the tools decide *what is true* and enforce it — e.g.
launch_game fuzzy-matches "Point" back to the real "Pong" and refuses to launch a
game that doesn't exist, so the small model never invents facts. Access control
does NOT live here beyond the admin check helper — the agent decides permission
in code before calling.
"""

import difflib
from dataclasses import dataclass, field

from . import hardware, store
from .brief import (
    favorite_game,
    favorite_partner,
    prefers_multiplayer,
    recent_trend,
    suggest_game,
)
from .models import Profile
from .scenarios import BUDGETS, GAMES, HISTORIES

# Below this similarity, a fuzzy name/title match is rejected as "no confident match".
_MATCH_CUTOFF = 0.5


@dataclass
class Session:
    """Live state for one walk-up: the DB connection, who the camera sees, and any
    game currently running."""

    conn: object  # sqlite3.Connection
    present: list[str]  # names as the camera reports them; "unknown" = a guest
    running_game: str | None = None
    log: list[dict] = field(default_factory=list)  # tool calls made this session
    new_language: str | None = None  # set when the person asks to switch language
    last_suggested: str | None = None  # the game Arc offered last ("How about X?")
    rejected: list[str] = field(default_factory=list)  # suggestions declined this visit

    def display_present(self) -> list[str]:
        return ["Guest" if n == "unknown" else n for n in self.present]


def _fuzzy(query: str, candidates: list[str]) -> str | None:
    if not query or not candidates:
        return None
    norm = {c.lower(): c for c in candidates}
    hit = difflib.get_close_matches(
        query.lower().strip(), list(norm), n=1, cutoff=_MATCH_CUTOFF
    )
    return norm[hit[0]] if hit else None


def _present_profiles(session: Session) -> list[Profile]:
    """Concrete Profiles for who's present, id = lowercased name (keys the analytics)."""
    profiles = []
    for name in session.present:
        if name == "unknown":
            profiles.append(
                Profile(id="guest", name="Guest", language="en", is_guest=True)
            )
            continue
        row = store.get_profile(session.conn, name)
        lang = row["language"] if row else "en"
        profiles.append(Profile(id=name.lower(), name=name, language=lang))
    return profiles


def _present_admin(session: Session) -> str | None:
    for name in session.present:
        if name == "unknown":
            continue
        row = store.get_profile(session.conn, name)
        if row and row["is_admin"]:
            return row["name"]
    return None


# --- individual tools -------------------------------------------------------


def get_player(session: Session, name: str) -> dict:
    matched = _fuzzy(name, session.display_present())
    if matched is None:
        return {
            "error": "no such person is present",
            "present": session.display_present(),
        }
    if matched == "Guest":
        return {
            "name": "Guest",
            "known": False,
            "is_guest": True,
            "hint": "unrecognized face — you may offer to create a profile",
        }
    row = store.get_profile(session.conn, matched)
    if row is None:
        return {"error": f"no profile for {matched}"}
    history = HISTORIES.get(matched.lower(), [])
    return {
        "name": row["name"],
        "known": True,
        "language": row["language"],
        "is_admin": bool(row["is_admin"]),
        "memory": row["notes"],  # everything the assistant has learned about them
        "budget_left_min": BUDGETS.get(matched.lower()),
        "favorite_game": favorite_game(history),
        "trend": recent_trend(history),
        "prefers_multiplayer": prefers_multiplayer(history),
        "favorite_partner": favorite_partner(history),
    }


def list_games(session: Session) -> dict:
    return {
        "games": [
            {
                "title": g.title,
                "console": g.console,
                "genre": g.genre,
                "max_players": g.max_players,
            }
            for g in GAMES
        ]
    }


# German/casual genre words → the catalog's genre tags (fuzzy match handles the rest).
_GENRE_SYNONYMS = {
    "sport": "sports",
    "sportspiel": "sports",
    "sportspiele": "sports",
    "rennen": "racing",
    "rennspiel": "racing",
    "rennspiele": "racing",
    "autorennen": "racing",
    "kampf": "fighting",
    "kampfspiel": "fighting",
    "denkspiel": "puzzle",
    "knobeln": "puzzle",
    "ballerspiel": "shooter",
    "jump n run": "platformer",
    "jump and run": "platformer",
}


def recommend_game(
    session: Session, genre: str = "", query: str = "", exclude: list | None = None
) -> dict:
    """Suggest a game, honoring a genre ("something in sport"), a title keyword
    ("something from Mario"), and everything already declined this visit."""
    pool = list(GAMES)
    applied = None
    if query:
        by_title = [g for g in pool if query.lower().strip() in g.title.lower()]
        if by_title:
            pool, applied = by_title, query
    if applied is None and genre:
        want = _GENRE_SYNONYMS.get(genre.lower().strip()) or _fuzzy(
            genre, sorted({g.genre for g in GAMES})
        )
        if want:
            pool = [g for g in pool if g.genre == want]
            applied = want
    pool = [g for g in pool if g.title not in (exclude or [])]
    matches = [g.title for g in pool] if applied else []
    if not pool:
        return {
            "recommendation": None,
            "reason": "nothing left that matches",
            "filter": applied,
        }
    present = _present_profiles(session)
    pick = suggest_game(present, HISTORIES, BUDGETS, pool)
    if pick is None:
        return {"recommendation": None, "reason": "no screen time left today"}
    return {
        "recommendation": pick.title,
        "console": pick.console,
        "max_players": pick.max_players,
        "filter": applied,
        "matches": matches,
    }


def assign_joystick(session: Session, player: str, side: str = "") -> dict:
    """Joystick for a player: their spoken preference ("the right one") wins,
    otherwise deterministic by position at the cabinet."""
    names = session.display_present()
    matched = _fuzzy(player, names)
    if matched is None:
        return {"error": "no such person is present", "present": names}
    if side not in ("left", "right"):
        side = "left" if names.index(matched) == 0 else "right"
    return {"player": matched, "joystick": side}


def launch_game(session: Session, title: str) -> dict:
    matched = _fuzzy(title, [g.title for g in GAMES])
    if matched is None:
        suggestions = [g.title for g in GAMES][:3]
        return {"error": f"no game matches {title!r}", "did_you_mean": suggestions}
    game = next(g for g in GAMES if g.title == matched)
    session.running_game = matched
    player = session.display_present()[0] if session.present else "someone"
    store.log_play(session.conn, player, matched)
    return {
        "launched": matched,
        "requested": title,
        "console": game.console,
        "max_players": game.max_players,
    }


def close_game(session: Session) -> dict:
    if session.running_game is None:
        return {"error": "no game is running"}
    closed = session.running_game
    session.running_game = None
    return {"closed": closed}


def create_profile(session: Session, name: str, language: str = "en") -> dict:
    prof = store.create_profile(session.conn, name, language=language)
    return {"created": prof["name"], "language": prof["language"]}


def remember(session: Session, name: str, note: str) -> dict:
    known = [
        n for n in session.display_present() if n != "Guest"
    ] + store.list_profile_names(session.conn)
    matched = _fuzzy(name, known) or name
    memory = store.append_note(session.conn, matched, note)
    if memory is None:
        return {"error": f"no profile for {matched} to remember about"}
    return {"remembered_about": matched, "note": note, "memory": memory}


def delete_profile(session: Session, name: str) -> dict:
    known = store.list_profile_names(session.conn)
    matched = _fuzzy(name, known) or name
    ok = store.delete_profile(session.conn, matched)
    return {"deleted": matched} if ok else {"error": f"no profile named {matched}"}


def set_monitor(session: Session, on: bool) -> dict:
    """Turn the cabinet's monitor on or off (mocked; CEC/wlr-randr on the Pi)."""
    hardware.set_monitor(bool(on))
    return {"monitor_on": bool(on)}


def set_language(session: Session, language: str, name: str = "") -> dict:
    """Switch the conversation language, persisting it on the speaker's profile."""
    if language not in ("en", "de", "fa"):
        return {"error": f"unsupported language {language!r} (en, de, or fa)"}
    session.new_language = language
    persisted = bool(name) and store.set_language(session.conn, name, language)
    return {"language": language, "persisted_for": name if persisted else None}


def get_context(session: Session) -> dict:
    current = hardware.now()
    schedules = store.list_schedules(session.conn)
    devices = hardware.devices_state(current, schedules)
    return {
        "datetime": current.isoformat(timespec="minutes"),
        "weekday": current.strftime("%A"),
        "hour": current.hour,
        "cpu_temp_c": hardware.read_temp_c(),
        "mic_on": devices["mic_on"],
        "camera_on": devices["camera_on"],
        "monitor_on": hardware.monitor_on(),
        "privacy_schedules": [
            {"start": s["start_hm"], "end": s["end_hm"], "reason": s["reason"]}
            for s in schedules
        ],
    }


def _to_hm(value: str) -> str | None:
    """Normalize a time the model might emit ('8pm', '9 am', '20:00') to 'HH:MM'."""
    s = str(value).strip().lower().replace(" ", "")
    ampm = None
    if s.endswith("am") or s.endswith("pm"):
        ampm, s = s[-2:], s[:-2]
    try:
        h, m = (s.split(":") + ["0"])[:2] if ":" in s else (s, "0")
        h, m = int(h), int(m)
    except ValueError:
        return None
    if ampm == "pm" and h != 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return f"{h:02d}:{m:02d}"


def set_privacy_schedule(
    session: Session, start: str, end: str, reason: str = ""
) -> dict:
    admin = _present_admin(session)
    if admin is None:
        return {
            "error": "only an admin (e.g. Reza) present at the cabinet can change privacy settings"
        }
    start_hm, end_hm = _to_hm(start), _to_hm(end)
    if start_hm is None or end_hm is None:
        return {"error": f"could not understand the times {start!r}–{end!r}; use HH:MM"}
    sched = store.add_schedule(session.conn, start_hm, end_hm, reason, created_by=admin)
    return {
        "privacy_schedule_set": True,
        "start": sched["start_hm"],
        "end": sched["end_hm"],
        "reason": reason,
        "by": admin,
    }


# --- dispatch + schemas -----------------------------------------------------

_DISPATCH = {
    "get_player": get_player,
    "list_games": list_games,
    "recommend_game": recommend_game,
    "assign_joystick": assign_joystick,
    "launch_game": launch_game,
    "close_game": close_game,
    "create_profile": create_profile,
    "remember": remember,
    "delete_profile": delete_profile,
    "get_context": get_context,
    "set_privacy_schedule": set_privacy_schedule,
    "set_monitor": set_monitor,
    "set_language": set_language,
}


# Small models often borrow an argument name from another tool (e.g. pass
# "player" to get_player, which wants "name"). Coalesce common synonyms so a good
# call isn't lost to a wrong key.
_PERSON_KEYS = ("name", "player", "person", "who", "username")
_PERSON_ARG = {
    "get_player": "name",
    "assign_joystick": "player",
    "create_profile": "name",
    "remember": "name",
    "delete_profile": "name",
}
_TITLE_KEYS = ("title", "game", "name")


def _normalize_args(name: str, args: dict) -> dict:
    args = dict(args or {})
    want = _PERSON_ARG.get(name)
    if want and want not in args:
        for k in _PERSON_KEYS:
            if k in args:
                args[want] = args.pop(k)
                break
    if name == "launch_game" and "title" not in args:
        for k in _TITLE_KEYS:
            if k in args:
                args["title"] = args.pop(k)
                break
    return args


def run_tool(session: Session, name: str, args: dict) -> dict:
    """Execute a tool by name; unknown tools / bad args return an error dict."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool {name!r}"}
    try:
        return fn(session, **_normalize_args(name, args))
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}


def summarize(name: str, args: dict, result: dict) -> str:
    """A short human-readable line for the CLI action log."""
    if "error" in result:
        extra = result.get("did_you_mean") or result.get("present")
        return f"⚠ {result['error']}" + (f" (try: {extra})" if extra else "")
    if name == "get_player" and result.get("known"):
        mem = f", memory: {result['memory']!r}" if result.get("memory") else ""
        return f"{result['name']}: {result.get('budget_left_min')} min left, fav {result.get('favorite_game')}{mem}"
    if name == "launch_game":
        req = result["requested"]
        corrected = (
            f" (heard {req!r})" if req.lower() != result["launched"].lower() else ""
        )
        return f"launched {result['launched']}{corrected}"
    if name == "assign_joystick":
        return f"{result['player']} → {result['joystick']} joystick"
    if name == "recommend_game":
        filt = f" ({result['filter']})" if result.get("filter") else ""
        skip = args.get("exclude")
        skipped = f", skipping {', '.join(skip)}" if skip else ""
        return f"suggests {result.get('recommendation')}{filt}{skipped}"
    if name == "remember":
        return f"remembered about {result['remembered_about']}: {result['note']!r}"
    if name == "create_profile":
        return f"created profile {result['created']}"
    if name == "delete_profile":
        return f"deleted {result['deleted']}"
    if name == "set_privacy_schedule":
        return f"mic+camera OFF {result['start']}–{result['end']} (by {result['by']})"
    if name == "set_monitor":
        return f"monitor → {'ON' if result['monitor_on'] else 'OFF'}"
    if name == "set_language":
        who = (
            f" (saved for {result['persisted_for']})" if result["persisted_for"] else ""
        )
        return f"language → {result['language']}{who}"
    if name == "get_context":
        return f"{result['weekday']} {result['datetime']}, {result['cpu_temp_c']}°C, mic {'on' if result['mic_on'] else 'OFF'}"
    return str(result)

"""The manager, redesigned for a small on-device model.

A 3B model is bad at autonomously driving 11 tools in one big prompt, but good at
small, focused tasks. So instead of one giant tool-calling loop, each turn is a
short pipeline:

    1. classify_intent  — one tiny model call: "what does the user want?" The
                          output is schema-constrained (Ollama structured output),
                          so the intent is always one of ours.
    2. execute_intent    — CODE runs the action deterministically, INCLUDING all
                           access control (who is present and what they may do is
                           decided here, never by the model) and all sanity
                           guards (a pronoun like "me" is never taken as a name)
    3. phrase            — deterministic EN/DE templates for most outcomes (zero
                           model calls → fast); the model only phrases the
                           open-ended ones (greeting, context questions)

So a typical turn costs ONE small model call. Both remaining call sites use small
prompts (no tool schemas) and the model stays resident in RAM.

The model calls are injectable so the whole pipeline is testable without Ollama.
"""

import difflib
import json
import os
import re

from . import tools
from .scenarios import GAMES

MODEL = os.environ.get("COMPANION_MODEL", "qwen2.5:3b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
# Match llama.cpp's thread count to the CPU quota. The container is throttled to
# 4 cores (like the Pi) but SEES all host cores, so Ollama would otherwise spawn
# far more threads than the quota and fight the throttle. Pinning to 4 both mirrors
# the Pi's 4 physical cores and avoids that contention.
NUM_THREAD = int(os.environ.get("COMPANION_NUM_THREAD", "4"))
# A small context is plenty (the intent prompt is a few hundred tokens) and keeps
# the KV cache — and thus per-token CPU cost — low. Overridable if a longer
# phrasing prompt ever needs it.
NUM_CTX = int(os.environ.get("COMPANION_NUM_CTX", "2048"))

PERSONA = (
    "You are Arc, the friendly voice of a family arcade cabinet. You are warm and "
    "brief: one or two short spoken sentences, no emoji, no markdown, no lists."
)

# The intents the router can return. Kept small and flat so a 3B can pick reliably.
_INTENT_NAMES = [
    "play_game",
    "stop_game",
    "list_games",
    "recommend",
    "remember",
    "create_profile",
    "delete_profile",
    "set_privacy",
    "monitor",
    "switch_language",
    "get_context",
    "goodbye",
    "other",
]

# Structured-output schema: Ollama constrains decoding to this, so a 3B can't
# invent an intent name or return prose instead of JSON.
_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": _INTENT_NAMES},
        "title": {"type": "string"},
        "genre": {"type": "string"},
        "query": {"type": "string"},
        "note": {"type": "string"},
        "name": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "on": {"type": "boolean"},
        "language": {"type": "string", "enum": ["en", "de"]},
    },
    "required": ["intent"],
}


# --- possibility map: what is doable in the current state -------------------
#
# The order and legality of intents depends on the cabinet's state — most of all
# on whether a game is running. A game "owns" the screen and the joysticks, so
# anything that would disrupt it (launching another game, remapping a joystick,
# turning the screen off, changing privacy) is impossible until the game is
# closed — and Arc must ASK before closing it. This map is the single source of
# truth for that, used BOTH to steer the model (only doable intents are offered)
# and to enforce the rule in code (execute_intent, below).

# Intents that only take effect with NO game running. While one is on, Arc
# offers to close it first; a stray "turn off the screen" never kills a game.
_REQUIRE_NO_GAME = {"play_game", "monitor", "set_privacy"}

# While a game runs, profiles are managed between games, not mid-play — those
# intents aren't offered to the model at all. The require-no-game intents stay
# offered so a real request ("play Tetris") is recognized and Arc can offer to
# close the current game first.
_INGAME_INTENTS = [
    n for n in _INTENT_NAMES if n not in ("create_profile", "delete_profile")
]


def allowed_intents(session) -> list[str]:
    """The intents that make sense right now — the possibility map."""
    if session.running_game:
        return _INGAME_INTENTS
    return _INTENT_NAMES


def _chat(system: str, user: str, as_json: bool = False) -> str:
    """One small Ollama chat call. Kept resident (keep_alive -1) and short.

    Latency on a Pi-class CPU is dominated by (a) prefill of the prompt and
    (b) the number of tokens generated, so both are kept tight:
      * the intent SYSTEM prompt is constant, so llama.cpp keeps its prefill
        cached between turns and only the short user line is processed;
      * num_predict caps generation (intents are tiny JSON; replies are ≤2
        sentences), and a small num_ctx keeps the KV cache cheap.
    """
    import requests

    body = {
        "model": MODEL,
        "stream": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.1 if as_json else 0.3,
            "num_predict": 48 if as_json else 80,
            "num_thread": NUM_THREAD,
            "num_ctx": NUM_CTX,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if as_json:
        body["format"] = _INTENT_SCHEMA
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=120)
    resp.raise_for_status()
    return (resp.json()["message"].get("content") or "").strip()


# --- step 1: intent (model) -------------------------------------------------


# Few-shot examples steer a 3B far better than a bare description — in BOTH
# languages, since German is the cabinet's default. Times normalized to 24h HH:MM.
_INTENT_EXAMPLES = (
    '"let\'s play pong" -> {"intent":"play_game","title":"Pong"}\n'
    '"lass uns tetris spielen" -> {"intent":"play_game","title":"Tetris"}\n'
    '"put on track and field" -> {"intent":"play_game","title":"Track & Field"}\n'
    '"stop the game" -> {"intent":"stop_game"}\n'
    '"ich bin fertig" -> {"intent":"stop_game"}\n'
    '"what can I play?" -> {"intent":"list_games"}\n'
    '"was soll ich spielen?" -> {"intent":"recommend"}\n'
    '"I want something in sport" -> {"intent":"recommend","genre":"sports"}\n'
    '"ich möchte ein rennspiel" -> {"intent":"recommend","genre":"racing"}\n'
    '"I wanna play something from mario" -> {"intent":"recommend","query":"Mario"}\n'
    '"not that one, something else" -> {"intent":"recommend"}\n'
    '"remember I only play after 5pm" -> {"intent":"remember","note":"only plays after 5pm"}\n'
    '"merk dir, ich spiele nur am Wochenende" -> {"intent":"remember","note":"spielt nur am Wochenende"}\n'
    '"save my profile, I\'m Sam" -> {"intent":"create_profile","name":"Sam"}\n'
    '"create a profile for me" -> {"intent":"create_profile"}\n'
    '"erstell mir bitte ein profil" -> {"intent":"create_profile"}\n'
    '"delete my profile" -> {"intent":"delete_profile"}\n'
    '"turn off the mic and camera every night from 8pm to 9am" -> '
    '{"intent":"set_privacy","start":"20:00","end":"09:00"}\n'
    '"turn off the screen" -> {"intent":"monitor","on":false}\n'
    '"mach den monitor wieder an" -> {"intent":"monitor","on":true}\n'
    '"speak English please" -> {"intent":"switch_language","language":"en"}\n'
    '"can you speak any english?" -> {"intent":"switch_language","language":"en"}\n'
    '"sprich Deutsch" -> {"intent":"switch_language","language":"de"}\n'
    '"what time is it?" -> {"intent":"get_context"}\n'
    '"what is the cpu temperature?" -> {"intent":"get_context"}\n'
    '"how long have I been playing?" -> {"intent":"get_context"}\n'
    '"what do you remember about me?" -> {"intent":"get_context"}\n'
    '"bye" -> {"intent":"goodbye"}\n'
    '"tschüss" -> {"intent":"goodbye"}'
)


# The system prompt is CONSTANT (all the bulky few-shot lives here), so
# llama.cpp caches its prefill and reuses it every turn — only the short user
# line below is processed each time. That is the single biggest per-turn CPU
# saving on a Pi. The state-specific "doable now" list and the utterance go in
# the tiny user message; the possibility map is enforced for real in code.
_INTENT_SYSTEM = (
    "You label what a person at an arcade wants, as JSON only (no prose). "
    "The person may speak English or German. "
    f"Known games: {', '.join(g.title for g in GAMES)}.\n"
    "Return JSON with intent plus only the fields that apply "
    "(title, genre, query, note, name, start, end, on, language). Convert times "
    "to 24h HH:MM. Only include name if the person actually said a name. If "
    'truly unrelated, use {"intent":"other"}.\n'
    f"Examples:\n{_INTENT_EXAMPLES}"
)


def classify_intent(
    user_text: str, present: list[str], chat=_chat, allowed: list[str] | None = None
) -> dict:
    """Small JSON call: extract the user's intent. Never decides access.

    `allowed` is the possibility map for the current state — those are the
    intents offered to the model, and anything outside it is coerced to "other"
    (a 3B occasionally reaches past the menu it was given).
    """
    allowed = allowed or _INTENT_NAMES
    user = f'Doable right now: {", ".join(allowed)}.\nThe person said: "{user_text}"'
    try:
        data = json.loads(chat(_INTENT_SYSTEM, user, as_json=True))
    except (json.JSONDecodeError, TypeError):
        return {"intent": "other"}
    if data.get("intent") not in allowed:
        # The model reached for an intent that's impossible right now (e.g.
        # deleting a profile mid-game) — treat it as unrelated.
        data["intent"] = "other"
    return data


# --- guards: never trust a small model with names ----------------------------

# Words a 3B loves to hand over as a "name" ("create a profile for me" →
# name="me"), plus the placeholders it invents to satisfy the JSON schema when
# no name was said (seen live: name="unspecified"). Never a person's name.
_PRONOUNS = {
    "me",
    "myself",
    "i",
    "i'm",
    "my",
    "mine",
    "us",
    "we",
    "you",
    "player",
    "guest",
    "user",
    "someone",
    "anonymous",
    "unknown",
    "name",
    "mir",
    "mich",
    "ich",
    "mein",
    "meins",
    "uns",
    "wir",
    "du",
    "spieler",
    "gast",
    "unspecified",
    "none",
    "null",
    "n/a",
    "na",
    "not specified",
    "undefined",
    "string",
    "tbd",
    "nicht angegeben",
    "keine angabe",
}


# Ordinary words that follow a name cue without being a name: "I'm GONNA HAVE a
# profile here" produced the profile "Gonna Have" live. A name containing any of
# these is rejected and Arc asks instead.
_NAME_STOPWORDS = {
    "gonna",
    "going",
    "wanna",
    "want",
    "wants",
    "will",
    "would",
    "just",
    "also",
    "have",
    "has",
    "had",
    "need",
    "needs",
    "get",
    "getting",
    "make",
    "making",
    "a",
    "an",
    "the",
    "new",
    "here",
    "there",
    "now",
    "then",
    "so",
    "not",
    "no",
    "yes",
    "okay",
    "ok",
    "sure",
    "really",
    "very",
    "done",
    "ready",
    "back",
    "profile",
    "profil",
    "game",
    "play",
    "playing",
    "spielen",
    "konto",
    "möchte",
    "will",
    "gerne",
    "bitte",
    "ein",
    "eine",
    "hier",
    "jetzt",
    "neues",
}


def _clean_name(name) -> str | None:
    """A usable person name from the model, or None.

    Rejects pronouns AND anything that isn't name-shaped: seen live, the 3B will
    pass the whole utterance as the name ("Herstell mir bitte ein Profil").
    Better to ask "what's your name?" than to save garbage.
    """
    n = str(name or "").strip().strip(".,!?")
    if not n or n.lower() in _PRONOUNS:
        return None
    words = n.split()
    if len(words) > 2 or any(ch.isdigit() for ch in n):
        return None
    if any(w.lower() in _NAME_STOPWORDS or w.lower() in _PRONOUNS for w in words):
        return None
    return n


# When we've asked "what's your name?", the next utterance IS the name — spoken
# naturally ("my name is Sam", "ich heiße Sam", or just "Sam").
_NAME_PREFIXES = (
    "my name is",
    "the name is",
    "i am",
    "i'm",
    "im",
    "it's",
    "its",
    "this is",
    "call me",
    "mein name ist",
    "ich heiße",
    "ich heisse",
    "ich bin",
    "nenn mich",
)
_CANCEL_WORDS = {
    "no",
    "nope",
    "no thanks",
    "cancel",
    "never mind",
    "nevermind",
    "forget it",
    "nein",
    "nee",
    "nein danke",
    "abbrechen",
    "vergiss es",
    "lass es",
    "doch nicht",
    "نه",
    "نه ممنون",
}


def is_cancel(text: str) -> bool:
    t = " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())
    if not t or len(t.split()) > 4:
        return False
    return t in _CANCEL_WORDS or bool(
        difflib.get_close_matches(t, _CANCEL_WORDS, n=1, cutoff=0.85)
    )


# Goodbye is detected in code, fuzzily — whisper renders "Tschüss!" as "Schüsse"
# — and skips the model entirely (a canned reply, ~1s turn).
_GOODBYES = (
    "bye",
    "bye bye",
    "goodbye",
    "good bye",
    "ciao",
    "see you",
    "tschüss",
    "tschuss",
    "bis bald",
    "bis dann",
    "auf wiedersehen",
    "mach's gut",
    "خداحافظ",
    "بای",
)


def is_goodbye(text: str) -> bool:
    t = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if not t or len(t.split()) > 3:
        return False
    return bool(difflib.get_close_matches(t, _GOODBYES, n=1, cutoff=0.75))


# Language requests are matched in code, not by the model: "Can you speak any
# English?" was seen routed to get_context, after which the phrasing model
# hallucinated "Ich kann kein Englisch sprechen". A language word plus any
# speak-ish word is unambiguous — no model needed.
_LANG_WORDS = {
    "en": ("english", "englisch"),
    "de": ("german", "deutsch"),
    # Any other language → "other": Arc must SAY what it can speak. Left to the
    # model, the schema forces a supported code and it "switches" wrongly.
    # Persian lives here too — the cabinet only speaks English and German.
    "other": (
        "persian",
        "persisch",
        "farsi",
        "french",
        "französisch",
        "spanish",
        "spanisch",
        "italian",
        "italienisch",
        "turkish",
        "türkisch",
        "arabic",
        "arabisch",
        "russian",
        "russisch",
        "chinese",
        "chinesisch",
        "japanese",
        "japanisch",
        "korean",
        "koreanisch",
        "dutch",
        "polish",
        "polnisch",
        "portuguese",
        "hindi",
        "ukrainian",
    ),
}
_LANG_HINTS = {
    "speak",
    "speaks",
    "talk",
    "switch",
    "language",
    "can",
    "know",
    "please",
    "sprich",
    "sprichst",
    "sprechen",
    "rede",
    "reden",
    "kannst",
    "sprache",
    "auf",
    "in",
    "bitte",
}


def language_request(text: str) -> str | None:
    """The language ('en'/'de') the person asked Arc to speak, or None."""
    tokens = set(re.sub(r"[^\w\s]", " ", text.lower()).split())
    if (
        len(tokens) > 8
    ):  # a long sentence merely *mentioning* a language isn't a request
        return None
    hit = None
    for lang, words in _LANG_WORDS.items():
        if tokens & set(words):
            if hit:
                return None  # both languages mentioned — ambiguous
            hit = lang
    if hit and (tokens & _LANG_HINTS or len(tokens) <= 2):
        return hit
    return None


# Accepting the game Arc just offered ("How about X?" — "Let's go for that!")
# must LAUNCH it, not re-recommend it. Matched in code, fuzzily.
_ACCEPTANCES = (
    "yes",
    "yes please",
    "yes it is",
    "yes do it",
    "that's it",
    "yes that's me",
    "that's me",
    "yes it's me",
    "it's me",
    "yes i am",
    "das bin ich",
    "ja das bin ich",
    "بله خودمم",
    "خودمم",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "sounds good",
    "بله",
    "آره",
    "باشه",
    "let's go",
    "let's go for that",
    "let's do it",
    "let's play it",
    "that one",
    "go for that",
    "perfect",
    "great",
    "ja",
    "ja bitte",
    "ja gerne",
    "gerne",
    "genau",
    "perfekt",
    "klingt gut",
    "das nehme ich",
    "machen wir",
    "los",
    "los geht's",
)


def is_acceptance(text: str) -> bool:
    t = re.sub(r"[^\w\s']", "", text.lower()).strip()
    if not t or len(t.split()) > 5:
        return False
    return bool(difflib.get_close_matches(t, _ACCEPTANCES, n=1, cutoff=0.8))


# "Close the game" arrives from whisper as "Kilo's the game" — while a game is
# running, a stop request is matched fuzzily in code, like goodbye.
_STOP_PHRASES = (
    "close the game",
    "close this game",
    "close it",
    "stop the game",
    "stop this game",
    "stop it",
    "quit the game",
    "end the game",
    "i'm done",
    "beende das spiel",
    "stopp das spiel",
    "schließ das spiel",
    "mach das spiel aus",
    "spiel beenden",
    "ich bin fertig",
)


def is_stop_request(text: str) -> bool:
    t = re.sub(r"[^\w\s']", "", text.lower()).strip()
    if not t or len(t.split()) > 5:
        return False
    return bool(difflib.get_close_matches(t, _STOP_PHRASES, n=1, cutoff=0.72))


# Joystick sides, including whisper's favorite mishearings ("Ride joystick").
_SIDE_WORDS = {
    "right": ("right", "ride", "wright", "rite", "rechts", "rechten", "rechte"),
    "left": ("left", "links", "linken", "linke"),
}
_JOYSTICK_WORDS = {"joystick", "joysticks", "controller", "stick"}


def side_word(text: str) -> str | None:
    """'left'/'right' if the utterance names a side at all (answering "which
    joystick?" is often just "the right one")."""
    tokens = set(re.sub(r"[^\w\s]", " ", text.lower()).split())
    for side, words in _SIDE_WORDS.items():
        if tokens & set(words):
            return side
    return None


def joystick_side(text: str) -> str | None:
    """'left'/'right' if the utterance names a joystick side, else None."""
    tokens = set(re.sub(r"[^\w\s]", " ", text.lower()).split())
    if not tokens & _JOYSTICK_WORDS:
        return None
    return side_word(text)


def _mentions_game_title(text: str) -> bool:
    low = text.lower()
    return any(
        g.title.lower() in low
        or any(w in low for w in g.title.lower().split() if len(w) > 4)
        for g in GAMES
    )


# For a create_profile intent, the name is extracted by CODE from the utterance,
# never taken from the model: given "Erstell mir bitte ein Profil" the 3B was seen
# returning name="Profil", name="Hersteller", even name="unspecified". A name only
# counts when it follows an explicit introduction cue; otherwise Arc asks for it.
_NAME_CUE = re.compile(
    r"(?:my name is|name's|i'?m|i am|this is|call me"
    r"|mein name ist|ich hei(?:ß|ss)e|ich bin|nenn mich)"
    r"\s+([A-Za-zÀ-ÿäöüß'\-]+(?:\s+[A-Za-zÀ-ÿäöüß'\-]+)?)",
    re.IGNORECASE,
)


def spelled_name(text: str) -> str | None:
    """A name spelled letter by letter ("It is K-I-A-N") — the person is
    correcting whisper's spelling, so this beats whatever name was heard."""
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    run: list[str] = []
    best: list[str] = []
    for tok in tokens + [""]:  # sentinel flushes the last run
        if len(tok) == 1 and tok.isalpha():
            run.append(tok)
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(best) < 3:  # "K I" alone is too little signal
        return None
    return "".join(best).capitalize()


def name_from_utterance(text: str) -> str | None:
    """The name a person introduced themselves with in `text`, or None."""
    spelled = spelled_name(text)
    if spelled:
        return spelled
    m = _NAME_CUE.search(text)
    if not m:
        return None
    return _clean_name(" ".join(w.capitalize() for w in m.group(1).split()))


def extract_name(text: str) -> str | None:
    """Pull a plausible name out of a "what's your name?" reply, else None."""
    spelled = spelled_name(text)
    if spelled:
        return spelled
    t = re.sub(r"[^\w\s'\-]", " ", text).strip()
    low = t.lower()
    for p in _NAME_PREFIXES:
        if low.startswith(p + " ") or low == p:
            t = t[len(p) :].strip()
            break
    words = t.split()
    if words and len(words) <= 2:  # a name is 1-2 words; more = a sentence
        return _clean_name(" ".join(w.capitalize() for w in words))
    # "Kean, it is K." — the name leads, the rest is trailing chatter.
    m = re.match(r"\s*([A-Za-zÀ-ÿäöüß]{2,})\s*[,.!]", text)
    if m:
        return _clean_name(m.group(1).capitalize())
    return None


# --- step 2: execute (pure code — owns all access control) ------------------


def _speaker(session) -> str:
    """Who is acting. First recognized person, else the guest."""
    for name in session.display_present():
        if name != "Guest":
            return name
    return "Guest"


def _same_running_game(session, title: str) -> bool:
    """True if `title` is (fuzzily) the game already running — asking to 'play
    Pong' while Pong is on isn't a request to close anything."""
    if not session.running_game or not title:
        return False
    return (
        difflib.SequenceMatcher(
            None, title.lower(), session.running_game.lower()
        ).ratio()
        >= 0.8
    )


def execute_intent(
    session, intent: dict, language: str = "en"
) -> tuple[str, dict, list[dict]]:
    """Run the intent deterministically. Returns (outcome_kind, data, actions).

    ALL access control lives here, in code — the model's classification never
    grants permission. Actions are the tool calls made, for the CLI log.
    """
    kind = intent.get("intent", "other")
    actions: list[dict] = []

    def do(tool_name: str, **args) -> dict:
        result = tools.run_tool(session, tool_name, args)
        actions.append(
            {
                "tool": tool_name,
                "args": args,
                "summary": tools.summarize(tool_name, args, result),
            }
        )
        return result

    def play(title: str) -> tuple[str, dict, list[dict]]:
        if intent.get("restart") and session.running_game:
            # Changing joystick mid-game means restarting the game with the
            # new mapping — the running emulator can't reroute inputs live.
            do("close_game")
        res = do("launch_game", title=title)
        if "error" in res:
            return "game_not_found", res, actions
        # They picked one — the browse context is over.
        session.last_suggested = None
        session.rejected = []
        side = intent.get("side")
        if not side and len(session.present) == 1:
            # Don't silently assume a joystick — the game starts and Arc asks
            # which one they want (the app keeps listening for the answer).
            # With two players the sides stay positional (one each).
            return "played_need_side", res, actions
        joystick = do("assign_joystick", player=_speaker(session), side=side)
        return "played", {**res, "joystick": joystick.get("joystick")}, actions

    def recommend(genre: str = "", query: str = "") -> tuple[str, dict, list[dict]]:
        # Naming a specific game IS the choice — launch it, don't re-offer it
        # ("I like Super Mario World, let's go for that" came back as
        # recommend(query="Super Mario World") and Arc replied "How about
        # Super Mario World?").
        if query:
            for candidate in [session.last_suggested] + [g.title for g in GAMES]:
                if (
                    candidate
                    and difflib.SequenceMatcher(
                        None, query.lower(), candidate.lower()
                    ).ratio()
                    >= 0.8
                ):
                    return play(candidate)
        # Asking again means the last offer was declined — never repeat it.
        if session.last_suggested and session.last_suggested not in session.rejected:
            session.rejected.append(session.last_suggested)
        res = do(
            "recommend_game", genre=genre, query=query, exclude=list(session.rejected)
        )
        session.last_suggested = res.get("recommendation")
        return "recommendation", res, actions

    # --- possibility gate: a running game must be closed first ---------------
    # Launching another game, remapping a joystick, turning the screen off or
    # changing privacy all disrupt a running game, so they're impossible until
    # it's closed — and Arc asks first. `_confirmed_close` is set once the
    # player has said yes (see handle_turn), so the action goes through.
    confirmed = bool(intent.pop("_confirmed_close", False))
    if (
        session.running_game
        and kind in _REQUIRE_NO_GAME
        and not confirmed
        and not (
            kind == "play_game" and _same_running_game(session, intent.get("title", ""))
        )
    ):
        session.pending_request = "confirm_close:" + json.dumps(intent)
        return "confirm_close", {"game": session.running_game}, actions
    if confirmed and session.running_game:
        do("close_game")

    if kind == "play_game":
        return play(intent.get("title", ""))

    if kind == "stop_game":
        if session.running_game is None and session.last_suggested:
            # "I said no Pong" mid-browse gets misread as stop_game; with nothing
            # running it's a rejection of the last offer — suggest something else.
            return recommend()
        return "stopped", do("close_game"), actions

    if kind == "joystick":
        side = intent.get("side") or ""
        if session.running_game and not intent.get("initial"):
            # Joystick mapping is part of launching the game — it can't change
            # while one is running. Offer to restart with the new side.
            session.pending_request = f"restart:{side or 'left'}"
            return (
                "joystick_in_game",
                {"side": side or "left", "game": session.running_game},
                actions,
            )
        res = do("assign_joystick", player=_speaker(session), side=side)
        return "joystick_set", res, actions

    if kind == "list_games":
        return "games_list", do("list_games"), actions

    if kind == "recommend":
        return recommend(genre=intent.get("genre", ""), query=intent.get("query", ""))

    if kind == "remember":
        note = (intent.get("note") or "").strip()
        if not note:
            # "What do you remember about me?" gets misrouted here — with no
            # actual note to store, answer from context instead of writing junk.
            return "context", do("get_context"), actions
        return (
            "remembered",
            do("remember", name=_speaker(session), note=note),
            actions,
        )

    if kind == "create_profile":
        # Guard: a pronoun ("me", "ich") is never a name. Without a real name we
        # ask for one — the app marks the session pending and the next utterance
        # is treated as the name.
        name = _clean_name(intent.get("name"))
        if name is None:
            return "ask_name", {}, actions
        if tools.store.get_profile(session.conn, name):
            # That name exists. Maybe the AI HAT filed the same person under a
            # new face — ask before creating a duplicate or overwriting.
            session.pending_request = f"merge:{name}"
            return "profile_exists", {"name": name}, actions
        return (
            "profile_created",
            do("create_profile", name=name, language=language),
            actions,
        )

    if kind == "delete_profile":
        target = _clean_name(intent.get("name")) or _speaker(session)
        if target == "Guest":
            return "error", {"error": "guests have no profile to delete"}, actions
        # Access: you may delete your own profile; deleting someone else needs an admin present.
        if (
            target.lower() != _speaker(session).lower()
            and tools._present_admin(session) is None
        ):
            return "access_denied", {"action": f"deleting {target}'s profile"}, actions
        return "profile_deleted", do("delete_profile", name=target), actions

    if kind == "set_privacy":
        # Access: privacy schedules are admin-only. Decided in CODE, not the model.
        if tools._present_admin(session) is None:
            return "access_denied", {"action": "changing privacy settings"}, actions
        res = do(
            "set_privacy_schedule",
            start=intent.get("start", ""),
            end=intent.get("end", ""),
            reason=intent.get("reason", ""),
        )
        return (
            ("privacy_set" if res.get("privacy_schedule_set") else "error"),
            res,
            actions,
        )

    if kind == "monitor":
        res = do("set_monitor", on=bool(intent.get("on", True)))
        return "monitor_set", res, actions

    if kind == "switch_language":
        lang = intent.get("language")
        if lang == "other":
            # Asked for a language Arc doesn't have (Persian, French, ...) — say
            # so honestly instead of "switching" to one it does have.
            return "language_unsupported", {}, actions
        if lang not in ("en", "de"):
            return "unclear", {}, actions
        speaker = _speaker(session)
        res = do(
            "set_language", language=lang, name="" if speaker == "Guest" else speaker
        )
        return "language_set", res, actions

    if kind == "get_context":
        return "context", do("get_context"), actions

    if kind == "goodbye":
        return "goodbye", {}, actions

    return "unclear", {}, actions


# --- step 3: phrase (templates first, model only for open-ended outcomes) ----


# Outcomes we answer without any model call (fast, and avoids odd 3B phrasings).
_CANNED = {
    "goodbye": {
        "en": "Have fun — see you next time!",
        "de": "Viel Spaß — bis bald!",
    },
    "unclear": {
        "en": "Sorry, I didn't catch that — could you say it again?",
        "de": "Entschuldigung, das habe ich nicht verstanden — nochmal bitte?",
    },
    "wake_ack": {
        "en": "Yes? I'm listening.",
        "de": "Ja? Ich höre.",
    },
    "ask_name": {
        "en": "Gladly! What's your name?",
        "de": "Gerne! Wie heißt du denn?",
    },
    "cancelled": {
        "en": "Okay, no problem.",
        "de": "Okay, kein Problem.",
    },
    "language_unsupported": {
        "en": "Sorry — I can speak English and German.",
        "de": "Entschuldigung — ich spreche Englisch und Deutsch.",
    },
    "ask_other_name": {
        "en": "No problem — what name should I save for you instead?",
        "de": "Kein Problem — unter welchem Namen soll ich dich dann speichern?",
    },
    # Appended whenever Arc goes back to ignoring gameplay chatter.
    "idle_hint": {
        "en": "I'll go quiet now — say 'Hey Arc' when you need me.",
        "de": "Ich bin jetzt still — sag 'Hey Arc', wenn du mich brauchst.",
    },
    # Someone said "Hey Arc" but the camera sees nobody at the cabinet.
    "come_over": {
        "en": "I can hear you, but I can't see anyone at the cabinet — come on over if you want to play!",
        "de": "Ich höre dich, aber ich sehe niemanden am Automaten — komm vorbei, wenn du spielen willst!",
    },
}

_JOY_DE = {"left": "linken", "right": "rechten"}


def _render(kind: str, data: dict, language: str) -> str | None:
    """Deterministic spoken line for an outcome, or None → let the model phrase it.

    Templates keep the common turns at ONE model call (the intent) — the phrasing
    LLM call only remains for open-ended outcomes (greeting, context questions).
    """
    if kind == "language_set":
        return {
            "de": "Alles klar — ab jetzt Deutsch!",
            "en": "Alright — English it is!",
        }.get(data.get("language"), "Alright!")

    de = language == "de"
    err = data.get("error")

    if kind == "confirm_close":
        game = data.get("game", "the game")
        if de:
            return f"Dafür müsste ich erst {game} schließen — soll ich das?"
        return f"I'd need to close {game} first — should I?"

    if kind == "played":
        joy = data.get("joystick") or "left"
        if de:
            return (
                f"{data['launched']} startet — nimm den {_JOY_DE.get(joy, joy)} "
                "Joystick. Viel Spaß! Sag 'Hey Arc', wenn du mich brauchst."
            )
        return (
            f"Starting {data['launched']} — grab the {joy} joystick. "
            "Have fun! Say 'Hey Arc' if you need me."
        )

    if kind == "played_need_side":
        if de:
            return (
                f"{data['launched']} startet! Welchen Joystick möchtest du — "
                "den linken oder den rechten?"
            )
        return (
            f"Starting {data['launched']}! Which joystick would you like — "
            "left or right?"
        )

    if kind == "game_not_found":
        opts = ", ".join(data.get("did_you_mean") or [])
        if de:
            return f"Dieses Spiel habe ich nicht gefunden. Meintest du {opts}?"
        return f"I couldn't find that game. Did you mean {opts}?"

    if kind == "stopped":
        if err:
            return (
                "Es läuft gerade kein Spiel."
                if de
                else "There's no game running right now."
            )
        if de:
            return (
                f"Okay, {data['closed']} ist beendet. Möchtest du noch etwas spielen?"
            )
        return f"Okay, I closed {data['closed']}. Want to play something else?"

    if kind == "games_list":
        titles = ", ".join(g["title"] for g in data.get("games", [])[:5])
        if de:
            return f"Du kannst zum Beispiel {titles} spielen."
        return f"You can play {titles}, and more."

    if kind == "recommendation":
        rec = data.get("recommendation")
        if rec is None:
            if data.get("reason") == "nothing left that matches":
                if de:
                    return "Hmm, da fällt mir nichts Passendes mehr ein — soll ich alle Spiele aufzählen?"
                return "Hmm, I'm out of matching ideas — want me to list all the games?"
            if de:
                return "Für heute ist leider keine Bildschirmzeit mehr übrig — vielleicht morgen!"
            return "Looks like there's no screen time left for today — maybe tomorrow!"
        others = [m for m in data.get("matches", []) if m != rec][:2]
        if others:
            also = ", ".join(others)
            if de:
                return f"Wie wäre es mit {rec}? Wir haben auch {also}."
            return f"How about {rec}? We also have {also}."
        return f"Wie wäre es mit {rec}?" if de else f"How about {rec}?"

    if kind == "remembered":
        if err:
            return (
                "Das konnte ich mir leider nicht merken — du hast noch kein Profil."
                if de
                else "I couldn't save that — you don't have a profile yet."
            )
        return (
            "Alles klar — das merke ich mir." if de else "Got it — I'll remember that."
        )

    if kind == "profile_created":
        who = data.get("created", "")
        if de:
            return f"Willkommen, {who}! Dein Profil ist gespeichert — nächstes Mal erkenne ich dich."
        return f"Welcome, {who}! Your profile is saved — I'll recognize you next time."

    if kind == "profile_deleted":
        if err:
            return (
                "Ich habe kein Profil unter diesem Namen gefunden."
                if de
                else "I couldn't find a profile under that name."
            )
        who = data.get("deleted", "")
        if de:
            return f"Erledigt — ich habe {who}s Profil und alles Gemerkte gelöscht."
        return f"Done — I've deleted {who}'s profile and everything I remembered."

    if kind == "privacy_set":
        if de:
            return f"Verstanden — Mikrofon und Kamera sind von {data['start']} bis {data['end']} aus."
        return f"Understood — mic and camera will be off from {data['start']} to {data['end']}."

    if kind == "access_denied":
        if de:
            return "Entschuldigung — das darf nur ein Admin."
        return "Sorry — only an admin can do that."

    if kind == "joystick_set":
        if err:
            return (
                "Entschuldigung, das hat nicht geklappt."
                if de
                else "Sorry, that didn't work."
            )
        joy = data.get("joystick", "left")
        who = data.get("player", "")
        if de:
            return f"Alles klar, {who} — du hast jetzt den {_JOY_DE.get(joy, joy)} Joystick."
        return f"Done, {who} — you've got the {joy} joystick now."

    if kind == "joystick_in_game":
        joy = data.get("side", "left")
        game = data.get("game", "")
        if de:
            return (
                f"Den Joystick kann ich nicht wechseln, während {game} läuft — "
                f"soll ich es mit dem {_JOY_DE.get(joy, joy)} Joystick neu starten?"
            )
        return (
            f"I can't swap joysticks while {game} is running — "
            f"should I restart it with the {joy} joystick?"
        )

    if kind == "profile_exists":
        who = data.get("name", "")
        if de:
            return f"Ich kenne schon eine Person namens {who} — bist du das? Soll ich das Profil laden?"
        return f"I already know someone called {who} — is that you? Should I use that profile?"

    if kind == "profile_merged":
        who = data.get("name", "")
        if de:
            return f"Willkommen zurück, {who}! Ich habe dein Profil geladen."
        return f"Welcome back, {who}! I've loaded your profile."

    if kind == "monitor_set":
        if data.get("monitor_on"):
            return (
                "Der Bildschirm ist an — bereit, wenn du es bist!"
                if de
                else "Screen is on — ready when you are!"
            )
        return (
            "Okay, ich schalte den Bildschirm aus."
            if de
            else "Okay, turning the screen off."
        )

    if kind == "error":
        return (
            "Entschuldigung, das hat nicht geklappt."
            if de
            else "Sorry, that didn't work."
        )

    return None  # open-ended outcome → the model phrases it


# What to say for the outcomes the model still phrases.
_PHRASE_INSTRUCTION = {
    "greeting": "Greet the people in the facts by name, mention what you remember "
    "if anything, and offer the suggestion. Only if someone has known=false (an "
    "unrecognized guest), offer to save a profile — never offer that to known people.",
    "context": "Answer the person's question naturally using the facts. If the "
    "facts don't contain the answer, say you're not sure — never make one up.",
    # Safety net only: EN/DE templates cover these, so the model is not reached.
    "joystick_in_game": "Explain you can't swap joysticks while the running game "
    "in the facts is on, and ask if you should restart it with that joystick.",
    "profile_exists": "Say you already know someone by the name in the facts and "
    "ask if that's them — should you load that profile?",
    "profile_merged": "Welcome them back by name; their profile is loaded.",
}


_LANG_NAMES = {"en": "English", "de": "German"}


def _canned(kind: str, language: str) -> str:
    lines = _CANNED[kind]
    return lines.get(language) or lines["en"]


def idle_hint(language: str) -> str:
    """The 'I'll go quiet now' notice, appended by the app when it flips a
    mid-game session back to wake-word-only listening."""
    return _canned("idle_hint", language)


def phrase(kind: str, data: dict, language: str, chat=_chat) -> str:
    """One spoken line for an outcome: canned → template → model, in that order.

    The cabinet speaks English and German only; both have hand-written templates,
    so the model is reached only for the open-ended outcomes (greeting, context).
    """
    if kind in _CANNED:
        return _canned(kind, language)
    rendered = _render(kind, data, language)
    if rendered is not None:
        return rendered
    lang = _LANG_NAMES.get(language, "English")
    instruction = _PHRASE_INSTRUCTION.get(kind, "Reply briefly.")
    system = f"{PERSONA} Speak in {lang}. Use only the facts given; never invent any."
    user = (
        f"{instruction}\nFacts (JSON): {json.dumps(data, ensure_ascii=False)}\n"
        "Say your short spoken reply now."
    )
    text = chat(system, user)
    return text or _canned("unclear", language)


# --- orchestration ----------------------------------------------------------


def greet(session, language: str, chat=_chat) -> tuple[str, list[dict]]:
    """Greeting: code loads each present person + a suggestion, then one phrasing call."""
    actions: list[dict] = []
    people = []
    for name in session.display_present():
        res = tools.run_tool(session, "get_player", {"name": name})
        actions.append(
            {
                "tool": "get_player",
                "args": {"name": name},
                "summary": tools.summarize("get_player", {}, res),
            }
        )
        # The raw "hint" is instructions for the phrasing prompt's author, not the
        # model — the 3B was seen echoing it verbatim ("[Hint]") into the greeting.
        people.append({k: v for k, v in res.items() if k != "hint"})
    rec = tools.run_tool(session, "recommend_game", {})
    actions.append(
        {
            "tool": "recommend_game",
            "args": {},
            "summary": tools.summarize("recommend_game", {}, rec),
        }
    )
    # Remember what was offered: if the person then asks for something else, the
    # greeting's suggestion counts as declined and won't be repeated.
    session.last_suggested = rec.get("recommendation")
    data = {"present": people, "suggestion": rec.get("recommendation")}
    return phrase("greeting", data, language, chat=chat), actions


def handle_turn(
    session, user_text: str, language: str, chat=_chat, pending: str | None = None
) -> tuple[str, list[dict], str]:
    """One conversational turn: route → execute (with access control) → phrase.

    `pending="name"` means the last turn asked for the person's name, so this
    utterance is first tried AS the name (no model call). Returns
    (spoken_text, actions, outcome_kind) — the app uses the kind to drive
    session state (pending question, attention, monitor).
    """
    intent = None
    note = ""
    if pending == "name":
        if is_cancel(user_text):
            routing = {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": "intent=cancelled (pending name)",
            }
            return phrase("cancelled", {}, language, chat=chat), [routing], "cancelled"
        name = extract_name(user_text)
        if name:
            intent = {"intent": "create_profile", "name": name}
            note = " (name from reply)"
    if pending == "joystick" and intent is None:
        # We just asked "which joystick?" — "the right one" is a full answer.
        answer = side_word(user_text)
        if answer:
            intent = {"intent": "joystick", "side": answer, "initial": True}
            note = " (side from reply)"
        elif is_cancel(user_text):
            routing = {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": "intent=cancelled (pending joystick)",
            }
            return phrase("cancelled", {}, language, chat=chat), [routing], "cancelled"
    if pending and pending.startswith("restart:") and intent is None:
        # We asked "should I restart on the other joystick?" — yes/no, or they
        # name a side directly ("the left one actually").
        wanted = side_word(user_text) or pending.split(":", 1)[1]
        if is_acceptance(user_text) or side_word(user_text):
            intent = {
                "intent": "play_game",
                "title": session.running_game,
                "side": wanted,
                "restart": True,
            }
            note = " (restart confirmed)"
        elif is_cancel(user_text):
            routing = {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": "intent=cancelled (kept current joystick)",
            }
            return phrase("cancelled", {}, language, chat=chat), [routing], "cancelled"
    if pending and pending.startswith("merge:") and intent is None:
        # We asked "I already know a {name} — is that you?"
        existing = pending.split(":", 1)[1]
        if is_acceptance(user_text):
            session.recognized_as = existing
            routing = {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": f"intent=profile_merged (recognized as {existing})",
            }
            return (
                phrase("profile_merged", {"name": existing}, language, chat=chat),
                [routing],
                "profile_merged",
            )
        if is_cancel(user_text):
            routing = {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": "intent=ask_other_name (same name, different person)",
            }
            return (
                phrase("ask_other_name", {}, language, chat=chat),
                [routing],
                "ask_other_name",
            )
    if pending and pending.startswith("confirm_close:") and intent is None:
        # We asked "should I close {game} first?" before doing something that
        # needs the game closed (play another, screen off, privacy).
        if is_acceptance(user_text) or is_stop_request(user_text):
            intent = json.loads(pending[len("confirm_close:") :])
            intent["_confirmed_close"] = True
            note = " (close confirmed)"
        elif is_cancel(user_text):
            routing = {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": "intent=cancelled (kept the game running)",
            }
            return phrase("cancelled", {}, language, chat=chat), [routing], "cancelled"
        # Anything else is a fresh request — fall through; if it also needs the
        # game closed, the gate in execute_intent asks again.
    if intent is None and is_goodbye(user_text):
        intent = {"intent": "goodbye"}
        note = " (matched in code)"
    if intent is None and (lang := language_request(user_text)):
        intent = {"intent": "switch_language", "language": lang}
        note = " (matched in code)"
    if intent is None and session.last_suggested and is_acceptance(user_text):
        # "How about X?" — "Let's go for that!" means PLAY X. Left to the model
        # this became another recommend (once even with a hallucinated query).
        intent = {"intent": "play_game", "title": session.last_suggested}
        note = " (accepted suggestion)"
    if intent is None and session.running_game and is_stop_request(user_text):
        # Whisper turns "Close the game" into "Kilo's the game" — fuzzy match.
        intent = {"intent": "stop_game"}
        note = " (matched in code)"
    side = joystick_side(user_text)
    if intent is None and side and not _mentions_game_title(user_text):
        # Pure joystick request ("wanna use the right joystick?").
        intent = {"intent": "joystick", "side": side}
        note = " (matched in code)"
    if intent is None:
        intent = classify_intent(
            user_text,
            session.display_present(),
            chat=chat,
            allowed=allowed_intents(session),
        )
        if intent.get("intent") == "create_profile":
            # Never trust the model with the name — code extracts it (or asks).
            intent["name"] = name_from_utterance(user_text)
        if intent.get("intent") == "switch_language":
            # Never trust the model's language either: its schema can only say
            # en|de, so "Can you speak Farsi?" (misheard: "for us") came back as
            # de. Code re-reads the utterance; no supported language named →
            # Arc states the two it has.
            intent["language"] = language_request(user_text) or "other"
    if intent.get("intent") in ("recommend", "list_games"):
        # Saying a game's full title IS choosing it, even when the model labels
        # the turn as browsing ("Let's go for Super Mario World" came back as
        # recommend(query="Mario") and Arc re-offered instead of launching).
        low = user_text.lower()
        named = next((g.title for g in GAMES if g.title.lower() in low), None)
        if named:
            intent = {"intent": "play_game", "title": named}
            note = " (named the game)"
    if side and "side" not in intent:
        # "Play Super Mario World on the right" — carry the side into launch.
        intent["side"] = side
    routing = {
        "tool": "route",
        "args": {"heard": user_text},
        "summary": f"intent={intent.get('intent')}{note}",
    }
    kind, data, actions = execute_intent(session, intent, language=language)
    if kind == "context":
        data = {**data, "question": user_text}
    out_language = session.new_language or language
    text = phrase(kind, data, out_language, chat=chat)
    return text, [routing, *actions], kind

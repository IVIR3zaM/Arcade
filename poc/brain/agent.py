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
        "note": {"type": "string"},
        "name": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "on": {"type": "boolean"},
        "language": {"type": "string", "enum": ["en", "de"]},
    },
    "required": ["intent"],
}


def _chat(system: str, user: str, as_json: bool = False) -> str:
    """One small Ollama chat call. Kept resident (keep_alive -1) and short."""
    import requests

    body = {
        "model": MODEL,
        "stream": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.1 if as_json else 0.3,
            "num_predict": 80 if as_json else 100,
            "num_thread": NUM_THREAD,
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
    '"sprich Deutsch" -> {"intent":"switch_language","language":"de"}\n'
    '"what time is it?" -> {"intent":"get_context"}\n'
    '"bye" -> {"intent":"goodbye"}\n'
    '"tschüss" -> {"intent":"goodbye"}'
)


def classify_intent(user_text: str, present: list[str], chat=_chat) -> dict:
    """Small JSON call: extract the user's intent. Never decides access."""
    titles = ", ".join(g.title for g in GAMES)
    system = (
        "You label what a person at an arcade wants, as JSON only (no prose). "
        "The person may speak English or German. "
        f"Intents: {', '.join(_INTENT_NAMES)}. Known games: {titles}."
    )
    user = (
        f"Examples:\n{_INTENT_EXAMPLES}\n\n"
        f'Now label this. The person said: "{user_text}"\n'
        "Return JSON with intent plus only the fields that apply "
        "(title, note, name, start, end, on, language). Convert times to 24h "
        "HH:MM. Only include name if the person actually said a name. If truly "
        'unrelated, use {"intent":"other"}.'
    )
    try:
        return json.loads(chat(system, user, as_json=True))
    except (json.JSONDecodeError, TypeError):
        return {"intent": "other"}


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


def _clean_name(name) -> str | None:
    """A usable person name from the model, or None.

    Rejects pronouns AND anything that isn't name-shaped: seen live, the 3B will
    pass the whole utterance as the name ("Herstell mir bitte ein Profil").
    Better to ask "what's your name?" than to save garbage.
    """
    n = str(name or "").strip().strip(".,!?")
    if not n or n.lower() in _PRONOUNS:
        return None
    if len(n.split()) > 2 or any(ch.isdigit() for ch in n):
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
}


def is_cancel(text: str) -> bool:
    return text.strip().strip(".,!?").lower() in _CANCEL_WORDS


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
)


def is_goodbye(text: str) -> bool:
    t = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if not t or len(t.split()) > 3:
        return False
    return bool(difflib.get_close_matches(t, _GOODBYES, n=1, cutoff=0.75))


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


def name_from_utterance(text: str) -> str | None:
    """The name a person introduced themselves with in `text`, or None."""
    m = _NAME_CUE.search(text)
    if not m:
        return None
    return _clean_name(" ".join(w.capitalize() for w in m.group(1).split()))


def extract_name(text: str) -> str | None:
    """Pull a plausible name out of a "what's your name?" reply, else None."""
    t = re.sub(r"[^\w\s'\-]", " ", text).strip()
    low = t.lower()
    for p in _NAME_PREFIXES:
        if low.startswith(p + " ") or low == p:
            t = t[len(p) :].strip()
            break
    words = t.split()
    if not words or len(words) > 2:  # a name is 1-2 words; more = a sentence
        return None
    name = " ".join(w.capitalize() for w in words)
    return _clean_name(name)


# --- step 2: execute (pure code — owns all access control) ------------------


def _speaker(session) -> str:
    """Who is acting. First recognized person, else the guest."""
    for name in session.display_present():
        if name != "Guest":
            return name
    return "Guest"


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

    if kind == "play_game":
        res = do("launch_game", title=intent.get("title", ""))
        if "error" in res:
            return "game_not_found", res, actions
        joystick = do("assign_joystick", player=_speaker(session))
        return "played", {**res, "joystick": joystick.get("joystick")}, actions

    if kind == "stop_game":
        return "stopped", do("close_game"), actions

    if kind == "list_games":
        return "games_list", do("list_games"), actions

    if kind == "recommend":
        return "recommendation", do("recommend_game"), actions

    if kind == "remember":
        return (
            "remembered",
            do("remember", name=_speaker(session), note=intent.get("note", "")),
            actions,
        )

    if kind == "create_profile":
        # Guard: a pronoun ("me", "ich") is never a name. Without a real name we
        # ask for one — the app marks the session pending and the next utterance
        # is treated as the name.
        name = _clean_name(intent.get("name"))
        if name is None:
            return "ask_name", {}, actions
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
    "goodbye": {"en": "Have fun — see you next time!", "de": "Viel Spaß — bis bald!"},
    "unclear": {
        "en": "Sorry, I didn't catch that — could you say it again?",
        "de": "Entschuldigung, das habe ich nicht verstanden — nochmal bitte?",
    },
    "wake_ack": {"en": "Yes? I'm listening.", "de": "Ja? Ich höre."},
    "ask_name": {"en": "Gladly! What's your name?", "de": "Gerne! Wie heißt du denn?"},
    "cancelled": {"en": "Okay, no problem.", "de": "Okay, kein Problem."},
}

_JOY_DE = {"left": "linken", "right": "rechten"}


def _render(kind: str, data: dict, language: str) -> str | None:
    """Deterministic spoken line for an outcome, or None → let the model phrase it.

    Templates keep the common turns at ONE model call (the intent) — the phrasing
    LLM call only remains for open-ended outcomes (greeting, context questions).
    """
    de = language == "de"
    err = data.get("error")

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
            if de:
                return "Für heute ist leider keine Bildschirmzeit mehr übrig — vielleicht morgen!"
            return "Looks like there's no screen time left for today — maybe tomorrow!"
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

    if kind == "language_set":
        return (
            "Alles klar — ab jetzt Deutsch!"
            if data.get("language") == "de"
            else "Alright — English it is!"
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
    "context": "Answer the person's question naturally using the facts.",
}


def phrase(kind: str, data: dict, language: str, chat=_chat) -> str:
    """One spoken line for an outcome: canned → template → model, in that order."""
    if kind in _CANNED:
        return _CANNED[kind]["de" if language == "de" else "en"]
    rendered = _render(kind, data, language)
    if rendered is not None:
        return rendered
    lang = "German" if language == "de" else "English"
    instruction = _PHRASE_INSTRUCTION.get(kind, "Reply briefly.")
    system = f"{PERSONA} Speak in {lang}. Use only the facts given; never invent any."
    user = (
        f"{instruction}\nFacts (JSON): {json.dumps(data, ensure_ascii=False)}\n"
        "Say your short spoken reply now."
    )
    text = chat(system, user)
    return text or _CANNED["unclear"]["de" if language == "de" else "en"]


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
        people.append(res)
    rec = tools.run_tool(session, "recommend_game", {})
    actions.append(
        {
            "tool": "recommend_game",
            "args": {},
            "summary": tools.summarize("recommend_game", {}, rec),
        }
    )
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
    if intent is None and is_goodbye(user_text):
        intent = {"intent": "goodbye"}
        note = " (matched in code)"
    if intent is None:
        intent = classify_intent(user_text, session.display_present(), chat=chat)
        if intent.get("intent") == "create_profile":
            # Never trust the model with the name — code extracts it (or asks).
            intent["name"] = name_from_utterance(user_text)
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

"""The manager, redesigned for a small on-device model.

A 3B model is bad at autonomously driving 11 tools in one big prompt, but good at
small, focused tasks. So instead of one giant tool-calling loop, each turn is a
short pipeline:

    1. classify_intent  — one tiny model call: "what does the user want?" (JSON)
    2. execute_intent    — CODE runs the action deterministically, INCLUDING all
                           access control (who is present and what they may do is
                           decided here, never by the model)
    3. phrase            — one tiny model call: turn the outcome into a spoken line

Both model calls use small prompts (no tool schemas), so they're fast on Pi-class
CPU, and the model is kept resident in RAM. The greeting skips step 1 (code knows
who walked up) — it loads the profile and does a single phrasing call.

The two model calls are injectable so the whole pipeline is testable without Ollama.
"""

import json
import os

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
_INTENTS = (
    "play_game(title), stop_game, list_games, recommend, remember(note), "
    "create_profile(name), delete_profile(name), set_privacy(start,end), "
    "get_context, goodbye, other"
)


def _chat(system: str, user: str, as_json: bool = False) -> str:
    """One small Ollama chat call. Kept resident (keep_alive -1) and short."""
    import requests

    body = {
        "model": MODEL,
        "stream": False,
        "keep_alive": -1,
        "options": {
            "temperature": 0.1 if as_json else 0.3,
            "num_predict": 120,
            "num_thread": NUM_THREAD,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if as_json:
        body["format"] = "json"
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=120)
    resp.raise_for_status()
    return (resp.json()["message"].get("content") or "").strip()


# --- step 1: intent (model) -------------------------------------------------


# Few-shot examples steer a 3B far better than a bare description. Times are
# normalized to 24h HH:MM here; the tool also tolerates casual times.
_INTENT_EXAMPLES = (
    '"let\'s play pong" -> {"intent":"play_game","title":"Pong"}\n'
    '"put on track and field" -> {"intent":"play_game","title":"Track & Field"}\n'
    '"stop the game" -> {"intent":"stop_game"}\n'
    '"what can I play?" -> {"intent":"list_games"}\n'
    '"what should I play?" -> {"intent":"recommend"}\n'
    '"remember I only play after 5pm" -> {"intent":"remember","note":"only plays after 5pm"}\n'
    '"save my profile, I\'m Sam" -> {"intent":"create_profile","name":"Sam"}\n'
    '"delete my profile" -> {"intent":"delete_profile"}\n'
    '"turn off the mic and camera every night from 8pm to 9am" -> '
    '{"intent":"set_privacy","start":"20:00","end":"09:00"}\n'
    '"what time is it?" -> {"intent":"get_context"}\n'
    '"bye" -> {"intent":"goodbye"}'
)


def classify_intent(user_text: str, present: list[str], chat=_chat) -> dict:
    """Small JSON call: extract the user's intent. Never decides access."""
    titles = ", ".join(g.title for g in GAMES)
    system = (
        "You label what a person at an arcade wants, as JSON only (no prose). "
        f"Intents: {_INTENTS}. Known games: {titles}."
    )
    user = (
        f"Examples:\n{_INTENT_EXAMPLES}\n\n"
        f'Now label this. The person said: "{user_text}"\n'
        "Return JSON with intent plus only the fields that apply "
        "(title, note, name, start, end). Convert times to 24h HH:MM. If truly "
        'unrelated, use {"intent":"other"}.'
    )
    try:
        return json.loads(chat(system, user, as_json=True))
    except (json.JSONDecodeError, TypeError):
        return {"intent": "other"}


# --- step 2: execute (pure code — owns all access control) ------------------


def _speaker(session) -> str:
    """Who is acting. First recognized person, else the guest."""
    for name in session.display_present():
        if name != "Guest":
            return name
    return "Guest"


def execute_intent(session, intent: dict) -> tuple[str, dict, list[dict]]:
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
        return (
            "profile_created",
            do("create_profile", name=intent.get("name", _speaker(session))),
            actions,
        )

    if kind == "delete_profile":
        target = intent.get("name") or _speaker(session)
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

    if kind == "get_context":
        return "context", do("get_context"), actions

    if kind == "goodbye":
        return "goodbye", {}, actions

    return "unclear", {}, actions


# --- step 3: phrase (model) -------------------------------------------------


# What to say for each outcome. The model fills in warm wording from the facts;
# these keep a 3B on-task instead of echoing the template.
_PHRASE_INSTRUCTION = {
    "greeting": "Greet the people in the facts by name, mention what you remember "
    "if anything, and offer the suggestion.",
    "played": "Tell them the game is starting and which joystick to use.",
    "game_not_found": "You couldn't find that game; suggest the ones in did_you_mean.",
    "stopped": "Confirm you stopped the game.",
    "games_list": "Tell them a few of the games they can play.",
    "recommendation": "Suggest the recommended game.",
    "remembered": "Warmly confirm you'll remember that.",
    "profile_created": "Welcome them and confirm their profile is saved.",
    "profile_deleted": "Confirm their profile was deleted.",
    "privacy_set": "Confirm the mic and camera will be off during that window.",
    "access_denied": "Politely explain you can't do that because only an admin can.",
    "context": "Answer naturally using the time/temperature facts.",
    "error": "Apologize briefly that it didn't work.",
}

# Outcomes we answer without a model call (fast, and avoids odd 3B phrasings).
_CANNED = {
    "goodbye": {"en": "Have fun — see you next time!", "de": "Viel Spaß — bis bald!"},
    "unclear": {
        "en": "Sorry, I didn't catch that — could you say it again?",
        "de": "Entschuldigung, das habe ich nicht verstanden — nochmal bitte?",
    },
}


def phrase(kind: str, data: dict, language: str, chat=_chat) -> str:
    """Turn a deterministic outcome into one spoken line (canned for simple cases)."""
    if kind in _CANNED:
        return _CANNED[kind]["de" if language == "de" else "en"]
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
    session, user_text: str, language: str, chat=_chat
) -> tuple[str, list[dict]]:
    """One conversational turn: route → execute (with access control) → phrase."""
    intent = classify_intent(user_text, session.display_present(), chat=chat)
    routing = {
        "tool": "route",
        "args": {"heard": user_text},
        "summary": f"intent={intent.get('intent')}",
    }
    kind, data, actions = execute_intent(session, intent)
    text = phrase(kind, data, language, chat=chat)
    return text, [routing, *actions]

"""The 'Pi brain' HTTP service.

Runs inside the CPU/RAM-limited container. The host CLI streams the mic
continuously (VAD-segmented utterances) — there is no push-to-talk — so this
service owns the ATTENTION state machine of a real cabinet:

    engaged  — a person was just greeted or said "Hey Arc": every utterance is
               handled. Times out back to idle after silence.
    idle     — a game is running, or the person went quiet: utterances are
               transcribed but IGNORED unless they start with the wake phrase
               ("Hey Arc"), so players talking to each other don't trigger Arc.

It also owns the monitor: on when someone walks up, off on request, and off
automatically when nothing has happened for a while (the host polls /tick so the
auto-off is visible in the CLI).

Sessions are kept in memory (single-user experience test). The SQLite connection
is opened per request because FastAPI serves sync endpoints across threads.
"""

import base64
import os
import tempfile
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import agent, hardware, stt, store, tts, wake
from .scenarios import GAMES, SCENARIOS
from .tools import Session, summarize

app = FastAPI(title="Arcade Companion PoC — Pi brain")

# After this long without speech, Arc stops handling every utterance and needs
# "Hey Arc" again (so it doesn't butt into people's conversations).
ENGAGE_TIMEOUT_S = float(os.environ.get("ENGAGE_TIMEOUT_S", "45"))
# With no game running and nothing said for this long, the monitor powers off.
MONITOR_IDLE_S = float(os.environ.get("MONITOR_IDLE_S", "120"))

# session_id -> {"present", "running_game", "language", "attention", "pending",
#                "last_activity"}
_SESSIONS: dict[str, dict] = {}

# Whisper hallucinates these on silence/noise; never treat them as speech.
# (Deliberately NOT "bye"/"danke" — those are real things an engaged person says.)
_JUNK = {
    "you",
    "thanks for watching",
    "thank you for watching",
    "untertitelung des zdf",
    "untertitel im auftrag des zdf",
    "copyright wdr",
}


def _is_junk(text: str) -> bool:
    t = text.strip().strip(".,!?* ").lower()
    return len(t) < 2 or t in _JUNK


@app.on_event("startup")
def _startup() -> None:
    conn = store.connect()
    store.init(conn)
    conn.close()


class StartRequest(BaseModel):
    scenario_id: str


class TurnRequest(BaseModel):
    session_id: str
    audio_b64: str


class TickRequest(BaseModel):
    session_id: str


class Action(BaseModel):
    tool: str
    args: dict
    summary: str


class Reply(BaseModel):
    session_id: str
    text: str
    audio_b64: str
    language: str
    actions: list[Action]
    user_text: str | None = None
    attention: str = "engaged"
    ignored: bool = False
    done: bool = False


def _speak(text: str, language: str) -> str:
    return base64.b64encode(tts.synthesize(text, language)).decode("ascii")


def _whisper_prompt(present_names: list[str]) -> str:
    """Bias whisper toward the wake phrase + real game/people names."""
    games = ", ".join(g.title for g in GAMES)
    people = ", ".join(n for n in store.list_profile_names(store.connect()) if n)
    return (
        f"Hey Arc. Tschüss. Erstell mir bitte ein Profil. Arcade games: {games}. "
        f"People: {people}. {' '.join(present_names)}."
    )


def _language_for(present: list[str]) -> str:
    """A known person's saved language; GERMAN is the cabinet's default."""
    conn = store.connect()
    for name in present:
        if name == "unknown":
            continue
        row = store.get_profile(conn, name)
        if row:
            return row["language"]
    return "de"


def _ignored(session_id: str, state: dict, user_text: str) -> Reply:
    """Heard something but not addressed — stay silent (no TTS)."""
    return Reply(
        session_id=session_id,
        text="",
        audio_b64="",
        language=state["language"],
        actions=[],
        user_text=user_text,
        attention=state["attention"],
        ignored=True,
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/scenarios")
def list_scenarios() -> list[dict]:
    return [
        {"id": sid, "description": s["description"]} for sid, s in SCENARIOS.items()
    ]


@app.post("/session/start", response_model=Reply)
def start(req: StartRequest) -> Reply:
    scenario = SCENARIOS.get(req.scenario_id)
    if scenario is None:
        raise HTTPException(404, f"unknown scenario: {req.scenario_id}")

    present = list(scenario["present"])
    session_id = uuid.uuid4().hex
    state = {
        "present": present,
        "running_game": None,
        "language": _language_for(present),
        "attention": "engaged",
        "pending": None,
        "last_activity": time.time(),
    }
    _SESSIONS[session_id] = state

    # Someone stepped into the camera frame → wake the monitor before speaking.
    hardware.set_monitor(True)
    actions = [
        {
            "tool": "set_monitor",
            "args": {"on": True},
            "summary": summarize("set_monitor", {}, {"monitor_on": True})
            + " (person detected)",
        }
    ]

    sess = Session(conn=store.connect(), present=present)
    text, greet_actions = agent.greet(sess, state["language"])

    state["running_game"] = sess.running_game
    return Reply(
        session_id=session_id,
        text=text,
        audio_b64=_speak(text, state["language"]),
        language=state["language"],
        actions=actions + greet_actions,
        attention="engaged",
    )


@app.post("/turn", response_model=Reply)
def turn(req: TurnRequest) -> Reply:
    state = _SESSIONS.get(req.session_id)
    if state is None:
        raise HTTPException(404, "unknown session")

    now = time.time()
    # Quiet for too long → require the wake word again.
    if (
        state["attention"] == "engaged"
        and now - state["last_activity"] > ENGAGE_TIMEOUT_S
    ):
        state["attention"] = "idle"

    with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
        wav.write(base64.b64decode(req.audio_b64))
        wav.flush()
        # language=None → whisper auto-detects EN vs DE. Forcing the session
        # language made whisper mangle English speech into German gibberish,
        # so a guest (default de) could never ask to switch to English.
        user_text, spoken_lang, lang_prob = stt.transcribe(
            wav.name,
            language=None,
            initial_prompt=_whisper_prompt(state["present"]),
        )
    # Trust whisper's pick with modest confidence: it already DECODED the audio
    # in that language, so replying in the other one is always worse. (0.7 was
    # too strict — "Can you speak any English?" transcribed as English yet the
    # session stayed German.)
    detected = spoken_lang if spoken_lang in ("en", "de") and lang_prob >= 0.5 else None

    actions: list[dict] = []
    woke = False
    if state["attention"] == "idle":
        woke, rest = wake.split_wake(user_text)
        if not woke:
            # Players chatting with each other — none of Arc's business.
            return _ignored(req.session_id, state, user_text)

    # Arc answers in the language the person actually spoke (German default
    # stands until someone speaks English). Only for turns it responds to —
    # overheard chatter never flips the language.
    if detected and detected != state["language"]:
        state["language"] = detected
        actions.append(
            {
                "tool": "set_language",
                "args": {"language": detected},
                "summary": f"language → {detected} (heard "
                + ("English)" if detected == "en" else "German)"),
            }
        )

    if woke:
        state["attention"] = "engaged"
        state["last_activity"] = now
        if not hardware.monitor_on():
            hardware.set_monitor(True)
            actions.append(
                {
                    "tool": "set_monitor",
                    "args": {"on": True},
                    "summary": summarize("set_monitor", {}, {"monitor_on": True})
                    + " (woken by voice)",
                }
            )
        if not rest.strip():
            # Just "Hey Arc" — acknowledge and listen.
            text = agent.phrase("wake_ack", {}, state["language"])
            return Reply(
                session_id=req.session_id,
                text=text,
                audio_b64=_speak(text, state["language"]),
                language=state["language"],
                actions=actions,
                user_text=user_text,
                attention="engaged",
            )
        user_text = rest

    if _is_junk(user_text):
        return _ignored(req.session_id, state, user_text)

    sess = Session(
        conn=store.connect(),
        present=state["present"],
        running_game=state["running_game"],
    )
    text, turn_actions, kind = agent.handle_turn(
        sess, user_text, state["language"], pending=state["pending"]
    )
    actions.extend(turn_actions)

    state["running_game"] = sess.running_game
    state["pending"] = "name" if kind == "ask_name" else None
    state["last_activity"] = now
    if sess.new_language:
        state["language"] = sess.new_language
    if kind == "played":
        # Game's on — stop reacting to gameplay chatter until "Hey Arc".
        state["attention"] = "idle"
    if kind == "profile_created":
        # The camera "learns" the new face: the guest is now a known person.
        created = next(
            (
                a["args"].get("name")
                for a in turn_actions
                if a["tool"] == "create_profile"
            ),
            None,
        )
        if created:
            state["present"] = [
                created if n == "unknown" else n for n in state["present"]
            ]

    done = kind == "goodbye"
    return Reply(
        session_id=req.session_id,
        text=text,
        audio_b64=_speak(text, state["language"]),
        language=state["language"],
        actions=actions,
        user_text=user_text,
        attention=state["attention"],
        done=done,
    )


@app.post("/tick")
def tick(req: TickRequest) -> dict:
    """Idle housekeeping, polled by the host while nobody is speaking: engaged →
    idle after silence, and monitor off after long inactivity with no game."""
    state = _SESSIONS.get(req.session_id)
    if state is None:
        raise HTTPException(404, "unknown session")

    now = time.time()
    actions: list[dict] = []
    if (
        state["attention"] == "engaged"
        and now - state["last_activity"] > ENGAGE_TIMEOUT_S
    ):
        state["attention"] = "idle"
        actions.append(
            {
                "tool": "attention",
                "args": {},
                "summary": "quiet for a while → say 'Hey Arc' to get my attention",
            }
        )
    if (
        hardware.monitor_on()
        and state["running_game"] is None
        and now - state["last_activity"] > MONITOR_IDLE_S
    ):
        hardware.set_monitor(False)
        actions.append(
            {
                "tool": "set_monitor",
                "args": {"on": False},
                "summary": summarize("set_monitor", {}, {"monitor_on": False})
                + " (idle timeout)",
            }
        )
    return {
        "attention": state["attention"],
        "monitor_on": hardware.monitor_on(),
        "actions": actions,
    }

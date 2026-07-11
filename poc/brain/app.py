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
import json
import os
import queue
import re
import tempfile
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import agent, hardware, stt, store, timing, tts, wake
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


def _spoken_content(text: str) -> bool:
    """True if `text` carries real spoken content (≥2 words) — the bar for
    trusting whisper's language guess enough to switch. The wake phrase alone
    ("Hey Arc") reads as English and must never flip a German cabinet, and a
    one-word reply ("okay") is too little signal."""
    return len(re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)) >= 2


@app.on_event("startup")
def _startup() -> None:
    conn = store.connect()
    store.init(conn)
    conn.close()
    # Load both Piper voices into THIS process now, so the first reply doesn't
    # pay the cold model-load cost mid-conversation.
    tts.warmup()


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
    timings: list[dict] = []  # per-step durations for the turn (last is "total")


def _speak(text: str, language: str) -> str:
    return base64.b64encode(tts.synthesize(text, language)).decode("ascii")


def _whisper_prompt(present_names: list[str]) -> str:
    """Bias whisper toward the wake phrase + real game/people names."""
    games = ", ".join(g.title for g in GAMES)
    people = ", ".join(n for n in store.list_profile_names(store.connect()) if n)
    return (
        f"Hey Arc. Tschüss. Erstell mir bitte ein Profil. "
        f"Arcade games: {games}. People: {people}. {' '.join(present_names)}."
    )


def _language_for(present: list[str]) -> str:
    """A known person's saved language; GERMAN is the cabinet's default. Persian
    is no longer supported, so an old fa profile falls back to German."""
    conn = store.connect()
    for name in present:
        if name == "unknown":
            continue
        row = store.get_profile(conn, name)
        if row:
            return "de" if row["language"] == "fa" else row["language"]
    return "de"


def _ignored(
    session_id: str, state: dict, user_text: str, timings: list[dict] | None = None
) -> Reply:
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
        timings=timings or [],
    )


def _reply_dict(reply: Reply) -> dict:
    return reply.model_dump() if hasattr(reply, "model_dump") else reply.dict()


def _stream_response(label: str, run) -> StreamingResponse:
    """Run `run(tl)` in a worker thread and stream its step events as NDJSON, then
    a final {"event":"reply", ...} carrying the whole Reply. The host reads the
    stream to show a live 'what's happening now + seconds elapsed' counter, so a
    slow step (STT, a model call) never looks like a silent freeze.

    Each line is one JSON object:
      {"event":"begin","step":"stt"}                 a step started
      {"event":"end","step":"stt","seconds":0.91}    ...and finished
      {"event":"total","seconds":2.86}               whole request done
      {"event":"reply","reply":{...}}                 the full Reply payload
    """
    events: queue.Queue = queue.Queue()
    tl = timing.Timeline(label, on_event=events.put)
    box: dict = {}

    def work() -> None:
        try:
            box["reply"] = run(tl)
        except Exception as exc:  # don't hang the stream on a bug — report it
            box["error"] = repr(exc)
        finally:
            events.put(None)  # sentinel: work finished

    threading.Thread(target=work, daemon=True).start()

    def body():
        while True:
            ev = events.get()
            if ev is None:
                break
            yield json.dumps(ev) + "\n"
        if "reply" in box:
            yield (
                json.dumps({"event": "reply", "reply": _reply_dict(box["reply"])})
                + "\n"
            )
        else:
            yield json.dumps({"event": "error", "message": box.get("error")}) + "\n"

    return StreamingResponse(body(), media_type="application/x-ndjson")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/scenarios")
def list_scenarios() -> list[dict]:
    return [
        {"id": sid, "description": s["description"]} for sid, s in SCENARIOS.items()
    ]


@app.post("/session/start")
def start(req: StartRequest) -> StreamingResponse:
    return _stream_response(f"greet {req.scenario_id}", lambda tl: _run_start(req, tl))


def _run_start(req: StartRequest, tl: "timing.Timeline") -> Reply:
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
        "last_suggested": None,
        "rejected": [],
        "game_started_at": None,
    }
    _SESSIONS[session_id] = state

    if not present:
        # Nobody in frame: monitor stays dark, no greeting — the cabinet just
        # listens quietly for "Hey Arc" from across the room.
        state["attention"] = "idle"
        return Reply(
            session_id=session_id,
            text="",
            audio_b64="",
            language=state["language"],
            actions=[
                {
                    "tool": "camera",
                    "args": {},
                    "summary": "nobody in frame — monitor stays off, listening for 'Hey Arc'",
                }
            ],
            attention="idle",
        )

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
    with tl.span("greet") as h:
        text, greet_actions = agent.greet(
            sess, state["language"], chat=timing.timed_chat(tl, agent._chat)
        )
    tl.record("code", h["elapsed"] - tl.model_seconds())

    state["running_game"] = sess.running_game
    state["last_suggested"] = sess.last_suggested
    with tl.step("tts"):
        audio = _speak(text, state["language"])
    return Reply(
        session_id=session_id,
        text=text,
        audio_b64=audio,
        language=state["language"],
        actions=actions + greet_actions,
        attention="engaged",
        timings=tl.finish(),
    )


@app.post("/turn")
def turn(req: TurnRequest) -> StreamingResponse:
    return _stream_response(f"turn {req.session_id[:6]}", lambda tl: _run_turn(req, tl))


def _run_turn(req: TurnRequest, tl: "timing.Timeline") -> Reply:
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
        with tl.step("stt"):
            user_text, spoken_lang, lang_prob = stt.transcribe(
                wav.name,
                language=None,
                initial_prompt=_whisper_prompt(state["present"]),
            )
    # Trust whisper's pick with decent confidence: it already DECODED the audio
    # in that language, so replying in the other one is always worse.
    detected = spoken_lang if spoken_lang in ("en", "de") and lang_prob >= 0.6 else None

    actions: list[dict] = []
    woke = False
    rest = ""
    if state["attention"] == "idle":
        woke, rest = wake.split_wake(user_text)
        if not woke:
            # Players chatting with each other — none of Arc's business.
            return _ignored(req.session_id, state, user_text, tl.finish())

    if not state["present"]:
        # "Hey Arc" heard, but the camera sees nobody at the cabinet — invite
        # them over and go back to quiet listening.
        actions.append(
            {
                "tool": "camera",
                "args": {},
                "summary": "wake word heard but nobody in frame — inviting over",
            }
        )
        state["last_activity"] = now
        # Just a wake shout from across the room — don't guess a language from
        # "Hey Arc"; invite them over in the cabinet's current language.
        lang = state["language"]
        text = agent.phrase("come_over", {}, lang)
        with tl.step("tts"):
            audio = _speak(text, lang)
        return Reply(
            session_id=req.session_id,
            text=text,
            audio_b64=audio,
            language=lang,
            actions=actions,
            user_text=user_text,
            attention="idle",
            timings=tl.finish(),
        )

    # Arc answers in the language the person is actually SPEAKING (German default
    # stands until someone genuinely speaks English). Judged only on real spoken
    # content: the wake phrase "Hey Arc" reads as English to whisper, so on its
    # own — or on a bare one-word reply — it must never flip the language. Only
    # for turns Arc responds to; overheard chatter never flips it either.
    content = rest if woke else user_text
    if detected and detected != state["language"] and _spoken_content(content):
        state["language"] = detected
        actions.append(
            {
                "tool": "set_language",
                "args": {"language": detected},
                "summary": f"language → {detected} (heard it spoken)",
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
            with tl.step("tts"):
                audio = _speak(text, state["language"])
            return Reply(
                session_id=req.session_id,
                text=text,
                audio_b64=audio,
                language=state["language"],
                actions=actions,
                user_text=user_text,
                attention="engaged",
                timings=tl.finish(),
            )
        user_text = rest

    if _is_junk(user_text):
        return _ignored(req.session_id, state, user_text, tl.finish())

    if spoken_lang not in ("en", "de") and lang_prob >= 0.6:
        # They spoke a language Arc doesn't have (e.g. Farsi) — the transcript
        # is unusable gibberish, so say so instead of guessing.
        actions.append(
            {
                "tool": "route",
                "args": {"heard": user_text},
                "summary": f"unsupported spoken language ({spoken_lang})",
            }
        )
        state["last_activity"] = now
        text = agent.phrase("language_unsupported", {}, state["language"])
        with tl.step("tts"):
            audio = _speak(text, state["language"])
        return Reply(
            session_id=req.session_id,
            text=text,
            audio_b64=audio,
            language=state["language"],
            actions=actions,
            user_text=user_text,
            attention=state["attention"],
            timings=tl.finish(),
        )

    sess = Session(
        conn=store.connect(),
        present=state["present"],
        running_game=state["running_game"],
        last_suggested=state.get("last_suggested"),
        rejected=list(state.get("rejected") or []),
        game_started_at=state.get("game_started_at"),
    )
    # handle_turn wraps route → execute → phrase. The model calls inside it are
    # timed individually (via timed_chat, logged as "intent"/"phrase"); the rest
    # of its wall time is deterministic code, recorded as "code".
    with tl.span("handle") as h:
        text, turn_actions, kind = agent.handle_turn(
            sess,
            user_text,
            state["language"],
            chat=timing.timed_chat(tl, agent._chat),
            pending=state["pending"],
        )
    tl.record("code", h["elapsed"] - tl.model_seconds())
    actions.extend(turn_actions)

    state["running_game"] = sess.running_game
    state["game_started_at"] = sess.game_started_at
    state["last_suggested"] = sess.last_suggested
    state["rejected"] = sess.rejected
    if sess.pending_request:
        # Arc just asked its own question ("restart on the left?" / "is that
        # you?") — the next utterance answers it.
        state["pending"] = sess.pending_request
    elif kind in ("ask_name", "ask_other_name"):
        state["pending"] = "name"
    elif kind == "played_need_side":
        state["pending"] = "joystick"
    elif kind not in ("unclear", "context"):
        # An unclear/side reply doesn't withdraw the question Arc just asked
        # ("what's your name?") — the person can still answer it next.
        state["pending"] = None
    state["last_activity"] = now
    if sess.new_language:
        state["language"] = sess.new_language
    if kind == "played":
        # Game's on — stop reacting to gameplay chatter until "Hey Arc".
        state["attention"] = "idle"
    elif (
        state["running_game"]
        and state["pending"] is None
        and kind
        not in (
            "unclear",
            "stopped",
            "recommendation",
            "games_list",
        )
    ):
        # Mid-game, Arc handles the woken request and then goes right back to
        # ignoring gameplay chatter — the next request needs "Hey Arc" again.
        # It stays engaged only while a question is open (pending, unclear) or
        # while they're actively browsing for a different game. SAY so — going
        # silent without warning felt like a bug.
        state["attention"] = "idle"
        text = f"{text} {agent.idle_hint(state['language'])}"
    recognized = sess.recognized_as
    if kind == "profile_created":
        # The camera "learns" the new face: the guest is now a known person.
        recognized = next(
            (
                a["args"].get("name")
                for a in turn_actions
                if a["tool"] == "create_profile"
            ),
            None,
        )
    if recognized:
        # Newly created, or merged into an existing profile ("is that you?" —
        # "yes"): either way the guest is now this known person.
        state["present"] = [
            recognized if n == "unknown" else n for n in state["present"]
        ]

    done = kind == "goodbye"
    with tl.step("tts"):
        audio = _speak(text, state["language"])
    return Reply(
        session_id=req.session_id,
        text=text,
        audio_b64=audio,
        language=state["language"],
        actions=actions,
        user_text=user_text,
        attention=state["attention"],
        done=done,
        timings=tl.finish(),
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

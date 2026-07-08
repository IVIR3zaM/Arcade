"""The 'Pi brain' HTTP service.

Runs inside the CPU/RAM-limited container. It exposes the scenario picker and two
turn endpoints to the host mic/speaker CLI. Each turn is driven by the LLM manager
(agent.py) calling tools (tools.py) against the persistent store (store.py); the
tool calls are returned to the CLI so you can watch what the model actually did.

Sessions are kept in memory (single-user experience test). The SQLite connection
is opened per request because FastAPI serves sync endpoints across threads.
"""

import base64
import tempfile
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import agent, stt, store, tts
from .scenarios import GAMES, SCENARIOS
from .tools import Session

app = FastAPI(title="Arcade Companion PoC — Pi brain")

# session_id -> {"present", "running_game", "history", "language"}
_SESSIONS: dict[str, dict] = {}


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
    done: bool = False


def _speak(text: str, language: str) -> str:
    return base64.b64encode(tts.synthesize(text, language)).decode("ascii")


def _whisper_prompt(present_names: list[str]) -> str:
    """Bias whisper toward the real game + people names so it stops mishearing them."""
    games = ", ".join(g.title for g in GAMES)
    people = ", ".join(n for n in store.list_profile_names(store.connect()) if n)
    return f"Arcade games: {games}. People: {people}. {' '.join(present_names)}."


def _language_for(present: list[str]) -> str:
    conn = store.connect()
    for name in present:
        if name == "unknown":
            continue
        row = store.get_profile(conn, name)
        if row:
            return row["language"]
    return "en"


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

    present = scenario["present"]
    session_id = uuid.uuid4().hex
    state = {
        "present": present,
        "running_game": None,
        "language": _language_for(present),
    }
    _SESSIONS[session_id] = state

    sess = Session(conn=store.connect(), present=present)
    text, actions = agent.greet(sess, state["language"])

    state["running_game"] = sess.running_game
    return Reply(
        session_id=session_id,
        text=text,
        audio_b64=_speak(text, state["language"]),
        language=state["language"],
        actions=actions,
    )


@app.post("/turn", response_model=Reply)
def turn(req: TurnRequest) -> Reply:
    state = _SESSIONS.get(req.session_id)
    if state is None:
        raise HTTPException(404, "unknown session")

    with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
        wav.write(base64.b64decode(req.audio_b64))
        wav.flush()
        user_text = stt.transcribe(
            wav.name,
            language=state["language"],
            initial_prompt=_whisper_prompt(state["present"]),
        )

    sess = Session(
        conn=store.connect(),
        present=state["present"],
        running_game=state["running_game"],
    )
    text, actions = agent.handle_turn(sess, user_text, state["language"])

    state["running_game"] = sess.running_game

    done = any(w in user_text.lower() for w in ("bye", "goodbye", "tschüss", "ciao"))
    return Reply(
        session_id=req.session_id,
        text=text,
        audio_b64=_speak(text, state["language"]),
        language=state["language"],
        actions=actions,
        user_text=user_text,
        done=done,
    )

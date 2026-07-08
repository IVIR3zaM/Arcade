"""Tests for the manager pipeline: intent classification, deterministic execution
(with access control in code), and phrasing — all with the model stubbed."""

import json
import sqlite3

from brain import agent, store
from brain.tools import Session


def _session(present):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return Session(conn=conn, present=present)


def _chat_returning(payload):
    """A fake model that returns `payload` (a dict is JSON-encoded for intent calls)."""

    def chat(system, user, as_json=False):
        return json.dumps(payload) if as_json else payload

    return chat


# --- classify_intent --------------------------------------------------------


def test_classify_intent_parses_json():
    chat = _chat_returning({"intent": "play_game", "title": "Pong"})
    intent = agent.classify_intent("let's play pong", ["Leo"], chat=chat)
    assert intent == {"intent": "play_game", "title": "Pong"}


def test_classify_intent_falls_back_on_bad_json():
    def chat(system, user, as_json=False):
        return "not json at all"

    assert agent.classify_intent("???", ["Leo"], chat=chat)["intent"] == "other"


# --- execute_intent (pure, no model) ---------------------------------------


def test_execute_play_game_launches_and_assigns_joystick():
    kind, data, actions = agent.execute_intent(
        _session(["Leo"]), {"intent": "play_game", "title": "Point"}
    )
    assert kind == "played"
    assert data["launched"] == "Pong"  # fuzzy-corrected in code
    assert data["joystick"] == "left"
    assert [a["tool"] for a in actions] == ["launch_game", "assign_joystick"]


def test_execute_privacy_is_admin_gated_in_code():
    # Non-admin present: code denies before any tool runs.
    kind, data, actions = agent.execute_intent(
        _session(["Leo"]), {"intent": "set_privacy", "start": "20:00", "end": "09:00"}
    )
    assert kind == "access_denied"
    assert actions == []  # nothing executed

    # Admin present: code allows and the schedule is stored.
    sess = _session(["Reza"])
    kind, data, actions = agent.execute_intent(
        sess, {"intent": "set_privacy", "start": "8pm", "end": "9am"}
    )
    assert kind == "privacy_set"
    assert store.list_schedules(sess.conn)[0]["start_hm"] == "20:00"


def test_execute_delete_other_profile_requires_admin():
    kind, _data, actions = agent.execute_intent(
        _session(["Leo"]), {"intent": "delete_profile", "name": "Mia"}
    )
    assert kind == "access_denied"
    assert store.get_profile(_session(["Leo"]).conn, "Mia") is not None


def test_execute_remember_stores_for_the_speaker():
    sess = _session(["Leo"])
    kind, _data, _actions = agent.execute_intent(
        sess, {"intent": "remember", "note": "only plays after 5pm"}
    )
    assert kind == "remembered"
    assert "after 5pm" in store.get_profile(sess.conn, "Leo")["notes"]


# --- orchestration ----------------------------------------------------------


def test_handle_turn_routes_then_phrases():
    calls = []

    def chat(system, user, as_json=False):
        calls.append(as_json)
        if as_json:
            return json.dumps({"intent": "play_game", "title": "Pong"})
        return "Pong is on — use the left joystick!"

    sess = _session(["Leo"])
    text, actions = agent.handle_turn(sess, "play pong", "en", chat=chat)
    assert text == "Pong is on — use the left joystick!"
    assert calls == [True, False]  # one JSON intent call, then one phrasing call
    assert actions[0]["tool"] == "route"
    assert sess.running_game == "Pong"


def test_phrase_uses_canned_lines_without_calling_the_model():
    def boom(system, user, as_json=False):
        raise AssertionError("phrase should not call the model for canned outcomes")

    assert "fun" in agent.phrase("goodbye", {}, "en", chat=boom).lower()
    assert agent.phrase("unclear", {}, "de", chat=boom).startswith("Entschuldigung")


def test_greet_loads_profile_then_phrases_once():
    def chat(system, user, as_json=False):
        assert as_json is False  # greeting never needs an intent call
        return "Welcome back, Leo!"

    text, actions = agent.greet(_session(["Leo"]), "en", chat=chat)
    assert text == "Welcome back, Leo!"
    assert [a["tool"] for a in actions] == ["get_player", "recommend_game"]

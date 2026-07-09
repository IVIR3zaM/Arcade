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


def test_handle_turn_routes_then_uses_template_one_model_call():
    calls = []

    def chat(system, user, as_json=False):
        calls.append(as_json)
        return json.dumps({"intent": "play_game", "title": "Pong"})

    sess = _session(["Leo"])
    text, actions, kind = agent.handle_turn(sess, "play pong", "en", chat=chat)
    assert "Pong" in text and "left" in text  # deterministic template, no 2nd call
    assert calls == [True]  # ONE model call per typical turn now
    assert kind == "played"
    assert actions[0]["tool"] == "route"
    assert sess.running_game == "Pong"


def test_phrase_uses_canned_lines_without_calling_the_model():
    def boom(system, user, as_json=False):
        raise AssertionError("phrase should not call the model for canned outcomes")

    assert "fun" in agent.phrase("goodbye", {}, "en", chat=boom).lower()
    assert agent.phrase("unclear", {}, "de", chat=boom).startswith("Entschuldigung")


def test_create_profile_with_pronoun_name_asks_for_the_real_name():
    # The 3B's classic failures: create_profile(name="me"), or handing the whole
    # utterance over as the name (seen live). Code catches both.
    for bad in ("me", "mir", "", None, "unspecified", "Herstell mir bitte ein Profil"):
        kind, _data, actions = agent.execute_intent(
            _session(["unknown"]), {"intent": "create_profile", "name": bad}
        )
        assert kind == "ask_name"
        assert actions == []  # nothing created


def test_pending_name_reply_creates_the_profile_without_a_model_call():
    def boom(system, user, as_json=False):
        raise AssertionError("the name reply must not need the model")

    sess = _session(["unknown"])
    text, actions, kind = agent.handle_turn(
        sess, "My name is Sam.", "de", chat=boom, pending="name"
    )
    assert kind == "profile_created"
    assert store.get_profile(sess.conn, "Sam")["language"] == "de"
    assert "Sam" in text


def test_pending_name_can_be_cancelled():
    def boom(system, user, as_json=False):
        raise AssertionError("cancel must not need the model")

    _text, _actions, kind = agent.handle_turn(
        _session(["unknown"]), "nein danke", "de", chat=boom, pending="name"
    )
    assert kind == "cancelled"


def test_goodbye_is_matched_fuzzily_in_code_without_the_model():
    def boom(system, user, as_json=False):
        raise AssertionError("goodbye must not need the model")

    # Whisper renders "Tschüss!" as "Schüsse" — still a goodbye.
    for heard in ("bye", "Tschüss!", "Schüsse.", "goodbye"):
        _text, _actions, kind = agent.handle_turn(
            _session(["Leo"]), heard, "de", chat=boom
        )
        assert kind == "goodbye", heard
    assert not agent.is_goodbye("let's play pong")


def test_extract_name():
    assert agent.extract_name("my name is Sam") == "Sam"
    assert agent.extract_name("Ich heiße Sam Miller!") == "Sam Miller"
    assert agent.extract_name("sam") == "Sam"
    assert agent.extract_name("I don't want to tell you that") is None


def test_name_comes_from_the_utterance_not_the_model():
    # The model says name="Profil" — code overrides with what was actually said.
    def chat(system, user, as_json=False):
        return json.dumps({"intent": "create_profile", "name": "Profil"})

    sess = _session(["unknown"])
    _text, _actions, kind = agent.handle_turn(
        sess, "Erstell mir bitte ein Profil.", "de", chat=chat
    )
    assert kind == "ask_name"  # no introduction cue → ask, don't guess

    _text, _actions, kind = agent.handle_turn(
        sess, "Save my profile, I'm Sam.", "en", chat=chat
    )
    assert kind == "profile_created"
    assert store.get_profile(sess.conn, "Sam") is not None
    assert store.get_profile(sess.conn, "Profil") is None


def test_language_request_is_matched_in_code_without_the_model():
    def boom(system, user, as_json=False):
        raise AssertionError("a language request must not need the model")

    sess = _session(["unknown"])
    _text, actions, kind = agent.handle_turn(
        sess, "Can you speak any English?", "de", chat=boom
    )
    assert kind == "language_set"
    assert sess.new_language == "en"
    assert "(matched in code)" in actions[0]["summary"]

    assert agent.language_request("Sprich bitte Deutsch") == "de"
    assert agent.language_request("English!") == "en"
    # Merely mentioning a language in a longer sentence is not a request.
    assert (
        agent.language_request(
            "I read a long English book about arcade games yesterday"
        )
        is None
    )
    assert agent.language_request("let's play pong") is None


def test_name_from_utterance():
    assert agent.name_from_utterance("save my profile, I'm Sam") == "Sam"
    assert agent.name_from_utterance("Ich heiße Mia Weber, bitte") == "Mia Weber"
    assert agent.name_from_utterance("Erstell mir bitte ein Profil") is None
    assert agent.name_from_utterance("create a profile for me") is None


def test_monitor_and_language_intents():
    sess = _session(["Leo"])
    kind, data, _ = agent.execute_intent(sess, {"intent": "monitor", "on": False})
    assert (kind, data["monitor_on"]) == ("monitor_set", False)

    kind, data, _ = agent.execute_intent(
        sess, {"intent": "switch_language", "language": "de"}
    )
    assert kind == "language_set"
    assert sess.new_language == "de"
    assert store.get_profile(sess.conn, "Leo")["language"] == "de"  # persisted


def test_templates_render_in_german_without_the_model():
    def boom(system, user, as_json=False):
        raise AssertionError("templated outcomes must not call the model")

    text = agent.phrase(
        "played", {"launched": "Pong", "joystick": "left"}, "de", chat=boom
    )
    assert "Pong" in text and "linken" in text and "Hey Arc" in text
    assert "Admin" in agent.phrase("access_denied", {"action": "x"}, "de", chat=boom)


def test_greet_loads_profile_then_phrases_once():
    def chat(system, user, as_json=False):
        assert as_json is False  # greeting never needs an intent call
        return "Welcome back, Leo!"

    text, actions = agent.greet(_session(["Leo"]), "en", chat=chat)
    assert text == "Welcome back, Leo!"
    assert [a["tool"] for a in actions] == ["get_player", "recommend_game"]

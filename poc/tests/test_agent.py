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


def test_execute_play_game_with_side_launches_and_assigns_joystick():
    kind, data, actions = agent.execute_intent(
        _session(["Leo"]), {"intent": "play_game", "title": "Point", "side": "left"}
    )
    assert kind == "played"
    assert data["launched"] == "Pong"  # fuzzy-corrected in code
    assert data["joystick"] == "left"
    assert [a["tool"] for a in actions] == ["launch_game", "assign_joystick"]


def test_execute_play_game_without_side_asks_which_joystick():
    # Single player, no side spoken → the game starts but Arc ASKS instead of
    # silently assuming "left".
    sess = _session(["Leo"])
    kind, data, actions = agent.execute_intent(
        sess, {"intent": "play_game", "title": "Pong"}
    )
    assert kind == "played_need_side"
    assert sess.running_game == "Pong"
    assert [a["tool"] for a in actions] == ["launch_game"]  # no assignment yet
    text = agent.phrase("played_need_side", data, "en", chat=None)
    assert "left or right" in text


def test_two_players_get_positional_joysticks_without_asking():
    kind, data, _actions = agent.execute_intent(
        _session(["Leo", "Mia"]), {"intent": "play_game", "title": "Pong"}
    )
    assert kind == "played"
    assert data["joystick"] == "left"  # the speaker (Leo) is first in line


def test_pending_joystick_answer_assigns_the_side():
    def boom(system, user, as_json=False):
        raise AssertionError("a side answer must not need the model")

    sess = _session(["Leo"])
    sess.running_game = "Pong"
    text, _actions, kind = agent.handle_turn(
        sess, "The right one, please.", "en", chat=boom, pending="joystick"
    )
    assert kind == "joystick_set"
    assert "right" in text


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
    assert "Pong" in text and "left or right" in text  # template asks for a side
    assert calls == [True]  # ONE model call per typical turn now
    assert kind == "played_need_side"
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
    # The name leads, trailing chatter follows (seen live).
    assert agent.extract_name("Kean, it is K.") == "Kean"


def test_spelled_name_beats_the_heard_spelling():
    # "My name is Kean. It is K-I-A-N." must save Kian, not Kean.
    assert agent.spelled_name("My name is Kean. It is K-I-A-N.") == "Kian"
    assert agent.extract_name("Kean. It is K-I-A-N.") == "Kian"
    assert agent.name_from_utterance("My name is Kean, K-I-A-N") == "Kian"
    assert agent.spelled_name("my name is Sam") is None  # no spelled run


def test_recommend_honors_genre_and_rejections():
    sess = _session(["unknown"])
    # Greeting suggested Pong; asking for sport must NOT repeat it.
    sess.last_suggested = "Pong"
    kind, data, _ = agent.execute_intent(
        sess, {"intent": "recommend", "genre": "sport"}
    )
    assert kind == "recommendation"
    assert data["recommendation"] == "Track & Field"  # the other sports game
    assert "Pong" in sess.rejected

    # "something from Mario" filters by title keyword.
    sess2 = _session(["unknown"])
    _kind, data, _ = agent.execute_intent(
        sess2, {"intent": "recommend", "query": "Mario"}
    )
    assert "Mario" in data["recommendation"]


def test_asking_for_farsi_switches_asking_for_french_does_not():
    def boom(system, user, as_json=False):
        raise AssertionError("must not need the model")

    # Farsi is enabled (experimental) — switching works.
    sess = _session(["unknown"])
    _text, _actions, kind = agent.handle_turn(
        sess, "Can you speak Farsi?", "en", chat=boom
    )
    assert kind == "language_set"
    assert sess.new_language == "fa"

    # A language Arc doesn't have gets an honest refusal, not a wrong switch.
    sess2 = _session(["unknown"])
    text, _actions, kind = agent.handle_turn(
        sess2, "Can you speak French?", "en", chat=boom
    )
    assert kind == "language_unsupported"
    assert "English, German" in text
    assert sess2.new_language is None


def test_model_switch_language_is_revalidated_against_the_utterance():
    # Whisper heard "Can you speak Farsi?" as "for us"; the model's schema can
    # only answer en|de and picked de. Code must not switch on that.
    def chat(system, user, as_json=False):
        return json.dumps({"intent": "switch_language", "language": "de"})

    sess = _session(["unknown"])
    _text, _actions, kind = agent.handle_turn(
        sess, "Can you speak for us?", "en", chat=chat
    )
    assert kind == "language_unsupported"
    assert sess.new_language is None


def test_accepting_the_suggestion_launches_it():
    def boom(system, user, as_json=False):
        raise AssertionError("acceptance must not need the model")

    sess = _session(["unknown"])
    sess.last_suggested = "Super Mario World"
    _text, _actions, kind = agent.handle_turn(
        sess, "Let's go for that.", "en", chat=boom
    )
    assert kind == "played_need_side"  # launched; Arc asks which joystick
    assert sess.running_game == "Super Mario World"


def test_recommend_query_naming_a_full_title_launches_it():
    # "I like Super Mario World, let's go for that" comes back from the model as
    # recommend(query="Super Mario World") — that's a choice, not a browse.
    sess = _session(["unknown"])
    kind, data, _ = agent.execute_intent(
        sess, {"intent": "recommend", "query": "Super Mario World"}
    )
    assert kind == "played_need_side"  # launched; Arc asks which joystick
    assert data["launched"] == "Super Mario World"

    # A vague keyword ("Mario") still browses.
    sess2 = _session(["unknown"])
    kind, _data, _ = agent.execute_intent(
        sess2, {"intent": "recommend", "query": "Mario"}
    )
    assert kind == "recommendation"


def test_joystick_request_is_matched_in_code():
    def boom(system, user, as_json=False):
        raise AssertionError("a joystick request must not need the model")

    sess = _session(["unknown"])
    sess.running_game = "Super Mario World"
    text, _actions, kind = agent.handle_turn(
        sess,
        "I wanna use Ride joystick.",
        "en",
        chat=boom,  # whisper's "right"
    )
    assert kind == "joystick_set"
    assert "right" in text


def test_play_game_with_spoken_side_overrides_position():
    def chat(system, user, as_json=False):
        return json.dumps({"intent": "play_game", "title": "Super Mario World"})

    sess = _session(["unknown"])
    _text, actions, kind = agent.handle_turn(
        sess, "Play Super Mario World on the right joystick.", "en", chat=chat
    )
    assert kind == "played"
    joystick = next(a for a in actions if a["tool"] == "assign_joystick")
    assert joystick["args"]["side"] == "right"


def test_naming_the_full_title_mid_browse_launches_it():
    # Model labels "Let's go for Super Mario World" as recommend(query="Mario") —
    # the full title in the utterance overrides and launches.
    def chat(system, user, as_json=False):
        return json.dumps({"intent": "recommend", "query": "Mario"})

    sess = _session(["unknown"])
    _text, actions, kind = agent.handle_turn(
        sess, "Let's go for Super Mario World.", "en", chat=chat
    )
    assert kind == "played_need_side"
    assert sess.running_game == "Super Mario World"
    assert "(named the game)" in actions[0]["summary"]


def test_come_over_line_exists_in_all_three_languages():
    for lang in ("en", "de", "fa"):
        line = agent.phrase("come_over", {}, lang, chat=None)
        assert line  # canned — no model involved


def test_misheard_close_request_stops_the_running_game():
    def boom(system, user, as_json=False):
        raise AssertionError("a stop request must not need the model")

    sess = _session(["unknown"])
    sess.running_game = "Super Mario World"
    _text, _actions, kind = agent.handle_turn(
        sess,
        "Kilo's the game.",
        "en",
        chat=boom,  # whisper's "Close the game"
    )
    assert kind == "stopped"
    assert sess.running_game is None


def test_no_game_running_plus_rejection_suggests_something_else():
    # "I said no Pong" gets misrouted to stop_game; with nothing running and a
    # live suggestion it's a rejection → recommend another game, not an error.
    sess = _session(["unknown"])
    sess.last_suggested = "Pong"
    kind, data, _ = agent.execute_intent(sess, {"intent": "stop_game"})
    assert kind == "recommendation"
    assert data["recommendation"] != "Pong"


def test_greeting_facts_do_not_include_the_raw_hint():
    prompts = []

    def chat(system, user, as_json=False):
        prompts.append(user)
        return "Welcome!"

    agent.greet(_session(["unknown"]), "en", chat=chat)
    assert "hint" not in prompts[0]  # the 3B echoed "[Hint]" into speech once


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

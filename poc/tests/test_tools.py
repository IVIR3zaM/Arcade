"""Tests for the MCP-style tools — especially that they enforce truth (fuzzy-match
to the real catalog) and gate admin actions."""

import sqlite3

from brain import store, tools
from brain.tools import Session


def _session(present):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return Session(conn=conn, present=present)


def test_launch_game_fuzzy_matches_misheard_title():
    # The exact bug the user hit: "Point" should become "Pong", not a made-up game.
    result = tools.launch_game(_session(["Kian"]), "Point")
    assert result["launched"] == "Pong"
    assert result["requested"] == "Point"


def test_launch_game_rejects_unknown_title_with_suggestions():
    result = tools.launch_game(_session(["Kian"]), "Zelda Rocket Zoom")
    assert "error" in result
    assert result["did_you_mean"]


def test_get_player_returns_profile_and_memory():
    sess = _session(["Kian"])
    store.append_note(sess.conn, "Kian", "loves sports")
    result = tools.get_player(sess, "Kian")
    assert result["known"] is True
    assert result["favorite_game"] == "Track & Field"
    assert "loves sports" in result["memory"]


def test_get_player_marks_unknown_face_as_guest():
    result = tools.get_player(_session(["unknown"]), "Guest")
    assert result["is_guest"] is True
    assert result["known"] is False


def test_assign_joystick_two_players_left_and_right():
    sess = _session(["Kian", "Nika"])
    assert tools.assign_joystick(sess, "Kian")["joystick"] == "left"
    assert tools.assign_joystick(sess, "Nika")["joystick"] == "right"


def test_remember_persists_a_learned_preference():
    sess = _session(["Kian"])
    tools.remember(sess, "Kian", "only plays evenings after 5pm")
    assert "after 5pm" in store.get_profile(sess.conn, "Kian")["notes"]


def test_create_then_delete_profile():
    sess = _session(["unknown"])
    assert tools.create_profile(sess, "Sam", "en")["created"] == "Sam"
    assert store.get_profile(sess.conn, "Sam") is not None
    assert tools.delete_profile(sess, "Sam")["deleted"] == "Sam"


def test_set_privacy_schedule_requires_admin_present():
    # Non-admin present -> refused.
    denied = tools.set_privacy_schedule(_session(["Kian"]), "20:00", "09:00", "night")
    assert "error" in denied
    # Admin (Reza) present -> allowed and stored.
    sess = _session(["Reza"])
    ok = tools.set_privacy_schedule(sess, "20:00", "09:00", "night")
    assert ok["privacy_schedule_set"] is True
    assert store.list_schedules(sess.conn)[0]["created_by"] == "Reza"


def test_close_game_only_when_running():
    sess = _session(["Kian"])
    assert "error" in tools.close_game(sess)
    tools.launch_game(sess, "Pong")
    assert tools.close_game(sess)["closed"] == "Pong"


def test_run_tool_unknown_name_returns_error():
    assert "error" in tools.run_tool(_session(["Kian"]), "make_coffee", {})

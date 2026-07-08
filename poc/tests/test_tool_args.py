"""Tests that run_tool tolerates the wrong-but-common argument keys small models emit."""

import sqlite3

from brain import store, tools
from brain.tools import Session


def _session(present):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return Session(conn=conn, present=present)


def test_get_player_accepts_player_key():
    # Model passed {"player": "Leo"} to get_player which really wants "name".
    result = tools.run_tool(_session(["Leo"]), "get_player", {"player": "Leo"})
    assert result["known"] is True
    assert result["name"] == "Leo"


def test_launch_game_accepts_game_key():
    result = tools.run_tool(_session(["Leo"]), "launch_game", {"game": "Pong"})
    assert result["launched"] == "Pong"


def test_remember_accepts_person_key():
    sess = _session(["Leo"])
    tools.run_tool(sess, "remember", {"person": "Leo", "note": "likes racing"})
    assert "racing" in store.get_profile(sess.conn, "Leo")["notes"]

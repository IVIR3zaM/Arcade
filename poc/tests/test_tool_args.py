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
    # Model passed {"player": "Kian"} to get_player which really wants "name".
    result = tools.run_tool(_session(["Kian"]), "get_player", {"player": "Kian"})
    assert result["known"] is True
    assert result["name"] == "Kian"


def test_launch_game_accepts_game_key():
    result = tools.run_tool(_session(["Kian"]), "launch_game", {"game": "Pong"})
    assert result["launched"] == "Pong"


def test_remember_accepts_person_key():
    sess = _session(["Kian"])
    tools.run_tool(sess, "remember", {"person": "Kian", "note": "likes racing"})
    assert "racing" in store.get_profile(sess.conn, "Kian")["notes"]

"""Tests for the persistent SQLite store (profiles, memory, schedules)."""

import sqlite3

from brain import store


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return conn


def test_init_seeds_known_family_including_admin():
    conn = _db()
    names = store.list_profile_names(conn)
    assert {"Leo", "Mia", "Reza"} <= set(names)
    assert store.get_profile(conn, "reza")["is_admin"] == 1
    assert store.get_profile(conn, "leo")["is_admin"] == 0


def test_create_and_delete_profile():
    conn = _db()
    store.create_profile(conn, "Sam", language="de", is_guest=0)
    assert store.get_profile(conn, "sam")["language"] == "de"
    assert store.delete_profile(conn, "Sam") is True
    assert store.get_profile(conn, "Sam") is None


def test_append_note_accumulates_memory():
    conn = _db()
    store.append_note(conn, "Leo", "only plays after 5pm")
    store.append_note(conn, "Leo", "prefers two-player games")
    memory = store.get_profile(conn, "Leo")["notes"]
    assert "after 5pm" in memory
    assert "two-player" in memory


def test_schedules_round_trip():
    conn = _db()
    store.add_schedule(conn, "20:00", "09:00", "kids asleep", "Reza")
    scheds = store.list_schedules(conn)
    assert scheds[0]["start_hm"] == "20:00"
    assert scheds[0]["created_by"] == "Reza"

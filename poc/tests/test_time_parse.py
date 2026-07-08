"""Tests for casual time parsing in set_privacy_schedule."""

import sqlite3

from brain import store, tools
from brain.tools import Session, _to_hm


def _admin_session():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init(conn)
    return Session(conn=conn, present=["Reza"])


def test_to_hm_handles_am_pm_and_24h():
    assert _to_hm("8pm") == "20:00"
    assert _to_hm("9 am") == "09:00"
    assert _to_hm("12am") == "00:00"
    assert _to_hm("12pm") == "12:00"
    assert _to_hm("20:00") == "20:00"
    assert _to_hm("nonsense") is None


def test_privacy_schedule_accepts_casual_times():
    sess = _admin_session()
    result = tools.set_privacy_schedule(sess, "8pm", "9am", "kids asleep")
    assert result["start"] == "20:00"
    assert result["end"] == "09:00"

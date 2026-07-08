"""Tests for the mocked Pi environment (privacy-window logic)."""

from datetime import datetime

from brain import hardware


def test_within_window_same_day():
    assert hardware.within_window(datetime(2026, 7, 8, 10, 0), "09:00", "17:00")
    assert not hardware.within_window(datetime(2026, 7, 8, 18, 0), "09:00", "17:00")


def test_within_window_wraps_past_midnight():
    # mic/camera off 20:00 → 09:00 next morning
    assert hardware.within_window(datetime(2026, 7, 8, 22, 0), "20:00", "09:00")
    assert hardware.within_window(datetime(2026, 7, 8, 3, 0), "20:00", "09:00")
    assert not hardware.within_window(datetime(2026, 7, 8, 12, 0), "20:00", "09:00")


def test_devices_off_during_a_schedule():
    sched = [{"start_hm": "20:00", "end_hm": "09:00", "reason": "night"}]
    off = hardware.devices_state(datetime(2026, 7, 8, 23, 0), sched)
    assert off["mic_on"] is False and off["camera_on"] is False
    on = hardware.devices_state(datetime(2026, 7, 8, 12, 0), sched)
    assert on["mic_on"] is True and on["camera_on"] is True

"""The Pi's environment, behind small mockable functions.

On the real cabinet these read the clock, the CPU thermal sensor, and the actual
mic/camera power state. Here they're stubs (the AGENTS.md hardware boundary): the
time is real, the temperature is faked, and the mic/camera "on" state is derived
from the privacy schedules an admin set. The LLM reads all of this via the
get_context tool so it can reason about *when* it is and whether it's even allowed
to listen.
"""

import os
from datetime import datetime


def now() -> datetime:
    """Current local time. Real — the assistant reasons about it."""
    return datetime.now()


def read_temp_c() -> float:
    """CPU temperature. Faked here (real read is vcgencmd on the Pi, Phase 7/8.9)."""
    return float(os.environ.get("FAKE_TEMP_C", "54.5"))


# The cabinet's one monitor. On the Pi this is `wlr-randr`/CEC power control; here
# it's a flag the tools flip and the idle timer turns off.
_MONITOR = {"on": False}


def monitor_on() -> bool:
    return _MONITOR["on"]


def set_monitor(on: bool) -> None:
    _MONITOR["on"] = bool(on)


def _hm_to_minutes(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def within_window(current: datetime, start_hm: str, end_hm: str) -> bool:
    """Is `current` inside a daily [start, end) window that may wrap past midnight?"""
    cur = current.hour * 60 + current.minute
    start = _hm_to_minutes(start_hm)
    end = _hm_to_minutes(end_hm)
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end  # wraps midnight (e.g. 20:00 → 09:00)


def devices_state(current: datetime, schedules: list[dict]) -> dict:
    """Whether mic + camera are currently on, given the active privacy schedules."""
    for s in schedules:
        if within_window(current, s["start_hm"], s["end_hm"]):
            return {
                "mic_on": False,
                "camera_on": False,
                "reason": s["reason"],
                "off_by": s,
            }
    return {"mic_on": True, "camera_on": True, "reason": "", "off_by": None}

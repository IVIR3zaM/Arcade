"""Step timing for the turn pipeline — so you can SEE what the engine is doing.

A `Timeline` does two things at once:

  * prints a live, indented log to the container's stdout as each step starts
    and finishes ("▶ stt … ✓ stt 0.91s"), so watching `docker compose` output
    shows the engine moving from step to step in real time; and
  * collects each leaf step's duration, which the API hands back in the response
    so the host CLI can print a one-line breakdown right under the reply.

Timing is per-request (one Timeline per turn), so nothing is shared across the
threads FastAPI serves on. Set ARC_TIMING=0 to silence the live log (the numbers
are still returned).
"""

import os
import time
from contextlib import contextmanager

_LIVE = os.environ.get("ARC_TIMING", "1") != "0"

# Steps that represent real model calls, so the CLI/derivation can tell model
# time apart from deterministic code time.
_MODEL_STEPS = {"intent", "phrase"}


class Timeline:
    def __init__(self, label: str, on_event=None):
        self._label = label
        self._t0 = time.perf_counter()
        self._depth = 0
        self.steps: list[dict] = []  # flat [{"step", "seconds"}] leaves
        # Optional sink for structured events (used to stream live progress to
        # the host CLI, so it can show "what's happening now + seconds elapsed").
        self._sink = on_event

    def _log(self, msg: str) -> None:
        if _LIVE:
            print(f"[{self._label}] {msg}", flush=True)

    def _emit(self, event: dict) -> None:
        if self._sink:
            self._sink(event)

    @contextmanager
    def step(self, name: str):
        """A leaf step: live-logged, streamed (begin→end), AND recorded."""
        indent = "  " * self._depth
        self._log(f"{indent}▶ {name}")
        self._emit({"event": "begin", "step": name})
        self._depth += 1
        start = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - start
            self._depth -= 1
            self._log(f"{indent}✓ {name}  {dt:.2f}s")
            self.steps.append({"step": name, "seconds": round(dt, 3)})
            self._emit({"event": "end", "step": name, "seconds": round(dt, 3)})

    @contextmanager
    def span(self, name: str):
        """A grouping step: live-logged (start/finish) but NOT streamed or
        recorded — its children (the model calls inside it) account for it.
        Yields a dict whose 'elapsed' is filled in when the block exits."""
        indent = "  " * self._depth
        self._log(f"{indent}▶ {name}")
        self._depth += 1
        start = time.perf_counter()
        box = {"elapsed": 0.0}
        try:
            yield box
        finally:
            box["elapsed"] = time.perf_counter() - start
            self._depth -= 1
            self._log(f"{indent}✓ {name}  {box['elapsed']:.2f}s")

    def model_seconds(self) -> float:
        """Total time recorded so far in model calls (intent + phrasing)."""
        return sum(s["seconds"] for s in self.steps if s["step"] in _MODEL_STEPS)

    def record(self, name: str, seconds: float) -> None:
        """Add a pre-measured leaf (e.g. derived 'code' time)."""
        seconds = round(max(seconds, 0.0), 3)
        self.steps.append({"step": name, "seconds": seconds})
        self._log(f"  ✓ {name}  {seconds:.2f}s")
        self._emit({"event": "end", "step": name, "seconds": seconds})

    def finish(self) -> list[dict]:
        """Log the grand total, stream it, and return the breakdown."""
        total = round(time.perf_counter() - self._t0, 3)
        self._log(f"✓ {self._label} total {total:.2f}s")
        self._emit({"event": "total", "seconds": total})
        return [*self.steps, {"step": "total", "seconds": total}]


def timed_chat(timeline: Timeline, chat):
    """Wrap a `chat(system, user, as_json=?)` so each model call is timed and
    labeled 'intent' (schema-constrained JSON) or 'phrase' (spoken reply)."""

    def wrapped(system: str, user: str, as_json: bool = False) -> str:
        with timeline.step("intent" if as_json else "phrase"):
            return chat(system, user, as_json=as_json)

    return wrapped

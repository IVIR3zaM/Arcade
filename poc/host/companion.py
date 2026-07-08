"""The command you run on the MacBook.

This is intentionally dumb: it lets you pick a scenario, then acts as the
cabinet's microphone and speaker. Docker Desktop on macOS can't reach the mic or
speakers, so the heavy AI (LLM, whisper, Piper) all runs in the container and
this side only records your voice and plays back what the brain says — your Mac's
mic + speakers standing in for the Pi's USB speakerphone.

Push-to-talk: press Enter to start talking, Enter again when you're done.
"""

import base64
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
import requests
import sounddevice as sd

BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:8080")
SAMPLE_RATE = 16000  # what whisper expects


def _play(audio_b64: str) -> None:
    """Play WAV bytes through the Mac speakers via `afplay`."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(base64.b64decode(audio_b64))
        path = f.name
    try:
        subprocess.run(["afplay", path], check=True)
    finally:
        os.unlink(path)


def _record() -> str:
    """Record from the mic between two Enter presses; return base64 WAV."""
    input("  🎙  Press Enter and start talking...")
    frames: list[np.ndarray] = []

    def callback(indata, _frames, _time, _status):
        frames.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback
    ):
        input("  ⏹  ...press Enter when you're done.")

    audio = np.concatenate(frames) if frames else np.zeros((1, 1), dtype="int16")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    with open(path, "rb") as fh:
        data = fh.read()
    os.unlink(path)
    return base64.b64encode(data).decode("ascii")


def _print_actions(actions: list) -> None:
    """Show what the LLM manager actually did — every tool call, args, and result."""
    if not actions:
        return
    for a in actions:
        args = ", ".join(f"{k}={v!r}" for k, v in a["args"].items())
        print(f"   ⚙  {a['tool']}({args}) → {a['summary']}")


def _choose_scenario() -> str:
    scenarios = requests.get(f"{BRAIN_URL}/scenarios", timeout=10).json()
    print("\nPick a scenario:\n")
    for i, s in enumerate(scenarios, 1):
        print(f"  {i}. {s['id']}\n     {s['description']}\n")
    while True:
        choice = input(f"Choose 1-{len(scenarios)}: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(scenarios):
            return scenarios[int(choice) - 1]["id"]
        print("  Please enter a valid number.")


def main() -> None:
    print("=== Arcade AI Companion — experience PoC ===")
    scenario_id = _choose_scenario()

    print("\n(Walking up to the cabinet...)\n")
    reply = requests.post(
        f"{BRAIN_URL}/session/start",
        json={"scenario_id": scenario_id},
        timeout=300,
    ).json()
    _print_actions(reply["actions"])
    print(f"🕹  Arc: {reply['text']}\n")
    _play(reply["audio_b64"])

    session_id = reply["session_id"]
    while True:
        audio_b64 = _record()
        print("  (thinking...)")
        reply = requests.post(
            f"{BRAIN_URL}/turn",
            json={"session_id": session_id, "audio_b64": audio_b64},
            timeout=300,
        ).json()
        print(f"\n🗣  You: {reply.get('user_text', '')}")
        _print_actions(reply["actions"])
        print(f"🕹  Arc: {reply['text']}\n")
        _play(reply["audio_b64"])
        if reply.get("done"):
            print("(session over — have fun!)")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

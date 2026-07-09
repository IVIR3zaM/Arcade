"""The command you run on the MacBook.

This is intentionally dumb: it lets you pick a scenario, then acts as the
cabinet's microphone and speaker. Docker Desktop on macOS can't reach the mic or
speakers, so the heavy AI (LLM, whisper, Piper) all runs in the container and
this side only records your voice and plays back what the brain says — your Mac's
mic + speakers standing in for the Pi's USB speakerphone.

There is NO push-to-talk: the mic streams continuously and a small energy VAD
segments utterances (start on voice, end on ~0.8s of silence), exactly like the
real cabinet. The mic is closed while Arc speaks so it doesn't hear itself. The
BRAIN decides whether an utterance was addressed to it (wake word "Hey Arc" when
idle) — ignored utterances show up dimmed here so you can see it choosing not to
answer. While you're silent, the CLI polls /tick so the cabinet's own housekeeping
(attention timeout, monitor auto-off) is visible too.
"""

import base64
import io
import os
import queue
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np
import requests
import sounddevice as sd

BRAIN_URL = os.environ.get("BRAIN_URL", "http://localhost:8080")
SAMPLE_RATE = 16000  # what whisper expects
FRAME = 480  # 30 ms @ 16 kHz

# --- VAD tuning (RMS-based; simple but fine for a demo room) -----------------
START_FRAMES = 3  # consecutive voiced frames to open an utterance (~90 ms)
END_SILENCE_FRAMES = 27  # unvoiced frames that close it (~810 ms)
PRE_ROLL_FRAMES = 12  # audio kept from just before speech started (~360 ms)
MIN_UTTERANCE_FRAMES = 12  # discard blips shorter than ~360 ms of speech
MAX_UTTERANCE_S = 15
TICK_EVERY_S = 6  # how often to poll /tick while nobody speaks


def _play(audio_b64: str) -> None:
    """Play WAV bytes through the Mac speakers via `afplay`."""
    if not audio_b64:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(base64.b64decode(audio_b64))
        path = f.name
    try:
        subprocess.run(["afplay", path], check=True)
    finally:
        os.unlink(path)


def _wav_b64(frames: list[np.ndarray]) -> str:
    audio = np.concatenate(frames)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


class Listener:
    """Continuous mic with utterance endpointing.

    The noise floor adapts while nobody speaks; a frame is 'voiced' when its RMS
    rises well above it. listen() blocks until one utterance is captured (calling
    `on_tick` periodically while waiting) and returns it as base64 WAV. The
    stream is closed between utterances so Arc's own replies aren't recorded.
    """

    def __init__(self) -> None:
        self.noise = 150.0  # adaptive noise-floor estimate (int16 RMS)

    def _threshold(self) -> float:
        return max(self.noise * 3.5, 300.0)

    def listen(self, on_tick=None) -> str | None:
        q: queue.Queue = queue.Queue()

        def callback(indata, _frames, _time, _status):
            q.put(indata.copy())

        pre: list[np.ndarray] = []
        speech: list[np.ndarray] = []
        in_speech = False
        voiced_run = 0
        silence_run = 0
        voiced_total = 0
        last_tick = time.time()
        max_frames = int(MAX_UTTERANCE_S * SAMPLE_RATE / FRAME)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME,
            callback=callback,
        ):
            while True:
                if on_tick and time.time() - last_tick > TICK_EVERY_S:
                    on_tick()
                    last_tick = time.time()
                try:
                    block = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
                voiced = rms > self._threshold()

                if not in_speech:
                    pre.append(block)
                    if len(pre) > PRE_ROLL_FRAMES:
                        pre.pop(0)
                    # Only quiet frames teach the noise floor.
                    if not voiced:
                        self.noise = 0.95 * self.noise + 0.05 * rms
                    voiced_run = voiced_run + 1 if voiced else 0
                    if voiced_run >= START_FRAMES:
                        in_speech = True
                        speech = list(pre)
                        voiced_total = voiced_run
                        silence_run = 0
                    continue

                speech.append(block)
                if voiced:
                    voiced_total += 1
                    silence_run = 0
                else:
                    silence_run += 1
                if silence_run >= END_SILENCE_FRAMES or len(speech) >= max_frames:
                    break

        if voiced_total < MIN_UTTERANCE_FRAMES:
            return None  # a door slam, not speech
        return _wav_b64(speech)


def _print_actions(actions: list) -> None:
    """Show what the LLM manager actually did — every tool call, args, and result."""
    for a in actions or []:
        args = ", ".join(f"{k}={v!r}" for k, v in a["args"].items())
        print(f"   ⚙  {a['tool']}({args}) → {a['summary']}")


def _status(attention: str) -> None:
    if attention == "idle":
        print("  🎧 (idle — say “Hey Arc” to get my attention)")
    else:
        print("  🎧 (listening...)")


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

    print("\n(Walking up to the cabinet — the camera spots you...)\n")
    reply = requests.post(
        f"{BRAIN_URL}/session/start",
        json={"scenario_id": scenario_id},
        timeout=300,
    ).json()
    _print_actions(reply["actions"])
    print(f"🕹  Arc: {reply['text']}\n")
    _play(reply["audio_b64"])

    session_id = reply["session_id"]
    attention = reply.get("attention", "engaged")
    listener = Listener()

    def on_tick() -> None:
        nonlocal attention
        try:
            t = requests.post(
                f"{BRAIN_URL}/tick", json={"session_id": session_id}, timeout=10
            ).json()
        except requests.RequestException:
            return
        _print_actions(t.get("actions"))
        if t["attention"] != attention:
            attention = t["attention"]
            _status(attention)

    _status(attention)
    while True:
        audio_b64 = listener.listen(on_tick=on_tick)
        if audio_b64 is None:
            continue
        print("  (heard something — thinking...)")
        reply = requests.post(
            f"{BRAIN_URL}/turn",
            json={"session_id": session_id, "audio_b64": audio_b64},
            timeout=300,
        ).json()
        attention = reply.get("attention", attention)
        if reply.get("ignored"):
            print(f"  🙈 (not for me: “{reply.get('user_text', '')}” — staying quiet)")
            _status(attention)
            continue
        print(f"\n🗣  You: {reply.get('user_text', '')}")
        _print_actions(reply["actions"])
        print(f"🕹  Arc: {reply['text']}\n")
        _play(reply["audio_b64"])
        if reply.get("done"):
            print("(session over — have fun!)")
            break
        _status(attention)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

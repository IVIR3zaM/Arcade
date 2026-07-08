# Arcade AI Companion — experience PoC

A throwaway proof-of-concept for **Phase 8** (the on-device voice + camera
companion — see [../ITERATIONS.md](../ITERATIONS.md)). Its job is to let you
**feel the experience** — and, crucially, to **test whether a small on-device LLM
can be the arcade's manager**: identify who walked up, load what it remembers
about them, suggest and launch games, assign joysticks, create/delete profiles,
learn lasting preferences, read the Pi's clock/temperature, and let an admin turn
the mic + camera off on a schedule — all by **calling tools** you can watch it call.

This is **not** production code and it is separate from the real dev environment.
It stands in for things Phase 8 will build for real:

| Real Phase 8 thing            | PoC stand-in                                             |
| ----------------------------- | -------------------------------------------------------- |
| Pi AI HAT+ (face recognition) | scenario says who the "camera" sees (by name)            |
| Camera / speakerphone         | your MacBook's **mic + speakers**                        |
| whisper.cpp STT / Piper TTS   | faster-whisper + Piper, in the container                 |
| Local LLM                     | **Ollama** (`qwen2.5:3b` default), in the container      |
| SQLite profiles + memory      | a **real SQLite DB** in a volume (survives restarts)     |
| Pi hardware (temp, mic/cam)   | mocked behind small functions in `brain/hardware.py`     |

## How the manager works — small model, split into atomic steps

A 3B model can't reliably drive a dozen tools from one giant prompt. So each turn
is a short pipeline of *small, focused* steps (`brain/agent.py`):

1. **classify_intent** — one tiny model call: what does the user want? Returns
   JSON like `{"intent":"play_game","title":"Pong"}` (few-shot-guided).
2. **execute_intent** — **code** runs the action deterministically, and **owns
   all access control**. Who is at the cabinet and what they may do is decided
   here, never by the model (e.g. only an admin can set a privacy schedule).
3. **phrase** — one tiny model call: turn the outcome into a warm spoken line
   (simple cases like goodbye are canned, no model call).

Small prompts (no tool schemas) → fast on Pi-class CPU; the model is kept resident
in RAM. The greeting skips step 1 (code already knows who walked up). The tools
still **enforce truth** — `launch_game` fuzzy-matches a misheard "Point" back to
"Pong" and refuses games that don't exist — so the model never invents facts.

**The actions (`brain/tools.py`)** — every one is printed in the CLI as it runs:

| Action | What it does |
| ------ | ------------ |
| `get_player` | query the DB for a person's profile, history, and remembered notes |
| `list_games` / `recommend_game` | browse the catalog / get the deterministic pick |
| `launch_game` / `close_game` | start (fuzzy-matched) / stop a game |
| `assign_joystick` | deterministic left/right for a player |
| `create_profile` / `delete_profile` | save a guest as a member / forget someone |
| `remember` | store a lasting note ("only plays after 5pm") for next time |
| `get_context` | read time, date, CPU temp, mic/camera state, privacy schedules |
| `set_privacy_schedule` | (admin-gated in code) turn mic + camera off on a window |

## How it's put together

Docker Desktop on macOS can't reach the mic or speakers, so the work is split:
one **Pi box** container does all the AI; the Mac is just its mic and speaker.

```
  MacBook (host)                     ONE container = the Pi 5 (capped 4 cores / 8GB)
 ┌───────────────────┐   HTTP + WAV  ┌────────────────────────────────────────────┐
 │ host/companion.py │ ─────────────▶│ FastAPI app.py                             │
 │  records your mic │               │   whisper STT (biased to the real names)   │
 │  plays replies    │               │   agent.py:  intent →(Ollama)              │
 │  prints the tool  │ ◀─────────────│              execute →(code + access ctrl)  │
 │  calls + WAV      │  text + WAV   │              phrase  →(Ollama)             │
 │                   │  + actions[]  │     └─ tools.py → SQLite store + hardware   │
 └───────────────────┘               │   Piper TTS · Ollama (3B, resident in RAM) │
                                      └────────────────────────────────────────────┘
```

Everything runs **inside this one container**, sharing a single **4-core / 8 GB**
budget — the same pool the Pi gives them. The base is Debian 12 Bookworm arm64,
which is what Raspberry Pi OS (Bookworm) is, running natively as arm64 on Apple
Silicon.

**Honest caveat about performance.** This matches the Pi's core *count*, RAM, OS,
and architecture — but not per-core *speed*. An Apple-Silicon core is ~2-3× a Pi
5 core, and Docker caps CPU time, not clock rate. Treat the latency and tokens/sec
you see as an **optimistic upper bound**; real performance is the Phase 8.9
hardware checkpoint. Give Docker Desktop ≥ 8 GB (Settings → Resources).

**What the PoC found (read this).** A 3B model *cannot* be an autonomous
many-tools agent — given one big prompt with a dozen tools it under-calls them and
sometimes goes silent. But **split into small atomic steps** (intent → code →
phrase) with access control in code, **a 3B works**: greeting, fuzzy game launch,
remembering preferences, admin privacy scheduling, and code-enforced refusals all
run correctly. On the Pi-accurate 4-core cap this lands at **~3–5 s per turn**
(one intent call + one phrasing call; canned replies like goodbye are ~1 s).

Two things made the difference and are worth remembering for the real build:
`num_thread` must match the core count (the container sees all host cores but is
CPU-throttled to 4 — left unpinned, Ollama spawns too many threads and fights the
throttle, ~4× slower), and the model stays resident (`OLLAMA_KEEP_ALIVE=-1`) so
there's no reload per turn. Want nicer wording at higher latency? `COMPANION_MODEL=qwen2.5:7b ./run.sh`.

## Run it

Requires Docker Desktop and Python 3 on the Mac. One command:

```bash
cd poc
./run.sh
```

It builds the container, then on **first run** downloads the models into cached
volumes — the LLM (from the Ollama registry) plus the whisper model and Piper
voices (from Hugging Face). Later runs reuse them and start fast. It then sets up
a tiny host venv for the mic CLI and shows the scenario picker.

Pick a scenario, then **push-to-talk**: press Enter to start speaking, Enter
again when you're done. Watch the `⚙` tool-call lines to see what the manager did.
Say "bye" to end. Grant microphone permission to your terminal the first time.

> The first-run fetch needs `huggingface.co` and the Ollama registry reachable.
> Behind a Hugging Face block, set `VOICES_BASE_URL` / `HF_ENDPOINT` to a mirror.

When you're done: `docker compose down` (from `poc/`). Profiles and memory persist
in the `pi_data` volume; `docker compose down -v` wipes them for a clean slate.

## Scenarios

- **leo-solo** — Leo (English): greet + load his history/memory, suggest, launch.
- **mia-solo** — Mia (German): greeted auf Deutsch.
- **leo-and-mia** — two players: a joystick each.
- **guest** — an unrecognized face: try "save my profile, my name is Sam".
- **reza-admin** — Reza (admin): try "turn off the mic and camera every night
  from 8pm to 9am".

Things to try by voice: *"let's play Pong"*, *"what can I play?"*, *"remember I
only play after 5pm"*, *"delete my profile"*. Edit `brain/scenarios.py` (catalog,
who's present) and `brain/store.py` (seeded people) to change the world.

## Tests

The deterministic core — tools (fuzzy match, admin gating), the store, the agent
loop (with a stubbed model), privacy-window logic, analytics — is unit-tested with
no model, audio, or network:

```bash
cd poc
python3 -m pytest tests -q
```

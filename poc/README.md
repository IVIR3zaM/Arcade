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
| Camera / speakerphone         | your MacBook's **mic + speakers** (always-on, VAD)       |
| Wake word ("Hey Arc")         | fuzzy match on the whisper transcript (`brain/wake.py`)  |
| whisper.cpp STT / Piper TTS   | faster-whisper + Piper, in the container                 |
| Local LLM                     | **Ollama** (`qwen2.5:3b` default), in the container      |
| SQLite profiles + memory      | a **real SQLite DB** in a volume (survives restarts)     |
| Pi hardware (temp, mic/cam, monitor) | mocked behind small functions in `brain/hardware.py` |

## How the manager works — small model, split into atomic steps

A 3B model can't reliably drive a dozen tools from one giant prompt. So each turn
is a short pipeline of *small, focused* steps (`brain/agent.py`):

1. **classify_intent** — one tiny model call: what does the user want? The output
   is **schema-constrained** (Ollama structured output), so the intent is always
   one of ours — the model physically can't answer in prose or invent an intent.
   Few-shot-guided in **both English and German**.
2. **execute_intent** — **code** runs the action deterministically, and **owns
   all access control AND sanity guards**. Who may do what is decided here, never
   by the model (only an admin sets privacy schedules), and model sloppiness is
   caught here too: "create a profile for **me**" never creates a profile named
   "me" — code rejects pronouns and asks *"what's your name?"*, then treats the
   next utterance as the name (no model call needed for that turn).
3. **phrase** — deterministic **EN/DE templates** for every routine outcome
   (launch, stop, remember, deny, ...) — zero model calls — so a typical turn
   costs **one** model call, not two. The model only phrases the open-ended
   moments: the greeting and free-form context questions.

Small prompts (no tool schemas) → fast on Pi-class CPU; the model is kept resident
in RAM. The greeting skips step 1 (code already knows who walked up). The tools
still **enforce truth** — `launch_game` fuzzy-matches a misheard "Point" back to
"Pong" and refuses games that don't exist — so the model never invents facts.

## How listening works — no push-to-talk, just like the cabinet

The mic is **always streaming**; a small VAD on the host segments utterances
(speech starts → keep talking → ~0.8 s of silence ends it) and the mic is closed
while Arc speaks so it never hears itself. Whether Arc *responds* is the brain's
**attention state machine** (`brain/app.py`):

- **engaged** — right after the camera greets you, or after "Hey Arc": every
  utterance is handled. Goes idle again after ~45 s of silence.
- **idle** — a game is running, or you went quiet: everything is transcribed but
  **ignored** (shown dimmed in the CLI) unless it starts with the wake phrase —
  so players talking *to each other* never trigger the manager. "**Hey Arc**,
  stop the game" wakes and commands in one breath; wake-word matching is fuzzy
  because whisper hears "Hey Ark/Arg/Hallo Arc" (`brain/wake.py`).

The cabinet also manages its own **monitor**: on when a person appears in frame,
on/off by voice, and **off automatically** when nothing has happened for ~2
minutes with no game running (the CLI polls `/tick`, so you see it happen).
**German is the default language** for guests; known people get their saved
language. Whisper **auto-detects the language of every utterance** (forcing the
session language would mangle English speech into German gibberish), so Arc
simply answers in whichever supported language you speak — and an explicit
"speak English" / "sprich Deutsch" still switches and persists it on your
profile. **Farsi is enabled as an experimental third language**: the wake word,
goodbye/yes/no words, and a handful of canned lines are hand-translated, and
every other reply is phrased by the LLM in Persian (Piper `fa_IR-amir` voice) —
it exists purely to test how far a small local model stretches. Any *other*
language gets an honest "I can speak English, German, and a bit of Farsi."

Launching a game **asks which joystick you want** (one player; two players get
one each automatically), and the answer — "the right one" — is understood
without the model, including whisper's "Ride"/"Wright" mishearings. **Mid-game,
Arc answers one woken request and immediately goes back to ignoring gameplay
chatter** — every new request needs "Hey Arc" again; it only stays engaged
while a question of its own is open (which joystick? what's your name?) or
while you're browsing for a different game.

**The actions (`brain/tools.py`)** — every one is printed in the CLI as it runs:

| Action | What it does |
| ------ | ------------ |
| `get_player` | query the DB for a person's profile, history, and remembered notes |
| `list_games` / `recommend_game` | browse the catalog / get the deterministic pick |
| `launch_game` / `close_game` | start (fuzzy-matched) / stop a game |
| `assign_joystick` | deterministic left/right for a player |
| `create_profile` / `delete_profile` | save a guest as a member / forget someone |
| `remember` | store a lasting note ("only plays after 5pm") for next time |
| `get_context` | read time, date, CPU temp, mic/camera/monitor state, privacy schedules |
| `set_privacy_schedule` | (admin-gated in code) turn mic + camera off on a window |
| `set_monitor` | turn the cabinet's screen on/off (also automatic: on at walk-up, off when idle) |
| `set_language` | switch EN ↔ DE mid-conversation and persist it on the profile |

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
sometimes goes silent, and left to fill arguments freely it does things like
`create_profile(name="me")`. But with the labor divided honestly — the model only
**classifies intent** (schema-constrained) and code does everything else
(execution, access control, name sanity, phrasing templates) — **a 3B works**:
greeting, fuzzy game launch, remembering preferences, guest onboarding, admin
privacy scheduling, and code-enforced refusals all run correctly. Routine turns
now cost **one** model call instead of two, so on the Pi-accurate 4-core cap a
turn (STT + intent + template + TTS) lands at **~2–4 s**; the outcomes that still
use a phrasing call (greeting, free-form questions) take ~5–8 s, and code-matched
replies (goodbye, the name reply) ~1–2 s. That's the honest answer to "can a
local LLM on a Pi manage the arcade": *yes for understanding, no for anything you
can't afford it getting wrong — those parts must be code.*

Three things made the difference and are worth remembering for the real build:
`num_thread` must match the core count (the container sees all host cores but is
CPU-throttled to 4 — left unpinned, Ollama spawns too many threads and fights the
throttle, ~4× slower), the model stays resident (`OLLAMA_KEEP_ALIVE=-1`) so
there's no reload per turn, and the fewer model calls per turn the better —
templates for routine replies halved the latency without hurting the experience.
Want nicer wording at higher latency? `COMPANION_MODEL=qwen2.5:7b ./run.sh`.

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

Pick a scenario, then **just talk** — the mic listens continuously and detects
when you start and stop speaking (no Enter). After a game launches (or ~45 s of
silence) Arc stops paying attention; say "**Hey Arc**" to get it back — anything
else you say is shown dimmed and ignored, exactly like the real cabinet. Watch
the `⚙` tool-call lines to see what the manager did. Say "bye" / "tschüss" to
end. Grant microphone permission to your terminal the first time, and use
speakers at a modest volume (the mic pauses while Arc talks, but a quiet room
makes the VAD happiest).

> The first-run fetch needs `huggingface.co` and the Ollama registry reachable.
> Behind a Hugging Face block, set `VOICES_BASE_URL` / `HF_ENDPOINT` to a mirror.

When you're done: `docker compose down` (from `poc/`). Profiles and memory persist
in the `pi_data` volume; `docker compose down -v` wipes them for a clean slate.

## Scenarios

- **leo-solo** — Leo (English): greet + load his history/memory, suggest, launch.
- **mia-solo** — Mia (German): greeted auf Deutsch.
- **leo-and-mia** — two players: a joystick each.
- **guest** — an unrecognized face (greeted **in German**, the default): try
  *"erstell mir ein Profil"* — Arc asks for your name, then remembers you.
- **reza-admin** — Reza (admin): try "turn off the mic and camera every night
  from 8pm to 9am".
- **nobody-home** — nobody in frame: the cabinet sits dark and silent. Say
  "Hey Arc" from across the room — it hears you, can't see you, and invites
  you over to play.

Things to try by voice: *"let's play Pong"*, then chat normally (ignored), then
*"Hey Arc, stop the game"*; *"what can I play?"*; *"remember I only play after
5pm"*; *"turn off the screen"*; *"speak English"* / *"sprich Deutsch"*; *"delete
my profile"*. Then go quiet for 2 minutes and watch the monitor turn itself off.
Edit `brain/scenarios.py` (catalog, who's present) and `brain/store.py` (seeded
people) to change the world.

## Tests

The deterministic core — tools (fuzzy match, admin gating), the store, the agent
loop (with a stubbed model), privacy-window logic, analytics — is unit-tested with
no model, audio, or network:

```bash
cd poc
python3 -m pytest tests -q
```

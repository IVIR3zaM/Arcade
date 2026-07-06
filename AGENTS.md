# Working on this repo (for AI coding agents)

This is for any AI agent working on the Arcade project — including future you.
Read [README.md](README.md) for what the project is and [ARCHITECTURE.md](ARCHITECTURE.md)
for how it's put together. This file is about **how we write the code**. Follow
it exactly.

## The short version

- **TDD, always.** Failing test first, then the minimum code to pass it, then
  refactor. No production code without a preceding test.
- **KISS and YAGNI, hard.** Solve today's actual requirement, plainly. Nothing
  speculative.
- **Boring over clever.** Explicit over implicit, flat over nested.
- **Keep the stack.** Don't add frameworks, databases, or services on your own.
  Adding one requires the user to ask for it, or to approve it after you
  propose it — until then, wait.

## TDD — the loop we actually follow

1. **Write a failing test** for the smallest next behavior. Run it. See it fail
   for the right reason.
2. **Write the minimum code** to make it pass. Not the general version — the
   specific thing the test asked for.
3. **Refactor** with the test green: remove duplication, improve names. Don't add
   capability during refactor.

Do not write production code that isn't demanded by a test. If you catch yourself
adding a branch, option, or parameter "so it's there later," stop — there's no
test for it, so it doesn't get written.

Prefer to work on the **hardware-independent** parts (see below), because those
are fully testable off-device. That's most of the system.

## KISS / YAGNI — non-negotiable

- Build for the requirement in front of you, not an imagined future one.
- No config options, feature flags, hooks, or extension points that nothing uses
  today.
- No "just in case" parameters, no generalizing a function before there's a
  second caller.
- If you're unsure whether something is needed: it isn't. Leave it out. It's
  cheap to add later _with a test_ when a real need appears.

## Design patterns — only to remove present-day complexity

Patterns are tools, not goals.

- Use a pattern **only** when it clearly reduces real, existing complexity or
  duplication right now.
- Never apply a pattern speculatively, or "because it's best practice," or to
  look professional.
- If a plain function or a small class does the job, use that. A plain function
  is the default; reach for more structure only when the plain version is
  genuinely worse.

## Readability — code as a top-to-bottom story

- A new reader (or the next agent) should be able to follow what happens by
  reading top to bottom, without chasing indirection through many layers.
- **Explicit over implicit.** No magic, no hidden side effects, no clever
  metaprogramming.
- **Flat over nested.** Prefer early returns and straight-line code over deep
  nesting.
- **Boring over clever.** The obvious solution a tired person can read at a
  glance beats the impressive one.
- Name things for what they are. Keep functions small and single-purpose.

## Hardware boundary — mockable, but not over-built

Every hardware-dependent piece must sit behind a small function or interface that
can be swapped for a mock in tests and in the UTM dev environment. Hardware-
dependent means: reading CPU temp (`vcgencmd`), any GPIO reads, real display
calls, real controller/USB behavior, actually killing a process or shutting down.

**How to do it (and how far to go):**

- A **simple constructor argument (dependency injection)** or a **simple
  conditional** keyed off an env flag (e.g. `ARCADE_ENV`) is enough. Pass in the
  real implementation on the Pi, a fake in tests/UTM.
- Keep the hardware-touching surface tiny: a "read temperature" function, a "run
  this command and wait" function, an input source. The _logic_ around them stays
  pure and testable.
- **Do not** build a plugin system, a registry, an abstract driver hierarchy, or
  a config-driven backend selector. That's exactly the speculative
  over-engineering this project rejects.

Example of the intended level:

```python
# pure logic — no hardware, fully testable
def should_shut_down(temp_c, threshold_c):
    return temp_c >= threshold_c

# real hardware read, isolated behind one small function
def read_temp_c():
    out = subprocess.check_output(["vcgencmd", "measure_temp"])
    return parse_temp(out)   # parse_temp is pure and unit-tested

# wiring: inject the reader so tests pass a fake
def watchdog_tick(read_temp=read_temp_c, threshold_c=80):
    if should_shut_down(read_temp(), threshold_c):
        ...
```

Tests call `should_shut_down` directly and call `watchdog_tick` with a fake
`read_temp`. No real sensor needed. That's the whole technique — don't add more
machinery than this.

## Stack — don't drift

Keep to what's already chosen (see [ARCHITECTURE.md](ARCHITECTURE.md)):

- Python + Pygame (launcher), FastAPI (API), SQLite (data), RetroArch +
  DuckStation (emulation), systemd (watchdog + services), Tailscale (remote
  access).
- **Do not** introduce a new web framework, ORM, database, message queue, task
  runner, container orchestrator, or similar on your own. It's allowed only when
  the user asked for it, or when you proposed it and the user approved. If you
  think one is warranted, propose it and **wait** for that approval — don't just
  add it. "Unless the user explicitly asks" means exactly this: the agent stops
  and waits for a human yes.

## Git, commits, and the changelog

- **You don't touch git.** Do not commit, create branches, checkout, or push.
  Make the change in the working tree and stop. The **user** reviews and commits.
- **Suggest a Conventional Commits message** for the user to use when you finish
  — `type(scope): subject` (e.g. `feat(launcher): ...`, `fix(watchdog): ...`,
  `test(shared): ...`, `docs: ...`). Suggest it; don't run it.
- **Keep a changelog.** All new work goes under the `## [Unreleased]` section of
  [CHANGELOG.md](CHANGELOG.md) (format: [Keep a Changelog](https://keepachangelog.com)),
  grouped by `Added` / `Changed` / `Fixed` / `Removed`. Add your entry there as
  part of the change — never leave the changelog stale.
- **Do one piece, then stop.** Finish a turn after a single small task: don't
  loop into the next one on your own.

## Before you finish a change

- `cairn verify` was run after the change and passes (format, lint, tests) —
  nothing is broken, no new lint issues. Run it before you call the change done.
- There's a failing-first test that now passes.
- No production code exists that a test doesn't require.
- Nothing speculative was added (no unused options, params, abstractions).
- New hardware-dependent code is behind a small, mockable function — and no
  more than that.
- The stack is unchanged (or the user explicitly approved a change).
- The code reads top-to-bottom and a tired human could follow it.
- Docs still match reality (updated if the change touched them).
- A `## [Unreleased]` entry was added to [CHANGELOG.md](CHANGELOG.md).
- You did **not** commit or branch — you stopped, gave a short summary and a
  suggested Conventional Commits message, and asked the user to review.

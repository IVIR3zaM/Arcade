# Agent prompt — how to drive the iterations

This is the standing instruction for an AI agent working through
[ITERATIONS.md](ITERATIONS.md). The goals: **make real progress, spend as few
tokens as possible, and never bite off more than one small piece at a time.**

Read [AGENTS.md](AGENTS.md) for the coding rules (TDD, KISS/YAGNI, hardware
boundary, keep the stack). Read [ITERATIONS.md](ITERATIONS.md) for the ordered
plan. This file is about *how to work*, not *what to build*.

## Your operating loop

1. **Pick the single next unchecked task** in [ITERATIONS.md](ITERATIONS.md), in
   order. Do not skip ahead to a later phase — earlier phases are prerequisites.
2. **Is it small?** A task is small if it's roughly one test + the code to pass
   it, touching one or two files, explainable in a sentence.
   - **Yes →** do it.
   - **No →** stop and split it (see below). Do only the first sub-piece this
     round.
3. **Do it with TDD:** failing test → minimum code → refactor. Nothing
   speculative.
4. **Mark the task** `[x]` in ITERATIONS.md (or `[~]` if you split it and only
   finished part).
5. **Keep the docs honest.** If what you did changed anything in
   [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md), or
   [ITERATIONS.md](ITERATIONS.md), update it now so the docs still match reality.
6. **Add a CHANGELOG entry** under `## [Unreleased]` in
   [CHANGELOG.md](CHANGELOG.md), grouped by type (Added/Changed/Fixed/...).
7. **Then stop.** Do **one** piece and end the turn — do not loop into the next
   task. Finish with:
   - a **short description** of what you did (one or two lines),
   - a **suggested Conventional Commits message** (see below) for the user to use
     — but **do not commit it yourself**,
   - and an explicit **ask for the user to review**.

## Do not commit, do not branch

You do the work in the working tree and stop there. **Never** run `git commit`,
`git branch`, `git checkout -b`, `git push`, or otherwise change git state. The
user reviews and commits themselves. Your job ends at "here's what I did, here's a
commit message you could use, please review."

## Split big tasks — one piece at a time

If a task is bigger than the "small" bar above:

- Break it into the smallest sub-steps that each end green (a passing test or a
  runnable result).
- Write the sub-steps down (as sub-bullets under the task in ITERATIONS.md, or
  state them in your reply).
- **Do only the first sub-step**, then stop. The next round picks up the next.

Never try to land a whole phase in one shot. Small, verified steps beat big
risky ones — and they cost far fewer tokens when something needs a redo.

## Spend few tokens — be economical

The single biggest token cost is reading and re-reading files. Be deliberate:

- **Read only what you need.** Target the specific file/function for this task.
  Don't re-read files already shown to you in this conversation — trust the
  current state. Don't read a whole directory to change one function.
- **Search before reading.** Use grep/glob to locate the exact spot, then read a
  narrow range — not the entire file, unless it's genuinely small.
- **Don't re-derive known facts.** If the architecture or a decision is already
  in [ARCHITECTURE.md](ARCHITECTURE.md) or earlier in the conversation, use it;
  don't rediscover it.
- **Keep output tight.** No long preambles, no restating the plan back, no
  narrating options you won't take. Make the edit, run the test, give a one- or
  two-line result.
- **Prefer precise edits** over rewriting whole files.
- **Don't run broad, noisy commands** (dumping large logs, listing huge trees)
  when a focused one answers the question.
- **Batch independent commands/reads** into one step when they don't depend on
  each other, instead of many round-trips.

## Stop-and-ask, don't guess

- If a task needs a **new framework/database/service**, do not add it — propose
  it and wait for a human yes (see [AGENTS.md](AGENTS.md)).
- If requirements are ambiguous in a way that changes what you build, ask one
  crisp question rather than guessing and redoing work (redoing work is the most
  expensive thing you can do).
- If real Pi hardware is required to verify a task and you can't reach it, do the
  hardware-independent part, mark the hardware check as pending, and say so.

## Suggested commit message (Conventional Commits)

End your turn by suggesting one commit message the user can copy. Use
[Conventional Commits](https://www.conventionalcommits.org/): `type(scope):
subject`, e.g.

```
feat(launcher): build emulator command from a Game
test(shared): cover build_command for each console
fix(watchdog): parse vcgencmd output with decimal temps
docs(iterations): mark Phase 1 CLI task done
```

Common types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`. Suggest it —
the user commits.

## Each turn, in one line

> Pick the next small task → TDD it (or split and do piece one) → mark it →
> keep docs honest → add an Unreleased CHANGELOG entry → stop with a short
> summary, a suggested commit message, and a request for review. Do not commit,
> do not loop.

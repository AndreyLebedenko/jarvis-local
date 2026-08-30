# Task v1.9.0-5: Docs + release verification

**Status:** Proposed. Not started.
**Story:** `tasks/story-v1.9.0-response-modes.md` (scope item 5). Closes the
story.
**Depends on:** task-v1.9.0-1..4 (all behavior in place).

## Summary

Document the three response modes and their trade-offs for users and config,
record any architectural decision that landed, and assemble the human-run
release verification handoff (hotkey, voice, and mode-3 audio timing are
hardware/manual checks). Then close the story.

## Context you need

- `tests/test_main.py` is 5700+ lines covering the whole `Orchestrator`/`App`
  history from task-08 onward, in one file. Existing `# --- ...` section
  markers already outline natural per-topic boundaries (turns: clipboard/
  journal/attachment; interrupt/cancel; response mode; wiring; debug mode;
  shutdown; playback lock; etc.) - see the "Pre-doc test suite cleanup" step
  below for splitting it along those lines.
- `config.example.toml`: the `[response] mode` entry gets its full explanatory
  comment here - the three modes, what each speaks/shows, the mode-2
  self-contained trade-off, and mode-3's two-pass timing. Task 1 added only the
  minimal parseable entry; this task writes the user-facing explanation.
- `README.md` / `README.ru.md`: user-facing description of switching modes (the
  drop-down, the cycling hotkey and its chosen `ctrl+alt+<letter>`, and - if it
  shipped - the voice command). Keep hotkey honesty (README must state the real
  binding actually registered).
- `PROJECT.md`: add a v1.9.0 note only if an architectural decision was
  recorded - the two-contract split, the mode-3 second pass being reasoning-off
  and form-only, the derivative's additive-in-turn persistence and its
  exclusion from the retrieval/memory corpus, and the mode-3 first-pass TTS
  suppression being a localized mode-keyed gate (not the global mute). Update
  in the same spirit as prior story notes; do not restate what the code already
  makes obvious.
- `docs/`: any user/architecture doc that enumerates runtime toggles
  (thinking mode, mic-sleep, visibility) should gain the response-mode entry so
  the set stays complete.
- The prior story's release-verification task (e.g.
  `tasks/done/task-v1.8.3-4-docs-and-release-verification.md`) for the shape of
  the handoff and the exact-command style.

## Boundary

- Docs + verification handoff only. No behavior change; if a doc reveals a
  behavior gap, write a bug report (`tasks/bug_reports/`) rather than fixing it
  here.
- PROJECT.md gets a note only if a real architectural decision needs recording;
  no note-for-note's-sake.
- The test-suite split below is test-file reorganization, not a behavior
  change - no test's assertions or fixture semantics may change as part of
  it, only which file each test lives in and how shared fixtures are shared.

## Pre-doc test suite cleanup

Runs first, before any documentation edit in this task.

- Split `tests/test_main.py` (5700+ lines) into multiple files by topic,
  following its own existing `# --- ...` section boundaries (e.g. turns,
  interrupt/cancel, response mode, wiring, debug mode, shutdown, playback
  lock). Extract shared fixtures/fakes (`_orchestrator`, `_FakeBackend`,
  `_FakeJournalRecorder`, etc.) into a shared module or conftest rather than
  duplicating them per file.
- Every test keeps its current name, body, and assertions unchanged - this
  is a file-layout move, not a rewrite.
- `python -m pytest`, `ruff check`, `ruff format --check` green (same total
  test count as before the split) before moving on to the docs requirements
  below.

## Requirements

- `config.example.toml` `[response] mode` documented with the three modes and
  their trade-offs.
- README (en + ru) updated: mode switching via drop-down, hotkey (real
  binding), and voice command if it shipped.
- `config.example.toml` `[hotkeys]` gains the `response_mode_toggle` entry
  with its real default binding. Known gap being closed here, surfaced by
  the owner on 2026-08-30: the binding (default `ctrl+alt+o`) shipped in
  task 2 but is listed neither in `config.example.toml` nor in either
  README's hotkey table; the prepared task-3 handoff silently depended on
  it (see
  `tasks/bug_reports/2026-08-30-handoff-silently-depends-on-undocumented-hotkey.md`
  and the handoff self-sufficiency rule, Testing protocol item 4 in
  `AGENTS.md`).
- Handoff self-sufficiency audit as part of assembling the verification
  handoff: every human-run handoff prepared by this story (tasks 2, 3, 4
  handoffs and the assembled release handoff) is checked against Testing
  protocol item 4 - each hotkey, config key, and implicit default named
  literally with a source reference, no step assuming a starting state of
  a persistent setting.
- PROJECT.md v1.9.0 note if warranted; docs toggle list updated.
- A single assembled human-run verification handoff with exact commands
  covering: default-unchanged behavior; mode 2 self-contained one-pass output;
  mode 3 streaming/timing/derivative/first-pass-silence; hotkey cycle + UI
  drop-down + persistence across restart; voice switch (or the recorded stop
  outcome from task 4).

## Verification

- `python -m pytest`, `ruff check`, `ruff format --check` green (docs changes
  must not break the pure suite; any doctest/config-example parse test stays
  green).
- The human runs the assembled handoff and reports; on green, the story's
  acceptance criteria are all satisfied.

## Acceptance criteria

- [ ] `tests/test_main.py` is split by topic (pre-doc cleanup step), same
      tests unchanged, before any doc edit in this task.
- [ ] `config.example.toml`, README (en + ru), and the docs toggle list
      describe all three modes and how to switch; hotkey honesty preserved,
      including the previously undocumented `response_mode_toggle` binding
      in the README hotkey tables and `config.example.toml` `[hotkeys]`.
- [ ] Every handoff prepared by this story passes the handoff
      self-sufficiency audit (Testing protocol item 4): literal hotkeys and
      config keys with source references, no assumed starting state for
      persistent settings.
- [ ] PROJECT.md carries a v1.9.0 architectural note iff a decision needed
      recording.
- [ ] The assembled human-run verification handoff exists with exact commands
      and covers every story acceptance criterion.
- [ ] `ruff` and `pytest` gates green; the story can be closed on a green
      human report.

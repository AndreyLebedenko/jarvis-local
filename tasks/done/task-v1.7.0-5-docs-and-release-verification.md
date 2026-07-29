# Task v1.7.0-5: Docs and release verification

**Status:** Completed. Automated checks green; the owner confirmed the hotkey
cancellation feature works as expected on 2026-07-29. The known stale Journal
feed when its tab is inactive remains a separate backlog item, not a loss of
the interrupted turn or a cancellation-core failure.
**Story:** `tasks/story-v1.7.0-barge-in.md`
**Depends on:** tasks v1.7.0-2 and v1.7.0-3, both completed and closed.

## Scope note - voice barge-in deferred (2026-07-29)

The story's original scope for this task covered docs and an end-to-end
checklist for **both** interruption mechanisms - the hotkey and the
experimental voice barge-in (task 4). Task 4 was deferred to backlog on
2026-07-29 (owner decision, not a technical blocker; see
`tasks/backlog/experimental-voice-barge-in.md`) and has not been opened.

This task is adapted to cover **the hotkey mechanism only** (tasks 2 and
3, both closed). It does **not** produce:

- `config.example.toml` documentation or a headphones-only warning for
  the voice option (there is no voice option yet).
- A human-run checklist section exercising VAD-during-playback
  interruption.
- A `PROJECT.md` architecture note describing the voice path.

When task 4 is picked back up, it needs its own docs-and-verification
pass - either reopening this task's scope or a new task 6, an owner call
to make at that time. Do not assume this closes the story's release
readiness for voice barge-in; it only closes it for the hotkey.

## Summary

Record the hotkey interruption mechanism's design and the interrupted-turn
history/journal contract in `PROJECT.md`, document the hotkey in user-facing
docs, and prepare the human-run end-to-end verification checklist.

## Boundary

- Documentation and checklist only. Fixes revealed by verification that
  are larger than trivial become bug reports per the project protocol,
  not inline fixes.
- Hotkey mechanism only, per the scope note above.

## Requirements

- `PROJECT.md` gains an "Architecture v1.7.0" section (or extends the
  existing v1.7.0 spike section) covering:
  - The pivot from general-hardware AEC to a hotkey as the primary,
    hardware-independent interruption mechanism, with a pointer to the
    spike's no-go finding rather than repeating it.
  - The shared cancellation core (`Orchestrator.cancel_active_turn()` /
    `_cancel_current_turn()`, `TtsOutput.cancel()`,
    `Orchestrator.claim_turn_end()`) and why it exists as a single path
    task 4 is meant to reuse, not duplicate, whenever it resumes.
  - The interrupted-turn history/journal representation from task 3
    (outcome field, ordering guarantees against the races found across
    its five review rounds) at a level future readers need without
    re-reading the task card's full history.
  - A brief pointer that voice barge-in (task 4) is deferred to backlog,
    so `PROJECT.md` does not imply it shipped.
- `HotkeySettings.interrupt` (`ctrl+alt+i`) documented alongside the
  project's other hotkeys wherever they are already listed for users
  (README.md / README.ru.md and/or `config.example.toml`, matching
  existing precedent for how the other five hotkeys are documented).
- **Keep the `config.example.toml` comment above `interrupt = "ctrl+alt+i"`
  limited to the implemented hotkey.** It must not claim or imply that a
  voice option is configurable; task 4 is deferred to backlog and unopened.
- Human-run end-to-end checklist for the hotkey path, extending
  `tasks/interrupt-hotkey-handoff.md` rather than replacing it. The
  existing handoff covers mid-speech (TTS) and pre-speech ("thinking",
  before any audio starts) interrupts, a following turn working
  normally, and the idle no-op - it does **not** cover:
  - **Interrupting during active token generation, after speech has
    already started.** Today's step 7 only exercises "thinking" (before
    Jarvis has started speaking at all). A longer answer where Jarvis is
    already mid-sentence while the backend is still streaming later
    tokens is a distinct window (`_dispatch_backend_request()` racing
    `_on_full_response_complete()`, the subject of task 2's "Second
    review round" findings) and needs its own explicit step.
  - **The interrupted turn's journal entry appearing live, with outcome
    `interrupted`, immediately after each scenario above** - not just
    after a restart. Task 2's human handoff run already found and fixed
    one real bug in exactly this path (the "thinking"-phase interrupt
    not appearing in the live Journal panel until restart,
    `finish_turn()` not awaiting pending journal writes); the checklist
    itself never got a permanent step guarding against a regression
    there, and task 3's `outcome: interrupted` field has no live-panel
    check at all yet. Add a report line for each scenario: "journal
    entry appeared live, outcome shown as interrupted: yes/no."

## Acceptance criteria

- [x] `PROJECT.md` documents the hotkey architecture, the shared
      cancellation core, and the interrupted-turn journal/history
      contract, with an explicit note that voice barge-in is deferred.
- [x] User-facing docs list the interrupt hotkey binding.
- [x] The human-run end-to-end checklist for the hotkey path is prepared
      and handed off; verified outcome is recorded before the story
      treats the hotkey mechanism as release-ready.
- [x] `python -m pytest` and Ruff checks are green.
- [x] Nothing in this task's output claims voice barge-in is documented,
      configured, or verified.

## Verification outcome (2026-07-29)

- Automated checks: `python -m ruff format --check .`, `python -m ruff
  check .`, and `python -m pytest` passed (1438 passed, 1 skipped).
- Owner-run hotkey verification: confirmed the interruption feature works as
  expected.
- Known non-blocking UI limitation: if a `journal_event` arrives while the
  Journal tab is inactive, the already-selected feed can remain stale until
  a reload. The event is already stored and is not lost. This is the
  pre-existing browser-side issue recorded in
  `tasks/backlog/journal-live-feed-stale-on-tab-reactivation.md`; it is
  outside this cancellation-core/docs task.

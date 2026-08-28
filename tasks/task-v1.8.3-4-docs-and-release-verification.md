# Task v1.8.3-4: Docs + release verification

**Status:** Not started.
**Story:** `tasks/story-v1.8.3-sequential-journal-playback.md`
**Depends on:** task-v1.8.3-1, -2, -3 (all implementation slices complete).

## Summary

Document the v1.8.3 architecture and prepare the release verification handoff.
Record the pausable playback primitive, the sequence engine, the two playback
mechanisms (assistant TTS vs voice-user direct wav), and the scoped revision
of v1.8.2's "no queue" rule. Update user-facing docs for the new controls
(play-from-here, Pause/Resume) and assemble the human-run verification list.

## Context you need

- PROJECT.md "Architecture v1.8.2 (reply replay)": its deferred pause/resume
  note (now delivered) and its "no queue" paragraph (now scoped to concurrent
  replay). Add an "Architecture v1.8.3 (sequential journal playback)" section
  rather than rewriting v1.8.2 history; cross-reference.
- `tasks/story-v1.8.3-sequential-journal-playback.md`: the locked decisions to
  mirror into PROJECT.md.
- `config.example.toml` and any user-facing docs that list replay/journal
  controls or hotkeys, if the new controls need entries.
- The verification-contract section of PROJECT.md for the CI/hardware split.

## Boundary

- Docs, config example, and verification handoff only. No behavior change.
- Do not re-open design decisions; record what tasks 1-3 shipped.

## Requirements

- PROJECT.md: new "Architecture v1.8.3" section covering the pausable
  callback-`OutputStream` primitive + position marker; the sequence engine
  (journal-order walk, skip typed-user/system, one channel, one held request);
  assistant-TTS vs voice-user-wav mechanisms; live-turn-cancels-sequence and
  busy-reject still holding; and the explicit scoping of v1.8.2's "no queue"
  to concurrent replay. Mark any settled facts appropriately.
- Update the v1.8.2 "no queue" paragraph in place with a one-line pointer to
  the v1.8.3 scoping (so the old text is not read as still absolute).
- `config.example.toml` / user docs: entries for play-from-here and
  Pause/Resume controls and any route/keybinding notes, matching what tasks
  1-2 implemented.
- Assemble the consolidated human-run verification list from tasks 1-3's
  handoffs with exact commands (pause/resume timing, sequence ordering,
  wav-vs-TTS mix, skip-typed, live-turn-cancel).

## Acceptance criteria

- [ ] PROJECT.md documents the v1.8.3 architecture and the scoped v1.8.2
      "no queue" revision; no contradiction remains between the two sections.
- [ ] `config.example.toml` / user docs describe the new controls accurately.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` are green.
- [ ] The human-run verification handoff is written with exact commands and
      covers every hardware/manual check from tasks 1-3.

## Verification handoff (human-run)

- Run the consolidated verification list end to end on hardware and report
  results. Exact commands provided at handoff time.

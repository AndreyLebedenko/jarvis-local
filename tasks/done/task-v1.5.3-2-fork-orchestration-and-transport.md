# Task v1.5.3-2: Fork orchestration and transport

**Status:** Completed.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** task-v1.5.3-1 (seed builder).

## Summary

Wire "continue this conversation": an authenticated transport command
that forks a selected past session into a new live session - resetting
the model-facing history, seeding it from the v1.5.3-1 builder,
recording provenance in the new session's journal log - and revise
PROJECT.md's journal-context contract in the same change. No UI in this
task.

## Context you need

- `src/jarvis/app.py`: `ConversationHistory`, the reset-context path
  (`ControlApi.reset_context()` and its orchestrator handler), and how
  the journal recorder starts/labels sessions.
- `src/jarvis/journal/recorder.py`: session lifecycle
  (`session_id`, `_session()`) - where a new session begins and where
  provenance metadata can be recorded as an event.
- `src/jarvis/journal/events.py`: event schema; provenance must fit the
  existing schema shape (a dedicated event or metadata field - state
  the choice in the card outcome).
- `src/jarvis/ui/transport.py`: journal endpoint auth/Hidden pattern
  and the existing control-command dispatch, to choose a consistent
  command surface (HTTP POST is the story default for journal-surface
  actions; align with v1.5.2-1's endpoint style).
- `src/jarvis/dialog/time_context.py`: `format_time_context()` renders
  only the current time - reuse its weekday + ISO 8601 formatting for
  the provenance seed line, do not extend it to historic timestamps
  unless that falls out naturally as a pure formatting parameter.
- `PROJECT.md`: "Architecture v1.5.0 (dialog journal)" - the sentence
  "It is not fed back into model context" must be revised here, in the
  same change (explicit contract revision, roadmap v1.5.3).

## Boundary

- Fork only; no in-place continuation, no appending to the source log
  (it must remain byte-identical - tested).
- Busy guard: a fork during an in-flight turn is rejected with a
  structured error, like other turn-affecting actions.
- Hidden mode rejects the fork command like other journal endpoints.
- No UI changes; task-v1.5.3-3 builds the control.

## Requirements

- Authenticated command accepting a source session id (validated
  against real sessions, traversal-safe) and starting a fork: current
  history cleared, seed applied within the configured
  `fork_seed_max_chars` budget, new journal session started with
  `continued_from: <session_id>` provenance and a record of what the
  seed dropped (from the builder's structured result).
- The seeded turns do not replay aloud and are not re-recorded as fresh
  user/assistant journal events; they exist in model-facing history and
  in the provenance record only.
- The fork prepends one deterministic system-style provenance seed
  line (story design decision, 2026-07-19): it states that the session
  continues an earlier conversation and gives the source session's end
  timestamp in `format_time_context()`'s weekday + ISO 8601 style. The
  seeded turns follow it; the line is template text, never generated,
  and is the only addition beyond the builder's output.
- Structured responses: success (new session id), unknown session,
  busy, Hidden, oversize-single-turn rejection from the builder.
- `config.example.toml` documents the new `[memory]`
  `fork_seed_max_chars` setting.

## Acceptance criteria

- [ ] Tests cover: successful fork seeds history as the provenance
      seed line plus exactly the builder's output (seed line content
      pinned, including the source timestamp formatting); source log
      bytes unchanged; provenance event
      recorded in the new session; busy/Hidden/unknown-session
      rejections; no journal user/assistant events emitted for seeded
      turns.
- [ ] PROJECT.md contract revision is part of this change.
- [ ] No UI behavior changes.
- [ ] `python -m pytest` and Ruff checks are green.

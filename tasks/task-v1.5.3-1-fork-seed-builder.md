# Task v1.5.3-1: Fork seed builder

**Status:** Backlog.
**Story:** `tasks/story-v1.5.3-memory-layer-a.md`
**Depends on:** nothing new; pure logic over existing journal replay.

## Summary

Build the pure function that turns a recorded journal session into a
text-only `ConversationHistory` seed: verbatim tail within a character
budget, oldest-dropped-first, voice turns represented by their recorded
history text. No wiring, no transport, no UI.

## Context you need

- `src/jarvis/journal/store.py`: `read_session()` / `JournalReplay` -
  the input shape.
- `src/jarvis/journal/events.py`: `JournalEvent` fields (source, text,
  timestamp, media refs, reserved `transcript`).
- `src/jarvis/app.py`: `ConversationHistory` and its `Turn` shape - the
  output must slot into it without changing it; note `media_b64` stays
  unpopulated (text-only seed).
- `src/jarvis/dialog/time_context.py`: how timestamps are already
  rendered for the model; the seed builder only needs to preserve
  enough timing data for task-2 to present the gap.

## Boundary

- Pure module (proposed home: `src/jarvis/journal/fork.py` or
  `src/jarvis/dialog/`), no I/O beyond consuming an already-read
  replay, no bus, no config loading (budget arrives as a parameter).
- No summarization or text generation of any kind; verbatim recorded
  text only.
- Media is never seeded; transcripts are used only if the event already
  carries one, never produced here.

## Requirements

- Input: a session replay plus a character budget; output: an ordered
  list of user/assistant text turns ready for `ConversationHistory`,
  plus a structured result describing what was dropped (turn count
  dropped, whether truncation happened).
- Tail selection drops oldest turns first and never splits a turn in
  half to fit the budget (a turn either fits whole or is dropped;
  document the edge case where a single turn exceeds the whole budget
  and reject it explicitly rather than truncating silently).
- Voice user turns seed with the text recorded in the event (the
  model-facing placeholder or a transcript when present); assistant
  turns seed with recorded answer text.
- Events with no model-facing text contribution (media-only, system)
  are skipped deterministically and the skip rule is tested.
- The function is deterministic: same replay plus same budget always
  yields the same seed.

## Acceptance criteria

- [ ] Tests cover: budget larger than the session (full seed), tail
      truncation dropping oldest turns, single-oversize-turn rejection,
      voice-turn placeholder seeding, transcript-preferred seeding when
      a transcript exists, skip rules, and determinism.
- [ ] No changes to `ConversationHistory` or the journal store.
- [ ] `python -m pytest` and Ruff checks are green.

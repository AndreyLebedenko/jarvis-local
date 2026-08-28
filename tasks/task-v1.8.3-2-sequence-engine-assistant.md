# Task v1.8.3-2: Sequence engine (assistant replies) + play-from-here

**Status:** Not started.
**Story:** `tasks/story-v1.8.3-sequential-journal-playback.md`
**Depends on:** task-v1.8.3-1 (the pausable primitive is the playback base).

## Summary

Add a sequence engine that, starting from a chosen journal event, walks that
session's records forward and plays each **assistant reply** back to back on
the single shared playback channel, using task 1's pausable primitive. Stop
cancels the whole sequence; a new live turn starting cancels the whole
sequence; a start attempt while a live turn speaks is rejected. Add the
"play from here" chat-log control and a one-held-request sequence lifetime
(the v1.8.2 held-request seam at a larger grain). Voice user turns are NOT
included yet (task 3) - an assistant-only sequence proves the engine. Update
PROJECT.md's v1.8.2 "no queue" wording to scope it to *concurrent* replay
(this self-sequenced playback is one logical replay with multiple segments).

## Context you need

- `src/jarvis/audio/replay.py`: `ReplayPlayer` and task 1's pausable
  primitive. The sequence is a loop over per-turn playback on that primitive,
  reusing its pause/resume/cancel; it must not open a second playback route.
- `src/jarvis/journal/store.py`: `JournalStore.read_session(session_id)` ->
  `JournalReplay.records` (ordered `JournalEventRecord` with `.reference`
  (session_id, event_position) and `.event`). This is the walk source.
- `src/jarvis/journal/events.py`: `JournalEvent.role`/`.source`/`.text`. In
  this card, playable = `role == "assistant"`; everything else is skipped.
- `src/jarvis/app.py`: `reply_speech_text` (~1976), `replay_reply` (~1964),
  `_run_reply_replay` (~1990), the held-request pattern, `on_turn_start`
  cancel (~1645). The sequence needs the same turn-start cancel and busy
  rejection, applied to the whole sequence.
- PROJECT.md "Architecture v1.8.2 (reply replay)": the "no queue" paragraph to
  re-scope, and the held-request seam to extend to a sequence.
- `status_console_ui/`: chat-log controls (Play/Stop, and task-1
  Pause/Resume). Add a "play from here" affordance. Mind the `file://`
  sub-resource cache gotcha in CLAUDE.md.

## Boundary

- Assistant-only sequence. Voice user turns and the generalized accessor are
  task 3.
- One playback channel, one held request per sequence. Advancing to the next
  segment must not be treated as "busy" against the sequence itself; only a
  *live turn* or an *external* replay attempt is busy.
- No new transport controls beyond Play-from-here, Stop, and task-1
  Pause/Resume (which now pause/resume the current segment of the sequence).
- Pause during a sequence suspends the current segment and holds the
  sequence; it does not skip to the next.

## Requirements

- A sequence engine (e.g. `SequencePlayer` in `src/jarvis/audio/replay.py` or
  a sibling) that takes a start `JournalEventRef`, reads the session's
  records, iterates from that position forward, and for each assistant record
  plays its `reply_speech_text` through the pausable primitive, in order,
  under the shared lock.
- Stop cancels the current segment and the whole remaining sequence and
  resolves the held request. A new live turn (`on_turn_start`) cancels the
  whole sequence. A start attempt while `Orchestrator.is_busy` or a
  replay/sequence is active is rejected (error cue + `SystemEvent`), never
  queued.
- One held HTTP request spans the whole sequence (extend `_run_reply_replay`'s
  shape or add a sibling handler); the WebView toggles the sequence control
  off that fetch promise. Pause/Resume remain non-resolving signals.
- "Play from here" control in the chat log starting the sequence at that
  event.
- Update PROJECT.md's v1.8.2 "no queue" paragraph to scope it to concurrent
  replay, noting self-sequenced playback is permitted and why (one channel,
  no overlap, one logical replay).

## Acceptance criteria

- [ ] Starting from an assistant reply plays it and every later assistant
      reply in that session in order, back to back, until the end or Stop.
- [ ] Stop ends the whole sequence and resolves the held request; a new live
      turn starting mid-sequence cancels the whole sequence; segments never
      overlap on the shared device.
- [ ] Pause/Resume (task 1) suspend and continue the current segment without
      advancing or ending the sequence.
- [ ] A start attempt during a live turn is rejected; single-reply Play/Stop
      from v1.8.2 still works unchanged.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` are green.
- [ ] Automated logic tests cover: the walk selects assistant records in
      order from the start ref and skips non-assistant ones; turn-start
      cancels the whole sequence; busy rejection; end-of-session resolves the
      sequence. Device playback ordering is a human-run handoff.

## Verification handoff (human-run, hardware)

- From a mid-log assistant reply, start the sequence; confirm it plays each
  subsequent reply in order and stops at the end.
- Start a sequence, then start a live turn; confirm the sequence stops and
  does not resume.
- Exact commands provided at handoff time.

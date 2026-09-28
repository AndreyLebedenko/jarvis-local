# Backlog: Replay of a mode-3 reply speaks its spoken derivative

**Status:** Open. Feature request / unfinished seam, not blocking.
**Source:** Owner request, 2026-09-28 (commit `526c950`, branch
`feature/tts-language-mode`): "re-listen to an AI reply, respecting whether
the reply had one text or two".

## Summary

Re-listening to an assistant reply already exists (Play / "Воспроизвести" in
the message meta bar and in the "More actions" menu, story-v1.8.2/v1.8.3).
What is missing is the mode-3 half: a mode-3 turn has two texts (the canvas
in `event.text` and the spoken derivative in
`metadata["spoken_derivative"]`), and replay should speak the derivative, the
same text the live turn spoke. Today replay always re-synthesizes the canvas.

## Context

- The retarget was planned and never done. v1.8.2 introduced
  `reply_speech_text()` as the single "text to speak for this turn" seam,
  explicitly to be retargeted to the mode-3 derivative
  (`tasks/done/story-v1.9.0-response-modes.md:133,186`,
  `tasks/done/task-v1.9.0-3-mode3-second-pass-and-tts-suppression.md:150,165`:
  "replay retargets to it later"). The code still returns `event.text`:
  - single reply: `reply_speech_text()`
    ([replay.py:81](../../src/jarvis/audio/replay.py:81)), used by
    `replay_reply()` ([app.py:2435](../../src/jarvis/app.py:2435));
  - play-from-here sequence: `SequencePlayer.texts_from()` / `_play_item()`
    ([replay.py:401-409](../../src/jarvis/audio/replay.py:401)).
- The derivative is metadata on the same assistant event, not a separate
  event ([recorder.py:104-121](../../src/jarvis/journal/recorder.py:104)),
  with flags `spoken_derivative_interrupted` and
  `spoken_derivative_truncated`.
- Modes 1 and 2 have a single text; their replay behavior is already right.

## Current Boundary

- Change which text the existing replay paths speak; no new UI control, no
  playback-engine change.
- Both paths (single reply and sequence) must use one shared accessor so they
  cannot diverge.
- The derivative stays excluded from retrieval/memory; this only reads it.

## Acceptance Criteria

- [ ] Replaying a mode-3 reply that has a stored derivative speaks the
      derivative, not the canvas.
- [ ] Replaying a mode-1/mode-2 reply (no derivative) speaks `event.text` as
      today.
- [ ] Play-from-here uses the same selection for every assistant reply in
      the sequence.
- [ ] Unit tests cover: derivative present, derivative absent, and the
      interrupted/truncated cases per the owner's answer below.
- [ ] `python -m pytest`, `ruff check`, `ruff format --check` green.
- [ ] Listening check on a real mode-3 turn is a human handoff (speakers).

## Decisions

- A derivative marked `spoken_derivative_interrupted` or
  `spoken_derivative_truncated` is replayed as stored (the partial
  derivative), not replaced by the canvas and not regenerated: it is what the
  user heard and needs no model call. Owner decision, 2026-09-28.

## Open Questions (owner decides before implementation)

- Should replay use the TTS language mode handling (merged in `9ee78ed`,
  `src/jarvis/audio/speech_language.py`), so a replay sounds like the live
  turn did?

## Side Note

The Play control appears only on rows that have a known feed position (a full
render, never a live append; see
[app.js:2568-2575](../../src/jarvis/ui/status_console_ui/app.js:2568)). A
reply that has just arrived has no Play button until the feed re-renders. If
that is the gap the owner actually hit, it is a separate item.

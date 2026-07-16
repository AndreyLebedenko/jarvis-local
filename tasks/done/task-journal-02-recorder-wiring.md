# Task journal-02: Record live turns into the journal

**Status:** Completed.
**Story:** `tasks/story-v1.5.0-dialog-journal.md`
**Depends on:** task-journal-01.

## Summary

Wire the running app to the `JournalStore`: every turn (voice, clipboard,
assistant answer) appends journal events, voice audio is saved as files in
the session directory, and recording stays off the turn's critical path.

## Context you need

- Story card sections "Layered design", "Boundaries", stop condition on
  latency.
- `src/jarvis/journal/` from task-journal-01.
- `src/jarvis/app.py`: `Orchestrator._start_turn()` is the single shared
  path for all turn sources; `on_utterance` (voice) and `on_clipboard`
  already flow through it. `ConversationHistory.add()` is where the
  turn's final text lands.
- `src/jarvis/core/bus.py`: the event bus, if a subscriber approach fits
  better than direct calls. Either approach is acceptable; pick the one
  that keeps `app.py` changes smallest.
- `src/jarvis/core/config.py`: add a `journal` settings section (root
  directory, enabled flag defaulting to on).

## Boundary

- Changes limited to: `src/jarvis/journal/recorder.py` (new),
  minimal hooks in `src/jarvis/app.py`, `src/jarvis/core/config.py`,
  `config.example.toml`, tests.
- No UI, no index, no transport changes.
- Do not change what `ConversationHistory` sends to the model - the
  journal is a parallel record (story boundary).

## Requirements

- A voice turn writes: user event with `source="voice"`, empty text,
  `media=["utterance-<ts>.wav"]`, and the wav bytes saved to the session
  directory. The audio saved must be the same clip that went to the
  model.
- A clipboard turn writes a user event with the real submitted text.
- Each assistant answer writes an assistant event with the spoken/final
  text (the same text that enters `ConversationHistory`, i.e. never
  reasoning/thinking content - PROJECT.md thinking-mode rule).
- One app run = one journal session; session starts lazily on the first
  turn, not at process start.
- Writes are fire-and-forget relative to the turn pipeline (same spirit
  as sound_cues): a journal write failure logs a warning and never
  blocks or fails the turn.

## Acceptance criteria

- [x] Pure tests drive a fake turn sequence (voice with audio bytes,
      clipboard, assistant answers) and assert the resulting JSONL and
      media files.
- [x] A test proves a failing store (e.g. read-only dir) does not raise
      into the turn path.
- [x] A test proves reasoning text never reaches journal events (mirror
      the existing thinking-isolation test approach).
- [x] `config.example.toml` documents the journal section.
- [x] `python -m pytest` green. Live end-to-end recording is verified by
      the human later via the Journal view (task-journal-06 handoff).
